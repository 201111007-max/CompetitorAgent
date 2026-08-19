"""统一凭据池 — 集中管理 API Key / Secret

从 dota_helper/secret_vault.py 复制 + 通用化迁移，保持双向零耦合：
- 日志前缀改为 ``competitor_agent.secret_vault``
- 加密落盘密钥环境变量改为 ``COMPETITOR_SECRETS_KEY``（与 dota_helper 隔离）
- 新增 ``get_data_dir()`` 统一解析数据根目录（默认 ``~/.competitor_agent``）

设计（沿用 dota_helper bugs.md P0 #3 的解决方案）：
- SecretVault: 单点读取（内存覆盖 > 环境变量 > 默认值）
- get_first(): 兼容旧别名链（OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY）
- require(): 必需凭据缺失显式抛 CredentialError
- set()/rotate(): 进程内注入 / 轮换（覆盖环境变量）
- get_access_log(): 最小权限审计（记录谁在何时读取了什么）
- 可选加密落盘: save_file()/load_file() 使用 Fernet 加密 JSON（cryptography，可选依赖）
- 遮蔽: __repr__ 永不泄露明文

本模块只依赖标准库（cryptography 仅在加密落盘时惰性导入）。
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("competitor_agent.secret_vault")

ENCRYPTION_KEY_ENV = "COMPETITOR_SECRETS_KEY"
_DATA_DIR_ENV = "COMPETITOR_AGENT_DATA_DIR"


class CredentialError(Exception):
    """必需凭据缺失或无效"""

    def __init__(self, name: str, hint: str = "") -> None:
        self.name = name
        self.hint = hint
        msg = f"缺少必需凭据: {name}"
        if hint:
            msg += f"（{hint}）"
        super().__init__(msg)


@dataclass
class AccessRecord:
    """单次凭据读取的审计记录"""
    name: str
    owner: str
    timestamp: float


class SecretVault:
    """统一凭据池

    优先级：内存覆盖（set / load_file）> 环境变量 > 默认值。
    所有读取写入访问审计，遵循最小权限原则：
    各模块通过 owner 声明需要的凭据，调用方用 get_access_log() 回溯访问轨迹。
    """

    def __init__(self, access_log_limit: int = 2000) -> None:
        self._overrides: dict[str, str] = {}
        self._access_log: list[AccessRecord] = []
        self._access_log_limit = access_log_limit

    def get(self, name: str, owner: str = "", default: str | None = None) -> str | None:
        """读取单个凭据（内存覆盖 > 环境变量 > default）"""
        value = self._overrides.get(name)
        if value is None:
            value = os.getenv(name)
        if value is None:
            value = default
        if isinstance(value, str):
            value = value.strip()
        self._record(name, owner)
        return value

    def get_first(
        self,
        names: Sequence[str],
        owner: str = "",
        default: str | None = None,
    ) -> str | None:
        """按优先级读取多个候选名，返回第一个非空值"""
        for name in names:
            value = self._overrides.get(name)
            if value is None:
                value = os.getenv(name)
            if isinstance(value, str):
                value = value.strip()
            if value:
                self._record(name, owner)
                return value
        self._record(", ".join(names), owner)
        return default

    def require(self, name: str, owner: str = "", hint: str = "") -> str:
        """读取必需凭据，缺失时抛 CredentialError"""
        value = self.get(name, owner)
        if not value:
            raise CredentialError(name, hint)
        return value

    def set(self, name: str, value: str) -> None:
        """注入凭据（进程内覆盖环境变量，优先级最高）"""
        self._overrides[name] = value
        logger.debug("凭据已注入: %s", name)

    def rotate(self, name: str, value: str) -> None:
        """轮换凭据（语义命名，行为同 set）"""
        self.set(name, value)

    def unset(self, name: str) -> None:
        """移除内存覆盖（恢复使用环境变量）"""
        self._overrides.pop(name, None)

    def get_access_log(self) -> list[AccessRecord]:
        return list(self._access_log)

    def clear_access_log(self) -> None:
        self._access_log.clear()

    def save_file(self, path: str, key: str | None = None) -> None:
        """将当前内存覆盖加密落盘（Fernet 对称加密）"""
        import json

        from cryptography.fernet import Fernet

        fernet_key = key or os.getenv(ENCRYPTION_KEY_ENV)
        if not fernet_key:
            raise CredentialError(ENCRYPTION_KEY_ENV, hint="加密凭据文件需要 Fernet 密钥")
        payload = json.dumps(self._overrides, ensure_ascii=False).encode("utf-8")
        token = Fernet(fernet_key.encode()).encrypt(payload)
        with open(path, "wb") as f:
            f.write(token)
        logger.info("凭据已加密落盘: %s", path)

    def load_file(self, path: str, key: str | None = None) -> int:
        """从加密 JSON 文件加载凭据覆盖"""
        import json

        from cryptography.fernet import Fernet, InvalidToken

        fernet_key = key or os.getenv(ENCRYPTION_KEY_ENV)
        if not fernet_key:
            raise CredentialError(ENCRYPTION_KEY_ENV, hint="解密凭据文件需要 Fernet 密钥")
        with open(path, "rb") as f:
            token = f.read()
        try:
            payload = Fernet(fernet_key.encode()).decrypt(token)
        except InvalidToken:
            raise CredentialError(path, hint="密钥不匹配或文件损坏")
        data = json.loads(payload.decode("utf-8"))
        for name, value in data.items():
            self._overrides[name] = value
        logger.info("已加载 %d 个凭据: %s", len(data), path)
        return len(data)

    def _record(self, name: str, owner: str) -> None:
        if len(self._access_log) >= self._access_log_limit:
            self._access_log.pop(0)
        self._access_log.append(AccessRecord(name=name, owner=owner, timestamp=time.time()))

    def __repr__(self) -> str:
        return f"SecretVault(access_log={len(self._access_log)})"

    __str__ = __repr__


def get_data_dir() -> Path:
    """解析竞品 Agent 数据根目录

    优先级：``COMPETITOR_AGENT_DATA_DIR`` 环境变量 > 用户目录 ``~/.competitor_agent``。

    用于统一放置：凭据加密文件、记忆系统、向量库等。
    """
    raw = os.getenv(_DATA_DIR_ENV)
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path.home() / ".competitor_agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_reports_dir() -> Path:
    """解析报告输出根目录（默认 ``<data_dir>/reports``，仓库外）。

    用于统一放置：竞品/对比/消融/基准/告警/模板等生成物，避免写入仓库工作树。
    """
    path = get_data_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


vault = SecretVault()

