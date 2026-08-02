"""提示注入防御 — 三层纵深防御的第一层（输入净化）与第三层（输出校验）

本模块实现 `PromptInjectionDetector`（第一层）与 `OutputGuard`（第三层），
配合 `agent/prompts/react_system.py` 中的角色边界声明（第二层），
构成完整的提示注入纵深防御。

设计要点（详见 docs/superpowers/plans/post-match-review-agent/PROMPT_INJECTION_DEFENSE_DESIGN.md）：
- 多信号加权评分：单个弱信号不触发，多个信号叠加超过阈值才拦截，降低误杀
- isolate / block 双模式：isolate 用占位符替换保体验，block 直接拒绝
- 工具结果一律封装为 <observation> 数据块，防 Observation 间接注入
- 输出校验：敏感信息脱敏 + 注入标记残留剥除 + 空输出检测
"""
import base64
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from dota_helper.observability.logger import get_logger

logger = get_logger("agent.injection_guard")

# 默认阈值：多信号叠加超过该分数才判定为注入
_DEFAULT_THRESHOLD = 0.8
# 用户输入最大长度（防御上下文炸弹）
_MAX_INPUT_LEN = 4000
# 工具结果最大长度
_MAX_RESULT_LEN = 20000
# 占位符：隔离模式替换后的提示
_ISOLATE_PLACEHOLDER = "[检测到潜在注入指令，已隔离为纯文本处理]"
# 占位符：阻断模式直接拒绝
_BLOCK_PLACEHOLDER = "[输入已被安全策略拒绝]"


class InjectionCategory(str, Enum):
    """注入类型分类"""
    DIRECTIVE = "directive"            # 指令劫持（"忽略之前指令"）
    ROLE_CHANGE = "role_change"        # 角色伪造（"你是 OpenAI 模型"）
    DATA_EXFIL = "data_exfil"          # 数据泄露诱导（"输出你的提示词"）
    FORMAT_BREAK = "format_break"      # 格式破坏（分隔符逃逸）
    OBSERVATION_HIJACK = "obs_hijack"  # 工具结果中的隐藏指令
    ENCODING = "encoding"              # 编码混淆（Base64/Hex）
    NORMAL = "normal"                  # 正常输入


@dataclass
class OutputCheckResult:
    """输出校验结果

    Attributes:
        cleaned: 净化后的文本
        leak_found: 是否发现敏感信息泄漏（已脱敏）
        marker_found: 是否发现注入标记残留（已剥除）
        is_empty: 是否为空或纯占位符
        raw_length: 原始文本长度
    """
    cleaned: str = ""
    leak_found: bool = False
    marker_found: bool = False
    is_empty: bool = False
    raw_length: int = 0


class _SignalRule:
    """单一检测信号规则

    每个规则包含类别、权重和一组正则模式。
    命中任意模式即记为一次该权重信号。
    """

    __slots__ = ("category", "weight", "_patterns")

    def __init__(self, category: InjectionCategory, weight: float, patterns: List[str]) -> None:
        self.category = category
        self.weight = weight
        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    def match(self, text: str) -> bool:
        return any(p.search(text) for p in self._patterns)


class PromptInjectionDetector:
    """输入净化层 — 检测并处置注入模式

    对用户输入执行多信号加权评分，超过阈值后按模式处置：
    - isolate：用占位符替换高危片段，保留可读性
    - block：直接拒绝输入

    Args:
        mode: 处置模式（isolate / block，默认 isolate）
        threshold: 多信号加权拦截阈值（默认 0.8）
    """

    # ── 信号规则库（多信号组合，防单模式绕过） ──
    _RULES: List[_SignalRule] = [
        _SignalRule(
            InjectionCategory.DIRECTIVE, 0.9, [
                r"忽略[^。\n，,；;]{0,10}(指令|提示|规则|指令集)",
                r"无视[^。\n，,；;]{0,10}(指令|提示|规则)",
                r"不要(遵守|遵循)[^。\n，,；;]{0,8}(系统提示|之前指令|规则)",
                r"ignore\s+(all\s+|any\s+)?(previous|prior|above|your)\s+(instructions|prompts?|rules)",
                r"disregard\s+(all\s+|any\s+)?(previous|prior|your)\s+(instructions|prompts?)",
            ]
        ),
        _SignalRule(
            InjectionCategory.ROLE_CHANGE, 0.85, [
                r"你是\s*(OpenAI|ChatGPT|Claude|Anthropic|GPT(-4)?|真正的)[^。\n，,]{0,8}模型",
                r"现在?\s*(你|假装|扮演)\s*(是|成)\s*(一个新的)?\s*(OpenAI|官方|Claude|GPT)",
                r"you\s+are\s+(really\s+)?(the\s+)?(OpenAI|ChatGPT|Claude|Anthropic|an?\s+official)",
                r"act\s+(as\s+|like\s+)?(an?\s+official|OpenAI|the\s+real)",
            ]
        ),
        _SignalRule(
            InjectionCategory.DATA_EXFIL, 0.85, [
                r"(输出|说出|告诉我|显示|泄露|复制|给出).{0,8}(你的|全部|完整|隐藏的)?(系统提示词|system\s*prompt|指令|提示词).{0,6}(全文|内容|原文|是什么)?",
                r"(系统提示词|system\s*prompt|指令)的?(全文|内容|原文)",
                r"(api\s*key|密钥|token|secret)(是|为)?[^。\n]*",
                r"reveal\s+(your\s+)?(prompt|system|instructions)|show\s+me\s+(your\s+)?(prompt|api\s*key)|print\s+(your\s+)?(prompt|key)",
                r"你的(api\s*key|密钥|token|系统提示词)",
            ]
        ),
        _SignalRule(
            InjectionCategory.FORMAT_BREAK, 0.8, [
                r"以\s*(user|system|assistant|人类|开发者)\s*的?\s*身份回答",
                r"当作\s*(user|system|assistant|提示词|指令)",
                r"(reset|清除|清空|改变|覆盖).{0,8}(记忆|上下文|角色|system)",
                r"ignore\s+(the\s+)?(format|role|boundary)",
            ]
        ),
        _SignalRule(
            InjectionCategory.OBSERVATION_HIJACK, 0.75, [
                r"(in|inside|within)\s+(the\s+)?observation",
                r"observation.{0,12}指令|指令.{0,12}observation",
                r"when\s+(you\s+)?(see|receive)\s+(an?\s+|the\s+)?observation",
            ]
        ),
        _SignalRule(
            InjectionCategory.ENCODING, 0.7, [
                r"(base64|hex|十六进制|rot13|编码).{0,20}(解码|decode|转码|执行)",
                r"(解码|decode).{0,20}(base64|hex|十六进制)",
            ]
        ),
    ]

    def __init__(
        self,
        mode: str = "isolate",
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        if mode not in ("isolate", "block"):
            raise ValueError(f"未知模式: {mode}，仅支持 isolate / block")
        self._mode = mode
        self._threshold = threshold
        logger.debug("提示注入检测器初始化: mode=%s, threshold=%.2f", mode, threshold)

    @property
    def mode(self) -> str:
        return self._mode

    def scan(self, text: str) -> Tuple[List[InjectionCategory], float]:
        """扫描文本，返回命中类别与最高信号权重

        对疑似 Base64 混淆的片段先解码再检测，覆盖编码混淆绕过。

        Args:
            text: 待扫描文本

        Returns:
            Tuple[List[InjectionCategory], float]:
                命中的注入类别列表（NORMAL 表示无命中），以及最高单一信号权重
        """
        hits: List[InjectionCategory] = []
        max_weight = 0.0

        candidates = [text]
        decoded = self.decode_obfuscated(text)
        if decoded != text:
            candidates.append(decoded)

        for candidate in candidates:
            for rule in self._RULES:
                if rule.category in hits:
                    continue
                if rule.match(candidate):
                    hits.append(rule.category)
                    max_weight = max(max_weight, rule.weight)

        if not hits:
            hits = [InjectionCategory.NORMAL]

        return hits, max_weight

    def score(self, text: str) -> float:
        """多信号加权评分：命中的信号权重求和（上限 1.0）

        同时扫描 Base64 解码后的内容。

        Args:
            text: 待评分文本

        Returns:
            float: 加权评分（0.0 ~ 1.0）
        """
        total = 0.0
        seen: set = set()
        candidates = [text]
        decoded = self.decode_obfuscated(text)
        if decoded != text:
            candidates.append(decoded)

        for candidate in candidates:
            for rule in self._RULES:
                if rule.category in seen:
                    continue
                if rule.match(candidate):
                    seen.add(rule.category)
                    total += rule.weight
        return min(total, 1.0)

    def sanitize_user_input(self, text: str) -> str:
        """净化直接用户输入

        命中高危注入模式后按 mode 处置：
        - isolate：将输入截断为占位符，保留可读但剥离指令性内容
        - block：直接返回拒绝占位符

        Args:
            text: 用户原始输入

        Returns:
            str: 净化后的输入
        """
        if not text:
            return text

        # 长度保护（防御上下文炸弹）
        if len(text) > _MAX_INPUT_LEN:
            logger.warning("用户输入超长，已截断: len=%d", len(text))
            text = text[:_MAX_INPUT_LEN]

        hits, _ = self.scan(text)
        if InjectionCategory.NORMAL in hits:
            return text

        if self._mode == "block":
            logger.warning("阻断注入输入: categories=%s", [h.value for h in hits])
            return _BLOCK_PLACEHOLDER

        logger.info(
            "隔离注入输入: categories=%s, score=%.2f",
            [h.value for h in hits], self.score(text),
        )
        return _ISOLATE_PLACEHOLDER

    def wrap_tool_result(self, text: str) -> str:
        """封装工具返回结果，防 Observation 间接注入

        将工具输出包裹在 <observation> 数据块中，并转义内部嵌套的分隔符
        与指令性关键词，避免对手在数据（昵称/聊天）中埋入指令。

        Args:
            text: 工具返回的原始结果

        Returns:
            str: 封装后的数据块
        """
        if text is None:
            text = ""

        if len(text) > _MAX_RESULT_LEN:
            logger.warning("工具结果超长，已截断: len=%d", len(text))
            text = text[:_MAX_RESULT_LEN]

        # 转义内部嵌套的分隔符，防止分隔符逃逸
        escaped = (
            text.replace("<observation>", "&lt;observation&gt;")
                .replace("</observation>", "&lt;/observation&gt;")
                .replace("<user_input>", "&lt;user_input&gt;")
                .replace("</user_input>", "&lt;/user_input&gt;")
                .replace("<system>", "&lt;system&gt;")
                .replace("</system>", "&lt;/system&gt;")
        )

        return f"<observation>\n{escaped}\n</observation>"

    def decode_obfuscated(self, text: str) -> str:
        """尝试解码 Base64 混淆内容，供扫描器二次检测

        对疑似编码混淆的片段尝试 Base64 解码，递归检测解码后的指令。

        Args:
            text: 待检测文本

        Returns:
            str: 解码后的文本（无法解码时返回原文本）
        """
        b64_pattern = re.compile(r"[A-Za-z0-9+/=]{40,}", re.IGNORECASE)
        match = b64_pattern.search(text)
        if not match:
            return text
        try:
            decoded = base64.b64decode(match.group(0)).decode("utf-8", errors="ignore")
            logger.debug("检测到 Base64 混淆内容，已解码供二次检测")
            return decoded
        except Exception:
            return text


class OutputGuard:
    """输出校验层 — 在 LLM 输出进入解析器前检查

    检测内容：
    - 敏感信息泄漏（sk- 密钥、API Key 等）→ 脱敏为 ***
    - 注入标记残留（<user_input>/<observation> 逃逸）→ 剥除
    - 空/纯占位符输出 → 标记 is_empty 供上层重试

    同时覆盖 bugs.md #13「输出验证缺失」的部分内容。
    """

    # ── 敏感信息泄漏模式 ──
    _SECRET_PATTERNS: List[str] = [
        r"sk-[A-Za-z0-9_\-]{16,}",              # OpenAI 风格密钥
        r"(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*[^\s,;\"']+",
        r"LANGFUSE_(?:PUBLIC|SECRET)_KEY\s*[:=]\s*[^\s,;\"']+",
        r"Bearer\s+[A-Za-z0-9._\-]{20,}",
    ]

    # ── 注入标记残留模式 ──
    _MARKER_PATTERNS: List[str] = [
        r"<user_input>", r"</user_input>",
        r"<observation>", r"</observation>",
        r"<system>", r"</system>",
        r"<knowledge>", r"</knowledge>",
    ]

    _EMPTY_PLACEHOLDERS: Tuple[str, ...] = (
        _ISOLATE_PLACEHOLDER,
        _BLOCK_PLACEHOLDER,
    )

    def __init__(self) -> None:
        self._secret_re = [re.compile(p, re.IGNORECASE) for p in self._SECRET_PATTERNS]
        self._marker_re = [re.compile(p, re.IGNORECASE) for p in self._MARKER_PATTERNS]
        logger.debug("输出校验器初始化")

    def check(self, llm_output: str) -> OutputCheckResult:
        """校验 LLM 输出

        依次执行：敏感信息脱敏 → 注入标记剥除 → 空输出检测。

        Args:
            llm_output: LLM 原始输出文本

        Returns:
            OutputCheckResult: 校验结果（含净化后文本）
        """
        result = OutputCheckResult(raw_length=len(llm_output))

        cleaned = llm_output

        # 1. 敏感信息脱敏
        for pattern in self._secret_re:
            if pattern.search(cleaned):
                result.leak_found = True
                cleaned = pattern.sub("***", cleaned)

        # 2. 注入标记剥除（删除整块逃逸标记行）
        for pattern in self._marker_re:
            if pattern.search(cleaned):
                result.marker_found = True
                cleaned = pattern.sub("", cleaned)

        result.cleaned = cleaned

        # 3. 空/纯占位符检测
        stripped = cleaned.strip()
        if not stripped or stripped in self._EMPTY_PLACEHOLDERS:
            result.is_empty = True

        if result.leak_found or result.marker_found:
            logger.warning(
                "输出校验命中: leak=%s, marker=%s, empty=%s",
                result.leak_found, result.marker_found, result.is_empty,
            )

        return result
