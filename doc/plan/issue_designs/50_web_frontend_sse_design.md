# 设计文档 50 — Web 前端 SSE 事件丢失修复与展示优化

> 触发：2026-08-19 用户要求分析 Web 前端 SSE 输出与样式——分析发现 **1 个真实生产 bug**
>（分析过程中的进度事件被静默丢弃，已实证）+ 1 个实现粗糙点（50ms 忙轮询）+ 若干展示/可维护性优化空间。
> 前置：43（`ReactLoop` 共享会话上下文 events）、47/49（主路径仅 LLM、Lead ReAct 编排——分析耗时变长，
> 中途进度可见性更重要）、28（结构化导出）。范围仅限 `web_app.py` 与其内嵌前端，不动分析内核。

## 1. 问题现状

### 1.1 Bug：运行中进度事件被静默丢弃（P0）

`web_app.py::_event_generator`（:81-）的事件桥：

```python
def _on_event(event: ProgressEvent) -> None:
    try:
        loop = asyncio.get_event_loop()          # ← 问题在这
        if loop.is_running():
            loop.call_soon_threadsafe(lambda: events_queue.put_nowait(event))
    except RuntimeError:
        pass                                      # ← 异常被吞，事件丢失
```

- 分析经 `run_in_executor` 在**工作线程**执行（`web_app.py:125`），`event_sink` 回调发生在工作线程；
- Python 3.11 中 `asyncio.get_event_loop()` 在非主线程无 current loop → 抛 `RuntimeError`
  （已实证：`ThreadPoolExecutor` 线程内调用返回 `RuntimeError: There is no current event loop in thread`）；
- 结果被 `except RuntimeError: pass` 吞掉 → **Lead 分析期间所有 `phase_start` / 子 Agent 进度事件全部丢失**，
  用户只看到 `session_started`（主线程 yield）和终态 `report`/`error`/`cancelled`；
- 测试未暴露：`tests/unit/web/test_web_cancel.py` 只断言取消路径，无用例断言"中途事件出现在 SSE 流"。

> 注：`/api/logs/stream/{sid}`（会话日志流）走文件尾随，不受此 bug 影响——这也是用户仍能看到日志的原因。

### 1.2 粗糙点：50ms 忙轮询（P0/P1 边界）

`_event_generator` 主循环 `await asyncio.sleep(0.05)` 轮询队列（`web_app.py:163`）：
空转耗 CPU（每次分析 ~每秒 20 次空调度），且给事件引入最多 50ms 人为延迟。
应改为 `await events_queue.get()` + 完成后排空残余事件。

### 1.3 展示与可维护性问题（P1/P2）

| 问题 | 现状（行号） |
|---|---|
| 报告不渲染 | markdown 报告 `textContent` 纯文本直出（:481，防 XSS 正确但标题/表格/代码块全无排版） |
| 表格解析手写 | `renderMatrix` 手写切 markdown 表格（:459-475），仅认「品类格局矩阵」，脆弱 |
| 进度字段闲置 | `data.progress` 只在兜底文案里出现（:414），无进度条；report payload 的 `dimensions` 列表未利用 |
| 布局 | 800px 单列、输入框写死 400px、无响应式、无暗色（`prefers-color-scheme`） |
| 可维护性 | HTML/CSS/JS 内嵌在 Python 字符串里（:312-521），无高亮/校验，改动需动 .py |

保留优点（不改）：XSS 处理（`textContent`/`escapeHtml`）、取消链路（POST cancel → 协作式中断）、
双 SSE 分工（事件流 + 会话日志流）、对比矩阵/复制/下载交互。

## 2. 目标设计

### 2.1 P0：修复事件桥

`_event_generator` 在 async 上下文（主线程、loop 运行中）先捕获运行中的 loop，闭包供 sink 使用：

```python
async def _event_generator(session_id: str, task: str):
    events_queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
    loop = asyncio.get_running_loop()            # 主线程捕获，线程安全

    def _on_event(event: ProgressEvent) -> None:
        loop.call_soon_threadsafe(events_queue.put_nowait, event)
```

`call_soon_threadsafe` 本身就是为跨线程设计的，不再需要 `is_running` 判断与 try/except 吞异常
（generator 关闭后 loop 仍存在，call_soon_threadsafe 对已关闭 loop 才抛 RuntimeError——该场景是会话
结束后迟到事件，保留窄捕获并记 debug 日志，不再静默）。

### 2.2 P0/P1：轮询改 await

```
while not analysis_task.done():
    event = await events_queue.get()      # 挂起而非忙轮询
    yield event.to_sse()
# analysis_task 完成后：drain 残余事件（get_nowait 循环）→ 终态处理（不变）
```

取消检查（`_sessions[sid].cancelled`）挂到 `asyncio.wait_for(events_queue.get(), timeout=0.2)`
的超时分支上，保持取消响应延迟 ≤200ms（现状 50ms，可接受折衷；或保留 cancel 专用 `asyncio.Event`
由 `/api/cancel` 直接 set，与队列 `asyncio.wait` 双等待——实现时取简单者）。

### 2.3 P1：报告 markdown 渲染 + 进度可视化

- **渲染**：引入轻量 markdown → HTML（推荐 **vendored** `marked.min.js` + `DOMPurify` 落 `static/vendor/`，
  不依赖 CDN——部署环境可能无外网）；渲染后 `renderMatrix` 手写解析删除（marked 原生出表格）。
  退路：若不想引 JS 依赖，服务端 `markdown` 库转 HTML + 前端 `DOMPurify` 二选一，仍须 sanitize。
- **进度**：`data.progress` 驱动顶部进度条；`phase_start/phase_complete` 渲染阶段徽章
  （plan → delegate:pricing… → report）；`report` payload 的 `dimensions`/`overall_confidence` 渲染为
  维度 chips + 置信度标签。
- **约束**：继续全部走 sanitize 后注入（DOMPurify），禁止 `innerHTML` 直灌 SSE 原文。

### 2.4 P2：布局与静态资源抽离

- `web_app.py` 内嵌 HTML 抽到 `competitor_agent/static/`（`index.html`/`app.js`/`style.css`），
  `index()` 读文件返回（`importlib.resources`，打包经 pyproject package-data 纳入 wheel）；
- 布局：头部（输入 + 操作）+ 主区双栏（左：事件流 + 会话日志 details；右：报告），≤760px 媒体查询退化为单列；
- 暗色：`prefers-color-scheme: dark` 一套 CSS 变量，无 JS 切换器（够用即可）。

## 3. 模块/接口设计

### 3.1 修改 `web_app.py::_event_generator`

- sink 改 §2.1 闭包捕获 loop；主循环改 §2.2 await + drain；其余（session_started / 终态三分支 /
  落盘 / 归档 / 取消）不变。
- **接口不变**：SSE 事件 schema（`ProgressEvent.to_dict`）不动，前端协议零变化。

### 3.2 新增 `competitor_agent/static/`

```
static/
├── index.html        # 结构 + 语义化标签
├── app.js            # EventSource 消费、渲染、交互（现 :367-519 迁移 + markdown 渲染 + 进度条）
├── style.css         # CSS 变量 + 双栏 + 暗色
└── vendor/           # marked.min.js / dompurify.min.js（vendored，无 CDN 依赖）
```

`index()` 改 `importlib.resources.files("competitor_agent.static").joinpath("index.html").read_text()`；
`/static/*` 挂 `StaticFiles`（web extra 已含 fastapi，无新依赖）。

### 3.3 测试

- 新增 `tests/unit/web/test_web_sse_events.py`：
  ① **中途事件断言**（本 bug 回归测试）：模拟分析线程中调 event_sink（`run_in_executor` 内发 3 个事件），
  断言 SSE 流按序包含它们——修复前必红、修复后绿；
  ② drain 语义：任务完成瞬间队列残余事件不丢失；
  ③ 取消响应 ≤300ms。
- 现有 `test_web_cancel.py` / `test_report_export.py` 保持绿（接口不变）。

## 4. 接入方式

- 配置：`review_config.yaml` 无新字段；`pyproject.toml` 加 package-data（`competitor_agent.static`）。
- 兼容：SSE 协议、REST 端点、事件类型全部不变；前端渲染层替换对 API 消费方无影响。
- 回退：P1/P2（渲染/布局）独立于 P0（bug 修复），可分批合入；P0 单独一个提交先上。

## 5. 验证方式

- `pytest tests/unit/web tests/integration -q` 全绿（含新回归测试）；
- 全量 `pytest -q`（competitor_agent/）不回归；
- **浏览器实测**（UI 变更必做）：启动 `web_app`，跑「分析 Cursor」——确认中途 phase 事件实时出现
  （修复前没有）、进度条推进、报告 markdown 排版、取消按钮生效、暗色/窄屏布局正常；
- 安全自查：markdown 渲染后注入路径全部经 DOMPurify；`vendor/` 文件来源记录版本号。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README/implementation_plan 登记 | 0.2d ✅ 2026-08-19 |
| 1 | P0 事件桥修复 + await 化 + 回归测试 | `web_app.py` + `test_web_sse_events.py` | 0.5d |
| 2 | P1 markdown 渲染 + 进度条/阶段徽章/维度 chips | static 三件套 + vendor | 1d |
| 3 | P2 布局/暗色/响应式 + package-data | style.css + pyproject | 0.5d |

## 7. 风险与缓解

1. **vendor 依赖体积/来源**：marked + DOMPurify 合计 ~100KB，记录版本与 hash；若评审不接受 JS 依赖，
   退路为服务端渲染（`markdown` 库）+ 前端 sanitize，代价是 Python 侧多一个依赖——同为可选项，实施时定。
2. **回归**：P0 改动触及取消/终态时序——`test_web_cancel.py` 必须保持绿，新增 drain 测试覆盖
   "完成瞬间事件不丢"。
3. **打包遗漏**：static 目录不进 wheel 会导致 `index()` 500——加 package-data 后补一个
   `importlib.resources` 可读性的单测。
