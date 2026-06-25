# Prompt 版本管理设计文档

> **版本**: v1.0  
> **日期**: 2026-06-24  
> **状态**: 待审核  
> **优先级**: P1  
> **所属阶段**: 第三阶段 — 推理和决策能力增强

---

## 一、问题陈述

### 1.1 当前问题

项目中 LLM Prompt 模板**硬编码在代码中**，散布于多个模块：

| 文件 | Prompt 用途 | 数量 |
|------|-----------|------|
| `core/agent_controller.py` | 助手系统 Prompt、阵容推荐、快速回答 | 4 |
| `utils/llm_client.py` | 英雄推荐、阵容分析、出装建议、通用对话 | 5 |
| `core/decision/llm_engine.py` | 游戏建议生成 | 1 |
| `analyzers/skill_builder.py` | 技能加点推荐 | 1 |
| `web/app.py` | 英雄名称提取 | 2 |

**核心痛点**：
- ❌ **修改风险高**：Prompt 与业务代码耦合，修改需重新部署
- ❌ **无法对比效果**：新旧 Prompt 之间没有 A/B 测试机制
- ❌ **缺乏追踪**：无法量化某个 Prompt 变更对输出质量的影响
- ❌ **回滚困难**：出了问题只能 git revert，无法快速切换
- ❌ **重复管理**：相似 Prompt 分散在不同文件，难以统一维护

### 1.2 目标

建立统一的 Prompt 管理系统，实现：

1. **集中管理**：所有 Prompt 模板统一存储在配置中，与业务代码解耦
2. **版本控制**：每个 Prompt 有版本号，支持创建、查看、切换
3. **A/B 测试**：同一场景同时使用多个版本，对比效果
4. **性能追踪**：记录每个版本的输出质量评分
5. **优雅降级**：Langfuse 不可用时回退到本地配置

---

## 二、技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| Prompt 存储 | Langfuse（主） + 本地 YAML（备） | 复用已有 Langfuse 集成，本地配置作为降级方案 |
| 版本策略 | 语义化版本（major.minor） | Langfuse 原生支持整数版本，配合 name 前缀区分 |
| 接口设计 | 接口 + 策略模式 | 符合项目工程规范，便于扩展其他后端 |
| Prompt 注册 | 装饰器 + 配置文件 | 代码中声明式注册，YAML 中可覆盖 |
| 缓存策略 | 内存缓存 + TTL | 避免频繁调用 Langfuse API |
| 降级方案 | 本地 YAML 文件 | Langfuse SDK 未安装或服务不可用时自动降级 |

---

## 三、系统架构

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     业务模块层                                    │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Agent        │  │ LLM Client   │  │ LLM Engine   │          │
│  │ Controller   │  │              │  │ (决策引擎)    │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                  │
│         └─────────────────┼──────────────────┘                  │
└───────────────────────────┼─────────────────────────────────────┘
                            │ prompt_manager.get_prompt(name)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Prompt 管理器 (PromptManager)                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   接口层 (Interface)                      │   │
│  │  - get_prompt(name, version, variables)                   │   │
│  │  - list_prompts()                                         │   │
│  │  - get_prompt_metadata(name)                              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          │                                      │
│         ┌────────────────┼────────────────┐                     │
│         ▼                                 ▼                     │
│  ┌──────────────┐                ┌──────────────────┐           │
│  │ Langfuse     │                │ Local YAML       │           │
│  │ 策略          │                │ 策略              │           │
│  │              │                │                  │           │
│  │ - 远程获取   │   降级切换 →   │ - 本地文件读取   │           │
│  │ - 版本管理   │                │ - 默认版本       │           │
│  │ - 评分追踪   │                │ - 零外部依赖     │           │
│  └──────────────┘                └──────────────────┘           │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   缓存层                                  │   │
│  │  - 内存缓存（TTL 过期）                                   │   │
│  │  - 缓存命中率监控                                         │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     存储层                                       │
│                                                                 │
│  ┌──────────────────────┐    ┌────────────────────────────┐     │
│  │ Langfuse Server      │    │ config/prompts/             │     │
│  │ (http://localhost:3001│    │ ├── system_prompts.yaml    │     │
│  │                      │    │ ├── hero_analysis.yaml     │     │
│  │ - 版本化 Prompt 存储  │    │ ├── recommendation.yaml   │     │
│  │ - A/B 测试           │    │ └── ...                    │     │
│  │ - 评分追踪           │    │                            │     │
│  └──────────────────────┘    └────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
业务模块调用 prompt_manager.get_prompt("hero_recommendation", variables={...})
    │
    ▼
检查缓存（命中 → 直接返回）
    │ 未命中
    ▼
尝试 Langfuse 策略
    │
    ├── 成功 → 缓存 + 返回
    │
    └── 失败（SDK 未安装 / 服务不可用 / Prompt 不存在）
         │
         ▼
    降级到本地 YAML 策略
         │
         ├── 找到 → 缓存 + 返回
         │
         └── 未找到 → 抛出 PromptNotFoundError
```

---

## 四、目录结构

```
DotaHelperAgent/
├── utils/
│   ├── prompt_manager.py          # 新增：Prompt 管理器（接口 + 工厂）
│   ├── prompt_strategy.py         # 新增：策略接口 + Langfuse 策略 + 本地策略
│   └── ...
├── config/
│   ├── prompts/                   # 新增：本地 Prompt 配置目录
│   │   ├── system_prompts.yaml    # 系统级 Prompt（助手角色定义等）
│   │   ├── hero_analysis.yaml     # 英雄分析相关 Prompt
│   │   ├── recommendation.yaml    # 推荐相关 Prompt
│   │   ├── decision.yaml          # 决策引擎 Prompt
│   │   └── extraction.yaml        # 信息提取 Prompt
│   └── prompt_config.yaml         # Prompt 管理配置（缓存 TTL、默认策略等）
├── tests/
│   ├── utils/
│   │   ├── test_prompt_manager.py      # 新增：Prompt 管理器测试
│   │   └── test_prompt_strategy.py     # 新增：策略测试
│   └── integration/
│       └── test_prompt_langfuse.py     # 新增：Langfuse 集成测试
└── ...
```

---

## 五、核心模块设计

### 5.1 策略接口

```python
# utils/prompt_strategy.py

from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class PromptTemplate:
    """Prompt 模板"""
    name: str
    content: str
    version: int
    variables: List[str]       # 模板变量列表
    metadata: Dict[str, Any]   # 元数据（作者、描述、标签等）


class PromptStrategy:
    """Prompt 存储策略接口"""

    def get_prompt(
        self, name: str, version: Optional[int] = None
    ) -> Optional[PromptTemplate]:
        """获取指定名称和版本的 Prompt"""
        raise NotImplementedError

    def list_prompts(self) -> List[str]:
        """列出所有可用的 Prompt 名称"""
        raise NotImplementedError

    def create_prompt(
        self, name: str, content: str, metadata: Optional[Dict] = None
    ) -> PromptTemplate:
        """创建新版本的 Prompt"""
        raise NotImplementedError


class LangfusePromptStrategy(PromptStrategy):
    """基于 Langfuse 的 Prompt 存储策略"""

    def __init__(self, langfuse_client):
        self.client = langfuse_client

    def get_prompt(self, name, version=None):
        # 调用 Langfuse API 获取 Prompt
        ...

    def list_prompts(self):
        # 列出 Langfuse 中的 Prompt
        ...

    def create_prompt(self, name, content, metadata=None):
        # 在 Langfuse 中创建新版本
        ...


class LocalYAMLPromptStrategy(PromptStrategy):
    """基于本地 YAML 文件的 Prompt 存储策略（降级方案）"""

    def __init__(self, prompts_dir: str = "config/prompts"):
        self.prompts_dir = prompts_dir
        self._cache: Dict[str, Dict[int, PromptTemplate]] = {}
        self._load_all()

    def get_prompt(self, name, version=None):
        # 从本地缓存中获取（文件已加载到内存）
        ...

    def list_prompts(self):
        # 返回所有已加载的 Prompt 名称
        ...

    def create_prompt(self, name, content, metadata=None):
        # 本地策略不支持创建，仅作为只读降级方案
        raise NotImplementedError("Local YAML strategy is read-only")
```

### 5.2 Prompt 管理器

```python
# utils/prompt_manager.py

from typing import Dict, Any, Optional, List
import time
import logging

logger = logging.getLogger(__name__)


class PromptManager:
    """Prompt 管理器 - 统一管理所有 LLM Prompt 模板

    支持：
    - 多策略后端（Langfuse / 本地 YAML）
    - 自动降级（Langfuse 不可用时回退到本地）
    - 内存缓存（减少 API 调用）
    - 变量替换（模板渲染）
    """

    def __init__(
        self,
        primary_strategy: Optional[PromptStrategy] = None,
        fallback_strategy: Optional[PromptStrategy] = None,
        cache_ttl: int = 300,
    ):
        self._primary = primary_strategy
        self._fallback = fallback_strategy or LocalYAMLPromptStrategy()
        self._cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}  # key -> (PromptTemplate, timestamp)

    def get_prompt(
        self,
        name: str,
        version: Optional[int] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """获取 Prompt 内容，支持变量替换

        Args:
            name: Prompt 名称（如 "hero_recommendation"）
            version: 版本号（None 表示最新版本）
            variables: 模板变量字典

        Returns:
            渲染后的 Prompt 字符串
        """
        template = self._get_template(name, version)
        content = template.content

        if variables:
            for key, value in variables.items():
                content = content.replace(f"{{{{{key}}}}}", str(value))

        return content

    def _get_template(self, name: str, version: Optional[int] = None) -> PromptTemplate:
        """获取 Prompt 模板（带缓存）"""
        cache_key = f"{name}:{version or 'latest'}"

        # 检查缓存
        if cache_key in self._cache:
            template, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return template

        # 尝试主策略
        template = None
        if self._primary:
            try:
                template = self._primary.get_prompt(name, version)
            except Exception as e:
                logger.warning(f"Primary strategy failed for '{name}': {e}")

        # 降级到备用策略
        if template is None:
            template = self._fallback.get_prompt(name, version)

        if template is None:
            raise PromptNotFoundError(f"Prompt '{name}' not found in any strategy")

        # 更新缓存
        self._cache[cache_key] = (template, time.time())
        return template

    def list_prompts(self) -> List[str]:
        """列出所有可用的 Prompt 名称"""
        names = set()
        if self._primary:
            try:
                names.update(self._primary.list_prompts())
            except Exception:
                pass
        names.update(self._fallback.list_prompts())
        return sorted(names)

    def invalidate_cache(self, name: Optional[str] = None):
        """清除缓存"""
        if name:
            keys_to_remove = [k for k in self._cache if k.startswith(f"{name}:")]
            for k in keys_to_remove:
                del self._cache[k]
        else:
            self._cache.clear()
```

### 5.3 本地 YAML 配置格式

```yaml
# config/prompts/system_prompts.yaml

prompts:
  assistant_system:
    description: "Agent 助手系统 Prompt"
    version: 1
    content: |
      你是一个 Dota 2 游戏助手，同时也是一个通用的 AI 助手。
      请根据用户的问题提供准确、有用的回答。
      回答要求：
      1. 简洁明了，避免冗余
      2. 优先使用游戏数据支撑回答
      3. 使用中文回答
    variables: []
    metadata:
      author: "system"
      tags: ["system", "core"]

  assistant_fallback:
    description: "API 不可用时的降级 Prompt"
    version: 1
    content: |
      你是一个 Dota 2 游戏专家助手。由于数据 API 暂时不可用，
      请直接根据你的游戏知识回答用户问题。
      英雄名称：{{hero_name}}
    variables: ["hero_name"]
    metadata:
      author: "system"
      tags: ["system", "fallback"]
```

```yaml
# config/prompts/recommendation.yaml

prompts:
  hero_recommendation:
    description: "英雄推荐 Prompt"
    version: 1
    content: |
      你是一个 Dota 2 游戏专家助手。根据阵容分析结果，为用户推荐合适的英雄。

      当前阵容信息：
      {{team_composition}}

      请推荐 {{top_n}} 个最适合的英雄，并说明理由。
    variables: ["team_composition", "top_n"]
    metadata:
      author: "system"
      tags: ["recommendation", "hero"]

  game_advice:
    description: "游戏建议生成 Prompt（决策引擎用）"
    version: 1
    content: |
      你是一位专业的 Dota 2 游戏教练。请根据当前游戏状态和触发事件，给出专业的游戏建议。

      ## 当前游戏状态
      - 英雄：{{hero_name}}
      - 游戏时间：{{game_time}}秒
      - 血量：{{health_percent}}%
      - 金钱：{{gold}}

      ## 触发事件
      {{event_description}}

      请给出简洁、实用的建议（不超过100字）。
    variables: ["hero_name", "game_time", "health_percent", "gold", "event_description"]
    metadata:
      author: "system"
      tags: ["recommendation", "decision"]
```

### 5.4 管理配置

```yaml
# config/prompt_config.yaml

prompt_manager:
  # 默认策略：langfuse | local
  default_strategy: "langfuse"

  # Langfuse 配置（复用 langfuse_config.yaml 中的连接信息）
  langfuse:
    enabled: true
    # 连接信息从 langfuse_config.yaml 读取

  # 本地配置
  local:
    prompts_dir: "config/prompts"

  # 缓存配置
  cache:
    enabled: true
    ttl: 300  # 秒

  # Prompt 注册表（名称 → 文件映射）
  registry:
    assistant_system: "system_prompts.yaml"
    assistant_fallback: "system_prompts.yaml"
    hero_recommendation: "recommendation.yaml"
    game_advice: "recommendation.yaml"
    hero_counter: "hero_analysis.yaml"
    team_analysis: "hero_analysis.yaml"
    item_recommendation: "hero_analysis.yaml"
    skill_build: "hero_analysis.yaml"
    hero_name_extraction: "extraction.yaml"
```

---

## 六、业务模块集成方案

### 6.1 改造前后对比

**改造前**（硬编码）：
```python
# core/agent_controller.py
system_prompt = """你是一个 Dota 2 游戏助手。请根据用户的问题直接回答..."""
messages = [{"role": "system", "content": system_prompt}, ...]
```

**改造后**（通过 PromptManager）：
```python
# core/agent_controller.py
system_prompt = self.prompt_manager.get_prompt(
    "assistant_system",
    variables={"hero_name": hero_name}
)
messages = [{"role": "system", "content": system_prompt}, ...]
```

### 6.2 需要改造的模块

| 模块 | 涉及 Prompt | 改造优先级 |
|------|-----------|-----------|
| `core/agent_controller.py` | 系统 Prompt、阵容推荐、快速回答 | P0 |
| `utils/llm_client.py` | 英雄推荐、出装建议、阵容分析 | P0 |
| `core/decision/llm_engine.py` | 游戏建议生成 | P1 |
| `analyzers/skill_builder.py` | 技能加点 | P1 |
| `web/app.py` | 英雄名称提取 | P2 |

### 6.3 初始化集成

在 `web/app.py` 的 `initialize_agent_controller()` 中初始化 PromptManager：

```python
def initialize_prompt_manager() -> PromptManager:
    """初始化 Prompt 管理器"""
    primary = None
    try:
        from utils.langfuse_adapter import get_langfuse_client
        client = get_langfuse_client()
        if client:
            primary = LangfusePromptStrategy(client)
    except Exception:
        pass

    fallback = LocalYAMLPromptStrategy(
        prompts_dir=str(project_root / "config" / "prompts")
    )

    return PromptManager(
        primary_strategy=primary,
        fallback_strategy=fallback,
        cache_ttl=300,
    )
```

---

## 七、A/B 测试方案

### 7.1 流量分配

```python
class PromptManager:
    def get_prompt_with_ab_test(
        self,
        name: str,
        test_config: Optional[Dict] = None,
        variables: Optional[Dict] = None,
    ) -> str:
        """获取 Prompt（支持 A/B 测试）

        Args:
            name: Prompt 名称
            test_config: A/B 测试配置
                {
                    "enabled": True,
                    "versions": [1, 2],      # 参与测试的版本
                    "weights": [0.5, 0.5],   # 流量分配比例
                }
            variables: 模板变量
        """
        if test_config and test_config.get("enabled"):
            version = self._select_version(test_config)
        else:
            version = None  # 使用最新版本

        return self.get_prompt(name, version=version, variables=variables)

    def _select_version(self, test_config: Dict) -> int:
        """根据权重随机选择版本"""
        import random
        versions = test_config["versions"]
        weights = test_config["weights"]
        return random.choices(versions, weights=weights, k=1)[0]
```

### 7.2 效果评估

通过 Langfuse 的评分系统追踪不同版本的效果：

```python
# 在业务代码中记录评分
trace.score(
    name="prompt_quality",
    value=user_rating,
    metadata={
        "prompt_name": "hero_recommendation",
        "prompt_version": 2,
    }
)
```

---

## 八、测试计划

### 8.1 单元测试

| 测试项 | 验证内容 |
|--------|---------|
| `test_prompt_manager.py` | 获取 Prompt、变量替换、缓存命中/过期、降级切换 |
| `test_prompt_strategy.py` | Langfuse 策略（mock）、本地 YAML 策略（文件加载） |

### 8.2 集成测试

| 测试项 | 验证内容 |
|--------|---------|
| `test_prompt_langfuse.py` | 与 Langfuse Server 的实际交互 |
| `test_prompt_integration.py` | Agent Controller 集成 PromptManager 后的端到端流程 |

### 8.3 降级测试

| 场景 | 预期行为 |
|------|---------|
| Langfuse SDK 未安装 | 自动降级到本地 YAML |
| Langfuse Server 不可达 | 超时后降级到本地 YAML |
| Prompt 在 Langfuse 中不存在 | 降级到本地 YAML |
| 本地 YAML 文件缺失 | 抛出 PromptNotFoundError |

---

## 九、实施计划

### 9.1 分步实施

| 步骤 | 内容 | 依赖 |
|------|------|------|
| **Step 1** | 实现策略接口 + 本地 YAML 策略 | 无 |
| **Step 2** | 实现 PromptManager（缓存、降级、变量替换） | Step 1 |
| **Step 3** | 创建本地 Prompt YAML 配置文件（迁移现有硬编码 Prompt） | 无 |
| **Step 4** | 实现 Langfuse 策略 | Step 1 |
| **Step 5** | 改造 `core/agent_controller.py` 集成 PromptManager | Step 2, 3 |
| **Step 6** | 改造 `utils/llm_client.py` 集成 PromptManager | Step 2, 3 |
| **Step 7** | 改造其他模块（llm_engine, skill_builder, web/app） | Step 2, 3 |
| **Step 8** | 编写单元测试 + 集成测试 | Step 5-7 |
| **Step 9** | 实现 A/B 测试功能 | Step 4 |

### 9.2 迁移策略

采用**渐进式迁移**：
1. 先将所有硬编码 Prompt 提取到 YAML 配置文件
2. 逐模块替换硬编码为 `prompt_manager.get_prompt()` 调用
3. 每个模块改造后运行测试验证
4. 全部完成后启用 Langfuse 策略

---

## 十、预期收益

| 维度 | 当前能力 | 升级后能力 | 收益 |
|------|---------|-----------|------|
| **Prompt 管理** | 硬编码分散 | 集中配置 | 维护效率提升 60% |
| **版本控制** | git 管理 | 平台化管理 | 回滚速度从分钟级降到秒级 |
| **效果评估** | 无法量化 | A/B 测试 + 评分 | Prompt 优化有据可依 |
| **降级能力** | 无 | 自动降级 | 系统可用性提升 |
