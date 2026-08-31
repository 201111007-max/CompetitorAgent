"""设计文档 74 §3.1/E2：用户级环境变量应用（user_env.py）单元测试。

跨平台安全验证：非 Windows no-op；Windows（mock winreg）按名单覆盖 os.environ。
"""

import os
import sys

from competitor_agent.config.user_env import apply_user_level_environment


def test_noop_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    assert apply_user_level_environment() == []


def test_overwrites_from_registry(monkeypatch) -> None:
    """Windows + 用户级注册表有值时：覆盖 shell 注入的污染 key/base_url。"""
    monkeypatch.setattr(os, "name", "nt")

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeWinreg:
        HKEY_CURRENT_USER = 1

        @staticmethod
        def OpenKey(hive, name):
            return FakeKey()

        @staticmethod
        def QueryValueEx(key, name):
            if name == "DEEPSEEK_API_KEY":
                return ("ark-fake-abc", 1)
            if name == "OPENAI_BASE_URL":
                return ("https://ark.example/v1", 1)
            if name == "TAVILY_API_KEY":
                return ("tvly-fake", 1)
            raise FileNotFoundError(name)

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-shell-polluted")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    applied = apply_user_level_environment()

    assert "DEEPSEEK_API_KEY" in applied
    assert "OPENAI_BASE_URL" in applied
    assert "TAVILY_API_KEY" in applied
    assert os.environ["DEEPSEEK_API_KEY"] == "ark-fake-abc"
    assert os.environ["OPENAI_BASE_URL"] == "https://ark.example/v1"
    assert os.environ["TAVILY_API_KEY"] == "tvly-fake"


def test_only_applies_known_keys(monkeypatch) -> None:
    """名单外键（如 PATH）不被覆盖；注册表无值键不覆盖已设 env。"""
    monkeypatch.setattr(os, "name", "nt")

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeWinreg:
        HKEY_CURRENT_USER = 1

        @staticmethod
        def OpenKey(hive, name):
            return FakeKey()

        @staticmethod
        def QueryValueEx(key, name):
            raise FileNotFoundError(name)

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg)
    monkeypatch.setenv("PATH", "C:\\custom")
    assert apply_user_level_environment() == []
    assert os.environ["PATH"] == "C:\\custom"
