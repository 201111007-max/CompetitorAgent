"""工具护栏 — 参数校验 / 副作用守卫 / 速率限制 / 审计

解决 bugs.md P0 #2「工具护栏/参数校验缺失」：
- ToolArgumentValidator: 基于工具 inputSchema 的轻量 JSON Schema 子集校验 + 全局硬约束表
- SensitiveOperationGuard: 写操作/外部请求操作策略控制（CONFIRM/BLOCK/ALLOW）+ 审计
- ToolRateLimiter: 令牌桶速率限制（按工具 + 按会话，可整体关闭）
- AuditLog: 所有工具调用（含被拒）的结构化审计记录

设计文档：docs/superpowers/plans/post-match-review-agent/TOOL_GUARDRAIL_DESIGN.md
"""
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.tool_guard")


# ── 护栏异常类型 ──


class ToolArgumentError(Exception):
    """工具参数校验失败（非法参数绝不透传下游）"""

    def __init__(self, errors: List[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(errors))


class ConfirmationRequired(Exception):
    """敏感操作需要用户确认

    注意：不使用 Exception.args 属性名（会被基类覆盖），改用 tool_args。
    """

    def __init__(self, tool_name: str, tool_args: Dict[str, Any], reason: str = "") -> None:
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.reason = reason
        super().__init__(f"工具 '{tool_name}' 需要确认后调用")


class RateLimitExceeded(Exception):
    """工具调用频率超限"""

    def __init__(self, tool_name: str, wait_seconds: float = 0.0) -> None:
        self.tool_name = tool_name
        self.wait_seconds = wait_seconds
        super().__init__(f"工具 '{tool_name}' 调用过于频繁，请稍后再试")


class ToolBlockedError(Exception):
    """工具被策略直接阻断"""

    def __init__(self, tool_name: str, reason: str = "") -> None:
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(reason or f"工具 '{tool_name}' 已被策略阻断")


class ToolConfirmationProvider:
    """确认回调协议 — 由上层（如 Web 前端）实现

    confirm() 返回 True 表示用户确认放行，False 表示拒绝。
    """

    async def confirm(self, tool_name: str, args: Dict[str, Any]) -> bool:
        raise NotImplementedError


# ── 审计日志 ──


@dataclass
class AuditRecord:
    """单条工具调用审计记录"""
    timestamp: float
    tool_name: str
    args: Any
    decision: str
    reason: str
    session_id: str


class AuditLog:
    """工具调用审计日志（内存保留 + 结构化日志输出）

    decision 取值：allowed / rejected / confirm_required / confirmed /
    blocked / rate_limited。
    """

    def __init__(self, max_records: int = 5000, logger_name: str = "agent.tool_guard.audit") -> None:
        self._records: List[AuditRecord] = []
        self._max_records = max_records
        self._logger = get_logger(logger_name)

    def record(
        self,
        tool_name: str,
        args: Any,
        decision: str,
        reason: str = "",
        session_id: str = "",
    ) -> None:
        """写入一条审计记录"""
        record = AuditRecord(
            timestamp=time.time(),
            tool_name=tool_name,
            args=self._truncate_args(args),
            decision=decision,
            reason=reason,
            session_id=session_id,
        )
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records.pop(0)
        self._logger.info(
            "tool_call audit: tool=%s, decision=%s, reason=%s, session=%s",
            tool_name, decision, reason, session_id,
        )

    @property
    def records(self) -> List[AuditRecord]:
        """全部审计记录（最多 max_records 条）"""
        return list(self._records)

    @property
    def recent(self) -> List[AuditRecord]:
        """最近 50 条审计记录（新→旧）"""
        return list(reversed(self._records[-50:]))

    def clear(self) -> None:
        """清空审计记录（测试用）"""
        self._records.clear()

    @staticmethod
    def _truncate_args(args: Any, limit: int = 500) -> Any:
        """参数超过 500 字符时截断"""
        text = str(args)
        if len(text) <= limit:
            return args
        return text[:limit] + f"...(truncated, total {len(text)} chars)"


# ── 第一层：参数校验 ──


@dataclass
class ValidationResult:
    """参数校验结果"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    normalized_args: Dict[str, Any] = field(default_factory=dict)


class ToolArgumentValidator:
    """基于工具 inputSchema 的轻量 JSON Schema 子集校验器

    支持关键字：type/required/minimum/maximum/maxLength/enum/items/maxItems/pattern。
    在 schema 之上叠加全局硬约束表，两套规则合并生效，防上游限流与资源耗尽。

    归一化策略（避免 LLM 输出字符串当整数被误拒）：
    - integer/number 字段："123" → 123（可强转）
    - 拒绝向下转换：True 不是整数（bool 是 int 子类，需排除）
    """

    # 全局硬约束：ID 类参数范围（match_id 为 64 位，account/team 为 32 位）
    _ID_RANGES = {
        "match_id": (1, 2**63 - 1),
        "account_id": (1, 2**32 - 1),
        "team_id": (1, 2**32 - 1),
    }

    # 全局硬约束：数量类参数（默认上限 100）
    _COUNT_RANGES = {
        "limit": (1, 100),
        "num_results": (1, 100),
        "recent_matches": (1, 100),
        "top_k": (1, 100),
    }

    # 全局硬约束：特殊范围参数
    _SPECIAL_RANGES = {
        "fulltext_max_chars": (0, 50000),
        "time_threshold_minutes": (0, 120),
    }

    # 全局硬约束：整数列表参数（元素 integer，长度边界）
    _INT_LIST_PARAMS = {
        "item_ids": (1, 100),
        "match_ids": (1, 100),
    }

    # 全局硬约束：站点列表参数
    _SITES_MAX_LEN = 10
    _SITES_MAX_STR_LEN = 100

    # 所有字符串参数最大长度
    _MAX_STR_LEN = 200

    def validate(
        self,
        tool_name: str,
        args: Any,
        schema: Optional[Dict[str, Any]],
    ) -> ValidationResult:
        """校验工具参数并归一化

        Args:
            tool_name: 工具名称
            args: 原始参数字典
            schema: 工具参数 schema（MCP inputSchema 或本地 ToolSchema 转换结果）

        Returns:
            ValidationResult: 校验结果（含归一化后的参数）
        """
        if not isinstance(args, dict):
            return ValidationResult(valid=False, errors=["参数必须是对象"], normalized_args={})

        schema = schema if isinstance(schema, dict) else {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []

        errors: List[str] = []
        normalized: Dict[str, Any] = {}

        # 1. 必填检查
        for req in required:
            if req not in args:
                errors.append(f"缺少必填参数: {req}")

        # 2. 逐参数 schema 校验 + 归一化
        for key, value in args.items():
            prop = properties.get(key, {}) if isinstance(properties, dict) else {}
            norm, errs = self._check_value(key, value, prop)
            if errs:
                errors.extend(errs)
            else:
                normalized[key] = norm

        # 3. 全局硬约束表（只对出现在参数中的字段生效）
        for key, value in normalized.items():
            errors.extend(self._check_global_constraint(key, value))

        return ValidationResult(valid=not errors, errors=errors, normalized_args=normalized)

    # ── 单参数校验 ──

    def _check_value(self, key: str, value: Any, prop: Any) -> Tuple[Any, List[str]]:
        """校验单个参数并归一化，返回 (归一化值, 错误列表)"""
        errors: List[str] = []
        prop = prop if isinstance(prop, dict) else {}
        param_type = prop.get("type")

        if param_type == "integer":
            norm, err = self._coerce_int(value)
            if err:
                return value, [f"{key}: {err}"]
            value = norm
        elif param_type == "number":
            norm, err = self._coerce_number(value)
            if err:
                return value, [f"{key}: {err}"]
            value = norm
        elif param_type == "string":
            if isinstance(value, bool) or not isinstance(value, str):
                return value, [f"{key}: 期望字符串，实际 {type(value).__name__}"]
            max_len = prop.get("maxLength")
            if isinstance(max_len, int) and len(value) > max_len:
                return value, [f"{key}: 长度超过上限 {max_len}"]
            pattern = prop.get("pattern")
            if isinstance(pattern, str) and pattern:
                try:
                    if not re.search(pattern, value):
                        return value, [f"{key}: 格式不符合要求"]
                except re.error:
                    logger.warning("schema pattern 无效: key=%s, pattern=%s", key, pattern)
            enum = prop.get("enum")
            if isinstance(enum, list) and value not in enum:
                return value, [f"{key}: 值不在允许范围内 {enum}"]
        elif param_type == "boolean":
            if not isinstance(value, bool):
                return value, [f"{key}: 期望布尔值，实际 {type(value).__name__}"]
        elif param_type == "array":
            if not isinstance(value, list):
                return value, [f"{key}: 期望数组，实际 {type(value).__name__}"]
            items = prop.get("items")
            item_type = items.get("type") if isinstance(items, dict) else None
            if item_type == "integer":
                normalized_items: List[Any] = []
                for i, item in enumerate(value):
                    norm, err = self._coerce_int(item)
                    if err:
                        return value, [f"{key}[{i}]: {err}"]
                    normalized_items.append(norm)
                value = normalized_items
            max_items = prop.get("maxItems")
            if isinstance(max_items, int) and len(value) > max_items:
                return value, [f"{key}: 元素个数超过上限 {max_items}"]
        elif param_type == "object":
            if not isinstance(value, dict):
                return value, [f"{key}: 期望对象，实际 {type(value).__name__}"]
        else:
            # 无 schema 定义时的枚举兜底
            enum = prop.get("enum")
            if isinstance(enum, list) and value not in enum:
                return value, [f"{key}: 值不在允许范围内 {enum}"]

        # 数值范围（schema 内 minimum/maximum）
        if param_type in ("integer", "number"):
            minimum = prop.get("minimum")
            maximum = prop.get("maximum")
            if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and value < minimum:
                return value, [f"{key}: 小于最小值 {minimum}"]
            if isinstance(maximum, (int, float)) and not isinstance(maximum, bool) and value > maximum:
                return value, [f"{key}: 大于最大值 {maximum}"]

        return value, errors

    # ── 归一化 ──

    @staticmethod
    def _coerce_int(value: Any) -> Tuple[Any, str]:
        """整数归一化：'123' → 123；拒绝 bool 与小数"""
        if isinstance(value, bool):
            return value, "True/False 不是整数"
        if isinstance(value, int):
            return value, ""
        if isinstance(value, float) and value.is_integer():
            return int(value), ""
        if isinstance(value, str):
            try:
                return int(value.strip()), ""
            except (TypeError, ValueError):
                return value, f"无法解析为整数: {value!r}"
        return value, f"期望整数，实际 {type(value).__name__}"

    @staticmethod
    def _coerce_number(value: Any) -> Tuple[Any, str]:
        """数值归一化：'12.5' → 12.5"""
        if isinstance(value, bool):
            return value, "True/False 不是数值"
        if isinstance(value, (int, float)):
            return value, ""
        if isinstance(value, str):
            try:
                return float(value.strip()), ""
            except (TypeError, ValueError):
                return value, f"无法解析为数值: {value!r}"
        return value, f"期望数值，实际 {type(value).__name__}"

    # ── 全局硬约束表 ──

    def _check_global_constraint(self, key: str, value: Any) -> List[str]:
        """叠加全局硬约束（在 schema 之上）"""
        errors: List[str] = []

        for name, (lo, hi) in self._ID_RANGES.items():
            if key == name:
                errors.extend(self._check_int_range(key, value, lo, hi))

        for name, (lo, hi) in self._COUNT_RANGES.items():
            if key == name:
                errors.extend(self._check_int_range(key, value, lo, hi))

        for name, (lo, hi) in self._SPECIAL_RANGES.items():
            if key == name:
                errors.extend(self._check_int_range(key, value, lo, hi))

        if key in self._INT_LIST_PARAMS:
            lo, hi = self._INT_LIST_PARAMS[key]
            if not isinstance(value, list):
                errors.append(f"{key}: 期望整数列表")
            else:
                if not (lo <= len(value) <= hi):
                    errors.append(f"{key}: 元素个数必须在 [{lo}, {hi}] 之间")
                else:
                    for i, item in enumerate(value):
                        if isinstance(item, bool) or not isinstance(item, int):
                            errors.append(f"{key}[{i}]: 元素必须是整数")
                            break

        if key == "sites":
            if not isinstance(value, list):
                errors.append("sites: 期望字符串列表")
            else:
                if len(value) > self._SITES_MAX_LEN:
                    errors.append(f"sites: 元素个数超过上限 {self._SITES_MAX_LEN}")
                for s in value:
                    if isinstance(s, bool) or not isinstance(s, str):
                        errors.append("sites: 元素必须是字符串")
                        break
                    if len(s) > self._SITES_MAX_STR_LEN:
                        errors.append(f"sites: 元素长度超过上限 {self._SITES_MAX_STR_LEN}")
                        break
                    if "://" in s:
                        errors.append("sites: 禁止包含 URL 协议头")
                        break

        # 所有字符串 ≤ 200 字符
        if isinstance(value, str) and len(value) > self._MAX_STR_LEN:
            errors.append(f"{key}: 字符串长度超过上限 {self._MAX_STR_LEN}")

        return errors

    @staticmethod
    def _check_int_range(key: str, value: Any, lo: int, hi: int) -> List[str]:
        """整数范围检查"""
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{key}: 期望整数"]
        if value < lo or value > hi:
            return [f"{key}: 超出范围 [{lo}, {hi}]"]
        return []


# ── 第二层：敏感操作守卫 ──


class SensitiveOperationGuard:
    """敏感操作守卫 — 写/外部请求操作策略控制 + 审计

    策略：
    - CONFIRM: 需显式确认（抛 ConfirmationRequired，由上层确认后放行）
    - BLOCK:   直接阻断（抛 ToolBlockedError，不进入确认流程）
    - ALLOW:   放行

    确认机制：确认一次后，该工具在会话内后续调用直接放行。
    """

    CONFIRM = "confirm"
    BLOCK = "block"
    ALLOW = "allow"

    DEFAULT_POLICIES = {
        "request_match_parse": CONFIRM,
        "request_match_parses": CONFIRM,
        "search_dota_history": BLOCK,
        "inject_ward_report_html": CONFIRM,
        "inject_multi_match_ward_report_html": CONFIRM,
    }

    def __init__(
        self,
        policies: Optional[Dict[str, str]] = None,
        audit_log: Optional[AuditLog] = None,
    ) -> None:
        self._policies = dict(self.DEFAULT_POLICIES)
        if policies:
            self._policies.update(policies)
        self._confirmed: Dict[str, set] = {}
        self._audit_log = audit_log

    def check(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        session_id: str = "",
    ) -> Tuple[str, str]:
        """返回 (decision, reason)

        decision 取值为 CONFIRM / BLOCK / ALLOW。
        """
        args = args or {}
        policy = self._policies.get(tool_name, self.ALLOW)

        if policy == self.BLOCK:
            self._record(tool_name, args, "blocked", "默认阻断（外部请求，需显式配置）", session_id)
            return self.BLOCK, "该工具默认被阻断，如需使用请显式配置"

        if policy == self.CONFIRM:
            if tool_name in self._confirmed.get(session_id, set()):
                return self.ALLOW, "已确认"
            self._record(tool_name, args, "confirm_required", "写/外部操作需确认", session_id)
            return self.CONFIRM, "该工具执行有副作用，需要确认后调用"

        return self.ALLOW, ""

    def confirm(self, tool_name: str, session_id: str = "") -> None:
        """标记工具在某会话内已确认，后续调用放行"""
        self._confirmed.setdefault(session_id, set()).add(tool_name)
        self._record(tool_name, {}, "confirmed", "用户已确认", session_id)

    def _record(
        self,
        tool_name: str,
        args: Dict[str, Any],
        decision: str,
        reason: str,
        session_id: str,
    ) -> None:
        if self._audit_log is not None:
            self._audit_log.record(tool_name, args, decision, reason, session_id)


# ── 第三层：速率限制 ──


class ToolRateLimiter:
    """令牌桶速率限制 — 按工具 + 按会话双层控制（可整体禁用）

    定位：与成本无关，是可靠性兜底——匹配上游（OpenDota/SerpApi）硬性限流、
    保护 MCP Server 子进程不被高频调用压垮、打断 LLM 失控循环。
    确认本地只读且上游无配额约束后，可 enabled=False 整体关闭，
    不影响参数校验/敏感守卫/审计。
    """

    # 默认限速配置（次/分钟）
    DEFAULT_RATES = {
        "default": 30,                          # 只读工具
        "analyze_multi_match_wards": 10,        # 批量工具
        "search_dota_history": 5,               # 外部请求 + 网页抓取
        "request_match_parse": 3,               # 写操作队列
        "request_match_parses": 3,
        "global": 120,                          # 全局会话兜底（防打垮子进程）
    }

    # 突发倍数：桶容量 = 速率 × 突发倍数
    BURST_FACTOR = 2.0

    def __init__(
        self,
        enabled: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._enabled = enabled
        self._rates = dict(self.DEFAULT_RATES)
        if config:
            self._rates.update(config)
        self._buckets: Dict[str, Dict[str, float]] = {}

    def allow(self, tool_name: str, session_id: str = "") -> Tuple[bool, float]:
        """检查是否放行，返回 (是否放行, 需等待秒数)

        超频时由调用方抛出 RateLimitExceeded。
        """
        if not self._enabled:
            return True, 0.0
        now = time.monotonic()

        # 1. 全局会话兜底
        global_rate = self._rates.get("global", 120)
        ok_global, wait_global = self._consume(f"global:{session_id}", global_rate, now)
        if not ok_global:
            return False, wait_global

        # 2. 工具级限速
        rate = self._rates.get(tool_name, self._rates.get("default", 30))
        return self._consume(f"{session_id}:{tool_name}", rate, now)

    def reset(self, session_id: str = "") -> None:
        """清空限速状态（测试用）"""
        prefix = f"global:{session_id}" if session_id else "global:"
        self._buckets = {
            k: v for k, v in self._buckets.items()
            if session_id and not k.startswith(f"{session_id}:") and k != prefix
        }

    def _consume(self, key: str, rate: float, now: float) -> Tuple[bool, float]:
        """令牌桶消费：恒定速率补令牌，容量 = 速率 × 突发倍数"""
        capacity = max(1.0, rate * self.BURST_FACTOR)
        refill = rate / 60.0

        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = {"tokens": capacity, "last": now}
            self._buckets[key] = bucket
        else:
            elapsed = now - bucket["last"]
            bucket["tokens"] = min(capacity, bucket["tokens"] + elapsed * refill)
            bucket["last"] = now

        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True, 0.0

        wait = (1.0 - bucket["tokens"]) / refill if refill > 0 else 60.0
        return False, wait
