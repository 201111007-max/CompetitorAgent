# 设计文档 92 —— 第四十二轮：广捕异常第一批整改（except:pass 清零 + 保证型路径）

> 第四十二轮。来源：`doc/tech_review_2026-09-12.md` P1-5「广捕异常泛滥（126 处
> `except Exception`，8 处 except:pass）」。评审修复方案为分级整改，本批只做第一批：
> ① 8 处 `except: pass` 清零；② 保证型路径（budget/cancel/checkpoint 调用链）上的
> 广捕收窄或改为记录后 re-raise。采集/外部源层的广捕整改留作下批（本批未触碰）。

## 1. 全量定位结论

- `except: pass`：AST 全仓扫描（排除 tests）确认评审计数的 8 处均为
  「`except <具体异常>: pass` 且无日志」——`core/checkpoint.py` 5 处（L90/107/119/157/261，
  保证型路径）、`config/loader.py` 1 处（L359）、`evaluation/behavior_eval.py` L172 与
  `evaluation/benchmark.py` L380 各 1 处。无字面裸 `except:`。
- 保证型路径 `except Exception` 现状：`core/budget.py`、`core/budget_controller.py`、
  `core/checkpoint.py` 取消标志族（set/is/clear_cancel）**零广捕**；`ReactLoop._step_guard`
  取消/预算门禁无 catch。保证型路径上实际存在的广捕只有 `facade/api.py` 三处
  trace 收尾（L409 analyze / L1866 run / L1927 _run_chat：cleanup 后 raise，不吞错但无
  日志）与一处结构性风险（取消分支的 checkpoint 保存失败会把"取消"变成 500）。

## 2. 整改分级清单（本批实施）

### A. checkpoint.py 5 处 except:pass（保证型路径，全部补日志，均不改为抛错）

| 位置 | 语义 | 改法与理由 |
| --- | --- | --- |
| L90 `_sweep_stale_tmp` | 清扫陈旧 tmp 文件 | `except OSError as exc` + `logger.debug`。清扫失败无害（下次 sweep 兜底），但留痕 |
| L107 `_write_bytes_atomic` finally | 清临时文件 | `except OSError as exc` + `logger.debug`。残留 tmp 由 sweep 兜底，finally 内绝不能抛 |
| L119 `_atomic_write` 备份旧文件 | .bak 是主文件损坏时的唯一恢复路径 | `except OSError as exc` + `logger.warning`。备份失败必须可见；主写不裹 catch，保存失败仍抛错（保证：checkpoint 保存失败=响亮报错，不静默） |
| L157 `CheckpointLock.__exit__`（Windows 分支） | msvcrt 解锁失败 | `except OSError as exc` + `logger.warning`。锁残留会卡死后续会话的 checkpoint 写 |
| L261 `delete_checkpoint` | 删除主文件/.bak/.lock | `except OSError as exc` + `logger.warning`。残留 checkpoint 会被 resume 误拾取 |

行为兼容：五处原本吞 OSError，改后仍不抛（清理/备份/解锁失败不该炸主流程），差别只在
从"无声"变"有日志"。checkpoint **保存主路径**（`_write_bytes_atomic(path, payload)`）
本就不裹 catch，保存失败照常冒泡——保证语义不变。

### B. config/loader.py L359（环境变量整型解析）

`except ValueError: pass` → `except ValueError` + `logger.warning`（带变量名与原始值）。
配错环境变量静默回退默认值是排障无凭的典型；仍回退默认值（不炸启动），行为兼容。

### C. evaluation 两处（behavior_eval.py L172 / benchmark.py L380）

`except (json.JSONDecodeError, TypeError): pass` → 补 `logger.debug`（两文件原无 logger，
各加模块级 `logging.getLogger(__name__)`）。语义不变：mock LLM 输出畸形 Args 时降级为空
参数字典，不炸评测管道；debug 级即可（脚本化回放中属预期分支）。

### D. 保证型路径 except Exception（facade/api.py）

1. **L409 / L1866 / L1927（analyze/run/_run_chat trace 收尾）**：已是
   `except Exception: end_trace(status="error"); raise`，不吞错、保证语义完好
   （广捕在此是"任意失败都要闭合 trace"的正当用法，收窄为具体异常反而会漏掉未知异常
   导致 trace 悬半）。按评审"改为记录后 re-raise"补 `logger.warning(..., exc_info=True)`，
   排障不再只靠 trace 状态。
2. **L450-453 取消分支 `_save_checkpoint_for_resume`**：当前 save_checkpoint 抛错会沿
   analyze/run 的 `except Exception → raise` 变成 500——**取消保证被破坏**（用户取消
   拿不到 CancelledResult）。改为在 `_save_checkpoint_for_resume` 内捕
   `(OSError, TypeError, ValueError)`（磁盘 IO + 序列化失败族，不捕 Exception 以免吞
   编程错误）+ `logger.error(..., exc_info=True)` 后返回：取消生效优先于 checkpoint
   落盘，checkpoint 丢失有 error 日志可排障（非静默）。正常路径（测试断言
   `load_checkpoint(sid) is not None`）不受影响。

## 3. 不改动项与理由

- 采集/外部源层广捕（collector/、llm/client 重试、mcp_server tools、verifier 抓取段）：
  降级链语义要求广捕，且多数已带日志/noqa 注释；少数无日志的（如 collector/search.py:282、
  crawl4ai_fetch.py:74）留作下批补 source+原因结构化日志。本批未触碰，故无需补。
- ReAct 工具执行回灌（react_agent.py:297、delegate_tool.py:218、langgraph nodes.py:114）：
  "异常回灌不冒泡卡死"是有意设计（异常文本进 Observation 供 LLM 自恢复），不动。
- 可选增强降级（memory 向量、langfuse、report_visuals、domain_pack、vector_store 等）：
  广捕 + noqa 注释 + 已有日志，低优先，不动。
- `core/input_sanitizer.py`：另一任务在改，明确不动。

## 4. 测试验收

- 受影响既有测试：`tests/unit/core/test_checkpoint.py`、
  `tests/unit/facade/test_cancellation.py`、budget 相关
  `tests/unit/core/test_budget*.py`、`tests/unit/facade/test_api*.py`、
  config loader 与 evaluation 相关测试。
- 全量：`python -m pytest tests/unit -x -q` 全绿。
- 行为兼容核验：8 处 except:pass 改后均不新增抛错路径；取消测试（含
  `test_cancel_during_run_returns_partial_result_and_stops` 的 checkpoint 断言）不回归。
