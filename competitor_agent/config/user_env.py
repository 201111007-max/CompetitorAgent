"""用户级环境变量应用（设计文档 74 §3.1/E2）——根治 shell env 污染。

现象：opencode/终端 shell 注入的 ``DEEPSEEK_API_KEY``（sk-...，DeepSeek 格式）与
``OPENAI_BASE_URL`` 遮蔽用户级注册表 ``HKCU\\Environment`` 的 Ark key/base_url，导致
LLM 客户端误用错误端点（``deepseek-chat`` @ ``api.deepseek.com``、0ms 空返回毒化报告）。

E2 用户决策：web app / 子 Agent 运行时**强制**使用用户级 env，忽略 shell 注入的同名键。

跨平台安全：非 Windows / 注册表不可读 → no-op（CI、测试、Linux/macOS 不受影响）。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("competitor_agent.config.user_env")

# 需要从用户级 env 覆盖的键（LLM 端点/Key + 搜索 Key + 可观测性 Key）。
# 收敛名单避免意外覆盖 PATH 等无关项；只覆盖与运行质量直接相关的键。
_APPLY_KEYS = (
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "LLM_API_KEY",
    "OPENAI_BASE_URL",
    "DEEPSEEK_BASE_URL",
    "TAVILY_API_KEY",
    "LANGFUSE_HOST",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


def apply_user_level_environment(keys: tuple[str, ...] = _APPLY_KEYS) -> list[str]:
    """把用户级环境变量（HKCU\\Environment）覆盖进 ``os.environ``，返回实际覆盖的键列表。

    仅覆盖 ``keys`` 名单内的键；注册表读取失败 → no-op 并告警（不阻断启动）。
    进程内后续构造的 LLMClient（web app/子 Agent/CLI）读到的 key/base_url 即用户级值。
    """
    if os.name != "nt":
        return []
    applied: list[str] = []
    try:
        import winreg

        # winreg 仅 Windows 存在，其 typeshed stub 也仅在 win32 暴露成员：Linux 上
        # ``winreg.OpenKey`` 等会报 attr-defined。用 getattr 取（类型为 Any）规避
        # 跨平台 mypy（本地 Windows 与 CI Linux 双平台零告警，且不引入 unused-ignore）。
        open_key = getattr(winreg, "OpenKey")  # noqa: B009 - 有意取模块成员规避跨平台 mypy
        query_value = getattr(winreg, "QueryValueEx")  # noqa: B009 - 有意取模块成员规避跨平台 mypy
        hive = getattr(winreg, "HKEY_CURRENT_USER")  # noqa: B009 - 有意取模块成员规避跨平台 mypy
        with open_key(hive, "Environment") as key:
            for name in keys:
                try:
                    value, _ = query_value(key, name)
                except FileNotFoundError:
                    continue
                if isinstance(value, str):
                    os.environ[name] = value
                    applied.append(name)
    except OSError as exc:
        logger.warning("读取用户级环境变量失败（HKCU\\Environment）: %s", exc)
        return []
    if applied:
        logger.info("已应用用户级环境变量（设计文档 74 §3.1/E2）: %s", ", ".join(applied))
    return applied
