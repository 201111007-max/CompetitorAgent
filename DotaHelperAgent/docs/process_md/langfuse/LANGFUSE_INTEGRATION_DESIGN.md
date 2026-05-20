# Langfuse 集成设计文档

> 创建日期：2026-05-20
> 状态：已完成

## 一、概述

### 1.1 目标

将 Langfuse 集成到 DotaHelperAgent 项目中，作为**可选组件**，实现：

1. **LLM 调用追踪**：记录 prompt、completion、token 使用量
2. **Agent 执行流程追踪**：追踪 ReAct 循环、目标分解、工具调用
3. **外部 API 调用追踪**：追踪 OpenDota API 调用、缓存命中/未命中
4. **用户反馈收集**：收集用户对回答的反馈（点赞/点踩、评分）

### 1.2 设计原则

- **可选性**：Langfuse SDK 未安装时，项目正常运行，无任何影响
- **兼容性**：与现有 Trace 系统完全兼容，trace_id 映射
- **优雅降级**：自动检测 SDK 可用性，静默跳过不可用功能
- **配置灵活**：通过配置文件或环境变量控制

### 1.3 部署方式

Self-hosted（自托管）：用户自行部署 Langfuse 服务器，数据完全自主控制。

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户请求                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Flask Web 层 (web/app.py)                        │
│  - 初始化 LangfuseClient                                                 │
│  - 创建 Langfuse Trace                                                   │
│  - 收集用户反馈                                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Agent Controller (core/agent_controller.py)          │
│  - ReAct 循环追踪                                                        │
│  - 目标分解追踪                                                          │
│  - 工具调用追踪                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│   LLM Client        │ │   Tool Registry     │ │   API Client        │
│   (LLM 调用追踪)     │ │   (工具执行追踪)     │ │   (外部 API 追踪)    │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Langfuse 适配层 (utils/langfuse_adapter.py)          │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  LangfuseClient (单例)                                          │   │
│  │  - 条件导入 langfuse SDK                                        │   │
│  │  - 空操作降级                                                    │   │
│  │  - 配置管理                                                      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  LangfuseTraceAdapter                                           │   │
│  │  - 适配现有 TraceContext → Langfuse Trace                       │   │
│  │  - Span 映射                                                     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  NoOp* 类 (空操作实现)                                           │   │
│  │  - NoOpTrace, NoOpSpan, NoOpEvent                               │   │
│  │  - 当 langfuse 不可用时使用                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Langfuse Server (Self-hosted)                        │
│  - PostgreSQL 数据库                                                    │
│  - Web UI (http://localhost:3000)                                       │
│  - API 端点                                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 与现有 Trace 系统的关系

```
┌─────────────────────────────────────────────────────────────┐
│                    现有 Trace 系统                           │
│  TraceContext (trace_id, span_id)                           │
│  TraceSpan, @traced 装饰器                                   │
│  TraceJSONFormatter                                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ 始终工作
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Langfuse 适配层 (可选)                          │
│                                                             │
│  有 langfuse SDK → 追踪到 Langfuse Server                   │
│  无 langfuse SDK → 静默跳过，不影响项目运行                   │
└─────────────────────────────────────────────────────────────┘
```

**关键映射关系**：

| 现有 Trace 系统 | Langfuse | 说明 |
|----------------|----------|------|
| trace_id | trace.id | 全局唯一追踪 ID |
| span_id | span.id | 当前操作 ID |
| parent_span_id | span.parent_observation_id | 父操作 ID |
| session_id | trace.session_id | 会话 ID |
| operation | span.name | 操作名称 |

---

## 三、文件结构

### 3.1 新增文件

```
DotaHelperAgent/
├── utils/
│   ├── langfuse_adapter.py      # Langfuse 适配器（核心）
│   └── langfuse_config.py       # Langfuse 配置管理
├── config/
│   └── langfuse_config.yaml     # Langfuse 配置文件
├── requirements.txt             # 修改：添加可选依赖说明
└── requirements-optional.txt    # 新增：可选依赖列表
```

### 3.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `web/app.py` | 初始化 LangfuseClient，创建 Trace，收集反馈 |
| `core/agent_controller.py` | Agent 执行流程追踪 |
| `utils/llm_client.py` | LLM 调用追踪 |
| `utils/api_client.py` | 外部 API 调用追踪 |
| `utils/trace_context.py` | 集成 Langfuse 适配器 |

---

## 四、核心组件设计

### 4.1 LangfuseClient（单例模式）

**文件**: `utils/langfuse_adapter.py`

```python
from typing import Optional, Dict, Any, Union
import logging

logger = logging.getLogger(__name__)

class LangfuseClient:
    """Langfuse 客户端包装器 - 单例模式
    
    如果 langfuse SDK 未安装，所有方法都是空操作
    """
    
    _instance: Optional["LangfuseClient"] = None
    
    def __new__(cls) -> "LangfuseClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
            cls._instance._enabled = False
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "LangfuseClient":
        """获取单例实例
        
        Returns:
            LangfuseClient: 单例实例
        """
        return cls()
    
    def init(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化 Langfuse 客户端
        
        Args:
            config: 配置字典，如果为 None 则从配置文件读取
        """
        if not LANGFUSE_AVAILABLE:
            logger.info("langfuse SDK 未安装，监控功能已禁用")
            return
        
        # 从配置文件或环境变量读取配置
        # 初始化 Langfuse 客户端
    
    @property
    def enabled(self) -> bool:
        """检查是否启用
        
        Returns:
            bool: 是否启用
        """
        return self._enabled and LANGFUSE_AVAILABLE
    
    def trace(self, trace_id: str, **kwargs: Any) -> Union["Trace", "NoOpTrace"]:
        """创建 Trace
        
        Args:
            trace_id: 追踪 ID（与现有 Trace 系统兼容）
            **kwargs: 其他参数（session_id, metadata 等）
        
        Returns:
            Union[Trace, NoOpTrace]: Langfuse Trace 或 NoOpTrace
        """
        if not self.enabled:
            return NoOpTrace()
        return self._client.trace(id=trace_id, **kwargs)
    
    def flush(self) -> None:
        """刷新数据到 Langfuse Server"""
        if self.enabled:
            self._client.flush()
```

### 4.2 NoOp 类（空操作实现）

**文件**: `utils/langfuse_adapter.py`

```python
from typing import Any, Optional, TypeVar

T = TypeVar('T', bound="NoOpTrace")
S = TypeVar('S', bound="NoOpSpan")
E = TypeVar('E', bound="NoOpEvent")


class NoOpTrace:
    """空操作 Trace - 当 langfuse 不可用时使用"""
    
    def span(self, **kwargs: Any) -> "NoOpSpan":
        """创建空操作 Span
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpSpan: 空操作 Span 实例
        """
        return NoOpSpan()
    
    def event(self, **kwargs: Any) -> "NoOpEvent":
        """创建空操作 Event
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpEvent: 空操作 Event 实例
        """
        return NoOpEvent()
    
    def update(self, **kwargs: Any) -> "NoOpTrace":
        """更新 Trace（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpTrace: 自身实例
        """
        return self
    
    def score(self, **kwargs: Any) -> "NoOpTrace":
        """记录评分（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpTrace: 自身实例
        """
        return self
    
    def __enter__(self) -> "NoOpTrace":
        """进入上下文管理器
        
        Returns:
            NoOpTrace: 自身实例
        """
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        pass


class NoOpSpan:
    """空操作 Span"""
    
    def event(self, **kwargs: Any) -> "NoOpEvent":
        """创建空操作 Event
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpEvent: 空操作 Event 实例
        """
        return NoOpEvent()
    
    def update(self, **kwargs: Any) -> "NoOpSpan":
        """更新 Span（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def score(self, **kwargs: Any) -> "NoOpSpan":
        """记录评分（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def end(self) -> "NoOpSpan":
        """结束 Span（空操作）
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def __enter__(self) -> "NoOpSpan":
        """进入上下文管理器
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        pass


class NoOpEvent:
    """空操作 Event"""
    
    def update(self, **kwargs: Any) -> "NoOpEvent":
        """更新 Event（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpEvent: 自身实例
        """
        return self
    
    def __enter__(self) -> "NoOpEvent":
        """进入上下文管理器
        
        Returns:
            NoOpEvent: 自身实例
        """
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        pass
```

### 4.3 LangfuseTraceAdapter（适配器）

**文件**: `utils/langfuse_adapter.py`

```python
from typing import Any, Optional, Union
from utils.trace_context import TraceContext


class LangfuseTraceAdapter:
    """适配现有 TraceContext 到 Langfuse
    
    使用方式:
        with LangfuseTraceAdapter(trace_context) as adapter:
            adapter.span("llm_call", input=prompt, output=completion)
    """
    
    def __init__(self, trace_context: TraceContext) -> None:
        """初始化适配器
        
        Args:
            trace_context: 现有的 Trace 上下文
        """
        self.trace_context = trace_context
        self._langfuse_trace: Optional[Union["Trace", NoOpTrace]] = None
    
    def __enter__(self) -> "LangfuseTraceAdapter":
        """进入上下文管理器
        
        Returns:
            LangfuseTraceAdapter: 自身实例
        """
        if LangfuseClient().enabled:
            self._langfuse_trace = LangfuseClient().trace(
                id=self.trace_context.trace_id,
                session_id=self.trace_context.session_id,
                metadata=self.trace_context.metadata
            )
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        if self._langfuse_trace:
            self._langfuse_trace.__exit__(exc_type, exc_val, exc_tb)
    
    def span(self, operation: str, **kwargs: Any) -> Union["Span", NoOpSpan]:
        """创建 Span
        
        Args:
            operation: 操作名称
            **kwargs: 其他参数
        
        Returns:
            Union[Span, NoOpSpan]: Span 实例或空操作 Span
        """
        if self._langfuse_trace:
            return self._langfuse_trace.span(name=operation, **kwargs)
        return NoOpSpan()
    
    def event(self, name: str, **kwargs: Any) -> Union["Event", NoOpEvent]:
        """创建 Event
        
        Args:
            name: 事件名称
            **kwargs: 其他参数
        
        Returns:
            Union[Event, NoOpEvent]: Event 实例或空操作 Event
        """
        if self._langfuse_trace:
            return self._langfuse_trace.event(name=name, **kwargs)
        return NoOpEvent()
    
    def score(self, name: str, value: float, **kwargs: Any) -> None:
        """记录评分
        
        Args:
            name: 评分名称
            value: 评分值
            **kwargs: 其他参数
        """
        if self._langfuse_trace:
            self._langfuse_trace.score(name=name, value=value, **kwargs)
```

### 4.4 条件导入

**文件**: `utils/langfuse_adapter.py`

```python
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 条件导入
try:
    from langfuse import Langfuse
    from langfuse.model import CreateTrace, CreateSpan, CreateEvent, CreateScore
    LANGFUSE_AVAILABLE: bool = True
except ImportError:
    LANGFUSE_AVAILABLE: bool = False
    Langfuse = None  # type: ignore
    logger.debug("langfuse 未安装，监控功能已禁用。安装: pip install langfuse")


def is_langfuse_available() -> bool:
    """检查 Langfuse SDK 是否可用
    
    Returns:
        bool: SDK 是否可用
    """
    return LANGFUSE_AVAILABLE
```

---

## 五、配置管理

### 5.1 配置文件

**文件**: `config/langfuse_config.yaml`

```yaml
langfuse:
  enabled: true  # 是否启用 Langfuse
  
  # Self-hosted 配置
  host: "http://localhost:3000"
  public_key: "${LANGFUSE_PUBLIC_KEY}"  # 从环境变量读取
  secret_key: "${LANGFUSE_SECRET_KEY}"
  
  # 追踪配置
  trace:
    llm_calls: true       # 追踪 LLM 调用
    agent_flow: true      # 追踪 Agent 流程
    tool_calls: true      # 追踪工具调用
    api_calls: true       # 追踪外部 API
  
  # 采样率 (0.0 - 1.0)
  sample_rate: 1.0
```

### 5.2 配置加载

**文件**: `utils/langfuse_config.py`

```python
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any


class LangfuseConfig:
    """Langfuse 配置管理"""
    
    DEFAULT_CONFIG: Dict[str, Any] = {
        "enabled": True,
        "host": "http://localhost:3000",
        "public_key": None,
        "secret_key": None,
        "trace": {
            "llm_calls": True,
            "agent_flow": True,
            "tool_calls": True,
            "api_calls": True
        },
        "sample_rate": 1.0
    }
    
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化配置管理器
        
        Args:
            config_path: 配置文件路径，可选
        """
        self.config: Dict[str, Any] = self.DEFAULT_CONFIG.copy()
        if config_path:
            self._load_from_file(config_path)
        self._load_from_env()
    
    def _load_from_file(self, config_path: str) -> None:
        """从 YAML 文件加载配置
        
        Args:
            config_path: 配置文件路径
        """
        path = Path(config_path)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)
                if yaml_config and 'langfuse' in yaml_config:
                    self._merge_config(yaml_config['langfuse'])
    
    def _load_from_env(self) -> None:
        """从环境变量加载配置"""
        self.config['enabled'] = os.getenv('LANGFUSE_ENABLED', 'true').lower() == 'true'
        self.config['host'] = os.getenv('LANGFUSE_HOST', self.config['host'])
        self.config['public_key'] = os.getenv('LANGFUSE_PUBLIC_KEY')
        self.config['secret_key'] = os.getenv('LANGFUSE_SECRET_KEY')
    
    def _merge_config(self, override: Dict[str, Any]) -> None:
        """合并配置
        
        Args:
            override: 要合并的配置字典
        """
        for key, value in override.items():
            if isinstance(value, dict) and key in self.config:
                self.config[key].update(value)
            else:
                self.config[key] = value
    
    @property
    def enabled(self) -> bool:
        """获取启用状态
        
        Returns:
            bool: 是否启用
        """
        return self.config['enabled']
    
    @property
    def host(self) -> str:
        """获取主机地址
        
        Returns:
            str: Langfuse 服务器地址
        """
        return self.config['host']
    
    @property
    def public_key(self) -> Optional[str]:
        """获取公钥
        
        Returns:
            Optional[str]: 公钥，可能为 None
        """
        return self.config['public_key']
    
    @property
    def secret_key(self) -> Optional[str]:
        """获取密钥
        
        Returns:
            Optional[str]: 密钥，可能为 None
        """
        return self.config['secret_key']
```

---

## 六、集成点设计

### 6.1 Flask Web 层集成

**文件**: `web/app.py`

```python
from typing import Dict, Any
from flask import Flask, request, g, Response
from utils.langfuse_adapter import LangfuseClient, LangfuseTraceAdapter

app = Flask(__name__)

# 初始化
langfuse_client: LangfuseClient = LangfuseClient.get_instance()
langfuse_client.init()


@app.before_request
def before_request() -> None:
    """请求前钩子 - 创建 Langfuse Trace"""
    # 创建 Langfuse Trace
    trace_id: str = request.headers.get('X-Trace-ID') or generate_trace_id()
    session_id: str = request.headers.get('X-Session-ID') or generate_session_id()
    
    g.langfuse_trace = langfuse_client.trace(
        id=trace_id,
        session_id=session_id,
        metadata={"path": request.path}
    )


@app.after_request
def after_request(response: Response) -> Response:
    """请求后钩子 - 刷新数据
    
    Args:
        response: Flask 响应对象
    
    Returns:
        Response: 响应对象
    """
    # 刷新数据
    if hasattr(g, 'langfuse_trace'):
        langfuse_client.flush()
    return response


# 用户反馈 API
@app.route('/api/feedback', methods=['POST'])
def submit_feedback() -> Dict[str, str]:
    """提交用户反馈
    
    Returns:
        Dict[str, str]: 响应状态
    """
    data: Dict[str, Any] = request.json or {}
    trace_id: Optional[str] = data.get('trace_id')
    score: Optional[float] = data.get('score')  # 0-1
    comment: str = data.get('comment', '')
    
    if langfuse_client.enabled and trace_id and score is not None:
        langfuse_client.trace(id=trace_id).score(
            name="user_feedback",
            value=score,
            comment=comment
        )
    
    return {"status": "ok"}
```

### 6.2 Agent Controller 集成

**文件**: `core/agent_controller.py`

```python
from typing import Dict, Any, Optional
from utils.langfuse_adapter import LangfuseClient


class AgentController:
    """Agent 控制器"""
    
    def solve(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行 Agent 解决问题
        
        Args:
            query: 用户查询
            context: 上下文信息
        
        Returns:
            Dict[str, Any]: 执行结果
        """
        langfuse_client: LangfuseClient = LangfuseClient.get_instance()
        
        with langfuse_client.trace(
            id=trace_context.trace_id,
            session_id=trace_context.session_id
        ) as trace:
            # Think
            with trace.span(name="think") as span:
                reasoning: str = self._think(query, context)
                span.update(metadata={"reasoning": reasoning})
            
            # Plan
            with trace.span(name="plan") as span:
                plan = self._plan(reasoning)
                span.update(metadata={"plan": plan})
            
            # Execute
            for step in plan.steps:
                with trace.span(name=f"execute_{step.tool}") as span:
                    result: Dict[str, Any] = self._execute(step)
                    span.update(output=result)
            
            # Reflect
            with trace.span(name="reflect") as span:
                reflection: str = self._reflect()
                span.update(metadata={"reflection": reflection})
        
        return result
```

### 6.3 LLM Client 集成

**文件**: `utils/llm_client.py`

```python
from typing import Dict, List, Any, Optional
from utils.langfuse_adapter import LangfuseClient


class LLMClient:
    """LLM 客户端"""
    
    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
        """发送聊天请求
        
        Args:
            messages: 消息列表
            **kwargs: 其他参数
        
        Returns:
            Dict[str, Any]: API 响应结果
        """
        langfuse_client: LangfuseClient = LangfuseClient.get_instance()
        
        with langfuse_client.trace(...) as trace:
            with trace.span(
                name="llm_call",
                input={"messages": messages},
                metadata={"model": self.config.model}
            ) as span:
                response: Dict[str, Any] = self._do_request(messages, **kwargs)
                
                # 记录输出和 token 使用量
                span.update(
                    output=response,
                    metadata={
                        "model": self.config.model,
                        "usage": response.get("usage", {})
                    }
                )
                
                return response
```

### 6.4 API Client 集成

**文件**: `utils/api_client.py`

```python
from typing import Dict, List, Any
from utils.langfuse_adapter import LangfuseClient


class OpenDotaClient:
    """OpenDota API 客户端"""
    
    def get_hero_matchups(self, hero_id: int) -> List[Dict[str, Any]]:
        """获取英雄克制数据
        
        Args:
            hero_id: 英雄 ID
        
        Returns:
            List[Dict[str, Any]]: 克制数据列表
        """
        langfuse_client: LangfuseClient = LangfuseClient.get_instance()
        
        with langfuse_client.trace(...) as trace:
            with trace.span(
                name="api_call",
                input={"hero_id": hero_id},
                metadata={"api": "opendota", "endpoint": "hero_matchups"}
            ) as span:
                response: List[Dict[str, Any]] = self._request(f"/heroes/{hero_id}/matchups")
                span.update(output={"count": len(response)})
                return response
```

---

## 七、数据流示例

### 7.1 完整请求链路

```
用户请求 "推荐克制帕吉的英雄"
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ Flask: 创建 Langfuse Trace                                 │
│ trace_id: "trace_abc123"                                   │
│ session_id: "sess_xyz"                                     │
└───────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ Agent: ReAct 循环                                          │
│ ├── Span: think (思考)                                     │
│ │   └── metadata: {"reasoning": "用户想要..."}            │
│ │                                                          │
│ ├── Span: plan (规划)                                      │
│ │   └── metadata: {"plan": "调用 analyze_counter_picks"}  │
│ │                                                          │
│ ├── Span: execute_tool (执行工具)                          │
│ │   ├── input: {"enemy_heroes": ["帕吉"]}                 │
│ │   └── output: {"recommendations": [...]}                │
│ │                                                          │
│ ├── Span: llm_call (LLM 调用)                             │
│ │   ├── input: {"messages": [...]}                        │
│ │   ├── output: {"content": "..."}                        │
│ │   └── metadata: {"usage": {"prompt_tokens": 100, ...}}  │
│ │                                                          │
│ ├── Span: observe (观察)                                   │
│ │   └── metadata: {"observation": "获取到 5 个推荐"}       │
│ │                                                          │
│ └── Span: reflect (反思)                                   │
│     └── metadata: {"reflection": "结果完整，质量良好"}     │
└───────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ 用户反馈                                                    │
│ Event: feedback                                            │
│ Score: helpfulness = 0.9                                   │
│ Comment: "很有帮助"                                         │
└───────────────────────────────────────────────────────────┘
```

---

## 八、依赖管理

### 8.1 requirements.txt

```txt
# 核心依赖
flask>=2.0.0
requests>=2.28.0
pyyaml>=6.0

# 可选依赖 - Langfuse 监控（推荐安装）
# 安装命令: pip install langfuse
# langfuse>=2.0.0
```

### 8.2 requirements-optional.txt

```txt
# 可选依赖
langfuse>=2.0.0
```

### 8.3 安装说明

```bash
# 基础安装（不包含 Langfuse）
pip install -r requirements.txt

# 完整安装（包含 Langfuse 监控）
pip install -r requirements.txt
pip install langfuse

# 或者
pip install -r requirements.txt -r requirements-optional.txt
```

---

## 九、错误处理

### 9.1 安全调用装饰器

```python
from typing import Callable, TypeVar, Any
from functools import wraps

F = TypeVar('F', bound=Callable[..., Any])


def safe_langfuse_call(func: F) -> F:
    """装饰器：安全调用 Langfuse，失败时静默跳过
    
    Args:
        func: 要包装的函数
    
    Returns:
        包装后的函数
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not LANGFUSE_AVAILABLE:
            return NoOpResult()
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Langfuse call failed: {e}")
            return NoOpResult()
    return wrapper  # type: ignore
```

### 9.2 行为对比

| 场景 | 有 langfuse SDK | 无 langfuse SDK |
|------|----------------|-----------------|
| 项目启动 | 正常启动，连接 Langfuse | 正常启动，打印提示信息 |
| Agent 执行 | 追踪到 Langfuse | 静默跳过，现有 Trace 系统正常工作 |
| LLM 调用 | 记录 prompt/completion | 静默跳过 |
| 用户反馈 | 发送到 Langfuse | 静默跳过 |
| 日志输出 | 同时输出到 Langfuse | 仅输出到现有日志系统 |

---

## 十、测试策略

### 10.1 单元测试

| 测试项 | 文件 | 内容 |
|-------|------|------|
| LangfuseClient 初始化 | `tests/utils/test_langfuse_adapter.py` | 有/无 SDK 时的初始化行为 |
| NoOp 类测试 | `tests/utils/test_langfuse_adapter.py` | 空操作类的方法调用 |
| 配置加载 | `tests/utils/test_langfuse_config.py` | YAML 和环境变量加载 |

### 10.2 集成测试

| 测试项 | 文件 | 内容 |
|-------|------|------|
| Flask 集成 | `tests/integration/test_langfuse_flask.py` | 请求追踪和反馈收集 |
| Agent 集成 | `tests/integration/test_langfuse_agent.py` | Agent 执行流程追踪 |
| LLM 集成 | `tests/integration/test_langfuse_llm.py` | LLM 调用追踪 |

### 10.3 E2E 测试

| 测试项 | 文件 | 内容 |
|-------|------|------|
| 完整链路 | `tests/e2e/test_langfuse_e2e.py` | 从请求到反馈的完整流程 |

---

## 十一、实施计划

### 11.1 阶段划分

| 阶段 | 任务 | 优先级 |
|------|------|--------|
| 1 | 创建 Langfuse 适配器核心模块 | P0 |
| 2 | 添加配置管理 | P0 |
| 3 | Flask Web 层集成 | P0 |
| 4 | Agent Controller 集成 | P1 |
| 5 | LLM Client 集成 | P1 |
| 6 | API Client 集成 | P2 |
| 7 | 用户反馈 API | P1 |
| 8 | 单元测试 | P1 |
| 9 | 集成测试 | P2 |

### 11.2 文件修改清单

#### 新增文件
- `utils/langfuse_adapter.py` - Langfuse 适配器
- `utils/langfuse_config.py` - 配置管理
- `config/langfuse_config.yaml` - 配置文件
- `requirements-optional.txt` - 可选依赖

#### 修改文件
- `web/app.py` - Flask 集成
- `core/agent_controller.py` - Agent 集成
- `utils/llm_client.py` - LLM 集成
- `utils/api_client.py` - API 集成
- `requirements.txt` - 添加可选依赖说明

---

## 十二、风险与注意事项

### 12.1 性能考虑
- Langfuse SDK 使用异步发送，对主流程影响极小
- 可通过 `sample_rate` 控制采样率，减少数据量

### 12.2 安全考虑
- API Key 从环境变量读取，不硬编码
- 敏感数据（如用户查询）可选择不记录

### 12.3 运维考虑
- Self-hosted 部署需要 PostgreSQL 数据库
- 建议配置日志轮转和数据清理策略

---

## 十三、后续扩展

1. **Prompt 管理**：使用 Langfuse 的 Prompt Management 功能
2. **A/B 测试**：基于 Langfuse 进行实验
3. **数据导出**：导出追踪数据进行分析
4. **告警规则**：基于追踪数据设置告警
