"""DotaHelperAgent API Server

基于 ReAct Agent 架构的 Flask API 后端，提供完整的 Agent 推理循环。
前端使用 Vue 3 + TypeScript + Vite，位于 frontend/ 目录。
"""

import sys
from pathlib import Path
from flask import Flask, request, jsonify, Response, g, stream_with_context
from flask_cors import CORS
import json
import time
import uuid
import threading
import re
import queue
import schedule
from typing import Optional, Dict, List, Any, Tuple, Generator
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent import DotaHelperAgent
from core.agent_controller import AgentController
from core.tool_registry import ToolRegistry
from core.conversation_manager import ConversationManager
from tools.agent_tools import create_all_tools
from core.config import AgentConfig, LLMConfig
from utils.localization import DotaLocalizer
from utils.llm_client import LLMClient
from utils.log_config import setup_logging_with_memory, get_logger
from utils.memory_log_handler import get_memory_handler
from utils.trace_context import (
    TraceContext, TraceSpan, set_current_trace, get_current_trace,
    generate_trace_id, get_current_trace_info
)

# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient
    from utils.langfuse_config import LangfuseConfig
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
    LangfuseConfig = None

# 初始化日志系统
logger, memory_handler = setup_logging_with_memory(
    log_level="DEBUG",
    daily_max_bytes=300*1024*1024,  # 300MB 每天分片
    memory_max_entries=10000,
    console_output=True
)

# 获取应用日志记录器
app_logger = get_logger("web_app", component="web")

app = Flask(__name__)
CORS(app)

# 全局变量
agent = None
agent_controller = None
llm_client = None
conversation_manager = None
cache_warming = False
cache_ready = False
localizer = DotaLocalizer()
api_client = None  # 全局 API 客户端实例，用于缓存刷新

# 日志目录（可配置，便于测试）
LOG_DIR = Path(__file__).parent.parent / "logs"

# 初始化 Langfuse 监控（可选）
project_root = Path(__file__).parent.parent
if LANGFUSE_AVAILABLE:
    langfuse_config = LangfuseConfig(config_path=str(project_root / "config" / "langfuse_config.yaml"))
    langfuse_client = LangfuseClient.get_instance()
    langfuse_client.init(config=langfuse_config.to_dict())
else:
    langfuse_client = None

HERO_PARSE_PROMPT = """你是一个 Dota 2 英雄名称解析专家。请从用户输入中准确提取英雄名称。

## 任务
从用户输入中识别所有提到的 Dota 2 英雄，并判断他们是己方还是敌方。

## 输出格式
严格返回以下 JSON 格式，不要包含任何其他内容：
{{
    "our_heroes": ["己方英雄英文名称列表"],
    "enemy_heroes": ["敌方英雄英文名称列表"],
    "confidence": 0.95
}}

## 判断规则
1. **敌方英雄标识词**：敌方、对面、对方、enemy、克制、对面有、敌方有、地方（typo，意为敌方）
2. **己方英雄标识词**：我方、我们、己方、our、we、我们选了、我们有、我方有
3. **默认规则**：
   - 如果用户只说"有"某个英雄，没有明确说明是己方还是敌方，默认为**敌方**
   - 如果用户说"推荐英雄"、"选什么英雄"等，前面提到的英雄通常是己方已选的
   - 如果用户说"克制XX"，XX 是敌方英雄
4. **模糊处理**：
   - 如果无法确定是己方还是敌方，根据上下文推断
   - 如果完全无法确定，放入 enemy_heroes（默认假设为敌方）

## 英雄名称处理
1. **必须转换为英文名称**，使用 Dota 2 官方英文名
2. 常见英雄映射参考：
   - 虚空假面 → faceless_void, 帕格纳 → pugna, 沙王 → sand_king
   - 敌法 → anti-mage, 幻影刺客 → phantom_assassin, 帕吉 → pudge
   - 斧王 → axe, 剑圣 → juggernaut, 影魔 → shadow_fiend
   - 祈求者/卡尔 → invoker, 水晶 → crystal_maiden, 莱恩 → lion
   - 斯温 → sven, 小小 → tiny, 军团 → legion_commander
   - 小鱼 → slark, 兽王 → beastmaster, 小鹿 → enchantress
   - 黑鸟 → obsidian_destroyer, 小黑 → drow_ranger
   - 司夜刺客 → nyx_assassin, 风暴之灵 → storm_spirit, 马格纳斯 → magnus
   - 斯拉克 → slark, 暗夜魔王 → night_stalker, 风行者 → windranger
3. 如果不确定英文名，尽量使用拼音或音译，保持小写，空格用下划线

## 示例
用户输入："我方英雄有虚空假面,帕格纳,沙王，推荐我选什么英雄"
输出：{{"our_heroes": ["faceless_void", "pugna", "sand_king"], "enemy_heroes": [], "confidence": 0.95}}

用户输入："对面有帕吉和斧王，选什么克制"
输出：{{"our_heroes": [], "enemy_heroes": ["pudge", "axe"], "confidence": 0.95}}

用户输入："我们选了影魔，对面有宙斯和水晶"
输出：{{"our_heroes": ["shadow_fiend"], "enemy_heroes": ["zeus", "crystal_maiden"], "confidence": 0.95}}

用户输入："有帕吉和斧王"（未明确说明是己方还是敌方）
输出：{{"our_heroes": [], "enemy_heroes": ["pudge", "axe"], "confidence": 0.7}}

## 用户输入
{query}

请只返回 JSON，不要其他任何内容："""


ITEM_PARSE_PROMPT = """你是一个 Dota 2 物品名称解析器。请从用户输入中提取物品名称。

支持的中英文物品名称：
- 英文名如：bfury, bkb, blink, aghanim, manta, hex
- 中文名如：圣剑、跳刀、黑皇杖、辉耀、羊刀

请从以下用户输入中提取所有物品名称，返回 JSON 格式：
{{
    "items": ["物品列表"]
}}

规则：
- 只返回物品的**英文名称**
- 如果没有找到任何物品，返回空列表

用户输入：{query}

请只返回 JSON，不要其他内容："""


def get_llm_client() -> Optional[LLMClient]:
    global llm_client
    if llm_client is None:
        try:
            llm_config = LLMConfig.from_yaml()
            if llm_config.enabled:
                llm_client = LLMClient(llm_config)
                app_logger.info("LLM client initialized successfully")
            else:
                llm_client = None
                app_logger.warning("LLM is disabled in config")
        except Exception as e:
            app_logger.error_ctx(f"Failed to initialize LLM client: {e}", extra_data={"error": str(e)})
            llm_client = None
    return llm_client


from functools import lru_cache


@lru_cache(maxsize=100)
def parse_heroes_with_llm_cached(query: str) -> tuple:
    """带缓存的英雄解析（缓存 100 个查询）
    
    注意：lru_cache 要求参数必须是可哈希的，所以返回 tuple 而不是 dict
    """
    result = parse_heroes_with_llm(query)
    return (tuple(result["our_heroes"]), tuple(result["enemy_heroes"]), result["confidence"])


def fallback_parse(query: str) -> dict:
    """降级解析策略：简单的关键词匹配
    
    当 LLM 解析失败时使用简单的关键词匹配作为降级方案
    """
    enemy_keywords = ["敌方", "对面", "对方", "enemy", "克制"]
    our_keywords = ["己方", "我方", "我们", "our", "we"]
    
    our_heroes = []
    enemy_heroes = []
    
    # 简单的关键词匹配
    query_lower = query.lower()
    
    # 检测敌方英雄
    if any(kw in query_lower for kw in enemy_keywords):
        # 尝试提取英雄名（简单实现）
        pass
    
    # 检测己方英雄
    if any(kw in query_lower for kw in our_keywords):
        # 尝试提取英雄名（简单实现）
        pass
    
    return {
        "our_heroes": our_heroes,
        "enemy_heroes": enemy_heroes,
        "confidence": 0.3
    }


def parse_heroes_with_llm(query: str) -> Dict[str, Any]:
    """使用 LLM 从 query 中解析英雄名称（增强版）
    
    完全依赖 LLM 进行英雄名称解析，支持缓存和降级策略。
    
    Args:
        query: 用户输入的查询文本
        
    Returns:
        dict: 包含 our_heroes、enemy_heroes 和 confidence 的字典
    """
    client = get_llm_client()
    if client is None:
        app_logger.warning("LLM 客户端未初始化，使用降级解析")
        return fallback_parse(query)

    try:
        messages = [
            {"role": "user", "content": HERO_PARSE_PROMPT.format(query=query)}
        ]
        response = client.chat(messages, max_tokens=512, temperature=0.1)

        if "error" in response:
            app_logger.warning(f"LLM 解析失败：{response['error']}，使用降级解析")
            return fallback_parse(query)

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # 提取 JSON 内容（可能包含 markdown 代码块）
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\{[\s\S]*\}', content, re.DOTALL)
            json_str = json_match.group() if json_match else content

        result = json.loads(json_str)
        parsed = {
            "our_heroes": result.get("our_heroes", []),
            "enemy_heroes": result.get("enemy_heroes", []),
            "confidence": result.get("confidence", 0.5)
        }
        
        app_logger.info(f"LLM 解析成功: our={parsed['our_heroes']}, enemy={parsed['enemy_heroes']}, confidence={parsed['confidence']}")
        return parsed
        
    except json.JSONDecodeError as e:
        app_logger.error(f"JSON 解析失败: {e}")
        app_logger.error(f"原始内容: {content}")
        return fallback_parse(query)
    except Exception as e:
        import traceback
        app_logger.error(f"LLM 解析异常：{e}")
        app_logger.error(f"Traceback: {traceback.format_exc()}")
        return fallback_parse(query)



def parse_items_with_llm(query: str) -> Dict[str, List[str]]:
    """使用 LLM 从 query 中解析物品名称"""
    client = get_llm_client()
    if client is None:
        return {"items": []}

    try:
        messages = [
            {"role": "user", "content": ITEM_PARSE_PROMPT.format(query=query)}
        ]
        response = client.chat(messages, max_tokens=512, temperature=0.1)

        if "error" in response:
            app_logger.warning(f"LLM 解析物品失败：{response['error']}")
            return {"items": []}

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {"items": result.get("items", [])}
    except Exception as e:
        app_logger.warning(f"LLM 解析物品异常：{e}")

    return {"items": []}


def parse_hero_from_query(query: str) -> Dict[str, Any]:
    """从 query 中提取单个英雄名称（用于出装/技能查询）"""
    if "出装" in query or "装备" in query or "item" in query.lower():
        prompt = f"""从以下用户输入中提取英雄名称，只返回一个英雄名称（英文名）：

用户输入：{query}

只返回英雄英文名，如 axe、pudge，不要其他内容。如果没有找到，返回空字符串："""
    elif "技能" in query or "加点" in query or "skill" in query.lower():
        prompt = f"""从以下用户输入中提取英雄名称，只返回一个英雄名称（英文名）：

用户输入：{query}

只返回英雄英文名，如 axe、pudge，不要其他内容。如果没有找到，返回空字符串："""
    else:
        return ""

    client = get_llm_client()
    if client is None:
        return ""

    try:
        messages = [{"role": "user", "content": prompt}]
        response = client.chat(messages, max_tokens=128, temperature=0.1)

        if "error" in response:
            return ""

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        hero = re.sub(r'[^a-z_]', '', content.lower())
        return hero
    except Exception as e:
        app_logger.warning(f"LLM 解析英雄名异常：{e}")
        return ""


def warm_cache() -> None:
    global cache_warming, cache_ready
    if cache_warming or cache_ready:
        return
    cache_warming = True
    app_logger.info("正在预热缓存，请稍候...")
    try:
        agt = get_agent()
        client = agt.client
        heroes = client.get_heroes()
        if heroes:
            enemy_ids = [1, 11, 15, 23, 25]
            for hid in enemy_ids:
                matchups = client.get_hero_matchups(hid)
                app_logger.info(f"已缓存英雄 {hid} 的克制数据")
        cache_ready = True
        app_logger.info("缓存预热完成！")
    except Exception as e:
        app_logger.error(f"缓存预热失败：{e}")
    cache_warming = False


def refresh_all_heroes_cache() -> None:
    """全量刷新所有英雄克制数据缓存（每日定时任务）"""
    global api_client
    
    try:
        app_logger.info("="*60)
        app_logger.info("开始全量刷新英雄克制数据缓存")
        app_logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        app_logger.info("="*60)
        
        # 获取 API 客户端
        if api_client is None:
            agt = get_agent()
            api_client = agt.client
        
        # 执行全量预热
        api_client.warm_up_cache(full_warmup=True)
        
        app_logger.info("全量缓存刷新完成")
        app_logger.info("="*60)
        
    except Exception as e:
        import traceback
        app_logger.error(f"全量缓存刷新失败: {e}")
        app_logger.error(traceback.format_exc())


def start_cache_scheduler() -> None:
    """启动缓存定时刷新任务"""
    # 每天凌晨 3 点执行全量缓存刷新
    schedule.every().day.at("03:00").do(refresh_all_heroes_cache)
    
    app_logger.info("已启动每日缓存刷新任务（每天 03:00）")
    
    # 在后台线程中运行调度器
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()


def initialize_agent_controller() -> None:
    """初始化 Agent 和 Agent Controller"""
    global agent, agent_controller, conversation_manager
    
    if agent_controller is not None:
        return agent_controller
    
    try:
        # 加载配置
        config = AgentConfig()
        
        # 创建会话管理器
        conversation_manager = ConversationManager(
            storage_dir="memory",
            session_ttl=1800,
            max_turns=20,
            max_context_turns=5
        )
        app_logger.info("ConversationManager 初始化完成")
        
        # 创建 DotaHelperAgent（带 Memory 支持）
        agent = DotaHelperAgent(
            config=config,
            enable_memory=True,
            memory_dir="memory"
        )
        
        # 创建 Tool Registry
        registry = ToolRegistry()
        
        # 创建所有 Agent Tools
        tools = create_all_tools(
            hero_analyzer=agent.hero_analyzer,
            item_recommender=agent.item_recommender,
            skill_builder=agent.skill_builder,
            client=agent.client
        )
        
        # 注册所有 Tools
        registry.register_batch(tools)
        app_logger.info(f"已注册 {len(registry)} 个 Agent Tools")
        
        # 获取 LLM 客户端
        llm_client = get_llm_client()
        if llm_client is None:
            app_logger.error("LLM 客户端未初始化，无法使用智能工具选择")
            raise Exception("LLM 客户端未初始化")
        
        # 创建 Agent Controller
        agent_controller = AgentController(
            tool_registry=registry,
            llm_client=llm_client,
            memory=agent.memory,
            conversation_manager=conversation_manager,
            max_turns=5,
            enable_reflection=True,
            enable_memory=True,
            metacognition_config={
                "type": "rule_based",
                "clarification_threshold": "low",
                "weights": {
                    "knowledge_coverage": 0.35,
                    "data_quality": 0.25,
                    "tool_match": 0.20,
                    "memory_relevance": 0.20
                }
            }
        )
        
        app_logger.info("Agent Controller 初始化完成（含元认知评估器）")
        return agent_controller
        
    except Exception as e:
        app_logger.error(f"Agent Controller 初始化失败：{e}")
        # 回退到基本模式
        agent = DotaHelperAgent()
        return None


@app.before_request
def setup_trace_context() -> None:
    """每个请求初始化 Trace 上下文"""
    # 优先从 Header 获取，其次从 Body，最后生成新的
    trace_id = request.headers.get('X-Trace-ID')
    session_id = request.headers.get('X-Session-ID')
    
    # 如果是 POST/PUT 请求，尝试从 body 获取
    if not trace_id and request.is_json:
        try:
            body = request.get_json(silent=True)
            if body:
                trace_id = body.get('trace_id')
                session_id = body.get('session_id')
        except Exception:
            pass
    
    # 如果仍然没有，生成新的
    if not trace_id:
        trace_id = generate_trace_id()
    if not session_id:
        session_id = f"sess_{uuid.uuid4().hex[:9]}"
    
    # 创建 Trace 上下文
    trace_ctx = TraceContext(
        trace_id=trace_id,
        span_id="root",
        session_id=session_id,
        operation=request.endpoint or "unknown"
    )
    
    # 存储到 Flask g 对象和 contextvars
    g.trace_ctx = trace_ctx
    set_current_trace(trace_ctx)
    
    # Langfuse 追踪（可选）
    if langfuse_client and langfuse_client.enabled:
        g.langfuse_trace = langfuse_client.observation(
            name=f"request_{request.path.replace('/', '_')}",
            as_type="chain",
            metadata={"path": request.path, "method": request.method, "trace_id": trace_id, "session_id": session_id}
        )
    
    # 记录请求开始
    app_logger.info_ctx(
        "Request started",
        session_id=session_id,
        extra_data={
            'trace_id': trace_id,
            'method': request.method,
            'path': request.path,
            'client_ip': request.remote_addr
        }
    )


@app.after_request
def cleanup_trace_context(response: Response) -> Response:
    """请求结束后清理并记录"""
    trace_ctx = getattr(g, 'trace_ctx', None)
    if trace_ctx:
        duration_ms = int((time.time() - trace_ctx.start_time) * 1000)
        app_logger.info_ctx(
            "Request completed",
            session_id=trace_ctx.session_id,
            extra_data={
                'trace_id': trace_ctx.trace_id,
                'status_code': response.status_code,
                'duration_ms': duration_ms
            }
        )
    
    # 刷新 Langfuse 数据到服务器
    if langfuse_client:
        langfuse_client.flush()
    
    return response


@app.route('/')
def index() -> Response:
    """API 服务根路径，返回服务信息"""
    return jsonify({
        "service": "DotaHelperAgent",
        "version": "1.0.0",
        "description": "Dota 2 智能助手 API",
        "docs": "https://github.com/your-repo/DotaHelperAgent",
        "endpoints": {
            "health": "/api/health",
            "chat": "/api/chat",
            "chat_stream": "/api/chat/stream",
            "tools": "/api/tools",
            "parse": "/api/parse/preview",
            "logs": "/api/logs",
            "trace": "/api/trace/<trace_id>",
            "memory": "/api/memory/stats",
            "feedback": "/api/feedback"
        }
    })


def get_agent() -> AgentController:
    global agent
    if agent is None:
        try:
            config = AgentConfig()
            agent = DotaHelperAgent(config=config)
        except Exception as e:
            app_logger.warning(f"Failed to load config: {e}")
            agent = DotaHelperAgent()
    return agent


def get_agent_safe() -> Optional[AgentController]:
    global cache_ready, cache_warming
    agt = get_agent()
    if not cache_ready and not cache_warming:
        threading.Thread(target=warm_cache, daemon=True).start()
    return agt


def _get_mock_recommendations(enemy_heroes: List[str]) -> str:
    mock_data = {
        "anti-mage": [
            {"hero": "Axe", "reason": "控制能力强，克制脆皮", "score": 0.92},
            {"hero": "Legion Commander", "reason": "对决优势，伤害高", "score": 0.88},
            {"hero": "Spirit Breaker", "reason": "追杀能力强", "score": 0.85},
        ],
        "invoker": [
            {"hero": "Lion", "reason": "打断技能，羊刀控制", "score": 0.91},
            {"hero": "Lina", "reason": "高爆发伤害", "score": 0.87},
            {"hero": "Zeus", "reason": "真实视界打断", "score": 0.84},
        ],
    }
    enemy_key = enemy_heroes[0].lower() if enemy_heroes else ""
    recommendations = mock_data.get(enemy_key, [
        {"hero": "Axe", "reason": "强力控制", "score": 0.90},
        {"hero": "Sven", "reason": "高伤害输出", "score": 0.85},
        {"hero": "Tiny", "reason": "爆发力强", "score": 0.82},
    ])

    answer = f"根据分析，{'、'.join(enemy_heroes)} 的克制英雄推荐：\n"
    for i, r in enumerate(recommendations, 1):
        answer += f"{i}. {r['hero']} (克制指数：{r['score']:.2f}) - {r['reason']}\n"
    answer += "\n⚠️ 提示：当前使用演示数据，完整功能需要等待缓存预热。"
    return answer


@app.before_request
def before_first_request() -> None:
    global cache_ready, cache_warming
    if not cache_ready and not cache_warming:
        threading.Thread(target=warm_cache, daemon=True).start()


@app.route('/api/health', methods=['GET'])
def health_check() -> Response:
    llm_enabled = get_llm_client() is not None
    controller_ready = agent_controller is not None
    memory_stats = agent.get_memory_stats() if agent else {}
    conversation_stats = conversation_manager.get_stats() if conversation_manager else {}
    
    return jsonify({
        "status": "ok",
        "service": "DotaHelperAgent",
        "llm_enabled": llm_enabled,
        "agent_controller_ready": controller_ready,
        "memory": memory_stats,
        "conversation": conversation_stats
    })


@app.route('/api/conversation/stats', methods=['GET'])
def conversation_stats() -> Response:
    """获取会话统计信息"""
    if conversation_manager is None:
        return jsonify({"error": "ConversationManager not initialized"})
    
    return jsonify(conversation_manager.get_stats())


@app.route('/api/conversation/<session_id>', methods=['GET'])
def get_conversation(session_id: str) -> Response:
    """获取会话历史"""
    if conversation_manager is None:
        return jsonify({"error": "ConversationManager not initialized"})
    
    try:
        session = conversation_manager.get_session(session_id)
        if session is None:
            return jsonify({"error": "Session not found"}), 404
        
        messages = []
        for msg in session.messages:
            try:
                messages.append(msg.to_dict())
            except Exception as e:
                app_logger.error(f"序列化消息失败: {e}")
                messages.append({"role": "unknown", "content": "[序列化失败]", "timestamp": 0})
        
        return jsonify({
            "session_id": session_id,
            "turn_count": session.turn_count,
            "messages": messages,
            "context_state": session.context_state
        })
    except Exception as e:
        app_logger.error(f"获取会话失败: {e}")
        return jsonify({"error": f"Failed to get conversation: {str(e)}"}), 500


@app.route('/api/test_tools', methods=['GET'])
def test_tools() -> Response:
    """测试工具执行"""
    if agent_controller is None:
        return jsonify({"error": "Agent Controller not initialized"})
    
    # 更新 Langfuse observation 的 input
    if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
        try:
            g.langfuse_trace.update(
                input={"test_type": "tools"},
                metadata={"endpoint": "test_tools"}
            )
        except Exception as e:
            app_logger.warning(f"更新 Langfuse input 失败: {e}")
    
    # 测试工具注册
    tools = agent_controller.tool_registry.list_tools()
    
    # 测试英雄解析
    test_query = "我们有敌法，黑鸟，小鹿，对面有军团，小鱼，兽"
    parsed = parse_heroes_with_llm(test_query)
    
    # 测试工具执行
    result = {}
    try:
        # 测试 analyze_counter_picks 工具
        counter_tool = agent_controller.tool_registry.get("analyze_counter_picks")
        if counter_tool:
            app_logger.info(f"Found tool: {counter_tool.name}")
            app_logger.info(f"Tool parameters: {counter_tool.parameters}")
            
            # 执行工具
            exec_result = agent_controller.tool_registry.execute(
                "analyze_counter_picks",
                our_heroes=parsed['our_heroes'],
                enemy_heroes=parsed['enemy_heroes'],
                top_n=3
            )
            result['tool_execution'] = {
                'success': exec_result.is_success(),
                'data': exec_result.data if exec_result.is_success() else None,
                'error': exec_result.error if not exec_result.is_success() else None
            }
        else:
            result['tool_execution'] = {'error': 'Tool not found'}
    except Exception as e:
        result['tool_execution'] = {'error': str(e)}
    
    # 更新 Langfuse observation 的 output
    if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
        try:
            g.langfuse_trace.update(
                output={
                    "success": True,
                    "tools": tools,
                    "parsed_heroes": parsed,
                    "test_result": result
                }
            )
            g.langfuse_trace.end()
        except Exception as e:
            app_logger.warning(f"更新 Langfuse output 失败: {e}")
    
    return jsonify({
        "tools": tools,
        "parsed_heroes": parsed,
        "test_result": result
    })


@app.route('/api/chat', methods=['POST'])
def chat() -> Response:
    """使用 Agent Controller 处理聊天请求（带 Trace 支持）"""
    data = request.get_json()
    query = data.get('query', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    context = data.get('context', {})
    
    # 获取当前 Trace 上下文
    trace_ctx = get_current_trace()
    trace_id = trace_ctx.trace_id if trace_ctx else generate_trace_id()

    # 更新 Langfuse observation 的 input
    if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
        try:
            g.langfuse_trace.update(
                input={"query": query, "context": context},
                metadata={"session_id": session_id, "trace_id": trace_id}
            )
        except Exception as e:
            app_logger.warning(f"更新 Langfuse input 失败: {e}")

    app_logger.info_ctx(
        "收到聊天请求",
        session_id=session_id,
        extra_data={
            "query": query,
            "session_id": session_id,
            "trace_id": trace_id,
            "context": context,
            "agent_controller_status": "已初始化" if agent_controller else "未初始化"
        }
    )

    # 记录请求日志
    app_logger.info_ctx(
        f"收到聊天请求",
        session_id=session_id,
        extra_data={"query": query, "context": context, "trace_id": trace_id}
    )

    # 如果没有 Agent Controller，回退到旧版实现
    if agent_controller is None:
        app_logger.warning_ctx("Agent Controller 未初始化，使用旧版实现", session_id=session_id)
        return _chat_legacy(query, context, session_id)

    agt = get_agent()

    result = {
        "success": True,
        "session_id": session_id,
        "trace_id": trace_id,
        "query": query,
        "agent_mode": True
    }

    if not query.strip():
        result["success"] = False
        result["error"] = "Query cannot be empty"
        app_logger.warning_ctx("查询为空", session_id=session_id)
        return jsonify(result)

    try:
        # 如果 context 中没有英雄信息，尝试从 query 中解析
        our_heroes = context.get('our_heroes', [])
        enemy_heroes = context.get('enemy_heroes', [])
        
        if not our_heroes and not enemy_heroes:
            app_logger.debug_ctx("Context 中无英雄信息，尝试使用 LLM 解析", session_id=session_id)
            with TraceSpan("parse_heroes", parent=trace_ctx) as parse_span:
                parsed = parse_heroes_with_llm(query)
            app_logger.debug_ctx(f"LLM 解析结果: {parsed}", session_id=session_id)
            if parsed['our_heroes'] or parsed['enemy_heroes']:
                context.update(parsed)
                app_logger.debug_ctx(f"更新 context: {context}", session_id=session_id)
                app_logger.debug_ctx(
                    f"从查询中解析到英雄",
                    session_id=session_id,
                    extra_data={"parsed": parsed}
                )
            else:
                app_logger.debug_ctx("LLM 解析未找到英雄", session_id=session_id)
        else:
            app_logger.debug_ctx("Context 已包含英雄信息，跳过解析", session_id=session_id)

        # 使用 Agent Controller 执行 ReAct 循环
        app_logger.info_ctx("开始调用 AgentController.solve()", session_id=session_id, extra_data={
            "query": query,
            "context": context,
            "session_id": session_id,
            "trace_id": trace_id
        })
        controller_result = agent_controller.solve(query, context, session_id)
        app_logger.info_ctx("AgentController.solve() 返回", session_id=session_id, extra_data={"result": str(controller_result)[:500]})
        
        # 整合结果
        result.update({
            "state": controller_result.get("state"),
            "turn_count": controller_result.get("turn_count"),
            "duration": controller_result.get("duration"),
            "reasoning": controller_result.get("reasoning", []),
            "actions": controller_result.get("actions", []),
            "reflections": controller_result.get("reflections", []),
            "success": controller_result.get("success", False)
        })

        if controller_result.get("success"):
            answer_data = controller_result.get("answer", {})
            app_logger.info_ctx(f"成功，answer_data: {answer_data}", session_id=session_id)
            if isinstance(answer_data, dict):
                result["final_answer"] = _format_answer(answer_data)
            else:
                result["final_answer"] = str(answer_data)
            app_logger.info_ctx(f"最终答案: {result['final_answer']}", session_id=session_id)
            app_logger.info_ctx(
                f"ReAct 循环完成",
                session_id=session_id,
                extra_data={
                    "turn_count": controller_result.get("turn_count"),
                    "duration": controller_result.get("duration")
                }
            )
        else:
            result["final_answer"] = controller_result.get("error", "处理失败")
            app_logger.error_ctx(
                f"处理失败，错误: {result['final_answer']}",
                session_id=session_id,
                extra_data={"error": controller_result.get("error")}
            )

        # 保存到记忆（如果启用）
        if agent and agent.enable_memory:
            agent.save_query_result(query, result, tags=["chat"])

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["final_answer"] = f"处理查询时出错：{str(e)}"
        import traceback
        app_logger.error_ctx(
            f"处理查询时出错: {str(e)}",
            session_id=session_id,
            extra_data={"error": str(e), "traceback": traceback.format_exc()}
        )

    app_logger.info_ctx(
        "返回结果",
        session_id=session_id,
        extra_data={
            "success": result['success'],
            "final_answer_preview": result.get('final_answer', 'N/A')[:200]
        }
    )

    # 更新 Langfuse observation 的 output
    if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
        try:
            g.langfuse_trace.update(
                output={
                    "success": result['success'],
                    "final_answer": result.get('final_answer', ''),
                    "turn_count": result.get('turn_count'),
                    "duration": result.get('duration')
                }
            )
            g.langfuse_trace.end()
        except Exception as e:
            app_logger.warning(f"更新 Langfuse output 失败: {e}")

    return jsonify(result)


def _format_answer_for_stream(answer_data) -> str:
    """格式化 Agent 答案为简洁文本（用于流式输出）
    
    去除所有JSON结构、形参、工具调用细节等，只保留用户关心的文字内容
    """
    if isinstance(answer_data, str):
        return answer_data
    
    # 处理列表数据（直接是英雄推荐列表）
    if isinstance(answer_data, list) and len(answer_data) > 0:
        formatted = []
        formatted.append("🎯 推荐结果：")
        for i, rec in enumerate(answer_data[:5], 1):
            if isinstance(rec, dict):
                hero_id = rec.get("hero_id")
                hero_en = rec.get("hero_name", rec.get("hero", "Unknown"))
                
                # 尝试获取中文名称
                hero_cn = None
                if hero_id:
                    hero_cn = localizer.get_hero_name_cn(hero_id)
                if not hero_cn:
                    hero_cn = _get_hero_cn_by_name(hero_en)
                
                hero_display = hero_cn if hero_cn else hero_en
                
                score = rec.get("score", 0)
                reasons = rec.get("reasons", rec.get("reason", []))
                reason_text = "; ".join(reasons[:2]) if isinstance(reasons, list) else str(reasons)
                formatted.append(f"{i}. {hero_display} (指数：{score:.2f}) - {reason_text}")
        return "\n".join(formatted)
    
    if not isinstance(answer_data, dict):
        return str(answer_data)
    
    # 处理目标分解合并结果格式
    if "sub_goals_summary" in answer_data:
        parts = []
        # 提取主要答案
        answer = answer_data.get("answer", {})
        app_logger.debug(f"sub_goals_summary 模式 - answer 类型: {type(answer)}")
        
        if isinstance(answer, dict):
            # 检查是否为空字典
            if not answer:
                app_logger.debug("answer 是空字典")
                # 检查是否有子目标结果
                results = answer_data.get("sub_goals_results", [])
                if results:
                    parts.append("📋 分析结果：")
                    for r in results:
                        desc = r.get("description", "")
                        result = r.get("result")
                        if result:
                            if isinstance(result, list):
                                formatted_result = _format_answer_for_stream(result)
                                parts.append(formatted_result)
                            elif isinstance(result, dict):
                                formatted_result = _format_answer_for_stream(result)
                                parts.append(formatted_result)
                            else:
                                parts.append(str(result))
                else:
                    parts.append("未能获取有效结果")
            else:
                formatted = _format_answer_for_stream(answer)
                app_logger.debug(f"格式化结果: {formatted[:200] if formatted else 'None'}")
                if formatted and formatted != str(answer):
                    parts.append(formatted)
                else:
                    app_logger.debug("格式化失败，从 sub_goals_results 提取")
                    # 尝试从子目标结果中提取有用信息
                    results = answer_data.get("sub_goals_results", [])
                    if results:
                        parts.append("📋 分析结果：")
                        for r in results:
                            desc = r.get("description", "")
                            result = r.get("result")
                            app_logger.debug(f"sub_goal result 类型: {type(result)}")
                            if result:
                                if isinstance(result, list):
                                    formatted_result = _format_answer_for_stream(result)
                                    parts.append(formatted_result)
                                elif isinstance(result, dict):
                                    formatted_result = _format_answer_for_stream(result)
                                    parts.append(formatted_result)
                                else:
                                    parts.append(str(result))
        elif isinstance(answer, list):
            app_logger.debug("answer 是列表，直接格式化")
            formatted = _format_answer_for_stream(answer)
            parts.append(formatted)
        elif isinstance(answer, str):
            app_logger.debug("answer 是字符串")
            parts.append(answer)
        
        # 如果有失败目标，简要说明
        failed = answer_data.get("failed_goals", [])
        if failed:
            parts.append("\n⚠️ 部分分析未完成：")
            for f in failed:
                parts.append(f"• {f.get('description', '未知')}")
        
        final_result = "\n".join(parts) if parts else str(answer_data)
        app_logger.debug(f"最终返回（前300字符）: {final_result[:300]}")
        return final_result
    
    # 检查是否有嵌套的 answer 字段
    if "answer" in answer_data and isinstance(answer_data["answer"], dict):
        actual_answer = answer_data["answer"]
    else:
        actual_answer = answer_data
    
    # 处理英雄推荐
    if "recommendations" in actual_answer:
        recs = actual_answer["recommendations"]
        if isinstance(recs, list) and len(recs) > 0:
            formatted = []
            formatted.append("🎯 推荐结果：")
            for i, rec in enumerate(recs[:5], 1):
                if isinstance(rec, dict):
                    hero_id = rec.get("hero_id")
                    hero_en = rec.get("hero_name", rec.get("hero", "Unknown"))
                    
                    # 尝试获取中文名称
                    hero_cn = None
                    if hero_id:
                        hero_cn = localizer.get_hero_name_cn(hero_id)
                    if not hero_cn:
                        hero_cn = _get_hero_cn_by_name(hero_en)
                    
                    hero_display = hero_cn if hero_cn else hero_en
                    
                    score = rec.get("score", 0)
                    reasons = rec.get("reasons", rec.get("reason", []))
                    reason_text = "; ".join(reasons[:2]) if isinstance(reasons, list) else str(reasons)
                    formatted.append(f"{i}. {hero_display} (指数：{score:.2f}) - {reason_text}")
            return "\n".join(formatted)
    
    # 处理出装推荐
    if "items" in actual_answer:
        items = actual_answer["items"]
        if isinstance(items, dict):
            formatted = ["🎒 出装推荐："]
            for stage, item_list in items.items():
                formatted.append(f"\n【{stage}】")
                if isinstance(item_list, list):
                    for item in item_list[:5]:
                        formatted.append(f"• {item}")
            return "\n".join(formatted)
    
    # 处理技能加点
    if "skills" in actual_answer:
        skills = actual_answer["skills"]
        if isinstance(skills, dict):
            formatted = ["📚 技能加点推荐："]
            if "order" in skills:
                formatted.append(f"加点顺序：{skills['order']}")
            if "primary" in skills:
                formatted.append(f"主加：{skills['primary']}")
            return "\n".join(formatted)
    
    # 处理纯文本答案
    if "answer" in actual_answer and isinstance(actual_answer["answer"], str):
        return actual_answer["answer"]
    
    # 处理 message 字段
    if "message" in actual_answer and isinstance(actual_answer["message"], str):
        message = actual_answer["message"]
        # 尝试解析 message 中的 JSON 字符串（如英雄推荐列表）
        try:
            parsed = json.loads(message)
            if isinstance(parsed, list):
                # 如果是列表，递归格式化
                formatted = _format_answer_for_stream(parsed)
                if formatted != message:
                    return formatted
        except (json.JSONDecodeError, ValueError):
            pass
        # 如果解析失败或不是列表，直接返回 message
        return message
    
    # 兜底：尝试提取关键信息
    if "content" in actual_answer:
        return str(actual_answer["content"])
    
    # 最后的兜底
    return str(actual_answer)


def _format_observation(result, tool_name: str) -> str:
    """格式化工具执行结果为简洁文本（用于流式展示）
    
    去除所有JSON结构、技术参数等，只保留用户能看懂的信息
    """
    if result is None:
        return "无结果"
    
    # 获取工具返回的数据
    data = result.data if hasattr(result, 'data') else result
    
    if data is None:
        return "无结果"
    
    # 根据工具类型格式化
    if tool_name == 'analyze_counter_picks':
        if isinstance(data, list) and len(data) > 0:
            formatted = []
            for i, rec in enumerate(data[:5], 1):
                if isinstance(rec, dict):
                    hero_name = rec.get("hero_name", "未知")
                    # 尝试获取中文名
                    hero_id = rec.get("hero_id")
                    if hero_id:
                        hero_cn = localizer.get_hero_name_cn(hero_id)
                        if hero_cn:
                            hero_name = hero_cn
                    
                    reasons = rec.get("reasons", [])
                    reason_text = "; ".join(reasons[:2]) if reasons else "强力推荐"
                    formatted.append(f"{i}. {hero_name} - {reason_text}")
            return "推荐英雄：\n" + "\n".join(formatted)
        return "暂无推荐"
    
    elif tool_name == 'recommend_items':
        if isinstance(data, dict):
            formatted = []
            for stage, items in data.items():
                formatted.append(f"【{stage}】")
                if isinstance(items, list):
                    for item in items[:5]:
                        formatted.append(f"• {item}")
            return "\n".join(formatted)
        return "暂无出装推荐"
    
    elif tool_name == 'recommend_skills':
        if isinstance(data, dict):
            formatted = []
            if "primary" in data:
                formatted.append(f"主加：{data['primary']}")
            if "order" in data:
                formatted.append(f"顺序：{data['order']}")
            return "\n".join(formatted) if formatted else "暂无技能推荐"
        return "暂无技能推荐"
    
    elif tool_name == 'get_hero_info':
        if isinstance(data, dict):
            return f"英雄：{data.get('name', '未知')}\n定位：{data.get('roles', '未知')}"
        return "暂无英雄信息"
    
    # 兜底：如果是列表或字典，提取关键信息
    if isinstance(data, list):
        if len(data) == 0:
            return "无结果"
        # 如果是简单列表，直接显示
        if all(isinstance(item, (str, int, float)) for item in data):
            return ", ".join(str(item) for item in data[:10])
        return f"包含 {len(data)} 项结果"
    
    if isinstance(data, dict):
        # 尝试提取关键信息
        for key in ['name', 'hero_name', 'title', 'result']:
            if key in data:
                return str(data[key])
        return f"包含 {len(data)} 个字段"
    
    return str(data)


def _format_answer(answer_data: dict) -> str:
    """格式化 Agent 答案为文本"""
    formatted = []
    
    # 处理目标分解合并结果格式
    if "sub_goals_summary" in answer_data:
        answer = answer_data.get("answer", {})
        
        # 如果 answer 是列表，直接格式化
        if isinstance(answer, list):
            return _format_answer_for_stream(answer_data)
        
        # 如果 answer 是字典，提取 recommendations
        if isinstance(answer, dict):
            if "recommendations" in answer:
                recs = answer["recommendations"]
                if isinstance(recs, list) and len(recs) > 0:
                    formatted.append("推荐结果：")
                    for i, rec in enumerate(recs[:5], 1):
                        if isinstance(rec, dict):
                            hero_id = rec.get("hero_id")
                            hero_en = rec.get("hero_name", rec.get("hero", "Unknown"))
                            
                            hero_cn = None
                            if hero_id:
                                hero_cn = localizer.get_hero_name_cn(hero_id)
                            if not hero_cn:
                                hero_cn = _get_hero_cn_by_name(hero_en)
                            
                            hero_display = hero_cn if hero_cn else hero_en
                            score = rec.get("score", 0)
                            reasons = rec.get("reasons", rec.get("reason", []))
                            reason_text = "; ".join(reasons[:2]) if isinstance(reasons, list) else str(reasons)
                            formatted.append(f"{i}. {hero_display} (指数：{score:.2f}) - {reason_text}")
                    return "\n".join(formatted)
            
            # 尝试从 sub_goals_results 中提取
            results = answer_data.get("sub_goals_results", [])
            if results:
                for r in results:
                    result = r.get("result")
                    if result:
                        if isinstance(result, list):
                            return _format_answer_for_stream(answer_data)
                        elif isinstance(result, dict) and "recommendations" in result:
                            answer = result
                            break
        
        # 如果 answer 是字符串
        if isinstance(answer, str):
            return answer
    
    # 检查是否有嵌套的 answer 字段（来自 thought.set_complete）
    if "answer" in answer_data and isinstance(answer_data["answer"], dict):
        actual_answer = answer_data["answer"]
    elif "answer" in answer_data and isinstance(answer_data["answer"], list):
        # 如果 answer 是列表，直接格式化列表
        return _format_answer_for_stream(answer_data["answer"])
    else:
        actual_answer = answer_data
    
    # 处理推荐
    if "recommendations" in actual_answer:
        recs = actual_answer["recommendations"]
        if isinstance(recs, list) and len(recs) > 0:
            formatted.append("推荐结果：")
            for i, rec in enumerate(recs[:5], 1):
                if isinstance(rec, dict):
                    hero_id = rec.get("hero_id")
                    hero_en = rec.get("hero_name", rec.get("hero", "Unknown"))
                    
                    # 尝试获取中文名称
                    hero_cn = None
                    if hero_id:
                        hero_cn = localizer.get_hero_name_cn(hero_id)
                    if not hero_cn:
                        # 如果无法通过 ID 获取，尝试通过英文名查找
                        hero_cn = _get_hero_cn_by_name(hero_en)
                    
                    hero_display = hero_cn if hero_cn else hero_en
                    
                    score = rec.get("score", 0)
                    reasons = rec.get("reasons", rec.get("reason", []))
                    reason_text = "; ".join(reasons[:2]) if isinstance(reasons, list) else str(reasons)
                    formatted.append(f"{i}. {hero_display} (指数：{score:.2f}) - {reason_text}")
    
    # 处理答案：如果是 dict 类型，不直接输出原始字典字符串
    if "answer" in answer_data:
        ans = answer_data['answer']
        if isinstance(ans, dict):
            # 已经通过 recommendations 处理过了，不再重复输出
            pass
        elif isinstance(ans, list):
            # 如果 answer 是列表，尝试格式化
            list_formatted = _format_answer_for_stream(ans)
            if list_formatted and list_formatted != str(ans):
                formatted.append(list_formatted)
        elif isinstance(ans, str):
            formatted.append(f"\n答案：{ans}")
        else:
            formatted.append(f"\n答案：{ans}")
    
    return "\n".join(formatted) if formatted else str(answer_data)


def _get_hero_cn_by_name(hero_en: str) -> Optional[str]:
    """通过英文名称获取中文名称"""
    if not hero_en or hero_en == "Unknown":
        return None
    
    hero_en_lower = hero_en.lower()
    
    # 常见英雄中英文映射
    hero_map = {
        'anti-mage': '敌法师',
        'axe': '斧王',
        'bane': '祸乱之源',
        'bloodseeker': '嗜血狂魔',
        'crystal maiden': '水晶室女',
        'drow ranger': '卓尔游侠',
        'earthshaker': '撼地者',
        'juggernaut': '主宰',
        'mirana': '米拉娜',
        'morphling': '变体精灵',
        'nevermore': '影魔',
        'phantom lancer': '幻影长矛手',
        'phantom assassin': '幻影刺客',
        'pudge': '帕吉',
        'pugna': '帕格纳',
        'razor': '剃刀',
        'sand king': '沙王',
        'shadow fiend': '影魔',
        'shadow shaman': '暗影萨满',
        'slardar': '斯拉达',
        'storm spirit': '风暴之灵',
        'sven': '斯温',
        'tiny': '小小',
        'vengeful spirit': '复仇之魂',
        'windranger': '风行者',
        'zeus': '宙斯',
        'kunkka': '昆卡',
        'faceless void': '虚空假面',
        'lion': '莱恩',
        'invoker': '祈求者',
        'templar assassin': '圣堂刺客',
        'chaos knight': '混沌骑士',
        'spirit breaker': '裂魂人',
        'rubick': '拉比克',
        'legion commander': '军团指挥官',
        'enchantress': '魅惑魔女',
        'beastmaster': '兽王',
        'obsidian destroyer': '殁境神蚀者',
        'slark': '斯拉克',
        'dazzle': '戴泽',
        'witch doctor': '巫医',
        'ogre magi': '食人魔魔法师',
        'wraith king': '冥魂大帝',
        'lich': '巫妖',
        'disruptor': '干扰者',
        'keeper of the light': '光之守卫',
        'tinker': '修补匠',
        'nature\'s prophet': '自然之兆',
        'lesser night stalker': '暗夜魔王',
        'broodmother': '育母蜘蛛',
        'bounty hunter': '赏金猎人',
        'weaver': '编织者',
        'jakiro': '杰奇洛',
        'batrider': '蝙蝠骑士',
        'chen': '陈',
        'silencer': '沉默术士',
        'outworld destroyer': '殁境神蚀者',
        'doom': '末日使者',
        'ancient apparition': '远古冰魄',
        'ursa': '熊战士',
        'gyrocopter': '矮人直升机',
        'alchemist': '炼金术士',
        'huskar': '哈斯卡',
        'night stalker': '暗夜魔王',
        'brood mother': '育母蜘蛛',
        'dragon knight': '龙骑士',
        'clockwerk': '发条技师',
        'death prophet': '死亡先知',
        'phantom assassin': '幻影刺客',
        'puck': '帕克',
        'queen of pain': '痛苦女王',
        'venomancer': '剧毒术士',
        'faceless': '虚空假面',
        'skeleton king': '冥魂大帝',
        'furion': '自然之兆',
        'troll warlord': '巨魔战将',
        'centaur warrunner': '半人马战行者',
        'magnataur': '马格纳斯',
        'shredder': '伐木机',
        'bristleback': '钢背兽',
        'tusk': '巨牙海民',
        'skywrath mage': '天怒法师',
        'abaddon': '亚巴顿',
        'elder titan': '上古巨神',
        'treant protector': '树精卫士',
        'earth spirit': '大地之灵',
        'ember spirit': '灰烬之灵',
        'fire remnant': '火之残灵',
        'terrorblade': '恐怖利刃',
        'phoenix': '凤凰',
        'oracle': '神谕者',
        'winter wyvern': '寒冬飞龙',
        'arc warden': '天穹守望者',
        'monkey king': '齐天大圣',
        'dark willow': '邪影芳灵',
        'pangolier': '石鳞剑士',
        'grimstroke': '天涯墨客',
        'mars': '玛尔斯',
        'snapfire': '电炎绝手',
        'void spirit': '虚无之灵',
        'holysmith': '破晓辰星',
        'dawnbreaker': '破晓辰星',
        'marci': '玛西',
        'primal beast': '兽',
        'muerta': '琼英碧灵',
    }
    
    return hero_map.get(hero_en_lower)


def _chat_legacy(query: str, context: Dict[str, Any], session_id: str) -> Generator:
    """旧版聊天实现（回退用）"""
    agt = get_agent_safe()
    
    result = {
        "success": True,
        "session_id": session_id,
        "query": query,
        "agent_mode": False,
        "reasoning": ["用户查询：" + query],
        "actions": [],
        "observations": [],
        "final_answer": "",
        "turns": 0
    }

    try:
        if "克制" in query or "counter" in query.lower() or "推荐" in query or "选什么英雄" in query:
            our_heroes = context.get('our_heroes', [])
            enemy_heroes = context.get('enemy_heroes', [])

            if not our_heroes and not enemy_heroes:
                parsed = parse_heroes_with_llm(query)
                our_heroes = parsed.get('our_heroes', [])
                enemy_heroes = parsed.get('enemy_heroes', [])

            if our_heroes or enemy_heroes:
                rec = agt.recommend_heroes(our_heroes, enemy_heroes)
                recommendations = rec.get('recommendations', [])

                if recommendations:
                    result["final_answer"] = f"根据分析，{'、'.join(enemy_heroes) if enemy_heroes else '敌方阵容'} 的克制英雄推荐：\n"
                    for i, r in enumerate(recommendations[:3], 1):
                        hero = r.get('hero_name', r.get('hero', 'Unknown'))
                        reasons = r.get('reasons', [])
                        reason_text = '; '.join(reasons[:2]) if reasons else '强力克制'
                        score = r.get('score', 0)
                        result["final_answer"] += f"{i}. {hero} (克制指数：{score:.2f}) - {reason_text}\n"
                else:
                    result["final_answer"] = _get_mock_recommendations(enemy_heroes)
            else:
                result["final_answer"] = "请告诉我您想克制什么英雄。"

        elif "出装" in query or "装备" in query or "item" in query.lower():
            hero_name = context.get('hero_name', '')
            if not hero_name:
                hero_name = parse_hero_from_query(query)
            if not hero_name:
                hero_name = 'pudge'

            rec = agt.recommend_items(hero_name)
            result["final_answer"] = f"{hero_name} 出装推荐：\n"
            for stage, items in rec.get('recommendations', {}).items():
                result["final_answer"] += f"\n【{stage}】\n"
                for item in items[:6]:
                    result["final_answer"] += f"- {item}\n"

        elif "技能" in query or "加点" in query or "skill" in query.lower():
            hero_name = context.get('hero_name', '')
            if not hero_name:
                hero_name = parse_hero_from_query(query)
            if not hero_name:
                hero_name = 'pudge'

            rec = agt.recommend_skills(hero_name)
            result["final_answer"] = f"{hero_name} 技能加点推荐：\n"
            for build in rec.get('recommendations', [])[:1]:
                result["final_answer"] += f"\n主加：{build.get('primary', '未知')}\n"
                for skill in build.get('skills', [])[:5]:
                    result["final_answer"] += f"- {skill}\n"

        else:
            result["final_answer"] = "您好！我是 DotaHelperAgent，可以帮您：\n1. 推荐克制英雄\n2. 推荐出装\n3. 推荐技能加点\n\n请告诉我您需要什么帮助？"

        result["turns"] = 1

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)

    return jsonify(result)


@app.route('/api/parse/preview', methods=['POST'])
def parse_preview() -> Response:
    """解析预览 API - 用于前端实时显示解析结果"""
    try:
        data = request.get_json()
        query = data.get('query', '')
        
        if not query:
            return jsonify({"error": "Query is required"}), 400
        
        # 更新 Langfuse observation 的 input
        if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
            try:
                g.langfuse_trace.update(
                    input={"query": query},
                    metadata={"endpoint": "parse_preview"}
                )
            except Exception as e:
                app_logger.warning(f"更新 Langfuse input 失败: {e}")
        
        parsed = parse_heroes_with_llm(query)
        
        # 更新 Langfuse observation 的 output
        if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
            try:
                g.langfuse_trace.update(
                    output={
                        "success": True,
                        "parsed": parsed
                    }
                )
                g.langfuse_trace.end()
            except Exception as e:
                app_logger.warning(f"更新 Langfuse output 失败: {e}")
        
        return jsonify({
            "success": True,
            "parsed": parsed,
            "query": query
        })
        
    except Exception as e:
        app_logger.error(f"Parse preview error: {e}")
        
        # 更新 Langfuse observation 的 error
        if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
            try:
                g.langfuse_trace.update(
                    output={
                        "success": False,
                        "error": str(e)
                    }
                )
                g.langfuse_trace.end()
            except Exception as e:
                app_logger.warning(f"更新 Langfuse output 失败: {e}")
        
        return jsonify({"error": str(e)}), 500


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream() -> Response:
    """流式输出接口（使用 Agent Controller，带 Trace 支持）"""
    data = request.get_json()
    query = data.get('query', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    context = data.get('context', {})
    
    # 获取当前 Trace 上下文（在请求上下文中获取）
    trace_ctx = get_current_trace()
    trace_id = trace_ctx.trace_id if trace_ctx else generate_trace_id()

    # 更新 Langfuse observation 的 input
    if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
        try:
            g.langfuse_trace.update(
                input={"query": query, "context": context},
                metadata={"session_id": session_id, "trace_id": trace_id}
            )
            app_logger.debug(f"已更新 Langfuse input: query={query[:50]}...")
        except Exception as e:
            app_logger.warning(f"更新 Langfuse input 失败: {e}")

    def generate():
        # 在生成器中恢复 Trace 上下文
        if trace_ctx:
            set_current_trace(trace_ctx)
            
        start_time = time.time()
        final_result = None

        yield f"event: start\ndata: {json.dumps({'timestamp': int(start_time), 'trace_id': trace_id})}\n\n"

        if not query.strip():
            yield f"event: error\ndata: {json.dumps({'error': 'Query cannot be empty'})}\n\n"
            yield f"event: complete\ndata: {json.dumps({'timestamp': int(time.time()), 'total_time': 0})}\n\n"
            return

        # 如果没有 Agent Controller，回退到简单流式
        if agent_controller is None:
            yield from _generate_stream_legacy(query, context, start_time)
            return

        try:
            # 使用流式执行（传递 Trace 上下文）
            for event in _execute_streaming(agent_controller, query, context, start_time, trace_ctx):
                yield event
                # 捕获最终结果
                if event.startswith("event: synthesize"):
                    try:
                        event_data = json.loads(event.split("data: ")[1])
                        final_result = event_data.get("answer", "")
                    except:
                        pass

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            yield f"event: complete\ndata: {json.dumps({'timestamp': int(time.time()), 'total_time': time.time() - start_time})}\n\n"
        
        # 更新 Langfuse observation 的 output 并结束
        if hasattr(g, 'langfuse_trace') and g.langfuse_trace:
            try:
                g.langfuse_trace.update(
                    output={
                        "success": final_result is not None,
                        "final_answer": final_result or "",
                        "duration": time.time() - start_time
                    }
                )
                g.langfuse_trace.end()
                app_logger.debug(f"已更新 Langfuse output 并结束: success={final_result is not None}")
            except Exception as e:
                app_logger.warning(f"更新 Langfuse output 失败: {e}")

    return Response(stream_with_context(generate()), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


def _execute_streaming(controller, query: str, context: dict, start_time: float, trace_ctx=None):
    """真正的流式执行 ReAct 循环（支持目标分解，带 Trace 支持）"""
    from core.agent_controller import AgentThought, AgentState
    from core.goal_planner import GoalStatus
    from utils.trace_context import TraceSpan, set_current_trace
    
    # 设置 Trace 上下文
    if trace_ctx:
        set_current_trace(trace_ctx)
    
    thought = AgentThought(query=query, context=context or {})
    controller.current_thought = thought

    try:
        # ===== 阶段 1: 目标分解 =====
        app_logger.info("阶段 1: 目标分解")
        yield f"event: goal_decomposition\ndata: {json.dumps({'step': 'goal_decomposition', 'status': '开始目标分解'})}\n\n"
        
        with TraceSpan("goal_decomposition", parent=trace_ctx):
            goal_plan = controller.goal_planner.plan(query, context)
        controller.current_goal_plan = goal_plan
        plan_id = f"plan_{int(time.time())}"
        controller.goal_tracker.register_plan(plan_id, goal_plan)
        
        # 输出目标分解结果
        goal_decomposition_data = {
            'step': 'goal_decomposition_result',
            'main_goal': goal_plan.main_goal,
            'sub_goals': [sg.to_dict() for sg in goal_plan.sub_goals]
        }
        yield f"event: goal_decomposition_result\ndata: {json.dumps(goal_decomposition_data)}\n\n"
        
        thought.add_reasoning(f"目标分解完成: {goal_plan.main_goal}")
        thought.add_reasoning(f"子目标数量: {len(goal_plan.sub_goals)}")
        
        # 如果只有一个子目标，使用传统 ReAct 循环
        if len(goal_plan.sub_goals) <= 1:
            app_logger.info("单目标查询，使用传统 ReAct 循环")
            yield from _execute_single_goal_streaming(controller, thought, goal_plan.sub_goals[0] if goal_plan.sub_goals else None, start_time, trace_ctx)
            return
        
        # ===== 阶段 2: 多子目标执行 =====
        app_logger.info("阶段 2: 执行子目标")
        yield f"event: goal_execution\ndata: {json.dumps({'step': 'goal_execution', 'status': '开始执行子目标'})}\n\n"
        
        while not goal_plan.is_complete():
            sub_goal = goal_plan.get_next_pending_goal()
            if not sub_goal:
                app_logger.warning("没有待执行的子目标，但计划未完成")
                break
            
            app_logger.info(f"执行子目标: {sub_goal.id} - {sub_goal.description} - 工具: {sub_goal.tool_name}")
            
            sub_goal_start_data = {
                'step': 'sub_goal_start',
                'sub_goal_id': sub_goal.id,
                'description': sub_goal.description,
                'tool_name': sub_goal.tool_name
            }
            yield f"event: sub_goal_start\ndata: {json.dumps(sub_goal_start_data)}\n\n"
            
            # 更新状态为执行中
            sub_goal.status = GoalStatus.IN_PROGRESS
            controller.goal_tracker.update_goal_status(plan_id, sub_goal.id, GoalStatus.IN_PROGRESS)
            
            # 执行子目标（消费生成器以实际执行）
            sub_goal_success = False
            for event in _execute_sub_goal_streaming(controller, thought, sub_goal, trace_ctx):
                yield event  # 转发子目标的事件到前端
                # 检查是否有完成或错误事件
                if event.startswith("event: sub_goal_complete"):
                    sub_goal_success = True
                elif event.startswith("event: sub_goal_failed"):
                    sub_goal_success = False
            
            if sub_goal_success:
                sub_goal.status = GoalStatus.COMPLETED
                controller.goal_tracker.update_goal_status(
                    plan_id, sub_goal.id, GoalStatus.COMPLETED, result=sub_goal.result
                )
                sub_goal_complete_data = {
                    'step': 'sub_goal_complete',
                    'sub_goal_id': sub_goal.id,
                    'status': 'completed'
                }
                yield f"event: sub_goal_complete\ndata: {json.dumps(sub_goal_complete_data)}\n\n"
                app_logger.info(f"子目标完成 ✓: {sub_goal.id}")
            else:
                sub_goal.status = GoalStatus.FAILED
                controller.goal_tracker.update_goal_status(
                    plan_id, sub_goal.id, GoalStatus.FAILED, error=sub_goal.error
                )
                sub_goal_failed_data = {
                    'step': 'sub_goal_failed',
                    'sub_goal_id': sub_goal.id,
                    'status': 'failed',
                    'error': sub_goal.error
                }
                yield f"event: sub_goal_failed\ndata: {json.dumps(sub_goal_failed_data)}\n\n"
                app_logger.error(f"子目标失败 ✗: {sub_goal.id} - {sub_goal.error}")
            
            # 将子目标结果添加到主 thought
            thought.add_observation({
                "sub_goal_id": sub_goal.id,
                "description": sub_goal.description,
                "status": sub_goal.status.value,
                "result": sub_goal.result
            })
        
        # ===== 阶段 3: 合并结果 =====
        app_logger.info("阶段 3: 合并结果")
        yield f"event: merge_results\ndata: {json.dumps({'step': 'merge_results', 'status': '合并子目标结果'})}\n\n"
        
        final_answer = controller._merge_sub_goal_results(goal_plan)
        app_logger.debug(f"final_answer 类型: {type(final_answer)}")
        app_logger.debug(f"final_answer 内容（前500字符）: {str(final_answer)[:500]}")
        
        thought.set_complete(final_answer)
        
        # 格式化最终答案（去除JSON结构，转为简洁文本）
        formatted_answer = _format_answer_for_stream(final_answer)
        app_logger.debug(f"formatted_answer 类型: {type(formatted_answer)}")
        app_logger.debug(f"formatted_answer 内容（前500字符）: {formatted_answer[:500]}")
        
        # 输出最终答案
        synthesize_event = {'step': 'synthesize', 'answer': formatted_answer}
        app_logger.debug(f"synthesize_event: {json.dumps(synthesize_event)[:500]}")
        yield f"event: synthesize\ndata: {json.dumps(synthesize_event)}\n\n"
        
    except Exception as e:
        import traceback
        app_logger.error(f"流式处理异常: {str(e)}")
        app_logger.error(traceback.format_exc())
        thought.set_failed(str(e))
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
    
    # 输出完成事件
    total_time = time.time() - start_time
    yield f"event: complete\ndata: {json.dumps({'timestamp': int(time.time()), 'total_time': round(total_time, 2), 'state': thought.state.value})}\n\n"


def _execute_single_goal_streaming(controller, thought, sub_goal, start_time: float, trace_ctx=None):
    """执行单个目标的流式输出"""
    from core.agent_controller import AgentState
    from utils.trace_context import set_current_trace
    
    if trace_ctx:
        set_current_trace(trace_ctx)
    
    try:
        for turn in range(controller.max_turns):
            thought.increment_turn()

            # 1. Think - 理解问题
            thought.state = AgentState.THINKING
            thought.add_reasoning(f"分析用户查询：{thought.query}")
            yield f"event: think\ndata: {json.dumps({'step': 'think', 'content': f'分析用户查询：{thought.query}'})}\n\n"
            
            if thought.state == AgentState.FAILED:
                break

            # 使用 LLM 智能选择工具
            try:
                tool_plan = controller.tool_selector.select_tools(
                    query=thought.query,
                    context=thought.context
                )
                thought.context['tool_plan'] = tool_plan
                thought.add_reasoning(f"LLM 选择工具：{[t.tool_name for t in tool_plan.tools]}")
                thought.add_reasoning(f"选择理由：{tool_plan.reasoning}")
                
                tool_names = [t.tool_name for t in tool_plan.tools]
                think_content = "选择工具: " + ", ".join(tool_names) + "\n理由: " + tool_plan.reasoning
                yield f"event: think\ndata: {json.dumps({'step': 'think', 'content': think_content})}\n\n"
            except Exception as e:
                error_msg = f"LLM 工具选择失败：{str(e)}"
                thought.set_failed(error_msg)
                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                break

            # 2. Plan - 制定计划
            thought.state = AgentState.PLANNING
            tool_plan = thought.context.get('tool_plan')
            if not tool_plan:
                thought.set_failed("工具计划缺失")
                break

            planned_tools = [t.tool_name for t in tool_plan.tools]
            thought.context['planned_tools'] = planned_tools
            thought.context['tool_params'] = {t.tool_name: t.parameters for t in tool_plan.tools}
            
            thought.add_reasoning(f"计划执行工具：{planned_tools}")
            yield f"event: plan\ndata: {json.dumps({'step': 'plan', 'actions': [{'tool': t} for t in planned_tools]})}\n\n"

            # 3. Execute - 执行行动
            thought.state = AgentState.ACTING
            
            for tool_name in planned_tools:
                tool = controller.tool_registry.get(tool_name)
                if not tool:
                    thought.add_reasoning(f"工具 {tool_name} 不存在")
                    continue

                params = thought.context.get('tool_params', {}).get(tool_name, {})
                thought.add_reasoning(f"执行工具：{tool_name}")
                yield f"event: action\ndata: {json.dumps({'step': 'action', 'tool': tool_name, 'status': '执行中'})}\n\n"

                try:
                    result = tool.execute(**params)
                    thought.add_action(tool_name, params, result)
                    
                    # 格式化观察结果，去除冗余信息
                    formatted_obs = _format_observation(result, tool_name)
                    yield f"event: observation\ndata: {json.dumps({'step': 'observation', 'tool': tool_name, 'result': formatted_obs})}\n\n"
                except Exception as e:
                    error_msg = f"工具执行失败：{str(e)}"
                    thought.add_reasoning(error_msg)
                    yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"

            # 4. Observe - 观察结果
            thought.state = AgentState.OBSERVING
            thought.add_reasoning(f"收集到 {len(thought.actions_taken)} 条观察结果")

            # 5. Reflect - 反思
            if controller.enable_reflection:
                thought.state = AgentState.REFLECTING
                has_result = len(thought.actions_taken) > 0 and any(a.get('result') for a in thought.actions_taken)
                
                if has_result:
                    thought.add_reasoning("已收集到足够的信息，准备生成答案")
                    # 提取ToolResult中的data字段，而不是整个对象
                    last_result = thought.actions_taken[-1].get('result')
                    # last_result 可能是 ToolResult 对象或字典（来自 to_dict()）
                    if hasattr(last_result, 'data'):
                        result_data = last_result.data
                    elif isinstance(last_result, dict):
                        result_data = last_result.get('data', last_result)
                    else:
                        result_data = last_result
                    thought.set_complete(result_data)
                else:
                    thought.add_reasoning("信息不足，需要继续收集")

                if thought.reflections:
                    yield f"event: reflect\ndata: {json.dumps({'step': 'reflect', 'content': thought.reflections[-1]})}\n\n"

            # 检查是否完成
            if thought.state == AgentState.COMPLETE:
                break

            if controller._should_finalize(thought):
                controller._finalize(thought)
                break

        # 强制结束
        if thought.state not in [AgentState.COMPLETE, AgentState.FAILED]:
            controller._finalize(thought)

        # 输出最终答案
        if thought.state == AgentState.COMPLETE:
            answer_data = thought.final_answer
            app_logger.debug(f"answer_data 类型: {type(answer_data)}")
            app_logger.debug(f"answer_data 内容（前500字符）: {str(answer_data)[:500]}")
            
            # 统一使用 _format_answer_for_stream 处理所有类型
            answer_text = _format_answer_for_stream(answer_data)
            app_logger.debug(f"answer_text 内容（前500字符）: {answer_text[:500]}")
            
            yield f"event: synthesize\ndata: {json.dumps({'step': 'synthesize', 'answer': answer_text})}\n\n"
        else:
            yield f"event: error\ndata: {json.dumps({'error': thought.error or '执行失败'})}\n\n"

    except Exception as e:
        thought.set_failed(str(e))
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"


def _execute_sub_goal_streaming(controller, thought, sub_goal, trace_ctx=None):
    """执行单个子目标的流式输出
    
    Returns:
        bool: 是否成功
    """
    from core.agent_controller import AgentThought, AgentState
    from utils.trace_context import set_current_trace, TraceSpan
    
    if trace_ctx:
        set_current_trace(trace_ctx)
    
    # 为子目标创建临时的 AgentThought
    sub_thought = AgentThought(
        query=f"{sub_goal.description} (来自: {controller.current_goal_plan.main_goal})",
        context={
            **(thought.context or {}),
            "sub_goal_id": sub_goal.id,
            "main_goal": controller.current_goal_plan.main_goal,
            "goal_plan": controller.current_goal_plan.to_dict()
        }
    )
    
    try:
        for turn in range(controller.max_turns):
            sub_thought.increment_turn()

            # 1. Think - 理解问题
            sub_thought.state = AgentState.THINKING
            sub_thought.add_reasoning(f"分析子目标：{sub_goal.description}")
            yield f"event: think\ndata: {json.dumps({'step': 'think', 'content': f'分析子目标：{sub_goal.description}'})}\n\n"
            
            if sub_thought.state == AgentState.FAILED:
                thought.set_failed(sub_thought.error)
                return False

            # 使用 LLM 智能选择工具
            try:
                tool_plan = controller.tool_selector.select_tools(
                    query=sub_thought.query,
                    context=sub_thought.context
                )
                sub_thought.context['tool_plan'] = tool_plan
                sub_thought.add_reasoning(f"LLM 选择工具：{[t.tool_name for t in tool_plan.tools]}")
                sub_thought.add_reasoning(f"选择理由：{tool_plan.reasoning}")
                
                tool_names = [t.tool_name for t in tool_plan.tools]
                think_content = f"[{sub_goal.id}] 选择工具: " + ", ".join(tool_names) + "\n理由: " + tool_plan.reasoning
                yield f"event: think\ndata: {json.dumps({'step': 'think', 'content': think_content})}\n\n"
            except Exception as e:
                error_msg = f"LLM 工具选择失败：{str(e)}"
                sub_thought.set_failed(error_msg)
                thought.set_failed(error_msg)
                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                return False

            # 2. Plan - 制定计划
            sub_thought.state = AgentState.PLANNING
            tool_plan = sub_thought.context.get('tool_plan')
            if not tool_plan:
                sub_thought.set_failed("工具计划缺失")
                thought.set_failed("工具计划缺失")
                return False

            planned_tools = [t.tool_name for t in tool_plan.tools]
            sub_thought.context['planned_tools'] = planned_tools
            sub_thought.context['tool_params'] = {t.tool_name: t.parameters for t in tool_plan.tools}
            
            sub_thought.add_reasoning(f"计划执行工具：{planned_tools}")
            yield f"event: plan\ndata: {json.dumps({'step': 'plan', 'actions': [{'tool': t} for t in planned_tools]})}\n\n"

            # 3. Execute - 执行行动
            sub_thought.state = AgentState.ACTING
            
            for tool_name in planned_tools:
                tool = controller.tool_registry.get(tool_name)
                if not tool:
                    sub_thought.add_reasoning(f"工具 {tool_name} 不存在")
                    continue

                params = sub_thought.context.get('tool_params', {}).get(tool_name, {})
                sub_thought.add_reasoning(f"执行工具：{tool_name}")
                yield f"event: action\ndata: {json.dumps({'step': 'action', 'tool': tool_name, 'status': '执行中'})}\n\n"

                try:
                    result = tool.execute(**params)
                    sub_thought.add_action(tool_name, params, result)
                    
                    # 格式化观察结果，去除冗余信息
                    formatted_obs = _format_observation(result, tool_name)
                    yield f"event: observation\ndata: {json.dumps({'step': 'observation', 'tool': tool_name, 'result': formatted_obs})}\n\n"
                except Exception as e:
                    error_msg = f"工具执行失败：{str(e)}"
                    sub_thought.add_reasoning(error_msg)
                    yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"

            # 4. Observe - 观察结果
            sub_thought.state = AgentState.OBSERVING
            sub_thought.add_reasoning(f"收集到 {len(sub_thought.actions_taken)} 条观察结果")

            # 5. Reflect - 反思（可选）
            if controller.enable_reflection:
                sub_thought.state = AgentState.REFLECTING
                has_result = len(sub_thought.actions_taken) > 0 and any(a.get('result') for a in sub_thought.actions_taken)
                
                if has_result:
                    sub_thought.add_reasoning("已收集到足够的信息，准备生成答案")
                    # 提取ToolResult中的data字段，而不是整个对象
                    last_result = sub_thought.actions_taken[-1].get('result')
                    # last_result 可能是 ToolResult 对象或字典（来自 to_dict()）
                    if hasattr(last_result, 'data'):
                        result_data = last_result.data
                    elif isinstance(last_result, dict):
                        result_data = last_result.get('data', last_result)
                    else:
                        result_data = last_result
                    sub_thought.set_complete(result_data)
                else:
                    sub_thought.add_reasoning("信息不足，需要继续收集")

                if sub_thought.reflections:
                    yield f"event: reflect\ndata: {json.dumps({'step': 'reflect', 'content': sub_thought.reflections[-1]})}\n\n"
            
            # 6. 检查是否完成（无论是否启用反思都要执行）
            if sub_thought.state != AgentState.COMPLETE:
                has_result = len(sub_thought.actions_taken) > 0 and any(a.get('result') for a in sub_thought.actions_taken)
                if has_result:
                    last_result = sub_thought.actions_taken[-1].get('result')
                    if hasattr(last_result, 'data'):
                        result_data = last_result.data
                    elif isinstance(last_result, dict):
                        result_data = last_result.get('data', last_result)
                    else:
                        result_data = last_result
                    sub_thought.set_complete(result_data)
                    sub_thought.add_reasoning("工具执行成功，标记为完成")

            # 检查是否完成
            if sub_thought.state == AgentState.COMPLETE:
                # 只返回结果，不修改主 thought 的状态
                sub_goal.result = sub_thought.final_answer
                return True

            if controller._should_finalize(sub_thought):
                controller._finalize(sub_thought)
                if sub_thought.state == AgentState.COMPLETE:
                    sub_goal.result = sub_thought.final_answer
                    return True
                else:
                    sub_goal.error = sub_thought.error
                    return False

        # 强制结束
        if sub_thought.state not in [AgentState.COMPLETE, AgentState.FAILED]:
            controller._finalize(sub_thought)

        if sub_thought.state == AgentState.COMPLETE:
            sub_goal.result = sub_thought.final_answer
            return True
        else:
            sub_goal.error = sub_thought.error
            return False

    except Exception as e:
        sub_thought.set_failed(str(e))
        thought.set_failed(str(e))
        return False


def _generate_stream_legacy(query: str, context: Dict[str, Any], start_time: float) -> Generator:
    """旧版流式生成（回退用）"""
    agt = get_agent_safe()
    
    yield f"event: think\ndata: {json.dumps({'step': 'think', 'content': f'用户查询：{query}'})}\n\n"
    yield f"event: plan\ndata: {json.dumps({'step': 'plan', 'actions': [{'tool': 'recommend_heroes', 'purpose': '分析克制关系'}]})}\n\n"
    
    try:
        our_heroes = context.get('our_heroes', [])
        enemy_heroes = context.get('enemy_heroes', [])
        
        if not our_heroes and not enemy_heroes:
            parsed = parse_heroes_with_llm(query)
            our_heroes = parsed.get('our_heroes', [])
            enemy_heroes = parsed.get('enemy_heroes', [])
        
        yield f"event: action\ndata: {json.dumps({'step': 'action', 'tool': 'recommend_heroes', 'status': 'started'})}\n\n"
        
        if our_heroes or enemy_heroes:
            rec = agt.recommend_heroes(our_heroes, enemy_heroes)
            yield f"event: observation\ndata: {json.dumps({'step': 'observation', 'result': rec})}\n\n"
        
        total_time = time.time() - start_time
        yield f"event: complete\ndata: {json.dumps({'timestamp': int(time.time()), 'total_time': round(total_time, 2)})}\n\n"
    
    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"


@app.route('/api/sessions', methods=['GET'])
def get_sessions() -> Response:
    return jsonify([])


@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id: str) -> Response:
    return jsonify({"session_id": session_id, "messages": []})


@app.route('/api/tools', methods=['GET'])
def get_tools() -> Response:
    """获取所有可用的 Agent Tools"""
    if agent_controller:
        tools_info = []
        for tool_name in agent_controller.tool_registry.list_tools():
            tool = agent_controller.tool_registry.get(tool_name)
            if tool:
                schema = tool.get_schema()
                tools_info.append({
                    "name": schema["name"],
                    "description": schema["description"],
                    "category": schema.get("category", "general"),
                    "parameters": schema["parameters"]
                })
        return jsonify(tools_info)
    else:
        # 回退到静态列表
        tools = [
            {"name": "recommend_heroes", "description": "推荐克制英雄", "category": "hero"},
            {"name": "recommend_items", "description": "推荐出装", "category": "item"},
            {"name": "recommend_skills", "description": "推荐技能加点", "category": "skill"}
        ]
        return jsonify(tools)


@app.route('/api/memory/stats', methods=['GET'])
def get_memory_stats() -> Response:
    """获取 Memory 系统统计信息"""
    if agent:
        return jsonify(agent.get_memory_stats())
    return jsonify({"enabled": False})


@app.route('/api/memory/clear', methods=['POST'])
def clear_memory() -> Response:
    """清空 Memory 系统"""
    if agent:
        agent.clear_memory()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Agent not initialized"})


# === Langfuse 用户反馈 API ===

@app.route('/api/feedback', methods=['POST'])
def submit_feedback() -> Response:
    """提交用户反馈
    
    Request JSON:
        {
            "trace_id": "trace_xxx",
            "score": 0.9,
            "comment": "很有帮助"
        }
    
    Returns:
        {"status": "ok"}
    """
    data = request.json or {}
    trace_id = data.get('trace_id')
    score = data.get('score')
    comment = data.get('comment', '')
    
    if langfuse_client and langfuse_client.enabled and trace_id and score is not None:
        try:
            langfuse_client.score(name="user_feedback", value=float(score), comment=comment)
            langfuse_client.flush()
        except Exception as e:
            app_logger.warning(f"记录用户反馈失败: {e}")
    
    return jsonify({"status": "ok"})


# === 日志 API 接口 ===

@app.route('/api/logs', methods=['GET'])
def get_logs() -> Response:
    """获取日志（从内存）"""
    session_id = request.args.get('session_id')
    level = request.args.get('level')
    component = request.args.get('component')
    limit = int(request.args.get('limit', 100))

    logs = memory_handler.get_logs(
        session_id=session_id,
        level=level,
        component=component,
        limit=limit
    )

    return jsonify({"success": True, "logs": logs})


@app.route('/api/logs/stream')
def stream_logs() -> Response:
    """SSE 流式日志"""
    session_id = request.args.get('session_id')

    def generate():
        log_queue = queue.Queue()

        def on_new_log(log_entry):
            if not session_id or log_entry.get('session_id') == session_id:
                log_queue.put(log_entry)

        memory_handler.subscribe(on_new_log)

        try:
            while True:
                try:
                    log_entry = log_queue.get(timeout=1)
                    yield f"data: {json.dumps(log_entry)}\n\n"
                except queue.Empty:
                    # 发送心跳保持连接
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            memory_handler.unsubscribe(on_new_log)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/logs/files', methods=['GET'])
def get_log_files() -> Response:
    """获取日志文件列表（支持新的文件夹结构）"""
    from pathlib import Path
    import re

    files = []

    if LOG_DIR.exists():
        # 遍历日期文件夹
        for date_dir in sorted(LOG_DIR.iterdir()):
            if not date_dir.is_dir():
                continue
            if not re.match(r'\d{4}-\d{2}-\d{2}', date_dir.name):
                continue

            # 遍历 part 文件夹
            for part_dir in sorted(date_dir.iterdir()):
                if not part_dir.is_dir() or not part_dir.name.startswith('part-'):
                    continue

                for log_file in sorted(part_dir.glob("*.log*")):
                    stat = log_file.stat()
                    files.append({
                        "name": log_file.name,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "path": str(log_file.relative_to(LOG_DIR)),
                        "date": date_dir.name,
                        "part": part_dir.name
                    })

    return jsonify({"success": True, "files": files})


@app.route('/api/logs/files/<path:filename>', methods=['GET'])
def get_log_file_content(filename: str) -> Response:
    """获取日志文件内容"""
    from pathlib import Path

    file_path = LOG_DIR / filename

    # 安全检查：确保文件在日志目录内
    try:
        file_path.relative_to(LOG_DIR)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid path"}), 403

    if not file_path.exists():
        return jsonify({"success": False, "error": "File not found"}), 404

    # 支持 tail 参数获取最后 N 行
    tail = request.args.get('tail', type=int)

    try:
        if tail:
            lines = file_path.read_text(encoding='utf-8').splitlines()
            content = '\n'.join(lines[-tail:])
        else:
            content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success": True,
        "filename": filename,
        "content": content
    })


@app.route('/api/logs/clear', methods=['POST'])
def clear_logs() -> Response:
    """清空内存日志"""
    data = request.get_json() or {}
    session_id = data.get('session_id')
    memory_handler.clear(session_id)
    app_logger.info_ctx("日志已清空", session_id=session_id)
    return jsonify({"success": True})


# === Trace 追踪 API 接口 ===

@app.route('/api/trace/<trace_id>', methods=['GET'])
def get_trace_logs(trace_id: str):
    """根据 trace_id 查询完整链路日志
    
    Args:
        trace_id: Trace ID
        
    Returns:
        包含该 trace_id 的所有日志和 Span 树
    """
    # 从内存处理器获取所有日志
    all_logs = memory_handler.get_logs(limit=10000)
    
    # 过滤包含该 trace_id 的日志
    def has_trace_id(log, tid):
        """检查日志是否包含指定的 trace_id"""
        # 直接检查 trace_id 字段
        if log.get('trace_id') == tid:
            return True
        # 检查 trace 对象中的 trace_id
        trace = log.get('trace')
        if trace and isinstance(trace, dict) and trace.get('trace_id') == tid:
            return True
        # 检查 extra_data 中的 trace_id
        extra = log.get('extra_data') or {}
        if isinstance(extra, dict) and extra.get('trace_id') == tid:
            return True
        return False
    
    trace_logs = [
        log for log in all_logs 
        if has_trace_id(log, trace_id)
    ]
    
    # 按时间排序
    trace_logs.sort(key=lambda x: x.get('timestamp', ''))
    
    # 构建 Span 树
    span_tree = build_span_tree(trace_logs)
    
    # 获取相关 session_id
    session_ids = set()
    for log in trace_logs:
        session_id = log.get('session_id') or log.get('trace', {}).get('session_id')
        if session_id:
            session_ids.add(session_id)
    
    return jsonify({
        'success': True,
        'trace_id': trace_id,
        'total_logs': len(trace_logs),
        'session_ids': list(session_ids),
        'span_tree': span_tree,
        'logs': trace_logs
    })


def build_span_tree(logs: list) -> dict:
    """构建 Span 树结构
    
    Args:
        logs: 日志列表
        
    Returns:
        Span 树结构
    """
    spans = {}
    root_spans = []
    
    for log in logs:
        # 尝试从多个位置获取 Trace 信息
        trace_info = log.get('trace') or {}
        
        # 如果 trace 为空，尝试从 extra_data 中获取
        if not trace_info:
            extra_data = log.get('extra_data') or {}
            if isinstance(extra_data, dict) and 'span_id' in extra_data:
                trace_info = {
                    'span_id': extra_data.get('span_id'),
                    'parent_span_id': extra_data.get('parent_span_id'),
                    'operation': extra_data.get('operation'),
                    'duration_ms': extra_data.get('duration_ms')
                }
        
        if not isinstance(trace_info, dict):
            continue
            
        span_id = trace_info.get('span_id')
        parent_id = trace_info.get('parent_span_id')
        
        if span_id and span_id not in spans:
            spans[span_id] = {
                'span_id': span_id,
                'parent_span_id': parent_id,
                'operation': trace_info.get('operation'),
                'session_id': log.get('session_id'),
                'start_time': None,
                'end_time': None,
                'duration_ms': trace_info.get('duration_ms'),
                'logs': [],
                'children': []
            }
        
        if span_id and span_id in spans:
            spans[span_id]['logs'].append({
                'timestamp': log.get('timestamp'),
                'level': log.get('level'),
                'message': log.get('message'),
                'component': log.get('component')
            })
    
    # 建立父子关系
    for span_id, span in spans.items():
        parent_id = span['parent_span_id']
        if parent_id and parent_id in spans:
            spans[parent_id]['children'].append(span_id)
        else:
            root_spans.append(span_id)
    
    return {
        'roots': root_spans,
        'spans': spans,
        'total_spans': len(spans)
    }


@app.route('/api/trace/search', methods=['GET'])
def search_traces() -> Response:
    """搜索 Trace
    
    Query Params:
        session_id: 会话ID
        operation: 操作名称
        start_time: 开始时间 (ISO格式)
        end_time: 结束时间 (ISO格式)
        limit: 返回数量限制
        
    Returns:
        Trace 列表
    """
    session_id = request.args.get('session_id')
    operation = request.args.get('operation')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    limit = int(request.args.get('limit', 100))
    
    # 获取所有日志
    all_logs = memory_handler.get_logs(limit=10000)
    
    # 收集唯一的 trace_id
    traces = {}
    for log in all_logs:
        trace_info = log.get('trace', {})
        trace_id = trace_info.get('trace_id') or log.get('trace_id')
        
        if not trace_id:
            continue
        
        # 过滤条件
        if session_id:
            log_session_id = trace_info.get('session_id') or log.get('session_id')
            if log_session_id != session_id:
                continue
        
        if operation and trace_info.get('operation') != operation:
            continue
        
        # 收集 trace 信息
        if trace_id not in traces:
            traces[trace_id] = {
                'trace_id': trace_id,
                'session_id': trace_info.get('session_id') or log.get('session_id'),
                'operation': trace_info.get('operation'),
                'first_seen': log.get('timestamp'),
                'last_seen': log.get('timestamp'),
                'log_count': 0
            }
        
        traces[trace_id]['log_count'] += 1
        traces[trace_id]['last_seen'] = max(
            traces[trace_id]['last_seen'],
            log.get('timestamp', '')
        )
    
    # 转换为列表并排序
    trace_list = list(traces.values())
    trace_list.sort(key=lambda x: x['last_seen'], reverse=True)
    
    return jsonify({
        'success': True,
        'total': len(trace_list),
        'traces': trace_list[:limit]
    })


@app.route('/api/generate_hero_query', methods=['POST'])
def generate_hero_query() -> Response:
    """随机生成英雄查询文本"""
    import random
    
    try:
        # 读取英雄数据
        heroes_file = Path(__file__).parent.parent / 'data' / 'heroes_cn.json'
        
        if not heroes_file.exists():
            return jsonify({
                "success": False,
                "error": "英雄数据文件不存在"
            }), 404
        
        with open(heroes_file, 'r', encoding='utf-8') as f:
            heroes_data = json.load(f)
        
        # 提取所有英雄中文名
        all_heroes = [info.get('cn', '') for info in heroes_data.values() if info.get('cn')]
        
        if len(all_heroes) < 9:  # 至少需要9个英雄
            return jsonify({
                "success": False,
                "error": "英雄数据不足"
            }), 500
        
        # 随机选择我方英雄数量（0-4个）
        our_count = random.randint(0, 4)
        
        # 随机选择敌方英雄数量（0-5个）
        enemy_count = random.randint(0, 5)
        
        # 确保总数不超过英雄总数
        total_needed = our_count + enemy_count
        if total_needed > len(all_heroes):
            total_needed = len(all_heroes)
            # 重新分配
            our_count = random.randint(0, min(4, total_needed))
            enemy_count = total_needed - our_count
        
        # 随机选择英雄（保证不重复）
        selected_heroes = random.sample(all_heroes, total_needed)
        
        # 分配我方和敌方
        our_heroes = selected_heroes[:our_count]
        enemy_heroes = selected_heroes[our_count:]
        
        # 生成查询文本
        parts = []
        if our_heroes:
            parts.append(f"我方英雄有{','.join(our_heroes)}")
        if enemy_heroes:
            parts.append(f"敌方英雄有{','.join(enemy_heroes)}")
        
        query = '，'.join(parts) + '，推荐我选什么英雄，并简要给出理由'
        
        return jsonify({
            "success": True,
            "query": query,
            "our_heroes": our_heroes,
            "enemy_heroes": enemy_heroes
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == '__main__':
    app_logger.info("=" * 50)
    app_logger.info("DotaHelperAgent API Server - ReAct Agent 架构")
    app_logger.info("=" * 50)
    app_logger.info("API Server: http://localhost:5000")
    app_logger.info("Frontend: cd frontend && npm run dev")
    app_logger.info("=" * 50)
    
    # 初始化 Agent Controller
    initialize_agent_controller()
    
    # 启动每日缓存刷新任务
    start_cache_scheduler()
    
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
