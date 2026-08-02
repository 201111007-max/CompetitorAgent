# dota_helper — 垂直领域 Agent 框架（以 Dota 2 复盘为落地示例）

> 一个**领域可插拔**的通用 Agent 框架，已在一个真实垂直领域（Dota 2 赛后复盘）完成落地验证。
> 框架层与领域层严格解耦：接入新领域只需替换数据源、分析器与知识库。

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

## 项目定位

本项目的价值不在"Dota 2"本身，而在于沉淀了一套可复用的**自主执行 Agent 架构**：

- **双循环编排**：战略循环制定分析策略（先规划），战术循环按策略逐轮迭代分析（后执行）
- **可控执行**：迭代预算控制 + Stop Hook 可验证终止 + 断点续跑
- **领域解耦**：接口 + 策略模式，LLM 驱动优先、规则驱动自动降级
- **自我进化**：四层记忆系统 + 技能自动沉淀，越用越强
- **能力开放**：53 个工具封装为标准 MCP Server，供任意 MCP Client 复用

Dota 2 复盘是这套框架的第一个落地领域（示例），换知识库/换数据源即可迁移到
企业知识问答、数据分析、行业助手等任何垂直场景。

## 安装

```bash
git clone <repo-url>
cd dota_helper
pip install -e .
```

可选依赖：

```bash
# MCP Server 支持
pip install -e ".[mcp]"

# 测试
pip install -e ".[test]"
```

## 配置

创建 `.env` 文件：

```env
# 推荐：DeepSeek API Key，用于 LLM 驱动分析
DEEPSEEK_API_KEY=your_deepseek_api_key

# 可选：OpenAI API Key 作为备选
OPENAI_API_KEY=your_openai_api_key

# 可选：领域数据源（示例为 OpenDota）API Key，提高请求限制
OPENDOTA_API_KEY=your_opendota_api_key
```

未配置 LLM Key 时，系统会自动降级为规则分析模式，仍可运行。

## 能力一：自主分析 Agent（示例：赛后复盘）

### Python API

```python
import asyncio
from dota_helper import create_default_api

async def main():
    api = create_default_api()

    # 执行完整复盘（示例领域任务）
    report = await api.review(match_id="8909780728")
    print(f"总体评分: {report.overall_score:.1f}/10")
    print(f"置信度: {report.overall_confidence:.1%}")
    print(f"关键发现: {report.key_findings}")
    print(f"改进建议: {report.improvement_areas}")

    # 流式获取复盘过程（SSE）
    async for event in api.review_stream(match_id="8909780728"):
        print(event)

asyncio.run(main())
```

### Web 复盘

```bash
python -m dota_helper.web_app
```

访问 http://127.0.0.1:8000/，在聊天框输入：

- `复盘比赛 8909780728`
- `分析这局的眼位`

Web 端会实时展示 ReAct 推理链和可视化面板。

## 能力二：ReAct Chat Agent

Web 服务同时暴露一个交互式 Chat Agent，支持自然语言查询领域数据。

启动 Web 服务后即可使用：

```bash
python -m dota_helper.web_app
```

示例对话：

- `分析比赛 8909780728 的视野`
- `回放比赛 8909780728`
- `这个英雄怎么克制 Phantom Assassin？`

前端会展示完整的 thought → action → observation → final 推理链，右侧可视化面板会根据查询内容渲染眼位热力图等结果。

## 能力三：MCP 工具集（领域能力对外开放）

`dota_helper` 包含一个 MCP Server，注册 50+ 个领域工具，可被任意 MCP Client 调用。

### 启动 Server

```bash
# stdio 模式
python -m dota_helper.mcp_server.server
```

### 编程方式创建

```python
from dota_helper.mcp_server.server import create_server

server = create_server()
```

### 工具分类（示例领域：Dota 2）

| 分类 | 说明 |
|------|------|
| 比赛查询 | 比赛详情、近期比赛、比赛趋势等 |
| 英雄查询 | 英雄信息、克制关系、英雄胜率等 |
| 玩家查询 | 玩家信息、近期比赛、队友/对手等 |
| 阵容分析 | 阵容优势、搭配分析等 |
| 视野/眼位 | 眼位效率、放置建议、可视化等 |
| 搜索 | 英雄搜索、物品搜索等 |
| 统计 | 排行榜、元数据统计等 |
| 复盘分析 | 视野效率、肉山时机、后期决策、完整报告等 |

## 更多 API 用法

### 查看分析历史

```python
# 列出所有分析记录
history = api.list_history()
for item in history:
    print(item["match_id"], item["created_at"])

# 获取指定任务的分析报告
report = api.get_report(match_id="8909780728")

# 查看分析状态
status = api.get_status(match_id="8909780728")

# 中断正在运行的分析
result = await api.interrupt(match_id="8909780728")
```

### 自定义分析技能（自我进化入口）

```python
api.register_analysis_skill(
    name="反补压制",
    definition="当某玩家在对线期反补数显著高于对手时，识别其兵线压制能力。"
)

skills = api.list_analysis_skills()
```

## 测试

```bash
# 运行全部测试
pytest -v

# 仅运行单元测试
pytest tests/unit -v

# 运行集成测试（需要网络和 API Key）
pytest tests/integration -v -m integration
```

## 许可证

Private — 仅供学习和研究使用。
