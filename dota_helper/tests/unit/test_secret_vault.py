"""统一凭据池测试 — 单点读取 / 别名链 / 必需校验 / 审计 / 轮换 / 加密落盘 / 遮蔽

覆盖 bugs.md P0 #3「凭据/密钥管理分散」修复验收：
- get: 内存覆盖 > 环境变量 > 默认值，读取即审计
- get_first: 多候选名按优先级返回第一个非空（兼容旧别名链）
- require: 缺失/空显式抛 CredentialError（替代静默 ""/None）
- set/rotate/unset: 进程内注入与轮换
- get_access_log/clear_access_log: 最小权限审计
- save_file/load_file: Fernet 加密落盘与读取（cryptography）
- __repr__: 永不泄露明文
- 集成: llm/client.py 与 facade/entrypoint.py 经 vault 解析密钥
"""
from pathlib import Path

import pytest

from dota_helper import vault as package_vault
from dota_helper.facade.entrypoint import _has_llm_key
from dota_helper.llm.client import LLMClient
from dota_helper.secret_vault import (
    AccessRecord,
    CredentialError,
    SecretVault,
)


# ── get：读取优先级 ──


def test_get_from_env(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "  sk-a  ")
    v = SecretVault()
    assert v.get("TEST_KEY_A") == "sk-a"


def test_get_default_when_unset(monkeypatch):
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    v = SecretVault()
    assert v.get("TEST_KEY_A") is None
    assert v.get("TEST_KEY_A", default="fallback") == "fallback"


def test_get_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "env-value")
    v = SecretVault()
    v.set("TEST_KEY_A", "override-value")
    assert v.get("TEST_KEY_A") == "override-value"


def test_get_unset_restores_env(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "env-value")
    v = SecretVault()
    v.set("TEST_KEY_A", "override-value")
    v.unset("TEST_KEY_A")
    assert v.get("TEST_KEY_A") == "env-value"


# ── get_first：别名链 ──


def test_get_first_priority_order(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "a")
    monkeypatch.setenv("TEST_KEY_B", "b")
    v = SecretVault()
    assert v.get_first(("TEST_KEY_A", "TEST_KEY_B")) == "a"


def test_get_first_skips_missing(monkeypatch):
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    monkeypatch.setenv("TEST_KEY_B", "b")
    v = SecretVault()
    assert v.get_first(("TEST_KEY_A", "TEST_KEY_B")) == "b"


def test_get_first_all_missing_returns_default(monkeypatch):
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    monkeypatch.delenv("TEST_KEY_B", raising=False)
    v = SecretVault()
    assert v.get_first(("TEST_KEY_A", "TEST_KEY_B")) is None
    assert v.get_first(("TEST_KEY_A", "TEST_KEY_B"), default="d") == "d"


def test_get_first_empty_value_skipped(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "   ")
    monkeypatch.setenv("TEST_KEY_B", "b")
    v = SecretVault()
    assert v.get_first(("TEST_KEY_A", "TEST_KEY_B")) == "b"


# ── require：必需凭据校验 ──


def test_require_returns_value(monkeypatch):
    monkeypatch.setenv("TEST_REQ", "sk-req")
    v = SecretVault()
    assert v.require("TEST_REQ") == "sk-req"


def test_require_missing_raises(monkeypatch):
    monkeypatch.delenv("TEST_REQ", raising=False)
    v = SecretVault()
    with pytest.raises(CredentialError) as exc:
        v.require("TEST_REQ")
    assert exc.value.name == "TEST_REQ"
    assert "TEST_REQ" in str(exc.value)


def test_require_empty_raises(monkeypatch):
    monkeypatch.setenv("TEST_REQ", "   ")
    v = SecretVault()
    with pytest.raises(CredentialError):
        v.require("TEST_REQ")


def test_require_hint_in_message(monkeypatch):
    monkeypatch.delenv("TEST_REQ", raising=False)
    v = SecretVault()
    with pytest.raises(CredentialError) as exc:
        v.require("TEST_REQ", hint="请检查 .env")
    assert "请检查 .env" in str(exc.value)


# ── set / rotate / unset ──


def test_set_and_rotate_override_env(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "env")
    v = SecretVault()
    v.set("TEST_KEY_A", "v1")
    assert v.get("TEST_KEY_A") == "v1"
    v.rotate("TEST_KEY_A", "v2")
    assert v.get("TEST_KEY_A") == "v2"
    v.unset("TEST_KEY_A")
    assert v.get("TEST_KEY_A") == "env"


def test_unset_missing_name_no_error():
    v = SecretVault()
    v.unset("NOT_SET")
    assert v.get("NOT_SET") is None


# ── 访问审计 ──


def test_access_log_records_owner(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "a")
    v = SecretVault()
    v.get("TEST_KEY_A", owner="module1")
    v.get("TEST_KEY_A", owner="module2")
    log = v.get_access_log()
    assert len(log) == 2
    assert [r.owner for r in log] == ["module1", "module2"]
    assert all(isinstance(r, AccessRecord) for r in log)
    assert all(r.name == "TEST_KEY_A" for r in log)
    assert all(r.timestamp > 0 for r in log)


def test_clear_access_log(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "a")
    v = SecretVault()
    v.get("TEST_KEY_A", owner="m")
    v.clear_access_log()
    assert v.get_access_log() == []


def test_access_log_caps_at_limit():
    v = SecretVault(access_log_limit=3)
    for i in range(6):
        v.get("TEST_KEY_%d" % i, owner="m")
    log = v.get_access_log()
    assert len(log) == 3
    assert log[0].name == "TEST_KEY_3"


def test_access_log_is_snapshot(monkeypatch):
    monkeypatch.setenv("TEST_KEY_A", "a")
    v = SecretVault()
    v.get("TEST_KEY_A", owner="m")
    snapshot = v.get_access_log()
    v.get("TEST_KEY_A", owner="m")
    assert len(snapshot) == 1
    assert len(v.get_access_log()) == 2


# ── 遮蔽：repr 不泄露明文 ──


def test_repr_does_not_leak_secrets():
    v = SecretVault()
    v.set("TEST_KEY_A", "sk-top-secret-abc123")
    rendered = repr(v)
    assert "sk-top-secret-abc123" not in rendered
    assert str(v) == rendered


# ── 加密落盘（Fernet / cryptography）──


def test_save_and_load_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTA_SECRETS_KEY", raising=False)
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    v = SecretVault()
    v.set("TEST_KEY_A", "secret-a")
    v.set("TEST_KEY_B", "secret-b")
    path = tmp_path / "secrets.enc"
    v.save_file(str(path), key=key)

    assert path.exists()
    raw = path.read_bytes()
    assert b"secret-a" not in raw and b"secret-b" not in raw

    v2 = SecretVault()
    count = v2.load_file(str(path), key=key)
    assert count == 2
    assert v2.get("TEST_KEY_A") == "secret-a"
    assert v2.get("TEST_KEY_B") == "secret-b"


def test_load_file_uses_env_key(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("DOTA_SECRETS_KEY", key)
    v = SecretVault()
    v.set("TEST_KEY_A", "secret-a")
    path = tmp_path / "secrets.enc"
    v.save_file(str(path))

    v2 = SecretVault()
    assert v2.load_file(str(path)) == 1
    assert v2.get("TEST_KEY_A") == "secret-a"


def test_load_file_missing_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTA_SECRETS_KEY", raising=False)
    v = SecretVault()
    v.set("TEST_KEY_A", "a")
    path = tmp_path / "secrets.enc"
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    v.save_file(str(path), key=key)

    v2 = SecretVault()
    with pytest.raises(CredentialError) as exc:
        v2.load_file(str(path))
    assert exc.value.name == "DOTA_SECRETS_KEY"


def test_load_file_wrong_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTA_SECRETS_KEY", raising=False)
    from cryptography.fernet import Fernet

    v = SecretVault()
    v.set("TEST_KEY_A", "a")
    path = tmp_path / "secrets.enc"
    v.save_file(str(path), key=Fernet.generate_key().decode())

    v2 = SecretVault()
    wrong = Fernet.generate_key().decode()
    with pytest.raises(CredentialError) as exc:
        v2.load_file(str(path), key=wrong)
    assert "密钥不匹配" in str(exc.value)


def test_save_file_missing_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTA_SECRETS_KEY", raising=False)
    v = SecretVault()
    v.set("TEST_KEY_A", "a")
    with pytest.raises(CredentialError):
        v.save_file(str(tmp_path / "secrets.enc"))


# ── 包级单例 ──


def test_package_singleton_is_secret_vault():
    from dota_helper.secret_vault import vault as module_vault

    assert isinstance(package_vault, SecretVault)
    assert package_vault is module_vault


# ── 集成：LLM 客户端经 vault 解析密钥 ──


def test_llm_client_reads_key_via_vault(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-llm-env")
    client = LLMClient()
    assert client._api_key == "sk-llm-env"


def test_llm_client_alias_chain_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    client = LLMClient()
    assert client._api_key == "sk-deepseek"


def test_llm_client_vault_override_beats_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    package_vault.set("OPENAI_API_KEY", "sk-override")
    try:
        client = LLMClient()
        assert client._api_key == "sk-override"
    finally:
        package_vault.unset("OPENAI_API_KEY")


def test_llm_client_explicit_param_wins(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    client = LLMClient(api_key="sk-explicit")
    assert client._api_key == "sk-explicit"


def test_llm_client_no_key_returns_empty(monkeypatch):
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    client = LLMClient()
    assert client._api_key == ""


def test_entrypoint_has_llm_key_uses_vault(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-llm")
    assert _has_llm_key() is True


def test_entrypoint_has_llm_key_false_when_missing(monkeypatch):
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert _has_llm_key() is False
