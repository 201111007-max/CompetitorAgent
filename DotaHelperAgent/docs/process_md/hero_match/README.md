# Hero Matchup 数据管理方案

本文件夹包含 Hero Matchup 数据管理方案的设计文档和实现说明。

---

## 文档列表

| 文档 | 描述 |
|------|------|
| [HERO_MATCHUP_DATA_MANAGER_DESIGN.md](HERO_MATCHUP_DATA_MANAGER_DESIGN.md) | 完整设计方案文档 |

---

## 方案概述

### 核心问题

OpenDota API 存在速率限制（60 次/分钟），导致英雄克制分析工具频繁返回空数据。

### 解决方案

```
┌─────────────────────────────────────────────────────────────────┐
│                    数据获取优先级                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. Memory Cache    → 最快，本地数据                              │
│  2. SQLite Cache    → 持久化存储                                  │
│  3. Local JSON      → 本地文件                                    │
│  4. LLM Knowledge   → 无需 API，直接回答                           │
│  5. DuckDuckGo      → 免费，获取最新信息                           │
│  6. OpenDota API    → 后台异步更新                                │
└─────────────────────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 文件 | 功能 |
|------|------|------|
| MatchupDataManager | `managers/matchup_data_manager.py` | 统一数据管理 |
| BackgroundLoader | `utils/background_loader.py` | 后台异步加载 |
| DuckDuckGoSearchTool | `tools/search_tools.py` | 搜索增强 |

---

## 快速开始

### 1. 安装依赖

```bash
pip install duckduckgo-search
```

### 2. 初始化

```python
from managers.matchup_data_manager import MatchupDataManager
from cache.cache_manager import get_cache
from utils.api_client import OpenDotaClient

matchup_manager = MatchupDataManager(
    cache_manager=get_cache(),
    api_client=OpenDotaClient(),
    auto_load_on_startup=True
)
```

### 3. 使用

```python
# 获取 matchup 数据
data = matchup_manager.get_matchup(hero_id=1)

# 检查状态
status = matchup_manager.get_status()
print(f"进度: {status['progress']}")
```

---

## 相关链接

- [Bug 记录](../../bugs/001_opendota_api_rate_limit.md)
- [SQLite 缓存设计](../SQLITE_MIGRATION_REPORT.md)