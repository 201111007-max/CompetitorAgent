# Hero Matchup 数据管理方案设计文档

**日期**: 2026-05-27
**版本**: v1.0
**状态**: 已实现

---

## 目录

1. [背景与问题](#背景与问题)
2. [设计方案](#设计方案)
3. [架构设计](#架构设计)
4. [核心模块实现](#核心模块实现)
5. [数据流程](#数据流程)
6. [配置与部署](#配置与部署)
7. [测试验证](#测试验证)
8. [待办事项](#待办事项)

---

## 背景与问题

### 原有问题

| 问题 | 影响 |
|------|------|
| OpenDota API 429 速率限制 | 工具返回空数据，用户无法获取推荐 |
| 每次请求单个英雄 matchup | 124 个英雄 = 124 次 API 调用 |
| 无本地数据持久化 | 每次重启需重新加载 |
| LLM Fallback 未触发 | 空数据时无响应 |

### 业界解决方案

| 方案 | 描述 | 适用场景 |
|------|------|---------|
| 多级缓存 | Memory → SQLite → Local File → API | 数据变化不频繁 |
| 后台异步加载 | 控制频率，避免 429 | 大批量数据加载 |
| 多数据源 | 主备切换，LLM Fallback | 高可用场景 |
| 搜索增强 | DuckDuckGo/Tavily 搜索 | 获取最新信息 |

---

## 设计方案

### 核心思路

```
┌─────────────────────────────────────────────────────────────────┐
│                        启动阶段                                   │
│  1. 检查是否有全量 matchup 数据存储                               │
│  2. 如果有 → 加载到缓存                                          │
│  3. 如果没有 → 启动后台异步加载                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        请求阶段                                   │
│  1. 查询英雄 matchup → 按优先级访问数据源                         │
│  2. 如果数据存在 → 直接使用                                       │
│  3. 如果数据不存在 → LLM + 搜索回答                               │
│  4. 同时触发后台加载该英雄数据                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 数据源优先级

| 优先级 | 数据源 | 响应时间 | 特点 |
|--------|--------|---------|------|
| 1 | Memory Cache | < 1ms | 最快，进程内 |
| 2 | SQLite Cache | < 10ms | 持久化，重启保留 |
| 3 | Local JSON File | < 50ms | 本地存储，可备份 |
| 4 | LLM Knowledge | 1-3s | 无需 API，兜底 |
| 5 | DuckDuckGo Search | 2-5s | 获取最新信息 |
| 6 | OpenDota API | 后台异步 | 实时数据更新 |

---

## 架构设计

### 模块结构

```
DotaHelperAgent/
├── managers/
│   ├── __init__.py
│   └── matchup_data_manager.py    # 统一数据管理
├── utils/
│   └── background_loader.py       # 后台异步加载
├── tools/
│   └ search_tools.py              # DuckDuckGo 搜索工具
├── data/
│   └ matchups/                    # 本地 JSON 存储
│       ├── hero_1.json
│       ├── hero_2.json
│       └── ...
├── analyzers/
│   └ hero_analyzer.py             # 修改：支持 MatchupDataManager
└── core/
│   └ agent_controller.py          # 修改：添加搜索增强 fallback
```

### 类关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                    MatchupDataManager                            │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  get_matchup(hero_id) → Dict                                ││
│  │  save_matchup(hero_id, data) → bool                         ││
│  │  get_status() → Dict                                        ││
│  │  is_data_ready() → bool                                     ││
│  └─────────────────────────────────────────────────────────────┘│
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  数据源优先级访问                                             ││
│  │  1. CacheManager.get()                                      ││
│  │  2. Local JSON File                                         ││
│  │  3. BackgroundLoader.add_task()                             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    BackgroundLoader                              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  start() → 启动后台线程                                      ││
│  │  stop() → 停止后台线程                                       ││
│  │  add_task(hero_id, priority) → 添加任务                     ││
│  │  get_stats() → 获取统计                                      ││
│  └─────────────────────────────────────────────────────────────┘│
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  优先级队列 + 速率控制                                        ││
│  │  rate_limit = 1.0 次/秒                                     ││
│  │  max_retries = 3                                            ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    DuckDuckGoSearchTool                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  execute(query, max_results) → ToolResult                   ││
│  │  免费，无需 API Key                                          ││
│  │  无速率限制                                                  ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心模块实现

### 1. MatchupDataManager

**文件**: `managers/matchup_data_manager.py`

**核心功能**:

| 方法 | 描述 |
|------|------|
| `get_matchup(hero_id)` | 按优先级获取 matchup 数据 |
| `save_matchup(hero_id, data)` | 保存到缓存 + 本地 JSON |
| `get_status()` | 获取数据状态（已加载/缺失） |
| `is_data_ready()` | 检查数据是否可用 |
| `_check_and_load_existing_data()` | 启动时检查数据完整性 |

**数据状态结构**:

```python
{
    "total_heroes": 124,
    "loaded_heroes": 80,
    "missing_heroes": 44,
    "missing_hero_ids": [1, 5, 10, ...],
    "last_update": "2026-05-27T00:00:00",
    "is_loading": True,
    "progress": "80/124"
}
```

### 2. BackgroundLoader

**文件**: `utils/background_loader.py`

**核心功能**:

| 方法 | 描述 |
|------|------|
| `start()` | 启动后台加载线程 |
| `stop()` | 停止后台加载 |
| `add_task(hero_id, priority)` | 添加加载任务 |
| `get_stats()` | 获取加载统计 |

**速率控制**:

```python
rate_limit = 1.0  # 1 次/秒，避免 429
max_retries = 3   # 最大重试次数
```

**优先级队列**:

| 优先级 | 用途 |
|--------|------|
| 0 | 用户查询的英雄（立即加载） |
| 1 | 缺失的英雄（按顺序加载） |

### 3. DuckDuckGoSearchTool

**文件**: `tools/search_tools.py`

**核心功能**:

| 方法 | 描述 |
|------|------|
| `execute(query, max_results)` | 执行搜索 |
| `_search(query)` | 调用 DuckDuckGo API |

**特点**:

- 免费，无需 API Key
- 无速率限制
- 自动添加 "Dota 2" 前缀
- 返回结构化结果

### 4. HeroAnalyzer 修改

**文件**: `analyzers/hero_analyzer.py`

**修改内容**:

```python
class HeroAnalyzer:
    def __init__(
        self,
        client: OpenDotaClient,
        config: Optional[MatchupConfig] = None,
        matchup_manager: Optional[MatchupDataManager] = None  # 新增
    ):
        self.matchup_manager = matchup_manager
    
    def _get_matchup_data(self, hero_id: int) -> Optional[List[Dict]]:
        """优先使用 MatchupDataManager"""
        if self.matchup_manager:
            data = self.matchup_manager.get_matchup(hero_id)
            if data:
                return data
        return self.client.get_hero_matchups(hero_id)
```

### 5. Agent Controller 修改

**文件**: `core/agent_controller.py`

**新增方法**:

```python
def _llm_fallback_with_search(self, thought: AgentThought) -> Optional[str]:
    """LLM Fallback + 搜索增强"""
    # 1. 尝试 DuckDuckGo 搜索
    search_tool = DuckDuckGoSearchTool()
    search_result = search_tool.execute(query=query, max_results=3)
    
    # 2. 将搜索结果作为上下文
    search_context = "..."
    
    # 3. LLM 回答（带搜索信息）
    fallback_prompt = f"...{search_context}..."
    response = self.llm.chat(...)
```

---

## 数据流程

### 启动流程

```
1. MatchupDataManager 初始化
   ↓
2. 检查 data/matchups/ 目录
   ↓
3. 如果有全量数据（124 个文件）
   → 加载到 CacheManager
   → 数据状态: ready
   ↓
4. 如果数据不完整
   → 启动 BackgroundLoader
   → 后台异步加载缺失数据
   → 数据状态: loading
```

### 请求流程

```
1. 用户查询: "推荐克制陈的英雄"
   ↓
2. HeroAnalyzer.analyze_matchups()
   ↓
3. MatchupDataManager.get_matchup(hero_id)
   ↓
4. 检查数据源优先级
   ├─ Memory Cache → 有数据 → 返回
   ├─ SQLite Cache → 有数据 → 返回
   ├─ Local JSON → 有数据 → 返回 + 加载到缓存
   └─ 无数据 → 返回 None
   ↓
5. 如果无数据
   ├─ 触发 BackgroundLoader.add_task(hero_id, priority=0)
   ├─ Agent Controller._llm_fallback_with_search()
   │   ├─ DuckDuckGo 搜索 "Dota 2 克制陈的英雄"
   │   ├─ LLM 回答（带搜索信息）
   └─ 返回 LLM 回答
   ↓
6. 后台加载完成
   → save_matchup(hero_id, data)
   → 下次请求直接使用缓存
```

---

## 配置与部署

### 安装依赖

```bash
pip install duckduckgo-search
```

### 初始化配置

```python
from cache.cache_manager import get_cache
from managers.matchup_data_manager import MatchupDataManager
from utils.api_client import OpenDotaClient

cache = get_cache()
api_client = OpenDotaClient()

matchup_manager = MatchupDataManager(
    cache_manager=cache,
    api_client=api_client,
    auto_load_on_startup=True
)

hero_analyzer = HeroAnalyzer(
    client=api_client,
    matchup_manager=matchup_manager
)
```

### 数据存储位置

| 目录 | 内容 |
|------|------|
| `data/matchups/` | 英雄 matchup JSON 文件 |
| `cache/cache.db` | SQLite 缓存数据库 |

---

## 测试验证

### 测试步骤

1. **启动测试**
   ```bash
   python web/app.py
   ```
   检查日志：
   - "发现全量 matchup 数据" 或 "启动后台全量加载"

2. **请求测试**
   ```bash
   curl -X POST http://localhost:5000/api/chat \
     -H "Content-Type: application/json" \
     -d '{"query": "推荐克制陈的英雄"}'
   ```
   检查响应：
   - 如果有数据：直接返回分析结果
   - 如果无数据：返回 LLM + 搜索回答

3. **状态查询**
   ```bash
   curl http://localhost:5000/api/matchup/status
   ```
   返回：
   ```json
   {
     "total_heroes": 124,
     "loaded_heroes": 80,
     "progress": "80/124",
     "is_loading": true
   }
   ```

### 验证命令

```bash
# 检查本地数据文件
ls data/matchups/

# 检查缓存状态
curl http://localhost:5000/api/cache/status

# 强制全量加载
curl -X POST http://localhost:5000/api/matchup/load-all
```

---

## 待办事项

### 高优先级

- [x] 集成 MatchupDataManager 到 web/app.py 启动流程
- [x] 添加 `/api/matchup/status` API 接口
- [x] 添加 `/api/matchup/load-all` API 接口
- [x] 测试 DuckDuckGo 搜索工具功能
- [x] 完善 API 调用日志埋点

### 中优先级

- [ ] 优化 BackgroundLoader 速率控制（动态调整）
- [ ] 添加数据过期机制（TTL）
- [ ] 添加数据完整性校验
- [ ] 创建单元测试文件

### 低优先级

- [ ] 支持增量更新（只更新变化的数据）
- [ ] 支持数据备份与恢复
- [ ] 添加 STRATZ API 作为备用数据源

---

## 日志埋点规范

### 日志格式

所有 API 调用相关日志使用统一格式：`[TAG] 描述: key=value, key=value`

### 日志标签定义

| 标签 | 模块 | 描述 |
|------|------|------|
| `[API_REQUEST]` | api_client.py | API 请求开始 |
| `[API_SUCCESS]` | api_client.py | API 请求成功 |
| `[API_429]` | api_client.py | 速率限制触发 |
| `[API_ERROR]` | api_client.py | API 请求失败 |
| `[API_FAILED]` | api_client.py | API 最终失败 |
| `[API_RATE_LIMIT]` | api_client.py | 速率限制等待 |
| `[CACHE_HIT]` | api_client.py | 缓存命中 |
| `[CACHE_MISS]` | api_client.py | 缓存未命中 |
| `[API_CACHE_SET]` | api_client.py | 数据写入缓存 |
| `[MATCHUP_CACHE_HIT]` | matchup_data_manager.py | Matchup 缓存命中 |
| `[MATCHUP_FILE_HIT]` | matchup_data_manager.py | 本地文件命中 |
| `[MATCHUP_MISS]` | matchup_data_manager.py | 数据不存在 |
| `[MATCHUP_SAVE]` | matchup_data_manager.py | 数据保存成功 |
| `[MATCHUP_SAVE_ERROR]` | matchup_data_manager.py | 数据保存失败 |
| `[BG_LOAD_START]` | background_loader.py | 后台加载开始 |
| `[BG_LOAD_SUCCESS]` | background_loader.py | 后台加载成功 |
| `[BG_LOAD_EMPTY]` | background_loader.py | 返回空数据 |
| `[BG_LOAD_ERROR]` | background_loader.py | 加载异常 |
| `[BG_LOAD_FAILED]` | background_loader.py | 加载失败 |
| `[SEARCH_START]` | search_tools.py | 搜索开始 |
| `[SEARCH_SUCCESS]` | search_tools.py | 搜索成功 |
| `[SEARCH_ERROR]` | search_tools.py | 搜索失败 |

### 日志字段说明

| 字段 | 描述 | 示例 |
|------|------|------|
| `endpoint` | API 端点 | `/heroes/1/matchups` |
| `hero_id` | 英雄 ID | `1` |
| `time` | 耗时（秒） | `1.23s` |
| `size` | 数据大小 | `1024bytes` 或 `124items` |
| `source` | 数据来源 | `memory_cache`, `local_json` |
| `retry` | 重试次数 | `1/3` |
| `status` | HTTP 状态码 | `429` |

### 日志示例

```
[API_REQUEST] 开始请求: endpoint=/heroes/1/matchups, params=None, retry=0
[API_SUCCESS] 请求成功: endpoint=/heroes/1/matchups, status=200, time=1.23s, total_time=1.25s, size=1024bytes
[CACHE_HIT] 英雄 matchup 缓存命中: hero_id=1, time=0.003s, size=124items
[MATCHUP_FILE_HIT] 从本地文件获取: hero_id=1, source=local_json, time=0.015s, file_read=0.010s, size=124items
[BG_LOAD_SUCCESS] 加载成功: hero_id=1, retry=0, api_time=1.23s, save_time=0.015s, total_time=1.25s, data_size=124items
[SEARCH_SUCCESS] 搜索完成: query='Dota 2 帕吉攻略', results=5, search_time=2.34s, total_time=2.35s
```

---

## 相关文件

| 文件 | 描述 |
|------|------|
| `managers/matchup_data_manager.py` | 统一数据管理 |
| `utils/background_loader.py` | 后台异步加载 |
| `tools/search_tools.py` | DuckDuckGo 搜索工具 |
| `analyzers/hero_analyzer.py` | 英雄分析器（已修改） |
| `core/agent_controller.py` | Agent 控制器（已修改） |
| `docs/bugs/001_opendota_api_rate_limit.md` | Bug 记录文档 |

---

## 参考资料

- [OpenDota API 文档](https://docs.opendota.com/)
- [DuckDuckGo Search 库](https://github.com/deedy5/duckduckgo_search)
- [SQLite 缓存设计](../SQLITE_MIGRATION_REPORT.md)