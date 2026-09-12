# PROGRESS

## 2026-09-09 doc83 `--no-blind` 补实现（✅ 完成）

**仓库/分支**：first-agent（子目录 competitor_agent）/ `design79-domain-pack`

**问题定位**（与任务描述一致）：
- CLI 已声明 `--no-blind`（`cli.py:744`，`dest="blind"`），但 `_run_eval_anchor` 起初从未读取 `args.blind`，`collect_pool` 硬编码盲评——参数是空操作。
- 前序提交 `73be296` 已补「实名展示 + CLI 接线」，但遗留两点：`blind=False` 仍执行确定性洗牌（违背既定方案「不打乱顺序」），且提交信息声称的 4 条用例未落盘（遗留工作区）。

**本次完成**：
1. 4 条测试落盘（任务步骤①）：
   - 纯函数层 2 条（`tests/unit/evaluation/test_anchor.py` 尾部）：
     - `test_no_blind_shows_filename_and_keeps_order`——实名展示 + 池原始顺序；
     - `test_no_blind_keeps_retest_flag`——重测标记保留且实名可见、不打乱。
   - CLI 接线 2 条（`tests/unit/facade/test_cli.py` 尾部，monkeypatch 模式）：
     - `test_no_blind_flag_reaches_collect_pool`——`--no-blind` 透传 `blind=False`；
     - `test_default_blind_true`——默认透传 `blind=True`。
2. `collect_pool(blind=)` 实现（步骤②）：`blind=False` 时跳过洗牌、保持池顺序（TDD：先 RED——洗牌导致 2 条失败——后转绿）；`blind=True` 行为不变（hash 展示 + seed 确定性洗牌）；`is_retest` 两种模式均保留供统计。
3. CLI 接线（步骤③）：`blind=getattr(args, "blind", True)`（`73be296` 已就位，本轮用例验证生效）；`_run_eval_anchor` 文档串同步「--no-blind 保持池顺序」语义。

**验证**（步骤④，全绿）：
- `tests/unit/evaluation/test_anchor.py`：16/16 passed
- `tests/unit/facade/test_cli.py`：39/39 passed
- `tests/unit/evaluation` 全目录：80 passed, 6 skipped（skip 为既有用例，非本次引入）
- ruff（3 个改动文件）：All checks passed；mypy（anchor.py）：no issues

**改动文件**：
- `competitor_agent/evaluation/anchor.py`（collect_pool 分支 + 文档串）
- `competitor_agent/cli.py`（文档串同步）
- `competitor_agent/tests/unit/evaluation/test_anchor.py`（+2 用例）
- `competitor_agent/tests/unit/facade/test_cli.py`（+2 用例）
