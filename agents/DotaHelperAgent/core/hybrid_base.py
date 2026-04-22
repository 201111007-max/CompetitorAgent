"""LLM + 数据驱动混合模式基类

提供通用的混合模式实现，支持：
- LLM 优先执行
- 数据驱动兜底
- 自动回退机制
- 统一的日志和错误处理
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional, Dict, Any, Callable
from enum import Enum


class ExecutionSource(Enum):
    """执行来源枚举"""
    LLM = "llm"
    DATA = "data"
    HYBRID = "hybrid"  # LLM + 数据混合


T = TypeVar('T')  # 结果类型
D = TypeVar('D')  # 数据输入类型


class HybridExecutor(ABC, Generic[T, D]):
    """混合执行器基类
    
    模板方法模式，定义执行流程：
    1. 尝试 LLM 执行
    2. 如果失败，回退到数据驱动
    3. 返回结果和来源标识
    """
    
    def __init__(self, llm_enabled: bool = False):
        """初始化混合执行器
        
        Args:
            llm_enabled: 是否启用 LLM
        """
        self.llm_enabled = llm_enabled
        self._llm_analyzer = None
    
    def set_llm_analyzer(self, llm_analyzer: Any) -> None:
        """设置 LLM 分析器
        
        Args:
            llm_analyzer: LLM 分析器实例
        """
        self._llm_analyzer = llm_analyzer
        self.llm_enabled = llm_analyzer is not None
    
    def execute(
        self,
        data: D,
        llm_executor: Optional[Callable[[], T]] = None,
        data_executor: Optional[Callable[[], T]] = None,
        fallback_on_error: bool = True
    ) -> Dict[str, Any]:
        """执行混合模式
        
        Args:
            data: 输入数据
            llm_executor: LLM 执行函数（如果为 None 则使用默认）
            data_executor: 数据驱动执行函数（如果为 None 则使用默认）
            fallback_on_error: 是否在 LLM 失败时回退到数据驱动
            
        Returns:
            包含结果和元数据的字典：
            {
                "result": T,              # 执行结果
                "source": ExecutionSource, # 执行来源
                "success": bool,           # 是否成功
                "error": Optional[str]     # 错误信息（如果有）
            }
        """
        result = {
            "result": None,
            "source": None,
            "success": False,
            "error": None
        }
        
        # 优先尝试 LLM 执行
        if self.llm_enabled and self._llm_analyzer:
            try:
                executor = llm_executor or self._execute_llm
                result["result"] = executor()
                result["source"] = ExecutionSource.LLM
                result["success"] = True
                return result
            except Exception as e:
                error_msg = f"LLM 执行失败：{str(e)}"
                if fallback_on_error:
                    print(f"⚠️ {error_msg}")
                    print("   切换到数据驱动模式...")
                else:
                    result["error"] = error_msg
                    return result
        
        # 使用数据驱动兜底
        try:
            executor = data_executor or self._execute_data
            result["result"] = executor(data)
            result["source"] = ExecutionSource.DATA
            result["success"] = True
        except Exception as e:
            result["error"] = f"数据驱动执行失败：{str(e)}"
        
        return result
    
    @abstractmethod
    def _execute_llm(self, data: D) -> T:
        """执行 LLM 逻辑（子类实现）
        
        Args:
            data: 输入数据
            
        Returns:
            执行结果
        """
        pass
    
    @abstractmethod
    def _execute_data(self, data: D) -> T:
        """执行数据驱动逻辑（子类实现）
        
        Args:
            data: 输入数据
            
        Returns:
            执行结果
        """
        pass
    
    def _log_execution(self, source: ExecutionSource, success: bool) -> None:
        """记录执行日志
        
        Args:
            source: 执行来源
            success: 是否成功
        """
        emoji = "[LLM]" if source == ExecutionSource.LLM else "[DATA]"
        status = "[OK]" if success else "[FAIL]"
        mode = "LLM" if source == ExecutionSource.LLM else "数据驱动"
        print(f"{emoji} {mode} 模式执行 {status}")


class HybridAnalyzer(HybridExecutor[Dict[str, Any], Dict[str, Any]]):
    """混合分析器基类
    
    专门用于 Dota 2 分析场景，提供通用的分析接口
    """
    
    def __init__(self, llm_enabled: bool = False):
        """初始化混合分析器
        
        Args:
            llm_enabled: 是否启用 LLM
        """
        super().__init__(llm_enabled)
        self._data_client = None
    
    def set_data_client(self, client: Any) -> None:
        """设置数据客户端
        
        Args:
            client: 数据客户端实例（如 OpenDotaClient）
        """
        self._data_client = client
    
    def analyze(
        self,
        input_data: Dict[str, Any],
        use_llm: Optional[bool] = None
    ) -> Dict[str, Any]:
        """执行分析
        
        Args:
            input_data: 输入数据
            use_llm: 是否使用 LLM（可选，默认根据配置）
            
        Returns:
            分析结果
        """
        if use_llm is False:
            # 强制使用数据驱动
            return self._execute_data(input_data)
        
        # 使用混合模式
        result = self.execute(
            data=input_data,
            llm_executor=lambda: self._execute_llm(input_data),
            data_executor=lambda _: self._execute_data(input_data)
        )
        
        # 添加来源标识
        if isinstance(result.get("result"), dict):
            result["result"]["source"] = result["source"].value
        
        self._log_execution(result["source"], result["success"])
        
        if result["error"]:
            print(f"错误：{result['error']}")
        
        return result["result"]
    
    @abstractmethod
    def _execute_llm(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """LLM 分析实现"""
        pass
    
    @abstractmethod
    def _execute_data(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """数据驱动分析实现"""
        pass


def create_hybrid_result(
    result: T,
    source: ExecutionSource,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """创建标准化的混合模式结果
    
    Args:
        result: 执行结果
        source: 执行来源
        metadata: 额外元数据
        
    Returns:
        标准化的结果字典
    """
    base = {
        "result": result,
        "source": source.value,
        "success": True
    }
    
    if metadata:
        base.update(metadata)
    
    return base
