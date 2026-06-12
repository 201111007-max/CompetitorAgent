# 知识管理能力升级设计文档

> **文档版本**: v1.0
> **创建时间**: 2026-06-12
> **优先级**: P0
> **预计工作量**: 1-2 周
> **状态**: 设计完成，待实施

---

## 一、背景和目标

### 1.1 当前问题

当前 DotaHelperAgent 使用三层记忆系统（短期、长期、情景记忆），但存在以下局限：

- ❌ 扁平的键值存储，缺乏结构化知识表示
- ❌ 无法有效存储和检索攻略、策略等复杂知识
- ❌ 缺乏知识更新和演化机制
- ❌ 无法处理知识冲突和置信度评估

### 1.2 升级目标

从"扁平记忆存储"升级为"知识图谱 + 向量检索"系统，实现：

1. **结构化知识存储**：使用知识图谱存储英雄、物品、技能等实体及其关系
2. **语义化知识检索**：使用向量数据库支持攻略文档的语义检索
3. **知识融合与推理**：整合多源知识，支持复杂推理
4. **知识演化机制**：支持知识的更新、冲突检测和置信度评估

### 1.3 预期收益

| 维度 | 当前能力 | 升级后能力 | 收益 |
|------|---------|-----------|------|
| **知识检索** | 关键词匹配 | 语义检索 | 检索准确率提升 40% |
| **知识推理** | 无推理能力 | 多跳推理 | 支持复杂问题回答 |
| **知识更新** | 手动更新 | 自动演化 | 维护成本降低 60% |
| **知识质量** | 无质量控制 | 置信度评估 | 推荐可信度提升 35% |

---

## 二、整体架构

### 2.1 目录结构

```
DotaHelperAgent/
├── knowledge/                    # 新增：知识管理系统
│   ├── __init__.py
│   ├── vector_store.py          # 向量数据库客户端
│   ├── fusion_engine.py         # 知识融合引擎
│   ├── entity_alignment.py      # 实体对齐
│   ├── conflict_detector.py     # 冲突检测
│   └── confidence_evaluator.py  # 置信度评估
├── tools/
│   ├── knowledge_tools.py       # 新增：知识查询工具
│   └── ...
├── data/
│   ├── guides/                  # 新增：攻略文档目录
│   │   ├── hero_guides/         # 英雄攻略
│   │   ├── item_guides/         # 物品攻略
│   │   └── strategy_guides/     # 策略攻略
│   └── knowledge_base/          # 新增：知识库数据
│       ├── heroes.json          # 英雄数据
│       ├── items.json           # 物品数据
│       └── abilities.json       # 技能数据
├── config/
│   ├── knowledge_config.yaml    # 新增：知识管理配置
│   └── ...
└── tests/
    ├── knowledge/               # 新增：知识系统测试
    │   ├── test_vector_store.py
    │   ├── test_knowledge_tools.py
    │   └── test_integration.py
    └── ...
```

### 2.2 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    知识管理系统架构                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              知识接入层                                │  │
│  │  - 攻略文档导入                                       │  │
│  │  - 数据源接入（OpenDota、Wiki 等）                    │  │
│  │  - 用户知识贡献                                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              知识处理层                                │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │ 知识抽取   │  │ 实体识别   │  │ 关系抽取   │     │  │
│  │  │ (NER)      │  │ (Entity)   │  │ (Relation) │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              知识存储层                                │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │ 知识图谱   │  │ 向量数据库 │  │ 元数据存储 │     │  │
│  │  │ (Neo4j)    │  │ (Chroma)   │  │ (SQLite)   │     │  │
│  │  │            │  │            │  │            │     │  │
│  │  │ 结构化知识 │  │ 非结构化   │  │ 知识元数据 │     │  │
│  │  │ 实体关系   │  │ 攻略文档   │  │ 置信度     │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              知识融合层                                │  │
│  │  - 实体对齐（统一不同数据源的英雄名称）               │  │
│  │  - 冲突检测（识别矛盾的攻略建议）                     │  │
│  │  - 置信度评估（根据数据源可信度加权）                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              知识服务层                                │  │
│  │  - 知识查询 API                                       │  │
│  │  - 知识推理 API                                       │  │
│  │  - 知识更新 API                                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、核心组件设计

### 3.1 向量数据库客户端（VectorStore）

**文件位置**: `knowledge/vector_store.py`

**职责**：
- 攻略文档的向量化存储
- 语义检索
- 元数据过滤

**核心接口**：

```python
class VectorStore:
    """向量数据库客户端

    功能：
    - 攻略文档向量化存储
    - 语义检索
    - 元数据过滤
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化向量数据库

        Args:
            config: 配置字典，包含：
                - persist_directory: 持久化目录
                - collection_name: 集合名称
                - embedding_model: Embedding 模型
                - embedding_dimension: 向量维度
        """

    def add_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """添加文档到向量数据库

        Args:
            doc_id: 文档ID
            text: 文档文本
            metadata: 元数据（标题、作者、标签等）

        Returns:
            是否成功
        """

    def add_documents_batch(
        self,
        documents: List[Dict[str, Any]]
    ) -> int:
        """批量添加文档

        Args:
            documents: 文档列表，每个文档包含 id, text, metadata

        Returns:
            成功添加的数量
        """

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """语义检索

        Args:
            query: 查询文本
            n_results: 返回结果数量
            where: 元数据过滤条件
            where_document: 文档内容过滤条件

        Returns:
            检索结果
        """

    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""

    def update_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """更新文档"""

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
```

**技术选型**：
- **数据库**: Chroma（轻量级、Python原生、支持本地存储）
- **Embedding模型**: OpenAI text-embedding-3-small（质量高、成本低）
- **向量维度**: 1536维

---

### 3.2 知识融合引擎（KnowledgeFusionEngine）

**文件位置**: `knowledge/fusion_engine.py`

**职责**：
- 实体对齐（统一不同数据源的英雄名称）
- 冲突检测（识别矛盾的攻略建议）
- 置信度评估（根据数据源可信度加权）
- 知识融合（整合多源知识）

**核心接口**：

```python
@dataclass
class FusedKnowledge:
    """融合后的知识"""
    query: str
    structured_knowledge: List[Dict[str, Any]]
    unstructured_knowledge: List[Dict[str, Any]]
    conflicts: List[Dict[str, Any]]
    confidence: float
    sources: List[str]
    timestamp: float


class KnowledgeFusionEngine:
    """知识融合引擎

    功能：
    - 实体对齐
    - 冲突检测
    - 置信度评估
    - 知识融合
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化知识融合引擎

        Args:
            config: 配置字典
        """

    def merge(
        self,
        structured_knowledge: List[Dict[str, Any]],
        unstructured_knowledge: List[Dict[str, Any]],
        query: str
    ) -> FusedKnowledge:
        """融合结构化和非结构化知识

        Args:
            structured_knowledge: 结构化知识（来自知识图谱）
            unstructured_knowledge: 非结构化知识（来自向量检索）
            query: 查询文本

        Returns:
            融合后的知识
        """

    def _align_entities(self, knowledge_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """实体对齐"""

    def _detect_conflicts(self, knowledge_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """冲突检测"""

    def _evaluate_confidence(self, knowledge: Dict[str, Any]) -> float:
        """置信度评估"""
```

**数据流**：
```
用户查询 → 向量检索 → 知识融合引擎
                    ↓
            实体对齐 → 冲突检测 → 置信度评估
                    ↓
                融合结果 → 返回给Agent
```

---

### 3.3 知识查询工具（KnowledgeQueryTool）

**文件位置**: `tools/knowledge_tools.py`

**职责**：
- 提供统一的查询接口
- 支持结构化和非结构化知识检索
- 集成到 Agent 工具注册表

**核心接口**：

```python
class KnowledgeQueryTool(Tool):
    """知识查询工具

    功能：
    - 查询知识库
    - 支持结构化和非结构化知识检索
    - 知识融合
    """

    def __init__(
        self,
        vector_store: VectorStore,
        fusion_engine: KnowledgeFusionEngine
    ):
        """初始化知识查询工具

        Args:
            vector_store: 向量数据库客户端
            fusion_engine: 知识融合引擎
        """

    def _query(
        self,
        query: str,
        knowledge_type: str = "unstructured",
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """查询知识

        Args:
            query: 查询文本
            knowledge_type: 知识类型（"structured" | "unstructured" | "both"）
            filters: 过滤条件

        Returns:
            查询结果
        """


class KnowledgeUpdateTool(Tool):
    """知识更新工具

    功能：
    - 添加攻略文档
    - 更新攻略文档
    - 删除攻略文档
    """

    def __init__(self, vector_store: VectorStore):
        """初始化知识更新工具

        Args:
            vector_store: 向量数据库客户端
        """

    def _update(
        self,
        action: str,
        doc_id: str,
        text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """更新知识

        Args:
            action: 操作类型（"add" | "update" | "delete"）
            doc_id: 文档ID
            text: 文档文本
            metadata: 元数据

        Returns:
            操作结果
        """
```

**工具参数**：
- `query`: 查询文本
- `knowledge_type`: "structured" | "unstructured" | "both"
- `filters`: 元数据过滤条件

---

### 3.4 配置管理（knowledge_config.yaml）

**文件位置**: `config/knowledge_config.yaml`

```yaml
knowledge:
  enabled: true

  # 向量数据库配置
  vector_store:
    type: "chroma"  # chroma | faiss
    persist_directory: "./data/chroma_db"
    collection_name: "dota_guides"
    embedding_model: "text-embedding-3-small"  # OpenAI
    embedding_dimension: 1536

  # 知识图谱配置
  knowledge_graph:
    enabled: false  # 第一阶段暂不实现
    type: "neo4j"
    uri: "bolt://localhost:7687"
    user: "neo4j"
    password: "password"

  # 知识融合配置
  fusion:
    entity_alignment: true
    conflict_detection: true
    confidence_threshold: 0.7

  # 数据源配置
  data_sources:
    - type: "opendota"
      enabled: true
      priority: 1
    - type: "local_guides"
      enabled: true
      priority: 2
      path: "./data/guides"
```

---

## 四、集成方案

### 4.1 AgentController 集成

**修改位置**: `core/agent_controller.py`

**集成点**：

```python
class AgentController:
    def __init__(self, ...):
        # ... 现有初始化代码 ...

        # 初始化知识管理系统
        knowledge_config = self.config.get('knowledge', {})
        if knowledge_config.get('enabled', False):
            # 初始化向量数据库
            self.vector_store = VectorStore(knowledge_config.get('vector_store', {}))

            # 初始化知识融合引擎
            self.fusion_engine = KnowledgeFusionEngine(knowledge_config.get('fusion', {}))

            # 注册知识工具
            self.tool_registry.register(KnowledgeQueryTool(
                self.vector_store,
                self.fusion_engine
            ))
            self.tool_registry.register(KnowledgeUpdateTool(
                self.vector_store
            ))

            logger.info("知识管理系统初始化完成")
```

---

### 4.2 ReAct 循环集成

**修改位置**: `core/agent_controller.py` 的 `_think()` 方法

**集成逻辑**：

```python
def _think(self, thought: AgentThought) -> None:
    """思考阶段 - 理解问题和意图"""

    # 1. 分析用户问题
    query_analysis = self._analyze_query(thought.query)

    # 2. 查询知识库（新增）
    if query_analysis.get('needs_knowledge', False):
        knowledge_result = self.tool_registry.execute(
            "query_knowledge",
            query=thought.query,
            knowledge_type="unstructured"
        )

        if knowledge_result.is_success():
            thought.context['knowledge'] = knowledge_result.data
            thought.add_reasoning(f"从知识库检索到相关信息")

    # 3. 制定行动计划
    plan = self.goal_planner.plan(thought.query, thought.context)
    thought.add_reasoning(f"制定计划: {plan}")
```

---

### 4.3 查询分析逻辑

**新增方法**: `_analyze_query()`

**功能**: 判断查询是否需要知识库支持

```python
def _analyze_query(self, query: str) -> Dict[str, Any]:
    """分析查询是否需要知识库"""
    # 关键词检测
    knowledge_keywords = [
        "攻略", "怎么", "如何", "推荐", "建议", "出装",
        "技能", "加点", "克制", "counter", "build"
    ]

    needs_knowledge = any(kw in query.lower() for kw in knowledge_keywords)

    return {
        'needs_knowledge': needs_knowledge,
        'query_type': 'knowledge' if needs_knowledge else 'general'
    }
```

---

### 4.4 数据导入流程

**新增脚本**: `scripts/import_knowledge.py`

**功能**：
- 从 OpenDota API 导入英雄、物品数据
- 从本地文件导入攻略文档
- 向量化并存储到 Chroma

**流程**：
```
1. 读取英雄数据
2. 读取物品数据
3. 读取攻略文档
4. 生成文档向量
5. 存储到 Chroma
6. 验证导入结果
```

---

## 五、测试策略

### 5.1 单元测试

**测试文件**：
- `tests/knowledge/test_vector_store.py`：测试向量数据库的增删改查
- `tests/knowledge/test_knowledge_tools.py`：测试知识工具的查询功能
- `tests/knowledge/test_fusion_engine.py`：测试知识融合逻辑

**测试覆盖**：
- VectorStore 的所有公共方法
- KnowledgeFusionEngine 的融合逻辑
- KnowledgeQueryTool 的查询功能
- 异常处理和边界情况

---

### 5.2 集成测试

**测试文件**：
- `tests/knowledge/test_integration.py`：测试端到端的知识查询流程
- `tests/core/test_agent_integration.py`：测试 Agent 集成后的查询能力

**测试场景**：
1. 添加攻略文档 → 检索 → 验证结果
2. Agent 查询 → 知识库检索 → 返回答案
3. 多轮对话 → 上下文理解 → 知识检索

---

### 5.3 测试数据

**准备数据**：
- 10-20个测试攻略文档
- 覆盖英雄攻略、物品攻略、策略攻略
- 包含中英文混合内容

**示例测试数据**：
```python
test_documents = [
    {
        "id": "guide_001",
        "text": "针对 PA 的出装思路：PA 是一个高爆发物理输出英雄，建议出装：BKB、蝴蝶、撒旦",
        "metadata": {
            "title": "PA 出装攻略",
            "hero": "Phantom Assassin",
            "tags": ["PA", "出装", "物理输出"]
        }
    },
    # ... 更多测试数据
]
```

---

## 六、实施计划

### 6.1 第1周：基础设施搭建

**Day 1-2：环境准备和依赖安装**
- 安装依赖：`chromadb`, `openai`
- 创建目录结构
- 编写配置文件 `knowledge_config.yaml`
- 准备测试数据

**Day 3-4：核心代码实现**
- 实现 `VectorStore` 类
- 实现 `KnowledgeFusionEngine` 类
- 实现 `EntityAlignment`、`ConflictDetector`、`ConfidenceEvaluator`
- 实现知识工具类

**Day 5：单元测试**
- 编写单元测试
- 验证核心功能
- 修复bug

---

### 6.2 第2周：集成与测试

**Day 1-2：系统集成**
- 集成到 `AgentController`
- 修改 ReAct 循环
- 添加查询分析逻辑
- 更新配置管理

**Day 3-4：数据导入和验证**
- 编写数据导入脚本
- 导入英雄、物品数据
- 导入攻略文档
- 验证检索效果

**Day 5：集成测试和优化**
- 编写集成测试
- 端到端测试
- 性能优化
- 文档编写

---

## 七、预期成果

### 7.1 功能成果

1. ✅ **向量数据库运行**：Chroma 数据库正常工作，支持持久化存储
2. ✅ **攻略文档检索**：支持语义检索，准确率提升 40%
3. ✅ **知识工具集成**：Agent 可以调用知识查询工具
4. ✅ **知识融合**：支持多源知识融合和冲突检测
5. ✅ **完整测试覆盖**：单元测试覆盖率 > 80%

---

### 7.2 技术成果

1. ✅ **代码质量**：模块化设计，易于维护
2. ✅ **性能指标**：检索响应时间 < 500ms
3. ✅ **可扩展性**：预留知识图谱接口
4. ✅ **可配置性**：所有参数可通过配置文件管理

---

### 7.3 文档成果

1. ✅ **API 文档**：知识工具使用文档
2. ✅ **配置文档**：知识管理系统配置指南
3. ✅ **测试报告**：集成测试报告
4. ✅ **使用示例**：知识查询示例代码

---

## 八、成功标准

### 8.1 必须达成

- ✅ 向量数据库正常运行
- ✅ 可以成功检索攻略文档
- ✅ Agent 可以调用知识工具
- ✅ 单元测试全部通过

---

### 8.2 期望达成

- ✅ 检索准确率 > 80%
- ✅ 检索响应时间 < 500ms
- ✅ 知识融合功能正常工作
- ✅ 集成测试全部通过

---

## 九、风险和应对

### 9.1 风险1：OpenAI API 成本

**影响**: 中等
**应对**: 使用本地 Embedding 模型（Sentence-Transformers）作为备选

---

### 9.2 风险2：检索准确率不足

**影响**: 高
**应对**: 优化 Embedding 模型，调整检索参数

---

### 9.3 风险3：性能不达标

**影响**: 中等
**应对**: 使用缓存机制，优化数据库索引

---

### 9.4 风险4：数据导入困难

**影响**: 低
**应对**: 先导入少量测试数据，验证流程后再批量导入

---

## 十、后续扩展

### 10.1 知识图谱集成

**优先级**: P1
**预计工作量**: 2-3周

**功能**：
- 使用 Neo4j 存储结构化知识
- 支持多跳推理
- 实体关系查询

---

### 10.2 多模态知识

**优先级**: P2
**预计工作量**: 1-2周

**功能**：
- 支持图片、视频等多模态知识
- 图像检索
- 视频片段检索

---

### 10.3 知识演化

**优先级**: P2
**预计工作量**: 1-2周

**功能**：
- 自动知识更新
- 版本管理
- 知识冲突自动解决

---

> **最后更新**: 2026-06-12
