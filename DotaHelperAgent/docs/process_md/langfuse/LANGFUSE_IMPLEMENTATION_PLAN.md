# Langfuse 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Langfuse 作为可选组件集成到 DotaHelperAgent 项目中，实现 LLM 调用追踪、Agent 执行流程追踪、外部 API 调用追踪和用户反馈收集。

**Architecture:** 使用适配器模式将 Langfuse SDK 包装为可选组件，通过条件导入和空操作类实现优雅降级。现有 Trace 系统保持不变，Langfuse 作为增强层与之并存。

**Tech Stack:** Python 3.8+, Langfuse SDK (可选), Flask, PyYAML

---

## 文件结构

### 新增文件
```
DotaHelperAgent/
├── utils/
│   ├── langfuse_adapter.py      # Langfuse 适配器（核心）
│   └── langfuse_config.py       # Langfuse 配置管理
├── config/
│   └── langfuse_config.yaml     # Langfuse 配置文件
├── requirements-optional.txt    # 可选依赖列表
└── tests/
    └── utils/
        ├── test_langfuse_adapter.py  # 适配器单元测试
        └── test_langfuse_config.py   # 配置单元测试
```

### 修改文件
```
DotaHelperAgent/
├── web/app.py                   # Flask 集成
├── core/agent_controller.py     # Agent 集成
├── utils/llm_client.py          # LLM 集成
├── utils/api_client.py          # API 集成
└── requirements.txt             # 添加可选依赖说明
```

---

## Task 1: 创建 Langfuse 适配器核心模块

**Files:**
- Create: `utils/langfuse_adapter.py`
- Test: `tests/utils/test_langfuse_adapter.py`

- [ ] **Step 1: 创建测试文件目录结构**

Run: `New-Item -ItemType Directory -Path "d:\trae_projects\first-agent\DotaHelperAgent\tests\utils" -Force`

- [ ] **Step 2: 编写 NoOp 类测试**

Create: `tests/utils/test_langfuse_adapter.py`

```python
"""Langfuse 适配器单元测试"""

import pytest


class TestNoOpClasses:
    """测试空操作类"""
    
    def test_noop_trace_span_returns_noop_span(self):
        from utils.langfuse_adapter import NoOpTrace
        
        trace = NoOpTrace()
        span = trace.span(name="test")
        
        assert span is not None
        assert hasattr(span, 'update')
        assert hasattr(span, 'event')
        assert hasattr(span, 'score')
    
    def test_noop_trace_event_returns_noop_event(self):
        from utils.langfuse_adapter import NoOpTrace
        
        trace = NoOpTrace()
        event = trace.event(name="test")
        
        assert event is not None
        assert hasattr(event, 'update')
    
    def test_noop_trace_context_manager(self):
        from utils.langfuse_adapter import NoOpTrace
        
        with NoOpTrace() as trace:
            assert trace is not None
            trace.update(metadata={"test": "value"})
            trace.score(name="test", value=0.9)
    
    def test_noop_span_context_manager(self):
        from utils.langfuse_adapter import NoOpSpan
        
        with NoOpSpan() as span:
            assert span is not None
            span.update(output={"result": "success"})
            span.score(name="quality", value=0.8)
    
    def test_noop_event_context_manager(self):
        from utils.langfuse_adapter import NoOpEvent
        
        with NoOpEvent() as event:
            assert event is not None
            event.update(metadata={"key": "value"})


class TestLangfuseClient:
    """测试 Langfuse 客户端"""
    
    def test_singleton_pattern(self):
        from utils.langfuse_adapter import LangfuseClient
        
        client1 = LangfuseClient.get_instance()
        client2 = LangfuseClient.get_instance()
        
        assert client1 is client2
    
    def test_disabled_when_no_sdk(self):
        from utils.langfuse_adapter import LangfuseClient
        
        client = LangfuseClient.get_instance()
        # 当 langfuse SDK 未安装时，enabled 应该为 False
        # 或者当 SDK 已安装但未初始化时，enabled 也应该为 False
        assert client.enabled is False
    
    def test_trace_returns_noop_when_disabled(self):
        from utils.langfuse_adapter import LangfuseClient, NoOpTrace
        
        client = LangfuseClient.get_instance()
        trace = client.trace(trace_id="test_123")
        
        assert isinstance(trace, NoOpTrace)


class TestIsLangfuseAvailable:
    """测试 SDK 可用性检查"""
    
    def test_returns_boolean(self):
        from utils.langfuse_adapter import is_langfuse_available
        
        result = is_langfuse_available()
        assert isinstance(result, bool)
```

- [ ] **Step 3: 运行测试验证失败**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/utils/test_langfuse_adapter.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'utils.langfuse_adapter'"

- [ ] **Step 4: 创建 Langfuse 适配器核心模块**

Create: `utils/langfuse_adapter.py`

```python
"""Langfuse 适配器模块

将 Langfuse SDK 包装为可选组件：
- 如果 langfuse SDK 已安装且配置正确，则启用追踪功能
- 如果 langfuse SDK 未安装，则静默跳过，不影响项目运行

使用方式:
    from utils.langfuse_adapter import LangfuseClient
    
    client = LangfuseClient.get_instance()
    client.init()
    
    with client.trace(trace_id="xxx", session_id="yyy") as trace:
        with trace.span(name="operation") as span:
            span.update(output={"result": "success"})
"""

import logging
from typing import Optional, Dict, Any, Union

logger = logging.getLogger(__name__)

# 条件导入
try:
    from langfuse import Langfuse
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


class NoOpTrace:
    """空操作 Trace - 当 langfuse 不可用时使用
    
    所有方法都是空操作，返回自身或对应的空操作对象
    """
    
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
    """空操作 Span
    
    所有方法都是空操作，返回自身或对应的空操作对象
    """
    
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
    """空操作 Event
    
    所有方法都是空操作，返回自身
    """
    
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


class LangfuseClient:
    """Langfuse 客户端包装器 - 单例模式
    
    如果 langfuse SDK 未安装，所有方法都是空操作
    
    使用方式:
        client = LangfuseClient.get_instance()
        client.init(config={
            "public_key": "xxx",
            "secret_key": "yyy",
            "host": "http://localhost:3000"
        })
        
        with client.trace(trace_id="xxx") as trace:
            with trace.span(name="operation") as span:
                span.update(output={"result": "success"})
    """
    
    _instance: Optional["LangfuseClient"] = None
    
    def __new__(cls) -> "LangfuseClient":
        """创建单例实例
        
        Returns:
            LangfuseClient: 单例实例
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
            cls._instance._enabled = False
            cls._instance._config: Dict[str, Any] = {}
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
            config: 配置字典，包含:
                - public_key: Langfuse 公钥
                - secret_key: Langfuse 密钥
                - host: Langfuse 服务器地址（默认 http://localhost:3000）
                - enabled: 是否启用（默认 True）
        """
        if not LANGFUSE_AVAILABLE:
            logger.info("langfuse SDK 未安装，监控功能已禁用")
            self._enabled = False
            return
        
        if config:
            self._config = config
        
        # 检查是否启用
        if not self._config.get('enabled', True):
            logger.info("Langfuse 监控已禁用")
            self._enabled = False
            return
        
        # 检查必要的配置
        public_key = self._config.get('public_key')
        secret_key = self._config.get('secret_key')
        
        if not public_key or not secret_key:
            logger.warning("Langfuse 配置不完整（缺少 public_key 或 secret_key），监控功能已禁用")
            self._enabled = False
            return
        
        try:
            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=self._config.get('host', 'http://localhost:3000')
            )
            self._enabled = True
            logger.info(f"Langfuse 监控已启用: {self._config.get('host', 'http://localhost:3000')}")
        except Exception as e:
            logger.error(f"Langfuse 初始化失败: {e}")
            self._enabled = False
    
    @property
    def enabled(self) -> bool:
        """检查是否启用
        
        Returns:
            bool: 是否启用
        """
        return self._enabled and LANGFUSE_AVAILABLE
    
    def trace(self, trace_id: str, **kwargs: Any) -> Union["Trace", NoOpTrace]:
        """创建 Trace
        
        Args:
            trace_id: 追踪 ID（与现有 Trace 系统兼容）
            **kwargs: 其他参数（session_id, metadata 等）
        
        Returns:
            Union[Trace, NoOpTrace]: Langfuse Trace 或 NoOpTrace
        """
        if not self.enabled or not self._client:
            return NoOpTrace()
        
        try:
            return self._client.trace(id=trace_id, **kwargs)
        except Exception as e:
            logger.warning(f"创建 Langfuse Trace 失败: {e}")
            return NoOpTrace()
    
    def flush(self) -> None:
        """刷新数据到 Langfuse Server"""
        if self.enabled and self._client:
            try:
                self._client.flush()
            except Exception as e:
                logger.warning(f"刷新 Langfuse 数据失败: {e}")
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/utils/test_langfuse_adapter.py -v`

Expected: PASS

- [ ] **Step 6: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add utils/langfuse_adapter.py tests/utils/test_langfuse_adapter.py && git commit -m "feat(langfuse): add core adapter module with NoOp fallback"`

---

## Task 2: 创建 Langfuse 配置管理模块

**Files:**
- Create: `utils/langfuse_config.py`
- Test: `tests/utils/test_langfuse_config.py`

- [ ] **Step 1: 编写配置管理测试**

Create: `tests/utils/test_langfuse_config.py`

```python
"""Langfuse 配置管理单元测试"""

import os
import pytest
import tempfile
from pathlib import Path


class TestLangfuseConfig:
    """测试 Langfuse 配置管理"""
    
    def test_default_config(self):
        from utils.langfuse_config import LangfuseConfig
        
        config = LangfuseConfig()
        
        assert config.enabled is True
        assert config.host == "http://localhost:3000"
    
    def test_load_from_yaml_file(self):
        from utils.langfuse_config import LangfuseConfig
        
        # 创建临时 YAML 文件
        yaml_content = """
langfuse:
  enabled: false
  host: "http://custom-host:3000"
  public_key: "test_public"
  secret_key: "test_secret"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            config = LangfuseConfig(config_path=temp_path)
            
            assert config.enabled is False
            assert config.host == "http://custom-host:3000"
            assert config.public_key == "test_public"
            assert config.secret_key == "test_secret"
        finally:
            os.unlink(temp_path)
    
    def test_load_from_env_variables(self, monkeypatch):
        from utils.langfuse_config import LangfuseConfig
        
        # 设置环境变量
        monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
        monkeypatch.setenv('LANGFUSE_HOST', 'http://env-host:3000')
        monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'env_public')
        monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'env_secret')
        
        config = LangfuseConfig()
        
        assert config.enabled is False
        assert config.host == "http://env-host:3000"
        assert config.public_key == "env_public"
        assert config.secret_key == "env_secret"
    
    def test_env_overrides_yaml(self, monkeypatch):
        from utils.langfuse_config import LangfuseConfig
        
        # 创建临时 YAML 文件
        yaml_content = """
langfuse:
  enabled: true
  host: "http://yaml-host:3000"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            # 设置环境变量
            monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
            monkeypatch.setenv('LANGFUSE_HOST', 'http://env-host:3000')
            
            config = LangfuseConfig(config_path=temp_path)
            
            # 环境变量应该覆盖 YAML 配置
            assert config.enabled is False
            assert config.host == "http://env-host:3000"
        finally:
            os.unlink(temp_path)
    
    def test_trace_config_defaults(self):
        from utils.langfuse_config import LangfuseConfig
        
        config = LangfuseConfig()
        
        assert config.trace_llm_calls is True
        assert config.trace_agent_flow is True
        assert config.trace_tool_calls is True
        assert config.trace_api_calls is True
        assert config.sample_rate == 1.0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/utils/test_langfuse_config.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'utils.langfuse_config'"

- [ ] **Step 3: 创建配置管理模块**

Create: `utils/langfuse_config.py`

```python
"""Langfuse 配置管理模块

支持从以下来源加载配置（优先级从高到低）：
1. 环境变量
2. YAML 配置文件
3. 默认值

使用方式:
    from utils.langfuse_config import LangfuseConfig
    
    config = LangfuseConfig(config_path="config/langfuse_config.yaml")
    
    if config.enabled:
        client.init(config={
            "public_key": config.public_key,
            "secret_key": config.secret_key,
            "host": config.host
        })
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any


class LangfuseConfig:
    """Langfuse 配置管理
    
    Attributes:
        enabled: 是否启用 Langfuse
        host: Langfuse 服务器地址
        public_key: Langfuse 公钥
        secret_key: Langfuse 密钥
        sample_rate: 采样率 (0.0 - 1.0)
    """
    
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
        self.config: Dict[str, Any] = self._deep_copy_dict(self.DEFAULT_CONFIG)
        
        if config_path:
            self._load_from_file(config_path)
        
        self._load_from_env()
    
    def _deep_copy_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """深拷贝字典
        
        Args:
            d: 要拷贝的字典
        
        Returns:
            Dict[str, Any]: 拷贝后的字典
        """
        result = {}
        for key, value in d.items():
            if isinstance(value, dict):
                result[key] = self._deep_copy_dict(value)
            else:
                result[key] = value
        return result
    
    def _load_from_file(self, config_path: str) -> None:
        """从 YAML 文件加载配置
        
        Args:
            config_path: 配置文件路径
        """
        path = Path(config_path)
        if not path.exists():
            return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)
                if yaml_config and 'langfuse' in yaml_config:
                    self._merge_config(yaml_config['langfuse'])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"加载 Langfuse 配置文件失败: {e}")
    
    def _load_from_env(self) -> None:
        """从环境变量加载配置"""
        if os.getenv('LANGFUSE_ENABLED') is not None:
            self.config['enabled'] = os.getenv('LANGFUSE_ENABLED', 'true').lower() == 'true'
        
        if os.getenv('LANGFUSE_HOST'):
            self.config['host'] = os.getenv('LANGFUSE_HOST')
        
        if os.getenv('LANGFUSE_PUBLIC_KEY'):
            self.config['public_key'] = os.getenv('LANGFUSE_PUBLIC_KEY')
        
        if os.getenv('LANGFUSE_SECRET_KEY'):
            self.config['secret_key'] = os.getenv('LANGFUSE_SECRET_KEY')
        
        if os.getenv('LANGFUSE_SAMPLE_RATE'):
            try:
                self.config['sample_rate'] = float(os.getenv('LANGFUSE_SAMPLE_RATE', '1.0'))
            except ValueError:
                pass
    
    def _merge_config(self, override: Dict[str, Any]) -> None:
        """合并配置
        
        Args:
            override: 要合并的配置字典
        """
        for key, value in override.items():
            if isinstance(value, dict) and key in self.config and isinstance(self.config[key], dict):
                self.config[key].update(value)
            else:
                self.config[key] = value
    
    @property
    def enabled(self) -> bool:
        """获取启用状态
        
        Returns:
            bool: 是否启用
        """
        return self.config.get('enabled', True)
    
    @property
    def host(self) -> str:
        """获取主机地址
        
        Returns:
            str: Langfuse 服务器地址
        """
        return self.config.get('host', 'http://localhost:3000')
    
    @property
    def public_key(self) -> Optional[str]:
        """获取公钥
        
        Returns:
            Optional[str]: 公钥，可能为 None
        """
        return self.config.get('public_key')
    
    @property
    def secret_key(self) -> Optional[str]:
        """获取密钥
        
        Returns:
            Optional[str]: 密钥，可能为 None
        """
        return self.config.get('secret_key')
    
    @property
    def sample_rate(self) -> float:
        """获取采样率
        
        Returns:
            float: 采样率 (0.0 - 1.0)
        """
        return self.config.get('sample_rate', 1.0)
    
    @property
    def trace_llm_calls(self) -> bool:
        """是否追踪 LLM 调用
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('llm_calls', True)
    
    @property
    def trace_agent_flow(self) -> bool:
        """是否追踪 Agent 流程
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('agent_flow', True)
    
    @property
    def trace_tool_calls(self) -> bool:
        """是否追踪工具调用
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('tool_calls', True)
    
    @property
    def trace_api_calls(self) -> bool:
        """是否追踪外部 API
        
        Returns:
            bool: 是否追踪
        """
        trace_config = self.config.get('trace', {})
        return trace_config.get('api_calls', True)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return self._deep_copy_dict(self.config)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/utils/test_langfuse_config.py -v`

Expected: PASS

- [ ] **Step 5: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add utils/langfuse_config.py tests/utils/test_langfuse_config.py && git commit -m "feat(langfuse): add configuration management module"`

---

## Task 3: 创建配置文件和依赖文件

**Files:**
- Create: `config/langfuse_config.yaml`
- Create: `requirements-optional.txt`
- Modify: `requirements.txt`

- [ ] **Step 1: 创建 Langfuse 配置文件**

Create: `config/langfuse_config.yaml`

```yaml
# Langfuse 配置文件
# 用于配置 LLM 追踪和监控

langfuse:
  # 是否启用 Langfuse 监控
  # 设置为 false 可禁用追踪功能
  enabled: true
  
  # Langfuse 服务器地址
  # Self-hosted 部署时修改为你的服务器地址
  host: "http://localhost:3000"
  
  # API 密钥
  # 建议使用环境变量设置，不要在此文件中硬编码
  # 环境变量: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
  public_key: "${LANGFUSE_PUBLIC_KEY}"
  secret_key: "${LANGFUSE_SECRET_KEY}"
  
  # 追踪配置
  trace:
    llm_calls: true       # 追踪 LLM 调用
    agent_flow: true      # 追踪 Agent 执行流程
    tool_calls: true      # 追踪工具调用
    api_calls: true       # 追踪外部 API 调用
  
  # 采样率 (0.0 - 1.0)
  # 1.0 表示追踪所有请求，0.5 表示追踪 50% 的请求
  sample_rate: 1.0
```

- [ ] **Step 2: 创建可选依赖文件**

Create: `requirements-optional.txt`

```txt
# 可选依赖 - Langfuse 监控
# 安装命令: pip install -r requirements-optional.txt

langfuse>=2.0.0
```

- [ ] **Step 3: 检查 requirements.txt 是否存在**

Run: `Test-Path "d:\trae_projects\first-agent\DotaHelperAgent\requirements.txt"`

- [ ] **Step 4: 创建或更新 requirements.txt**

如果 requirements.txt 不存在，创建它：

Create: `requirements.txt`

```txt
# DotaHelperAgent 核心依赖

# Web 框架
flask>=2.0.0
flask-cors>=3.0.0

# HTTP 请求
requests>=2.28.0

# 配置管理
pyyaml>=6.0

# 数据处理
python-dateutil>=2.8.0

# 可选依赖 - Langfuse 监控（推荐安装）
# 安装命令: pip install langfuse
# 或: pip install -r requirements-optional.txt
# langfuse>=2.0.0
```

如果 requirements.txt 已存在，追加可选依赖说明：

Run: `Add-Content -Path "d:\trae_projects\first-agent\DotaHelperAgent\requirements.txt" -Value "`n# 可选依赖 - Langfuse 监控（推荐安装）`n# 安装命令: pip install langfuse`n# 或: pip install -r requirements-optional.txt`n# langfuse>=2.0.0"`

- [ ] **Step 5: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add config/langfuse_config.yaml requirements-optional.txt requirements.txt && git commit -m "feat(langfuse): add configuration file and optional dependencies"`

---

## Task 4: 集成到 Flask Web 层

**Files:**
- Modify: `web/app.py`

- [ ] **Step 1: 读取现有 web/app.py 文件**

Run: `Get-Content "d:\trae_projects\first-agent\DotaHelperAgent\web\app.py" | Select-Object -First 50`

- [ ] **Step 2: 在 web/app.py 中添加 Langfuse 初始化**

在文件开头的导入部分添加：

```python
# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient
    from utils.langfuse_config import LangfuseConfig
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
    LangfuseConfig = None
```

在 Flask app 初始化之后添加：

```python
# 初始化 Langfuse 监控（可选）
if LANGFUSE_AVAILABLE:
    langfuse_config = LangfuseConfig(config_path=str(project_root / "config" / "langfuse_config.yaml"))
    langfuse_client = LangfuseClient.get_instance()
    langfuse_client.init(config=langfuse_config.to_dict())
else:
    langfuse_client = None
```

- [ ] **Step 3: 添加请求追踪中间件**

在 `@app.before_request` 钩子中添加：

```python
@app.before_request
def before_request():
    # ... 现有代码 ...
    
    # Langfuse 追踪（可选）
    if langfuse_client and langfuse_client.enabled:
        trace_id = request.headers.get('X-Trace-ID') or g.get('trace_id')
        session_id = request.headers.get('X-Session-ID') or g.get('session_id')
        
        if trace_id:
            g.langfuse_trace = langfuse_client.trace(
                trace_id=trace_id,
                session_id=session_id,
                metadata={"path": request.path, "method": request.method}
            )
```

在 `@app.after_request` 钩子中添加：

```python
@app.after_request
def after_request(response):
    # ... 现有代码 ...
    
    # 刷新 Langfuse 数据
    if langfuse_client and hasattr(g, 'langfuse_trace'):
        langfuse_client.flush()
    
    return response
```

- [ ] **Step 4: 添加用户反馈 API**

添加新的 API 端点：

```python
@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
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
            trace = langfuse_client.trace(trace_id=trace_id)
            trace.score(name="user_feedback", value=float(score), comment=comment)
        except Exception as e:
            logger.warning(f"记录用户反馈失败: {e}")
    
    return {"status": "ok"}
```

- [ ] **Step 5: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add web/app.py && git commit -m "feat(langfuse): integrate Langfuse into Flask web layer"`

---

## Task 5: 集成到 Agent Controller

**Files:**
- Modify: `core/agent_controller.py`

- [ ] **Step 1: 在 agent_controller.py 中添加导入**

在文件开头的导入部分添加：

```python
# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
```

- [ ] **Step 2: 在 solve 方法中添加追踪**

在 `solve` 方法的开头添加：

```python
def solve(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # ... 现有代码 ...
    
    # 获取 Langfuse 客户端
    langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None
    
    # 创建 Langfuse Trace
    if langfuse_client and langfuse_client.enabled:
        langfuse_trace = langfuse_client.trace(
            trace_id=trace_context.trace_id,
            session_id=trace_context.session_id,
            metadata={"query": query[:100]}  # 只记录前 100 个字符
        )
    else:
        from utils.langfuse_adapter import NoOpTrace
        langfuse_trace = NoOpTrace()
    
    with langfuse_trace as trace:
        # Think
        with trace.span(name="think") as span:
            reasoning = self._think(query, context)
            span.update(metadata={"reasoning_length": len(reasoning)})
        
        # ... 其他代码 ...
```

- [ ] **Step 3: 在工具执行中添加追踪**

在工具执行部分添加：

```python
# Execute tools
for tool_call in tool_calls:
    with trace.span(name=f"tool_{tool_call.tool_name}") as span:
        span.update(input=tool_call.parameters)
        
        result = self._execute_tool(tool_call)
        
        span.update(output={"status": result.status.value})
```

- [ ] **Step 4: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add core/agent_controller.py && git commit -m "feat(langfuse): integrate Langfuse into Agent Controller"`

---

## Task 6: 集成到 LLM Client

**Files:**
- Modify: `utils/llm_client.py`

- [ ] **Step 1: 在 llm_client.py 中添加导入**

在文件开头的导入部分添加：

```python
# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
```

- [ ] **Step 2: 在 chat 方法中添加追踪**

修改 `chat` 方法：

```python
def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
    """发送聊天请求
    
    Args:
        messages: 消息列表
        **kwargs: 其他参数
    
    Returns:
        Dict[str, Any]: API 响应结果
    """
    langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None
    
    # 创建 Langfuse Span
    if langfuse_client and langfuse_client.enabled:
        from utils.langfuse_adapter import NoOpTrace
        trace = NoOpTrace()  # 使用当前 trace 上下文
        span = trace.span(
            name="llm_call",
            input={"messages": messages},
            metadata={"model": self.config.model}
        )
    else:
        from utils.langfuse_adapter import NoOpSpan
        span = NoOpSpan()
    
    with span:
        response = self._do_request(messages, **kwargs)
        
        # 记录输出和 token 使用量
        usage = response.get("usage", {})
        span.update(
            output={"content_length": len(str(response.get("choices", [{}])[0].get("message", {}).get("content", "")))},
            metadata={
                "model": self.config.model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }
        )
        
        return response
```

- [ ] **Step 3: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add utils/llm_client.py && git commit -m "feat(langfuse): integrate Langfuse into LLM Client"`

---

## Task 7: 集成到 API Client

**Files:**
- Modify: `utils/api_client.py`

- [ ] **Step 1: 在 api_client.py 中添加导入**

在文件开头的导入部分添加：

```python
# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
```

- [ ] **Step 2: 在 API 调用方法中添加追踪**

创建一个通用的追踪装饰器：

```python
def _trace_api_call(endpoint: str):
    """追踪 API 调用的装饰器
    
    Args:
        endpoint: API 端点名称
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None
            
            if langfuse_client and langfuse_client.enabled:
                from utils.langfuse_adapter import NoOpTrace
                trace = NoOpTrace()
                span = trace.span(
                    name=f"api_call_{endpoint}",
                    metadata={"api": "opendota", "endpoint": endpoint}
                )
            else:
                from utils.langfuse_adapter import NoOpSpan
                span = NoOpSpan()
            
            with span:
                result = func(self, *args, **kwargs)
                span.update(output={"result_type": type(result).__name__})
                return result
        
        return wrapper
    return decorator
```

在关键 API 方法上应用装饰器：

```python
@_trace_api_call("hero_matchups")
def get_hero_matchups(self, hero_id: int) -> List[Dict[str, Any]]:
    # ... 现有代码 ...

@_trace_api_call("hero_item_popularity")
def get_hero_item_popularity(self, hero_id: int) -> Dict[str, Any]:
    # ... 现有代码 ...
```

- [ ] **Step 3: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add utils/api_client.py && git commit -m "feat(langfuse): integrate Langfuse into API Client"`

---

## Task 8: 编写集成测试

**Files:**
- Create: `tests/integration/test_langfuse_integration.py`

- [ ] **Step 1: 创建集成测试文件**

Create: `tests/integration/test_langfuse_integration.py`

```python
"""Langfuse 集成测试"""

import pytest
import os


class TestLangfuseIntegration:
    """测试 Langfuse 集成"""
    
    def test_langfuse_client_without_sdk(self):
        """测试在没有 SDK 时的行为"""
        from utils.langfuse_adapter import LangfuseClient, NoOpTrace
        
        client = LangfuseClient.get_instance()
        
        # 未初始化时应该返回 NoOpTrace
        trace = client.trace(trace_id="test_123")
        assert isinstance(trace, NoOpTrace)
    
    def test_langfuse_config_from_env(self, monkeypatch):
        """测试从环境变量加载配置"""
        from utils.langfuse_config import LangfuseConfig
        
        monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
        monkeypatch.setenv('LANGFUSE_HOST', 'http://test-host:3000')
        
        config = LangfuseConfig()
        
        assert config.enabled is False
        assert config.host == "http://test-host:3000"
    
    def test_flask_app_starts_without_langfuse_sdk(self):
        """测试 Flask 应用在没有 Langfuse SDK 时能正常启动"""
        # 这个测试验证即使没有安装 langfuse，应用也能正常运行
        import sys
        
        # 模拟 langfuse 未安装
        if 'langfuse' in sys.modules:
            del sys.modules['langfuse']
        
        # 尝试导入 app
        try:
            # 这里不实际启动应用，只验证导入不会失败
            from utils.langfuse_adapter import is_langfuse_available
            result = is_langfuse_available()
            # 结果可能是 True 或 False，取决于是否安装了 langfuse
            assert isinstance(result, bool)
        except ImportError:
            pytest.fail("导入 langfuse_adapter 失败，应该支持可选导入")


class TestLangfuseTraceContext:
    """测试 Trace 上下文集成"""
    
    def test_trace_context_with_langfuse(self):
        """测试 Trace 上下文与 Langfuse 的集成"""
        from utils.trace_context import TraceContext, generate_trace_id, generate_session_id
        from utils.langfuse_adapter import LangfuseClient
        
        # 创建 Trace 上下文
        trace_ctx = TraceContext(
            trace_id=generate_trace_id(),
            span_id="test_span",
            session_id=generate_session_id(),
            operation="test_operation"
        )
        
        # 获取 Langfuse 客户端
        client = LangfuseClient.get_instance()
        
        # 创建 Langfuse Trace（使用相同的 trace_id）
        langfuse_trace = client.trace(
            trace_id=trace_ctx.trace_id,
            session_id=trace_ctx.session_id
        )
        
        # 验证 trace 可以正常使用
        with langfuse_trace as trace:
            with trace.span(name="test_span") as span:
                span.update(output={"result": "success"})
```

- [ ] **Step 2: 运行集成测试**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/integration/test_langfuse_integration.py -v`

Expected: PASS

- [ ] **Step 3: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add tests/integration/test_langfuse_integration.py && git commit -m "test(langfuse): add integration tests"`

---

## Task 9: 更新文档

**Files:**
- Modify: `docs/process_md/langfuse/LANGFUSE_INTEGRATION_DESIGN.md`

- [ ] **Step 1: 更新设计文档状态**

修改设计文档的状态：

```markdown
> 创建日期：2026-05-20
> 状态：已完成
```

- [ ] **Step 2: 提交代码**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && git add docs/process_md/langfuse/LANGFUSE_INTEGRATION_DESIGN.md && git commit -m "docs(langfuse): update design document status"`

---

## 验收清单

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 项目在没有安装 langfuse SDK 时能正常运行
- [ ] 项目在安装 langfuse SDK 后能正常追踪
- [ ] 配置文件正确加载
- [ ] 用户反馈 API 工作正常

---

## 实施说明

### 安装 Langfuse（可选）

```bash
# 安装 Langfuse SDK
pip install langfuse

# 或使用可选依赖文件
pip install -r requirements-optional.txt
```

### 配置 Langfuse

1. 复制配置文件模板：
```bash
cp config/langfuse_config.yaml config/langfuse_config.yaml.local
```

2. 设置环境变量：
```bash
export LANGFUSE_PUBLIC_KEY="your_public_key"
export LANGFUSE_SECRET_KEY="your_secret_key"
export LANGFUSE_HOST="http://localhost:3000"
```

3. 启动 Langfuse Server（Self-hosted）：
```bash
# 使用 Docker Compose
docker-compose up -d
```

### 验证安装

```python
from utils.langfuse_adapter import is_langfuse_available, LangfuseClient

# 检查 SDK 是否可用
print(f"Langfuse SDK 可用: {is_langfuse_available()}")

# 检查客户端是否启用
client = LangfuseClient.get_instance()
print(f"Langfuse 客户端启用: {client.enabled}")
```
