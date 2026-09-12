# evals/ —— 黄金断言与评测指标版本化（设计文档 76）

本目录是**人工高频维护区**（与代码资产 `competitor_agent/tests/evaluation/fixtures` 解耦）。

## 目录结构

```
evals/
├── golden/                # 黄金断言集（3 固定任务，must_have / trap 两型）
│   ├── analyze_cursor.yaml
│   ├── compare_claude_code_vs_copilot.yaml
│   └── track_codex_changes.yaml
└── history.jsonl          # 评测指标版本化快照（benchmark --snapshot 追加，纳入 git）
```

## 断言核实流程（季度维护）

1. **草拟**：opencode 依据知识库 + 官方来源草拟断言（`claim`/`source_of_truth`/`tags`/`type`）。
2. **人工核实**：用户逐条核对 claim 与 source_of_truth，**回填该文件的 `verified_date`**（YYYY-MM-DD）。
   未核实/格式非法/超过 90 天的断言集会在 benchmark 报告头部打印 stale 提醒（仅提醒，不失败）。
3. **季度复核**：每年 1/4/7/10 月检查 `verified_date` 距今是否 > 90 天，过期则重新核实并更新日期。

## 判定器

- **mock/CI**：`KeywordGoldenJudge` —— 确定性关键词匹配（无 LLM、无网络、可复现）。
  同义改写识别不到是已知局限，由 real 模式的 LLM 判定器补足。
- **real**：`LLMGoldenJudge` —— LLM 判定 covered/missing/contradicted（must_have）与
  passed/tripped（trap）；解析失败保守缺省，不误判失败。

## 指标版本化

```bash
python -m competitor_agent.cli benchmark --snapshot     # 跑完写快照到 evals/history.jsonl
python -m competitor_agent.cli eval-diff <from> <to>    # commit 短 hash 或 latest/N
python -m competitor_agent.cli eval-diff latest/2 latest
```

快照含 `ts / commit / harness_version / llm_mode / metrics`（只收数字）；`judge_spearman`
占位 None，doc 83 人工锚点校准完成后回填。新指标（must_have 召回率 / trap 通过率）
**只记录不卡 CI**（doc 75 §2 用户决策），攒到基线后再定红线。
