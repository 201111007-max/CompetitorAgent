# 设计文档 19 — 工程卫生：Python 版本声明 / 锁表泄漏 / coverage 无门槛

> 对应 `implementation_plan.md` 第 11 节问题 21-23（P3）

## 1. 问题现状

### 21. `requires-python` 声明与真实能力不一致
- `pyproject.toml:5` 声明 `requires-python = ">=3.9"`，`[tool.poetry]` 也是 `python = "^3.9"`；
- 但代码中已使用 **3.11+ 才有的语法/类型**：`core/checkpoint.py:19` 的 `from typing import Self`（`Self` 在 3.11 引入），CI 矩阵仅测 3.10-3.12（见 README 问题 21 描述，且实际 `mypy` 配置与运行环境为 3.10+）。
- 后果：在真实 3.9 环境安装/运行会 `ImportError` / 语法错误，声明不可信，误导用户与评审。

### 22. `_session_locks` 全局表只增不减（内存泄漏语义）
- `core/checkpoint.py:165-180`：

  ```python
  _session_locks: dict[str, threading.Lock] = {}
  ...
  def _session_lock(session_id):
      with _session_locks_guard:
          lock = _session_locks.get(session_id)
          if lock is None:
              lock = threading.Lock()
              _session_locks[session_id] = lock
          return lock

  def _drop_session_lock(session_id):
      with _session_locks_guard:
          _session_locks.pop(session_id, None)
  ```

- `_drop_session_lock` 仅在 `delete_checkpoint` 被调用（`checkpoint.py:269`）。但：
  - **取消/异常的会话若从未走到 `delete_checkpoint`**（例如进程被强杀、或某些提前返回路径），锁条目永久残留；
  - 长生命周期服务中会话 id 持续增长 → 全局 dict 单调膨胀，属典型内存泄漏语义。
- 注：当前进程内锁仅用于串行化同 session 写，残留条目本身不阻塞功能，但作为"服务级"组件不可接受。

### 23. CI 覆盖率无门槛 + 陈旧产物
- CI 上传 `.coverage` 二进制文件却未配置 `[tool.coverage.report] fail_under` 门槛，覆盖率下降无人知晓；
- `.coverage` 为本地二进制，跨 runner 不可比，应改为生成可审阅的 `xml` / `html` 报告（如 `pytest --cov --cov-report=xml --cov-report=html`）。

## 2. 目标设计

1. **Python 版本声明真实**：`requires-python` 与 poetry `python` 对齐到代码实际最低支持版本（≥3.10，若保留 `Self` 则 ≥3.11），并让 CI 矩阵与之匹配。
2. **锁表按会话回收**：`_session_locks` 在会话结束后（无论正常 `delete` 还是异常/取消）都能回收；或改为弱引用 / LRU，避免单调增长。
3. **覆盖率门槛 + 可读报告**：配置 `fail_under` 门禁，CI 生成 `coverage.xml` / `html`，不再上传裸 `.coverage`。

## 3. 模块/接口设计

### 3.1 Python 版本对齐（`pyproject.toml`）

```toml
[project]
requires-python = ">=3.10"        # 或 >=3.11（若保留 typing.Self）

[tool.poetry]
python = "^3.10"

[tool.mypy]
python_version = "3.10"           # 与运行/CI 一致

[tool.ruff]
target-version = "py310"

[tool.black]
target-version = ["py310"]
```

- 若想保留 3.9 兼容，则把 `from typing import Self` 改为 `from typing_extensions import Self`（需加依赖），否则直接抬版本到 3.10/3.11 最省事。推荐抬到 `>=3.10` 并移除 3.9 相关不一致声明。

### 3.2 锁表回收（`core/checkpoint.py`）

方案 A（弱引用，推荐，零泄漏）：

```python
import weakref
_session_locks: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
```

当外部不再持有该 session 的锁引用时自动回收，无需手动 `_drop_session_lock`。注意：`_session_lock` 返回锁给调用方持有期间不会回收，正好符合"会话活跃期持有、结束后释放"。

方案 B（显式回收 + 异常兜底）：在 `save_checkpoint` 包装或 `analyze` 的 `finally` 中确保 `_drop_session_lock(sid)`，覆盖取消/异常路径。

建议 A，并保留 `_drop_session_lock` 作为显式清理入口（双保险）。

### 3.3 覆盖率门禁（`pyproject.toml` + CI）

```toml
[tool.coverage.run]
source = ["competitor_agent"]

[tool.coverage.report]
fail_under = 85          # 与当前实际覆盖率对齐后设定
show_missing = true

[tool.pytest.ini_options]
addopts = "--cov=competitor_agent --cov-report=term-missing --cov-report=xml --cov-report=html"
```

- CI 改为上传 `coverage.xml` + `htmlcov/`，移除 `.coverage` 二进制上传。
- `fail_under` 初值取当前真实覆盖率（如 80%），随修复逐步抬升。

## 4. 接入方式

```
pyproject.toml
  ├─ requires-python / poetry.python / mypy / ruff / black 版本统一
  └─ [tool.coverage.report] fail_under + [tool.pytest.ini_options] addopts
core/checkpoint.py
  └─ _session_locks → WeakValueDictionary（或加 finally 兜底回收）
CI workflow
  └─ 上传 coverage.xml / htmlcov，不再上传 .coverage
```

## 5. 验证方式

- **版本声明**：
  - `python -c "import competitor_agent"` 在声明的 `requires-python` 最低版本上可运行；
  - `ruff` / `mypy` 不报目标版本不支持的语法。
- **锁表回收**：
  - 单测：创建 1000 个 session 后 `_drop_session_lock` 全部清理，断言 `len(_session_locks) == 0`（方案 B）；或断言弱引用在外部释放后自动清空（方案 A）；
  - 模拟"取消但未 delete"路径后，确认锁表不单调增长。
- **覆盖率门禁**：
  - 本地 `pytest` 触发 `coverage.xml` / `htmlcov/` 生成；
  - 临时把 `fail_under` 设到 100 验证 CI 会**失败**（证明门禁生效），再复原。

## 6. 实现优先级与工作量

- 优先级：**低**（P3，工程卫生，不影响功能正确性）。
- 工作量：约 0.5-1 天（改 `pyproject.toml` 三处 + 锁表一行 + CI 配置）。
- 建议放在 P0/P1 功能修复之后，作为收尾；`fail_under` 阈值需先测出当前真实覆盖率再设定，避免一上线就红。
