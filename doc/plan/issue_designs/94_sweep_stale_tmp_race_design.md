# 设计文档 94 —— 第四十四轮：_sweep_stale_tmp 误删并发进程活跃 tmp（xdist 偶发失败根因）

> 第四十四轮。来源：`-n auto` 迁入 addopts 后本地全量并行暴露
> `test_compare_parallel::test_parallel_compare_same_semantics_as_serial` 偶发失败
> （约 1/5 全量跑）。抓现场确认：失败侧报告缺「结构化矩阵已导出」注记。
>
> **根因（真 bug，非测试问题）**：`core/checkpoint.py::_sweep_stale_tmp` 在每次
> 原子写成功后 glob `.{stem}.*.tmp` 全删——tmp 文件名虽含 pid/uuid
> （`.{stem}.{pid}.{uuid8}.tmp`），sweep 却不按 pid 过滤，**无法区分其他进程
> 崩溃留下的陈旧 tmp 与其他进程正在写入的活跃 tmp**。xdist 两 worker 并发跑
> 同名输出（cursor___windsurf.json）的 compare 测试时：worker B 完成写入后
> sweep 删掉 worker A 尚在写入的活跃 tmp → A 的 `os.replace` 抛
> FileNotFoundError → 被 `_export_comparison_json` 广捕吞掉（design 92 已补
> 日志）→ 该次报告无导出注记 → 确定性断言炸。生产上两个并发 CLI/web 进程
> 写同名报告/checkpoint 同样可踩。CI 今早 `-n auto` 已上线，该 flake 本就
> 存在（概率性），addopts 只是让本地默认暴露。

## 1. 方案

`_sweep_stale_tmp` 改为**只删 mtime 早于阈值（1 小时）的 tmp**：

- 活跃写入是毫秒级，1 小时阈值不可能误删活跃 tmp；
- 崩溃残留 tmp 延迟至多 1 小时被后续写入清扫，可接受（个人项目 tmp 垃圾成本极低）；
- 不选 pid 活性检测（os.kill(pid,0)）：Windows 语义不一致，且 pid 复用会误判，
  年龄方案跨平台零分支。

单点修改 `core/checkpoint.py::_sweep_stale_tmp`，`_write_bytes_atomic` 调用点不变。

## 2. 测试验收

`tests/unit/core/test_checkpoint*.py` 增补：
- 新鲜 tmp（模拟他进程活跃写入）→ sweep 后仍存在；
- 旧 tmp（os.utime 拨回 2 小时前）→ sweep 后删除；
- 既有原子写测试零改动通过。
回归验证：全量 `pytest tests/unit`（默认并行）连跑 ≥3 轮无该用例失败。

## 3. 风险权衡

- 阈值 1 小时为常量：若某次真实写入超过 1 小时（不可能——单次导出为 KB 级
  JSON），才会误删；接受。
- 崩溃 tmp 最长残留 1 小时：磁盘影响可忽略；下次写入同 stem 文件时才触发清扫，
  无人写的 stem 的 tmp 永不清扫（现状即如此，不变）。
