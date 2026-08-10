# 设计文档 07 — `@file:` 任意文件读取

> 对应 `implementation_plan.md` 第 11 节问题 7（P2）

## 1. 问题现状

- `input_sanitizer.py:57-89` 的 `expand_references` 会把白名单目录内文件内容读入并嵌入 prompt。
- 虽然限制了路径穿越，但 `competitor_agent/` 本身在白名单（`input_sanitizer.py:18`），可读取**源码/配置/凭据文件**内容注入上下文。
- 该函数在 `analyze()` 入口被调用（`api.py:98`），是**真实攻击面**。

## 2. 目标设计

1. 收紧 `@file:` 引用范围，仅允许读取**明确允许的数据文件**（如评测用例、报告模板），禁止读取源码/配置/凭据。
2. 增加文件类型与大小限制。
3. 对读取内容同样做不可信处理（见设计文档 06）。

## 3. 模块/接口设计

### 3.1 白名单收紧（`input_sanitizer.py`）

- 将白名单从"目录"细化为"**允许的文件扩展名 + 目录**"。
- 默认仅允许：`.md`、`.txt`、`.json`、`.yaml`（数据文件），**禁止** `.py`、`.toml`、`.env`、`.yaml` 中的敏感配置等。

```python
ALLOWED_REF_EXTENSIONS = {".md", ".txt", ".json", ".yaml"}
ALLOWED_REF_DIRS = ["evaluation/cases", "reports/templates"]  # 数据目录
MAX_REF_FILE_SIZE = 64 * 1024  # 64KB
```

### 3.2 解析增强（`expand_references`）

```python
def expand_references(text: str) -> str:
    for ref in find_refs(text):   # @file:path
        path = resolve(ref.path)
        if not is_allowed(path):  # 扩展名 + 目录 + 大小校验
            continue              # 拒绝并跳过，不读取
        content = read_file(path)
        text = text.replace(ref.raw, wrap_untrusted(content, path))
    return text
```

### 3.3 拒绝策略

- 不合规引用**静默跳过**（不读取、不报错），避免信息泄露。
- 可选：记录日志便于审计。

## 4. 接入方式

```
用户输入 → expand_references
  → 校验扩展名/目录/大小
  → 合规则读取并包裹为不可信数据
  → 不合规则跳过
```

## 5. 验证方式

- **单元测试**：`@file:../secret.py` 被拒绝；`@file:cases/foo.md` 被读取；超大文件被拒绝。
- **集成测试**：确认无法通过 `@file:` 读取源码/配置。

## 6. 实现优先级与工作量

- 优先级：**中**（P2，安全）。
- 工作量：约 0.5 天。
- 建议与设计文档 06（提示注入）一并实现。
