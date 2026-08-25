"""SecretVault 单元测试 — M0 0.4 出口条件

覆盖：get/set/rotate/unset/加密落盘/审计/遮蔽/数据目录解析。
"""
from pathlib import Path

import pytest

from competitor_agent.secret_vault import (
    CredentialError,
    SecretVault,
    get_data_dir,
)

try:  # pragma: no cover
    import cryptography  # noqa: F401

    _HAS_CRYPTOGRAPHY = True
except Exception:  # noqa: BLE001 - cryptography 缺失时跳过加解密用例 # pragma: no cover
    _HAS_CRYPTOGRAPHY = False

_skip_no_crypto = pytest.mark.skipif(
    not _HAS_CRYPTOGRAPHY, reason="cryptography 未安装，加解密回环不可测"
)


@pytest.fixture
def vault() -> SecretVault:
    return SecretVault(access_log_limit=10)


class TestGetSet:
    def test_get_default(self, vault: SecretVault) -> None:
        assert vault.get("NO_SUCH_KEY_XYZ", default="fallback") == "fallback"

    def test_get_missing_returns_none(self, vault: SecretVault) -> None:
        assert vault.get("NO_SUCH_KEY_XYZ") is None

    def test_set_overrides_env(self, vault: SecretVault, monkeypatch) -> None:
        monkeypatch.setenv("TEST_VAULT_KEY", "from-env")
        vault.set("TEST_VAULT_KEY", "from-override")
        assert vault.get("TEST_VAULT_KEY") == "from-override"

    def test_unset_restores_env(self, vault: SecretVault, monkeypatch) -> None:
        monkeypatch.setenv("TEST_VAULT_KEY", "from-env")
        vault.set("TEST_VAULT_KEY", "override")
        vault.unset("TEST_VAULT_KEY")
        assert vault.get("TEST_VAULT_KEY") == "from-env"

    def test_rotate_sets_value(self, vault: SecretVault) -> None:
        vault.rotate("TEST_VAULT_KEY", "v2")
        assert vault.get("TEST_VAULT_KEY") == "v2"

    def test_get_first_priority(self, vault: SecretVault, monkeypatch) -> None:
        monkeypatch.setenv("PRIMARY_KEY", "primary")
        monkeypatch.delenv("SECONDARY_KEY", raising=False)
        assert vault.get_first(["PRIMARY_KEY", "SECONDARY_KEY"]) == "primary"

    def test_get_first_falls_back(self, vault: SecretVault) -> None:
        assert vault.get_first(["A_B_C", "D_E_F"], default="none") == "none"

    def test_get_strips_whitespace(self, vault: SecretVault, monkeypatch) -> None:
        monkeypatch.setenv("PADDED_KEY", "  token  ")
        assert vault.get("PADDED_KEY") == "token"

    def test_require_missing_raises(self, vault: SecretVault) -> None:
        with pytest.raises(CredentialError) as exc:
            vault.require("REQUIRED_MISSING")
        assert exc.value.name == "REQUIRED_MISSING"

    def test_require_returns_value(self, vault: SecretVault) -> None:
        vault.set("REQUIRED_OK", "secret")
        assert vault.require("REQUIRED_OK") == "secret"


class TestAudit:
    def test_access_log_records_owner(self, vault: SecretVault) -> None:
        vault.get("LOG_KEY", owner="test-owner")
        records = vault.get_access_log()
        assert len(records) == 1
        assert records[0].name == "LOG_KEY"
        assert records[0].owner == "test-owner"

    def test_access_log_limit_evicts_old(self) -> None:
        v = SecretVault(access_log_limit=2)
        for i in range(5):
            v.get(f"K{i}")
        records = v.get_access_log()
        assert len(records) == 2
        assert records[-1].name == "K4"

    def test_clear_access_log(self, vault: SecretVault) -> None:
        vault.get("LOG_KEY")
        vault.clear_access_log()
        assert vault.get_access_log() == []


class TestEncryptedPersistence:
    def test_save_requires_key(self, vault: SecretVault, tmp_path: Path) -> None:
        with pytest.raises(CredentialError):
            vault.save_file(str(tmp_path / "secrets.enc"))

    def test_load_missing_key(self, vault: SecretVault, tmp_path: Path) -> None:
        with pytest.raises(CredentialError):
            vault.load_file(str(tmp_path / "secrets.enc"))


@_skip_no_crypto
class TestEncryptionRoundtrip:
    def test_roundtrip(self, tmp_path: Path) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        v1 = SecretVault()
        v1.set("API_KEY", "sk-1234")
        path = tmp_path / "secrets.enc"
        v1.save_file(str(path), key=key.decode())
        v2 = SecretVault()
        n = v2.load_file(str(path), key=key.decode())
        assert n == 1
        assert v2.get("API_KEY") == "sk-1234"

    def test_load_wrong_key_raises(self, tmp_path: Path) -> None:
        from cryptography.fernet import Fernet

        key1 = Fernet.generate_key()
        key2 = Fernet.generate_key()
        v1 = SecretVault()
        v1.set("API_KEY", "sk-1234")
        path = tmp_path / "secrets.enc"
        v1.save_file(str(path), key=key1.decode())
        v2 = SecretVault()
        with pytest.raises(CredentialError):
            v2.load_file(str(path), key=key2.decode())


class TestRedaction:
    def test_repr_does_not_leak(self, vault: SecretVault) -> None:
        vault.set("API_KEY", "sk-TOP-SECRET")
        assert "sk-TOP-SECRET" not in repr(vault)

    def test_no_plaintext_attrs(self, vault: SecretVault) -> None:
        vault.set("API_KEY", "sk-TOP-SECRET")
        assert not hasattr(vault, "_plaintext")


class TestDataDir:
    def test_returns_path_and_creates(self, monkeypatch, tmp_path: Path) -> None:
        target = tmp_path / "data"
        monkeypatch.setenv("COMPETITOR_AGENT_DATA_DIR", str(target))
        result = get_data_dir()
        assert result == target
        assert target.is_dir()

    def test_default_under_home(self, monkeypatch) -> None:
        monkeypatch.delenv("COMPETITOR_AGENT_DATA_DIR", raising=False)
        result = get_data_dir()
        assert result == Path.home() / ".competitor_agent"
        assert result.is_dir()


class TestSingleton:
    def test_vault_is_shared(self) -> None:
        from competitor_agent.secret_vault import vault as shared

        shared.set("SINGLETON_KEY", "x")
        assert shared.get("SINGLETON_KEY") == "x"