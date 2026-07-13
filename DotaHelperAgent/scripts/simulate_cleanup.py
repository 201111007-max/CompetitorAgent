"""模拟清理脚本 - 生成待删除文件清单

将 DotaHelperAgent 精简为仅保留以下核心功能：
1. 英雄分析、出装推荐、问答
2. 比赛录像分析及总结（待新建）
3. 前端页面展示
4. 分析结果保存为 MD 文件（待新建）

本脚本仅模拟删除操作，生成清单报告，不实际删除任何文件。
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from dataclasses import dataclass, field


@dataclass
class DeleteItem:
    """待删除项"""
    path: str
    item_type: str  # "file" or "dir"
    reason: str
    category: str  # 所属模块分类


@dataclass
class CleanupReport:
    """清理报告"""
    files_to_delete: List[DeleteItem] = field(default_factory=list)
    dirs_to_delete: List[DeleteItem] = field(default_factory=list)
    files_to_keep: List[str] = field(default_factory=list)
    total_files: int = 0
    total_size_bytes: int = 0

    @property
    def total_delete_count(self) -> int:
        return len(self.files_to_delete) + len(self.dirs_to_delete)


# ============================================================
# 项目根目录
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent


def get_file_size(path: Path) -> int:
    """获取文件或目录大小"""
    try:
        if path.is_file():
            return path.stat().st_size
        elif path.is_dir():
            total = 0
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
            return total
    except (OSError, PermissionError):
        return 0


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def collect_delete_targets() -> CleanupReport:
    """收集所有待删除的文件和目录"""
    report = CleanupReport()

    # ========================================================
    # 1. 整目录删除
    # ========================================================
    dirs_to_remove = [
        # --- GSI 实时游戏状态模块 ---
        ("gsi", "GSI 实时游戏状态监控模块，与目标功能无关"),

        # --- 决策引擎（为 GSI 主动推荐服务）---
        ("core/decision", "决策融合器（规则/数据/LLM引擎），为 GSI 主动推荐服务"),

        # --- 推荐系统工具 ---
        # 注意：tools/ 目录下的单独文件在文件列表中处理

        # --- 知识管理系统 ---
        ("knowledge", "ChromaDB 向量检索系统，非核心需求，复杂度高"),

        # --- 反馈学习系统 ---
        ("feedback", "用户反馈学习系统，为 GSI 推荐优化服务"),

        # --- 评估系统 ---
        ("evaluation", "Agent 质量评估系统，非核心需求"),

        # --- 部署配置 ---
        ("deploy", "Langfuse Docker 部署配置，非核心"),

        # --- 语音资源 ---
        ("resources/voice", "13 个语音提醒 .wav 文件，GSI 事件提醒专用"),

        # --- 评分策略 ---
        ("strategies", "评分策略模块，仅服务于旧分析流程"),

        # --- 不需要的 Skill 子目录 ---
        ("skills/lineup_analyzer", "阵容分析 Skill，非核心功能"),
        ("skills/meta_analyzer", "元分析 Skill，非核心功能"),
        ("skills/knowledge_query", "知识查询 Skill，依赖已删除的 knowledge 模块"),

        # --- 测试目录（已删除模块对应的测试）---
        ("tests/gsi", "GSI 模块测试"),
        ("tests/feedback", "反馈系统测试"),
        ("tests/evaluation", "评估系统测试"),
        ("tests/knowledge", "知识系统测试"),

        # --- 脚本（已删除模块相关）---
        ("scripts/evaluation", "评估脚本"),
    ]

    for dir_path, reason in dirs_to_remove:
        full_path = PROJECT_ROOT / dir_path
        if full_path.exists():
            category = dir_path.split("/")[0]
            report.dirs_to_delete.append(DeleteItem(
                path=dir_path,
                item_type="dir",
                reason=reason,
                category=category,
            ))

    # ========================================================
    # 2. 单独文件删除
    # ========================================================
    files_to_remove = [
        # --- 核心：事件触发器（GSI 推荐相关）---
        ("core/event_trigger.py", "事件触发器，为 GSI 主动推荐服务"),

        # --- 工具层：已删除模块的工具文件 ---
        ("tools/gsi_tools.py", "GSI 数据工具"),
        ("tools/recommendation_tools.py", "推荐系统工具，为 GSI 主动推荐服务"),
        ("tools/knowledge_tools.py", "知识管理工具，依赖已删除的 knowledge 模块"),

        # --- 工具层：utils ---
        ("utils/voice_player.py", "语音播放器，GSI 事件提醒专用"),
        ("utils/background_loader.py", "知识数据后台加载器，依赖已删除的 knowledge 模块"),

        # --- 配置文件 ---
        ("config/gsi_config.yaml", "GSI 配置"),
        ("config/feedback_config.yaml", "反馈学习配置"),
        ("config/recommendation_config.yaml", "推荐系统配置"),
        ("config/knowledge_config.yaml", "知识管理配置"),
        ("config/parallel_execution_config.yaml", "并行执行配置（暂不需要）"),

        # --- Prompt 模板（已删除模块相关）---
        ("config/prompts/decision.yaml", "决策 Prompt，为 GSI 决策引擎服务"),
        ("config/prompts/recommendation.yaml", "推荐 Prompt，为 GSI 推荐服务"),

        # --- 前端：GSI 相关组件 ---
        ("frontend/src/components/GsiStatusPanel.vue", "GSI 状态面板组件"),

        # --- 前端：GSI/推荐 composable ---
        ("frontend/src/composables/useGsiStream.ts", "GSI 流式处理 Hook"),
        ("frontend/src/composables/useRecommendationStream.ts", "推荐流式处理 Hook"),

        # --- 前端：GSI 类型定义 ---
        ("frontend/src/types/gsi.ts", "GSI 类型定义"),

        # --- 测试：已删除模块对应的单独测试文件 ---
        ("tests/utils/test_voice_player.py", "语音播放器测试"),
        ("tests/unit/test_background_loader.py", "后台加载器测试"),
        ("tests/unit/test_event_trigger.py", "事件触发器测试"),
        ("tests/unit/test_recommendation_tools.py", "推荐工具测试"),
        ("tests/integration/test_feedback_integration.py", "反馈集成测试"),
        ("tests/integration/test_voice_integration.py", "语音集成测试"),
        ("tests/integration/test_parallel_execution_integration.py", "并行执行集成测试"),

        # --- 测试：顶层散落的已删除模块测试 ---
        ("tests/test_data_engine.py", "数据引擎测试（decision 模块）"),
        ("tests/test_decision_fusion.py", "决策融合测试（decision 模块）"),
        ("tests/test_llm_engine.py", "LLM 引擎测试（decision 模块）"),
        ("tests/test_rule_engine.py", "规则引擎测试（decision 模块）"),

        # --- Skill 测试 ---
        ("tests/skills/test_knowledge_query.py", "知识查询 Skill 测试"),
        ("tests/skills/test_lineup_analyzer.py", "阵容分析 Skill 测试"),
        ("tests/skills/test_meta_analyzer.py", "元分析 Skill 测试"),

        # --- 脚本 ---
        ("scripts/import_knowledge.py", "知识导入脚本，依赖已删除的 knowledge 模块"),
    ]

    for file_path, reason in files_to_remove:
        full_path = PROJECT_ROOT / file_path
        if full_path.exists():
            category = file_path.split("/")[0]
            report.files_to_delete.append(DeleteItem(
                path=file_path,
                item_type="file",
                reason=reason,
                category=category,
            ))

    # ========================================================
    # 3. 统计
    # ========================================================
    for item in report.dirs_to_delete:
        full_path = PROJECT_ROOT / item.path
        report.total_size_bytes += get_file_size(full_path)
        # 统计目录下的文件数
        if full_path.is_dir():
            report.total_files += len(list(full_path.rglob("*")))

    for item in report.files_to_delete:
        full_path = PROJECT_ROOT / item.path
        if full_path.is_file():
            report.total_size_bytes += full_path.stat().st_size
            report.total_files += 1

    return report


def generate_markdown_report(report: CleanupReport) -> str:
    """生成 Markdown 格式的清理报告"""
    lines = []
    lines.append("# DotaHelperAgent 精简清理报告")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 项目路径：`{PROJECT_ROOT}`")
    lines.append("")
    lines.append("## 一、精简目标")
    lines.append("")
    lines.append("将 DotaHelperAgent 精简为仅保留以下核心功能：")
    lines.append("")
    lines.append("1. **英雄分析、出装推荐、问答** - 现有功能保留")
    lines.append("2. **比赛录像分析及总结** - 待新建")
    lines.append("3. **前端页面展示** - 保留并调整")
    lines.append("4. **分析结果保存为 MD 文件** - 待新建")
    lines.append("")
    lines.append("## 二、删除统计概览")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 待删除目录数 | {len(report.dirs_to_delete)} |")
    lines.append(f"| 待删除文件数 | {len(report.files_to_delete)} |")
    lines.append(f"| 涉及文件总数 | {report.total_files} |")
    lines.append(f"| 释放空间 | {format_size(report.total_size_bytes)} |")
    lines.append("")

    # 按模块分类汇总
    categories: Dict[str, List[DeleteItem]] = {}
    for item in report.dirs_to_delete + report.files_to_delete:
        cat = item.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)

    lines.append("## 三、按模块分类的删除清单")
    lines.append("")

    category_descriptions = {
        "gsi": "GSI 实时游戏状态模块",
        "core": "Agent 核心模块（决策引擎/事件触发）",
        "tools": "工具层（GSI/推荐/知识工具）",
        "knowledge": "知识管理系统",
        "feedback": "反馈学习系统",
        "evaluation": "评估系统",
        "deploy": "部署配置",
        "resources": "资源文件（语音）",
        "strategies": "评分策略",
        "skills": "Skill 模块",
        "config": "配置文件",
        "frontend": "前端文件",
        "tests": "测试文件",
        "scripts": "脚本文件",
        "utils": "工具函数",
    }

    for cat in sorted(categories.keys()):
        items = categories[cat]
        cat_desc = category_descriptions.get(cat, cat)
        lines.append(f"### {cat_desc} (`{cat}/`)")
        lines.append("")
        lines.append("| 类型 | 路径 | 删除原因 |")
        lines.append("|------|------|---------|")
        for item in sorted(items, key=lambda x: x.path):
            type_icon = "DIR" if item.item_type == "dir" else "FILE"
            lines.append(f"| {type_icon} | `{item.path}` | {item.reason} |")
        lines.append("")

    # ========================================================
    # 保留清单
    # ========================================================
    lines.append("## 四、保留模块清单")
    lines.append("")
    lines.append("### 4.1 后端保留")
    lines.append("")

    keep_backend = [
        ("core/agent.py", "Agent 主类"),
        ("core/agent_controller.py", "ReAct 循环控制器"),
        ("core/tool_registry.py", "工具注册表"),
        ("core/llm_tool_selector.py", "LLM 智能工具选择器"),
        ("core/conversation_manager.py", "会话管理器"),
        ("core/context_augmenter.py", "上下文增强器"),
        ("core/goal_planner.py", "目标分解与追踪"),
        ("core/reflection_evaluator.py", "多维度反思评估"),
        ("core/dependency_analyzer.py", "依赖分析器"),
        ("core/parallel_executor.py", "并行执行器"),
        ("core/parallel_execution_config.py", "并行执行配置"),
        ("core/hybrid_base.py", "混合模式基类"),
        ("core/config.py", "配置类定义"),
        ("core/metacognition/", "元认知模块（LLM 驱动评估）"),
        ("analyzers/", "分析器（英雄/物品/技能）"),
        ("tools/base.py", "工具基类"),
        ("tools/agent_tools.py", "工具工厂"),
        ("tools/hero_tools.py", "英雄分析工具"),
        ("tools/build_tools.py", "出装/技能推荐工具"),
        ("tools/search_tools.py", "搜索工具（问答用）"),
        ("managers/", "数据管理器"),
        ("cache/", "缓存系统"),
        ("memory/", "记忆系统"),
        ("utils/api_client.py", "OpenDota API 客户端"),
        ("utils/llm_client.py", "LLM 客户端"),
        ("utils/localization.py", "本地化工具"),
        ("utils/log_config.py", "日志配置"),
        ("utils/memory_log_handler.py", "内存日志处理器"),
        ("utils/prompt_manager.py", "Prompt 管理器"),
        ("utils/prompt_strategy.py", "Prompt 策略"),
        ("utils/trace_context.py", "Trace 上下文"),
        ("utils/trace_persistence.py", "Trace 持久化"),
        ("utils/langfuse_adapter.py", "Langfuse 适配器（可选）"),
        ("utils/langfuse_config.py", "Langfuse 配置"),
        ("web/app.py", "Flask API 后端（需精简 API 端点）"),
        ("skills/base.py", "Skill 基类"),
        ("skills/registry.py", "Skill 注册表"),
        ("skills/fallback.py", "降级处理"),
        ("skills/exceptions.py", "异常定义"),
        ("skills/dialogue_understander/", "对话理解 Skill"),
        ("skills/web_search/", "网络搜索 Skill"),
        ("data/", "数据文件（英雄/物品/对局数据）"),
        ("config/llm_config.yaml*", "LLM 配置"),
        ("config/langfuse_config.yaml", "Langfuse 配置"),
        ("config/prompt_config.yaml", "Prompt 配置"),
        ("config/skills_config.yaml", "Skill 配置"),
        ("config/prompts/system_prompts.yaml", "系统 Prompt"),
        ("config/prompts/hero_analysis.yaml", "英雄分析 Prompt"),
        ("config/prompts/skill_build.yaml", "技能加点 Prompt"),
        ("config/prompts/skills.yaml", "Skill Prompt"),
    ]

    lines.append("| 路径 | 说明 |")
    lines.append("|------|------|")
    for path, desc in keep_backend:
        lines.append(f"| `{path}` | {desc} |")
    lines.append("")

    lines.append("### 4.2 前端保留")
    lines.append("")

    keep_frontend = [
        ("src/components/ChatBox.vue", "聊天主界面"),
        ("src/components/HeroPanel.vue", "英雄选择面板"),
        ("src/components/LogPanel.vue", "日志侧边栏"),
        ("src/components/MarkdownRenderer.vue", "Markdown 渲染"),
        ("src/components/MessageActions.vue", "消息操作"),
        ("src/components/RightDrawer.vue", "右侧抽屉"),
        ("src/components/SidePanel.vue", "侧边面板"),
        ("src/components/ThinkingSteps.vue", "思考步骤展示"),
        ("src/components/TopStatusBar.vue", "顶部状态栏"),
        ("src/composables/useChatStream.ts", "聊天流式处理"),
        ("src/composables/useHeroQuery.ts", "英雄查询 Hook"),
        ("src/composables/useLogStream.ts", "日志流式处理"),
        ("src/stores/chat.ts", "聊天状态"),
        ("src/stores/hero.ts", "英雄状态"),
        ("src/stores/log.ts", "日志状态"),
        ("src/types/chat.ts", "聊天类型"),
        ("src/types/hero.ts", "英雄类型"),
        ("src/types/log.ts", "日志类型"),
        ("src/styles/", "样式文件"),
        ("src/App.vue", "根组件"),
        ("src/main.ts", "入口文件"),
        ("src/router/", "路由配置"),
        ("src/views/", "视图组件"),
    ]

    lines.append("| 路径 | 说明 |")
    lines.append("|------|------|")
    for path, desc in keep_frontend:
        lines.append(f"| `frontend/{path}` | {desc} |")
    lines.append("")

    # ========================================================
    # 待新建清单
    # ========================================================
    lines.append("## 五、待新建模块")
    lines.append("")
    lines.append("| 模块 | 路径 | 说明 |")
    lines.append("|------|------|------|")
    lines.append("| 比赛录像分析器 | `analyzers/match_analyzer.py` | 通过 OpenDota API 获取比赛数据，分析关键事件和玩家表现 |")
    lines.append("| 比赛分析工具 | `tools/match_tools.py` | Agent 工具层：获取比赛、总结比赛 |")
    lines.append("| MD 导出器 | `utils/markdown_export.py` | 将分析结果格式化为 Markdown 并保存为文件 |")
    lines.append("| 比赛分析 API | `web/app.py` 新增端点 | `/api/match/analyze`, `/api/match/export` |")
    lines.append("| 前端比赛分析页 | `frontend/src/views/MatchAnalysis.vue` | 输入比赛 ID → 展示分析 → 导出 MD |")
    lines.append("| 比赛分析配置 | `config/prompts/match_analysis.yaml` | 比赛分析 Prompt 模板 |")
    lines.append("")

    # ========================================================
    # web/app.py 端点清理
    # ========================================================
    lines.append("## 六、web/app.py API 端点清理")
    lines.append("")
    lines.append("### 6.1 待删除的 API 端点（约 22 个）")
    lines.append("")
    lines.append("| 路由 | 方法 | 原功能 |")
    lines.append("|------|------|--------|")
    lines.append("| `/api/gsi/events` | GET | GSI 事件 SSE 推送 |")
    lines.append("| `/api/gsi/state` | GET | GSI 状态查询 |")
    lines.append("| `/api/gsi/recommendations` | GET | 主动推荐 SSE 推送 |")
    lines.append("| `/api/gsi/recommendation/status` | GET | 推荐系统状态 |")
    lines.append("| `/api/gsi/recommendation/query` | GET | 主动推荐查询 |")
    lines.append("| `/api/gsi/data` | POST | GSI 数据推送（测试用） |")
    lines.append("| `/api/voice/status` | GET | 语音播放器状态 |")
    lines.append("| `/api/voice/toggle` | POST | 语音开关 |")
    lines.append("| `/api/voice/volume` | POST | 语音音量 |")
    lines.append("| `/api/voice/event` | POST | 事件语音开关 |")
    lines.append("| `/api/feedback/explicit` | POST | 显式反馈提交 |")
    lines.append("| `/api/feedback/implicit` | POST | 隐式反馈提交 |")
    lines.append("| `/api/feedback/stats` | GET | 反馈统计查询 |")
    lines.append("| `/api/feedback/strategy` | GET | 策略参数查询 |")
    lines.append("| `/api/feedback/strategy/reset` | POST | 策略参数重置 |")
    lines.append("| `/api/feedback/calibrate` | POST | 手动校准 |")
    lines.append("| `/api/feedback` | POST | Langfuse 反馈 |")
    lines.append("| `/api/generate_hero_query` | POST | 随机英雄查询生成 |")
    lines.append("| `/api/test_tools` | GET | 工具测试（可保留或移除） |")
    lines.append("")

    lines.append("### 6.2 保留的 API 端点（约 30 个）")
    lines.append("")
    lines.append("| 路由 | 方法 | 功能 |")
    lines.append("|------|------|------|")
    lines.append("| `/` | GET | 服务根路径 |")
    lines.append("| `/api/health` | GET | 健康检查 |")
    lines.append("| `/api/chat` | POST | Agent 聊天（同步） |")
    lines.append("| `/api/chat/stream` | POST | Agent 聊天（SSE 流式） |")
    lines.append("| `/api/parse/preview` | POST | 解析预览 |")
    lines.append("| `/api/tools` | GET | 工具列表 |")
    lines.append("| `/api/skills` | GET | Skill 列表 |")
    lines.append("| `/api/skills/<name>/invoke` | POST | Skill 调用 |")
    lines.append("| `/api/conversation/stats` | GET | 会话统计 |")
    lines.append("| `/api/conversation/<session_id>` | GET | 会话历史 |")
    lines.append("| `/api/sessions` | GET | 会话列表 |")
    lines.append("| `/api/sessions/<session_id>` | GET | 会话详情 |")
    lines.append("| `/api/memory/stats` | GET | 记忆统计 |")
    lines.append("| `/api/memory/clear` | POST | 清空记忆 |")
    lines.append("| `/api/logs` | GET | 日志查询 |")
    lines.append("| `/api/logs/stream` | GET | 日志 SSE 流 |")
    lines.append("| `/api/logs/files` | GET | 日志文件列表 |")
    lines.append("| `/api/logs/files/<path:filename>` | GET | 日志文件内容 |")
    lines.append("| `/api/logs/clear` | POST | 清空日志 |")
    lines.append("| `/api/cache/warmup` | POST | 缓存预热 |")
    lines.append("| `/api/cache/status` | GET | 缓存状态 |")
    lines.append("| `/api/matchup/status` | GET | 对局数据状态 |")
    lines.append("| `/api/matchup/load-all` | POST | 对局数据加载 |")
    lines.append("| `/api/matchup/hero/<hero_id>` | GET | 英雄对局数据 |")
    lines.append("| `/api/matchup/stop-load` | POST | 停止加载 |")
    lines.append("| `/api/trace/<trace_id>` | GET | Trace 查询 |")
    lines.append("| `/api/trace/<trace_id>/persist` | POST | Trace 持久化 |")
    lines.append("| `/api/trace/<trace_id>/history` | GET | 历史 Trace |")
    lines.append("| `/api/traces/recent` | GET | 最近 Trace |")
    lines.append("| `/api/traces/statistics` | GET | Trace 统计 |")
    lines.append("| `/api/traces/errors` | GET | 错误 Trace |")
    lines.append("| `/api/trace/search` | GET | Trace 搜索 |")
    lines.append("| `/api/errors` | GET | 错误日志 |")
    lines.append("")

    # ========================================================
    # 执行指令
    # ========================================================
    lines.append("## 七、执行指令参考")
    lines.append("")
    lines.append("确认清单无误后，可使用以下命令执行实际删除：")
    lines.append("")
    lines.append("```bash")
    lines.append("# 在 Windows PowerShell 中执行（项目根目录下）")
    lines.append("# 请仔细核对后再执行！")
    lines.append("")
    lines.append("# 删除目录")

    for item in report.dirs_to_delete:
        lines.append(f'Remove-Item -Recurse -Force "{item.path}"')

    lines.append("")
    lines.append("# 删除文件")
    for item in report.files_to_delete:
        lines.append(f'Remove-Item -Force "{item.path}"')

    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("> 本报告由 `scripts/simulate_cleanup.py` 自动生成，仅用于模拟分析，未执行任何删除操作。")

    return "\n".join(lines)


def main():
    """主函数"""
    print("=" * 60)
    print("  DotaHelperAgent 精简清理 - 模拟执行")
    print("=" * 60)
    print()

    # 收集删除目标
    report = collect_delete_targets()

    # 打印摘要
    print(f"待删除目录:  {len(report.dirs_to_delete)} 个")
    print(f"待删除文件:  {len(report.files_to_delete)} 个")
    print(f"涉及文件总数: {report.total_files} 个")
    print(f"预计释放空间: {format_size(report.total_size_bytes)}")
    print()

    # 按类别打印
    categories: Dict[str, List[DeleteItem]] = {}
    for item in report.dirs_to_delete + report.files_to_delete:
        cat = item.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)

    for cat in sorted(categories.keys()):
        items = categories[cat]
        print(f"\n[{cat}]")
        for item in sorted(items, key=lambda x: x.path):
            tag = "DIR " if item.item_type == "dir" else "FILE"
            print(f"  {tag}  {item.path}")
            print(f"        -> {item.reason}")

    # 生成 Markdown 报告
    report_md = generate_markdown_report(report)
    report_path = PROJECT_ROOT / "docs" / "CLEANUP_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")

    print()
    print("=" * 60)
    print(f"  详细报告已生成: {report_path}")
    print("=" * 60)
    print()
    print("提示: 本报告仅为模拟分析，未执行任何删除操作。")
    print("请审阅报告后，再决定是否手动执行删除。")


if __name__ == "__main__":
    main()
