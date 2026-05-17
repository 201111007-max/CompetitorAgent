---
name: "python-type-hints"
description: "Enforces Python Type Hints in all Python code operations. Invoke when user asks to write, generate, create, modify, refactor, optimize Python code, or add/check Type Hints."
---

# Python Type Hints

This skill enforces the use of Python Type Hints (PEP 484) in all Python code operations.

## When to Invoke

**CRITICAL: Invoke this skill IMMEDIATELY when:**

### Code Generation Scenarios
- User asks to **write** Python code
- User asks to **generate** Python code
- User asks to **create** Python code
- User asks to **implement** a function or class
- User asks to **build** a script or module

### Code Modification Scenarios
- User asks to **modify** existing Python code
- User asks to **refactor** Python code
- User asks to **optimize** Python code
- User asks to **update** Python code
- User asks to **improve** Python code

### Type Hint Specific Scenarios
- User asks to **add Type Hints** to existing code
- User asks to **check Type Hint** usage
- User asks to **补充 Type Hint** (Chinese)
- User asks to **添加类型注解** (Chinese)
- User asks to **检查类型提示** (Chinese)
- User mentions "type hint", "Type Hint", "类型注解", "类型提示"

## Trigger Keywords

Invoke this skill when user message contains:
- "type hint", "Type Hint", "类型注解", "类型提示"
- "add type", "补充类型", "添加类型"
- "check type", "检查类型"
- "refactor", "重构", "optimize", "优化"
- "modify", "修改", "update", "更新"
- "write", "写", "generate", "生成", "create", "创建"

## Type Hints Requirements

### 1. Function Type Hints

```python
# Required
def greet(name: str) -> str:
    return f"Hello, {name}!"

def process_data(data: list[int], config: dict[str, int]) -> tuple[int, str]:
    total = sum(data)
    return total, f"Processed {len(data)} items"
```

### 2. Variable Type Hints

```python
# Required
x: int = 10
name: str = "Alice"
scores: list[float] = [1.0, 2.0, 3.0]
config: dict[str, int] = {"lr": 0.001}
```

### 3. Class Type Hints

```python
class User:
    def __init__(self, name: str, age: int) -> None:
        self.name: str = name
        self.age: int = age

    def get_info(self) -> str:
        return f"{self.name}, {self.age}"
```

### 4. Import Type Hints

```python
from typing import List, Dict, Tuple, Optional, Union, Any
from typing import Callable, Iterator, Type
```

### 5. Complex Types

```python
# Optional - may be None
def find_user(user_id: int) -> Optional[Dict[str, str]]:
    if user_id > 0:
        return {"id": str(user_id), "name": "Tom"}
    return None

# Union - multiple types
def parse_value(value: str) -> Union[int, float]:
    try:
        return int(value)
    except ValueError:
        return float(value)

# Any - when type is unknown
def log_message(message: Any) -> None:
    print(message)

# Callable - function as parameter
def apply_function(func: Callable[[int], int], value: int) -> int:
    return func(value)
```

## Type Hints Cheat Sheet

| Type | Hint | Example |
|------|------|---------|
| Integer | `int` | `x: int = 10` |
| Float | `float` | `x: float = 1.5` |
| String | `str` | `x: str = "hello"` |
| Boolean | `bool` | `x: bool = True` |
| List | `list[T]` | `x: list[int] = [1, 2, 3]` |
| Dict | `dict[K, V]` | `x: dict[str, int] = {"a": 1}` |
| Tuple | `tuple[T1, T2]` | `x: tuple[int, str] = (1, "a")` |
| Optional | `Optional[T]` | `x: Optional[int] = None` |
| Union | `Union[T1, T2]` | `x: Union[int, str] = 1` |
| Any | `Any` | `x: Any = ...` |
| None | `None` | `-> None` |

## Benefits of Type Hints

1. **Better IDE Support**: Auto-complete, error detection
2. **Self-Documenting Code**: Clear input/output types
3. **Runtime Safety**: Catches type errors early
4. **Refactoring**: Easier to change code safely

## Example Scenarios

### ✅ Should Invoke

**Code Generation:**
- "写一个新函数"
- "创建一个新类"
- "实现一个功能"

**Code Modification:**
- "检查并补充 Type Hint"
- "为这个函数添加类型注解"
- "优化这段代码"
- "重构这个函数"

**Type Hint Specific:**
- "检查当前项目是否使用了 Type Hint"
- "补充缺失的 Type Hint"
- "添加类型注解"

### ❌ Should NOT Invoke

- "运行测试"
- "查看日志"
- "部署项目"
- "安装依赖"

## Important Notes

- **ALWAYS use type hints** in all Python code
- Include return type annotations: `-> type`
- Include parameter type annotations: `(param: type)`
- Include variable type annotations when helpful
- Use `typing` module for complex types
- **INVOKE THIS SKILL IMMEDIATELY** when any trigger condition is met
