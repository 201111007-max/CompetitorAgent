# 设计文档 16 — `get_history` 直捅私有字段，`raw` 结构不一致

> 对应 `implementation_plan.md` 第 11 节问题 18（P1）

## 1. 问题现状

- `facade/api.py:486-514` 的 `get_history` 直接访问记忆层私有字段：

  ```python
  if competitor:
      sessions = self._memory._sessions.retrieve(competitor)  # type: ignore[attr-defined]
  else:
      sessions = self._memory.recent_sessions()               # type: ignore[attr-defined]
  ```

  这**绕过了 `IFourLayerMemory` 协议**（`interfaces/memory.py` 只声明 `archive_session` / `save_note` / `record_skill` 等，没有 `recent_sessions` / `_sessions`）。任何记忆实现替换（如换成 DB 后端）都会立刻 break。
- 更严重的：**各处 `raw` 归档结构不一致**，导致 history 返回的报告基本为空：
  - `analyze_stream`（`api.py:454-465`）归档 `raw={"terminal_state":..., "dimension_count":...}` —— **没有 `markdown_report`**。
  - `web_app.py` 归档 `raw={"markdown_report":...}`。
  - `get_history` 取值 `raw.get("markdown_report", "")`，遇到 `analyze_stream` 写入的会话时拿到空串。
- 后果：`/api/history` 要么返回空 markdown，要么只在某些入口才有内容，**feature 形同虚设**，且强耦合记忆内部实现。

## 2. 目标设计

1. 为记忆层补齐**协议化的会话查询能力**（按竞品过滤 + 最近列表），不再触碰 `_sessions` 私有字段。
2. **统一 `AnalysisSession.raw` 的 schema**：所有归档点写入一致字段（至少含 `markdown_report`、`terminal_state`、`dimension_count`），`get_history` 稳定读取。
3. `get_history` 返回的 `CompetitorReport` 必须带真实 markdown，可被前端直接渲染。

## 3. 模块/接口设计

### 3.1 扩展 `IFourLayerMemory` 协议

```python
@runtime_checkable
class IFourLayerMemory(Protocol):
    ...
    def list_sessions(self, competitor: str | None = None) -> list[AnalysisSession]:
        """L1: 列出归档会话；competitor 为空返回最近 N 条"""
        ...
```

- 实现侧（当前内存/磁盘后端）把内部 `_sessions.retrieve` / `recent_sessions` 暴露为 `list_sessions`。
- `get_history` 改为：

  ```python
  sessions = self._memory.list_sessions(competitor)
  ```

### 3.2 统一 `raw` schema（新增常量/文档契约）

约定 `AnalysisSession.raw` 必含：

```python
RAW_SCHEMA = {
    "markdown_report": str,
    "terminal_state": str,
    "dimension_count": int,
    "competitor_name": str,
    "created_at": str,
}
```

- 归档点统一用 `ReportBuilder` 产出后写入，避免手搓 dict：
  - `analyze_stream` 归档改为 `raw={"markdown_report": report.markdown_report, "terminal_state": report.terminal_state, "dimension_count": len(report.dimension_results), ...}`（复用 `analyze()` 已构建的 `report`，而非只存两个字段）。
  - `web_app.py` 归档对齐同一 schema。
- 建议新增 `AnalysisSession.from_report(report, session_id)` 工厂，单一出口保证 schema 一致。

### 3.3 `get_history` 健壮读取

```python
reports = []
for s in self._memory.list_sessions(competitor):
    raw = s.raw or {}
    reports.append(CompetitorReport(
        competitor=Competitor(name=s.competitor_name),
        markdown_report=str(raw.get("markdown_report", "")),
        terminal_state=str(raw.get("terminal_state", "")),
        created_at=s.created_at,
    ))
return reports
```

## 4. 接入方式

```
analyze() / analyze_stream() / web_app
  → self._memory.archive_session(AnalysisSession.from_report(report, sid))   # 统一 raw
get_history(competitor)
  → self._memory.list_sessions(competitor)                                   # 协议化
  → 由 raw.markdown_report 组装 CompetitorReport
```

## 5. 验证方式

- **单元测试**：
  - `memory.list_sessions(competitor)` 按竞品过滤正确；空参数返回最近 N 条。
  - 构造一个由 `analyze_stream` 归档的会话，`get_history()` 返回的 `markdown_report` 非空且与原始报告一致。
- **契约测试**：
  - 断言所有 `archive_session` 调用写入的 `raw` 含 `markdown_report` 键（可用 spy 注册校验）。
- **回归**：现有 `tests/integration/test_memory_loop.py`（记忆沉淀/落盘重载）不受影响；`/api/history` 端到端返回可渲染 markdown。

## 6. 实现优先级与工作量

- 优先级：**中**（P1，history 真实可用 + 解耦记忆实现）。
- 工作量：约 1 天（协议扩 1 方法 + 统一归档出口 + history 改写 + 测试）。
- 与问题 17（流式路径）强相关：`analyze_stream` 的归档点正是本问题的修复对象，二者应同批改。
