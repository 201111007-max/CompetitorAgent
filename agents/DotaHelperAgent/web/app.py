"""DotaHelperAgent Web API Server

基于 ReAct Agent 架构的 Flask 后端，支持完整的 Agent 推理循环
"""

import sys
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import json
import time
import uuid
import threading
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent import DotaHelperAgent
from core.agent_controller import AgentController
from core.tool_registry import ToolRegistry
from tools.agent_tools import create_all_tools
from core.config import AgentConfig, LLMConfig
from utils.llm_client import LLMClient

app = Flask(__name__)
CORS(app)

WEB_DIR = Path(__file__).parent

# 全局变量
agent = None
agent_controller = None
llm_client = None
cache_warming = False
cache_ready = False

HERO_PARSE_PROMPT = """你是一个 Dota 2 英雄名称解析器。请从用户输入中提取英雄名称。

支持的中英文英雄名称：
- 英文名如：pudge, anti-mage, invoker, axe, sven, lion, crystal_maiden, shadow_fiend, natures_prophet
- 中文名如：帕吉 (爸爸)、幻影刺客 (PA)、祈求者 (Invoker)、斧王、剑圣、恶魔巫师、斯温 (Sven)、军团 (Legion Commander)、黑鸟 (Obsidian Destroyer)、船长 (Kunkka)

请从以下用户输入中提取所有英雄名称，返回 JSON 格式：
{{
    "our_heroes": ["己方英雄列表"],
    "enemy_heroes": ["敌方英雄列表"]
}}

规则：
- 如果用户说"敌方"、"enemy"、"克制"、"地方"（typo，通常是敌方）、"敌方有"等，认为是敌方英雄
- 如果用户说"己方"、"our"、"我们"、"我方有"、"我方"等，认为是己方英雄
- 如果只说"有"谁，没有明确说是己方还是敌方，默认是敌方英雄
- 注意："地方"是"敌方"的 typo，应该算作敌方
- 只返回英雄的**英文名称**（如 pudge, sven），不要中文名
- 如果没有找到任何英雄，返回空列表

用户输入：{query}

请只返回 JSON，不要其他内容："""


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


def get_llm_client():
    global llm_client
    if llm_client is None:
        try:
            llm_config = LLMConfig.from_yaml()
            if llm_config.enabled:
                llm_client = LLMClient(llm_config)
            else:
                llm_client = None
        except Exception as e:
            print(f"Failed to initialize LLM client: {e}")
            llm_client = None
    return llm_client


def parse_heroes_with_llm(query):
    """使用 LLM 从 query 中解析英雄名称"""
    client = get_llm_client()
    if client is None:
        # 没有 LLM 时，使用规则解析
        return parse_heroes_with_rules(query)

    try:
        messages = [
            {"role": "user", "content": HERO_PARSE_PROMPT.format(query=query)}
        ]
        response = client.chat(messages, max_tokens=512, temperature=0.1)

        if "error" in response:
            print(f"LLM 解析英雄失败：{response['error']}")
            return parse_heroes_with_rules(query)

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "our_heroes": result.get("our_heroes", []),
                "enemy_heroes": result.get("enemy_heroes", [])
            }
    except Exception as e:
        print(f"LLM 解析英雄异常：{e}")

    return parse_heroes_with_rules(query)


def parse_heroes_with_rules(query):
    """使用规则从 query 中解析英雄名称（LLM 不可用时的备用方案）"""
    our_heroes = []
    enemy_heroes = []
    
    # 常见英雄名称映射（中文 -> 英文）
    hero_map = {
        '敌法': 'anti-mage',
        '幻影刺客': 'phantom_assassin',
        'pa': 'phantom_assassin',
        '小黑': 'drow_ranger',
        '黑鸟': 'obsidian_destroyer',
        'od': 'obsidian_destroyer',
        '小鹿': 'enchantress',
        '军团': 'legion_commander',
        '小鱼': 'slark',
        '兽': 'beastmaster',
        '兽王': 'beastmaster',
        '帕吉': 'pudge',
        '斧王': 'axe',
        '祈求者': 'invoker',
        '卡尔': 'invoker',
        '剑圣': 'juggernaut',
        'jugg': 'juggernaut',
        '水晶': 'crystal_maiden',
        'cm': 'crystal_maiden',
        'lion': 'lion',
        '莱恩': 'lion',
        '斯温': 'sven',
        '小小': 'tiny',
        '影魔': 'shadow_fiend',
        'sf': 'shadow_fiend',
    }
    
    query_lower = query.lower()
    
    # 检测敌方英雄的关键词
    enemy_keywords = ['敌方', '对面', 'enemy', '克制', '对面有', '敌方有']
    
    # 检测己方英雄的关键词
    our_keywords = ['我方', '我们', '己方', 'our', 'we', '我们选了', '我们有']
    
    # 先判断是敌方还是己方
    is_enemy = False
    for keyword in enemy_keywords:
        if keyword in query_lower:
            is_enemy = True
            break
    
    # 使用更智能的分割方式 - 按逗号、空格分割
    # 但要保留"我们有"、"对面有"这样的关键词用于判断
    parts = re.split(r'[，,]', query_lower)
    
    current_side = 'enemy' if is_enemy else 'our'
    
    for part in parts:
        part = part.strip()
        
        # 检查这部分是否包含侧边关键词
        for keyword in our_keywords:
            if keyword in part:
                current_side = 'our'
                break
        for keyword in enemy_keywords:
            if keyword in part:
                current_side = 'enemy'
                break
        
        # 提取英雄名称
        words = part.split()
        for word in words:
            word = word.strip()
            if len(word) < 1 or len(word) > 20:
                continue
            
            # 跳过关键词
            if word in our_keywords or word in enemy_keywords:
                continue
                
            # 检查是否是英雄名称
            if word in hero_map:
                hero = hero_map[word]
                if current_side == 'our':
                    our_heroes.append(hero)
                else:
                    enemy_heroes.append(hero)
    
    print(f"[DEBUG] Rule-based hero parsing: our={our_heroes}, enemy={enemy_heroes}")
    return {"our_heroes": our_heroes, "enemy_heroes": enemy_heroes}


def parse_items_with_llm(query):
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
            print(f"LLM 解析物品失败：{response['error']}")
            return {"items": []}

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {"items": result.get("items", [])}
    except Exception as e:
        print(f"LLM 解析物品异常：{e}")

    return {"items": []}


def parse_hero_from_query(query):
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
        print(f"LLM 解析英雄名异常：{e}")
        return ""


def warm_cache():
    global cache_warming, cache_ready
    if cache_warming or cache_ready:
        return
    cache_warming = True
    print("正在预热缓存，请稍候...")
    try:
        agt = get_agent()
        client = agt.client
        heroes = client.get_heroes()
        if heroes:
            enemy_ids = [1, 11, 15, 23, 25]
            for hid in enemy_ids:
                matchups = client.get_hero_matchups(hid)
                print(f"已缓存英雄 {hid} 的克制数据")
        cache_ready = True
        print("缓存预热完成！")
    except Exception as e:
        print(f"缓存预热失败：{e}")
    cache_warming = False


def initialize_agent_controller():
    """初始化 Agent 和 Agent Controller"""
    global agent, agent_controller
    
    if agent_controller is not None:
        return agent_controller
    
    try:
        # 加载配置
        config = AgentConfig()
        
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
        print(f"[OK] 已注册 {len(registry)} 个 Agent Tools")
        
        # 创建 Agent Controller
        agent_controller = AgentController(
            tool_registry=registry,
            memory=agent.memory,
            max_turns=5,
            enable_reflection=True,
            enable_memory=True
        )
        
        print("[OK] Agent Controller 初始化完成")
        return agent_controller
        
    except Exception as e:
        print(f"[ERROR] Agent Controller 初始化失败：{e}")
        # 回退到基本模式
        agent = DotaHelperAgent()
        return None


@app.route('/')
def index():
    return send_file(WEB_DIR / 'index.html')


@app.route('/web/<path:filename>')
def serve_web(filename):
    return send_file(WEB_DIR / filename)


def get_agent():
    global agent
    if agent is None:
        try:
            config = AgentConfig()
            agent = DotaHelperAgent(config=config)
        except Exception as e:
            print(f"Failed to load config: {e}")
            agent = DotaHelperAgent()
    return agent


def get_agent_safe():
    global cache_ready, cache_warming
    agt = get_agent()
    if not cache_ready and not cache_warming:
        threading.Thread(target=warm_cache, daemon=True).start()
    return agt


def _get_mock_recommendations(enemy_heroes):
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
def before_first_request():
    global cache_ready, cache_warming
    if not cache_ready and not cache_warming:
        threading.Thread(target=warm_cache, daemon=True).start()


@app.route('/api/health', methods=['GET'])
def health_check():
    llm_enabled = get_llm_client() is not None
    controller_ready = agent_controller is not None
    memory_stats = agent.get_memory_stats() if agent else {}
    
    return jsonify({
        "status": "ok",
        "service": "DotaHelperAgent",
        "llm_enabled": llm_enabled,
        "agent_controller_ready": controller_ready,
        "memory": memory_stats
    })


@app.route('/api/test_tools', methods=['GET'])
def test_tools():
    """测试工具执行"""
    if agent_controller is None:
        return jsonify({"error": "Agent Controller not initialized"})
    
    # 测试工具注册
    tools = agent_controller.tool_registry.list_tools()
    
    # 测试英雄解析
    test_query = "我们有敌法，黑鸟，小鹿，对面有军团，小鱼，兽"
    parsed = parse_heroes_with_rules(test_query)
    
    # 测试工具执行
    result = {}
    try:
        # 测试 analyze_counter_picks 工具
        counter_tool = agent_controller.tool_registry.get("analyze_counter_picks")
        if counter_tool:
            print(f"[TEST] Found tool: {counter_tool.name}")
            print(f"[TEST] Tool parameters: {counter_tool.parameters}")
            
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
    
    return jsonify({
        "tools": tools,
        "parsed_heroes": parsed,
        "test_result": result
    })


@app.route('/api/chat', methods=['POST'])
def chat():
    """使用 Agent Controller 处理聊天请求"""
    data = request.get_json()
    query = data.get('query', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    context = data.get('context', {})

    # 如果没有 Agent Controller，回退到旧版实现
    if agent_controller is None:
        return _chat_legacy(query, context, session_id)

    agt = get_agent()

    result = {
        "success": True,
        "session_id": session_id,
        "query": query,
        "agent_mode": True
    }

    if not query.strip():
        result["success"] = False
        result["error"] = "Query cannot be empty"
        return jsonify(result)

    try:
        # 如果 context 中没有英雄信息，尝试从 query 中解析
        if 'our_heroes' not in context and 'enemy_heroes' not in context:
            parsed = parse_heroes_with_llm(query)
            if parsed['our_heroes'] or parsed['enemy_heroes']:
                context.update(parsed)
                print(f"[DEBUG] Parsed heroes from query: {parsed}")

        # 使用 Agent Controller 执行 ReAct 循环
        controller_result = agent_controller.solve(query, context)
        
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
            if isinstance(answer_data, dict):
                result["final_answer"] = _format_answer(answer_data)
            else:
                result["final_answer"] = str(answer_data)
        else:
            result["final_answer"] = controller_result.get("error", "处理失败")

        # 保存到记忆（如果启用）
        if agent and agent.enable_memory:
            agent.save_query_result(query, result, tags=["chat"])

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["final_answer"] = f"处理查询时出错：{str(e)}"

    return jsonify(result)


def _format_answer(answer_data: dict) -> str:
    """格式化 Agent 答案为文本"""
    formatted = []
    
    # 处理推荐
    if "recommendations" in answer_data:
        recs = answer_data["recommendations"]
        if isinstance(recs, list) and len(recs) > 0:
            formatted.append("推荐结果：")
            for i, rec in enumerate(recs[:5], 1):
                if isinstance(rec, dict):
                    hero = rec.get("hero_name", rec.get("hero", "Unknown"))
                    score = rec.get("score", 0)
                    reasons = rec.get("reasons", rec.get("reason", []))
                    reason_text = "; ".join(reasons[:2]) if isinstance(reasons, list) else str(reasons)
                    formatted.append(f"{i}. {hero} (指数：{score:.2f}) - {reason_text}")
    
    # 处理答案
    if "answer" in answer_data:
        formatted.append(f"\n答案：{answer_data['answer']}")
    
    return "\n".join(formatted) if formatted else str(answer_data)


def _chat_legacy(query, context, session_id):
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


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """流式输出接口（使用 Agent Controller）"""
    data = request.get_json()
    query = data.get('query', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    context = data.get('context', {})

    def generate():
        start_time = time.time()

        yield f"event: start\ndata: {json.dumps({'timestamp': int(start_time)})}\n\n"

        if not query.strip():
            yield f"event: error\ndata: {json.dumps({'error': 'Query cannot be empty'})}\n\n"
            yield f"event: complete\ndata: {json.dumps({'timestamp': int(time.time()), 'total_time': 0})}\n\n"
            return

        # 如果没有 Agent Controller，回退到简单流式
        if agent_controller is None:
            yield from _generate_stream_legacy(query, context, start_time)
            return

        try:
            # 使用 Agent Controller 执行
            controller_result = agent_controller.solve(query, context)
            
            # 流式输出思考过程
            for reasoning in controller_result.get('reasoning', []):
                yield f"event: think\ndata: {json.dumps({'step': 'think', 'content': reasoning})}\n\n"
            
            # 流式输出行动
            for action in controller_result.get('actions', []):
                yield f"event: action\ndata: {json.dumps({'step': 'action', 'tool': action.get('tool_name')})}\n\n"
            
            # 流式输出反思
            for reflection in controller_result.get('reflections', []):
                yield f"event: reflect\ndata: {json.dumps({'step': 'reflect', 'content': reflection})}\n\n"
            
            # 输出最终答案
            if controller_result.get('success'):
                answer = controller_result.get('answer', {})
                yield f"event: synthesize\ndata: {json.dumps({'step': 'synthesize', 'answer': answer})}\n\n"
            else:
                error = controller_result.get('error', '处理失败')
                yield f"event: error\ndata: {json.dumps({'error': error})}\n\n"

            total_time = time.time() - start_time
            yield f"event: complete\ndata: {json.dumps({'timestamp': int(time.time()), 'total_time': round(total_time, 2), 'turns': controller_result.get('turn_count', 0)})}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            yield f"event: complete\ndata: {json.dumps({'timestamp': int(time.time()), 'total_time': time.time() - start_time})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


def _generate_stream_legacy(query, context, start_time):
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
def get_sessions():
    return jsonify([])


@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    return jsonify({"session_id": session_id, "messages": []})


@app.route('/api/tools', methods=['GET'])
def get_tools():
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
def get_memory_stats():
    """获取 Memory 系统统计信息"""
    if agent:
        return jsonify(agent.get_memory_stats())
    return jsonify({"enabled": False})


@app.route('/api/memory/clear', methods=['POST'])
def clear_memory():
    """清空 Memory 系统"""
    if agent:
        agent.clear_memory()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Agent not initialized"})


if __name__ == '__main__':
    print("=" * 50)
    print("DotaHelperAgent Web Server - ReAct Agent 架构")
    print("=" * 50)
    print("API Server: http://localhost:5000")
    print("Web UI: http://localhost:5000/web/index.html")
    print("=" * 50)
    
    # 初始化 Agent Controller
    initialize_agent_controller()
    
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
