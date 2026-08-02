"""统一凭据池 — 集中管理 API Key / Secret

解决 bugs.md P0 #3「凭据/密钥管理分散」：
- SecretVault: 单点读取（内存覆盖 > 环境变量 > 默认值），消除各模块分散的 os.getenv
- get_first(): 兼容旧别名链（OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY），解析逻辑集中在此
- require(): 必需凭据缺失显式抛 CredentialError（替代静默 ""/None）
- set()/rotate(): 进程内注入 / 轮换（覆盖环境变量）
- get_access_log(): 最小权限审计（记录谁在何时读取了什么）
- 可选加密落盘: save_file()/load_file() 使用 Fernet 加密 JSON（cryptography，可选依赖）
- 遮蔽: __repr__ 永不泄露明文

注意：本模块只依赖标准库（cryptography 仅在加密落盘时惰性导入），
以保证被 llm / mcp_server / observability 等下层模块导入时不产生循环依赖。
"""
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger("dota_helper.secret_vault")


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
    所有读取都会写入访问审计，遵循最小权限原则：
    各模块通过 owner 声明自己需要的凭据，调用方可用 get_access_log() 回溯访问轨迹。
    """

    def __init__(self, access_log_limit: int = 2000) -> None:
        self._overrides: Dict[str, str] = {}
        self._access_log: List[AccessRecord] = []
        self._access_log_limit = access_log_limit

    def get(self, name: str, owner: str = "", default: Optional[str] = None) -> Optional[str]:
        """读取单个凭据（内存覆盖 > 环境变量 > default）

        Args:
            name: 凭据名（环境变量名）
            owner: 读取方标识（用于审计）
            default: 环境变量缺失时的兜底值

        Returns:
            凭据值，未配置时返回 default（默认 None）
        """
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
        default: Optional[str] = None,
    ) -> Optional[str]:
        """按优先级读取多个候选名，返回第一个非空值

        用于兼容旧的多环境变量别名（如 OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY）。
        解析逻辑集中在此，调用方无需自行展开。

        Args:
            names: 按优先级排列的候选环境变量名
            owner: 读取方标识（用于审计）
            default: 全部缺失时的兜底值

        Returns:
            第一个非空值；全部缺失返回 default
        """
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
        """读取必需凭据，缺失时抛 CredentialError（替代静默返回空串/None）

        Args:
            name: 凭据名（环境变量名）
            owner: 读取方标识（用于审计）
            hint: 缺失时的补充提示（如配置指引）

        Returns:
            非空凭据值

        Raises:
            CredentialError: 凭据未配置或为空
        """
        value = self.get(name, owner)
        if not value:
            raise CredentialError(name, hint)
        return value

    def set(self, name: str, value: str) -> None:
        """注入凭据（进程内覆盖环境变量，优先级最高）

        Args:
            name: 凭据名
            value: 凭据值
        """
        self._overrides[name] = value
        logger.debug("凭据已注入: %s", name)

    def rotate(self, name: str, value: str) -> None:
        """轮换凭据（语义化命名，行为同 set）

        Args:
            name: 凭据名
            value: 新的凭据值
        """
        self.set(name, value)

    def unset(self, name: str) -> None:
        """移除内存覆盖（恢复使用环境变量）"""
        self._overrides.pop(name, None)

    def get_access_log(self) -> List[AccessRecord]:
        """返回访问审计日志（按读取时间顺序）"""
        return list(self._access_log)

    def clear_access_log(self) -> None:
        """清空访问审计日志"""
        self._access_log.clear()

    def save_file(self, path: str, key: Optional[str] = None) -> None:
        """将当前内存覆盖加密落盘（Fernet 对称加密）

        Args:
            path: 输出文件路径
            key: Fernet 密钥（URL-safe base64），缺省读 DOTA_SECRETS_KEY 环境变量

        Raises:
            CredentialError: 缺少加密密钥
        """
        import json

        from cryptography.fernet import Fernet

        fernet_key = key or os.getenv("DOTA_SECRETS_KEY")
        if not fernet_key:
            raise CredentialError("DOTA_SECRETS_KEY", hint="加密凭据文件需要 Fernet 密钥")
        payload = json.dumps(self._overrides, ensure_ascii=False).encode("utf-8")
        token = Fernet(fernet_key.encode()).encrypt(payload)
        with open(path, "wb") as f:
            f.write(token)
        logger.info("凭据已加密落盘: %s", path)

    def load_file(self, path: str, key: Optional[str] = None) -> int:
        """从加密 JSON 文件加载凭据覆盖

        Args:
            path: 输入文件路径
            key: Fernet 密钥，缺省读 DOTA_SECRETS_KEY 环境变量

        Returns:
            加载的凭据数量

        Raises:
            CredentialError: 缺少密钥、密钥不匹配或文件损坏
        """
        import json

        from cryptography.fernet import Fernet, InvalidToken

        fernet_key = key or os.getenv("DOTA_SECRETS_KEY")
        if not fernet_key:
            raise CredentialError("DOTA_SECRETS_KEY", hint="解密凭据文件需要 Fernet 密钥")
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


vault = SecretVault()
