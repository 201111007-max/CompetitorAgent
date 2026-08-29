# 设计文档 68 —— Web 前端产品化：情报档案台（Dossier Console）+ 报告库 / 审批工作流

> 第十八轮。基于 doc 67 已完成的后端产品化闭环（报告落盘 + 审批状态机 + Web 审批接口），
> 当前前端仍是"裸对话页"——报告生成后一次性展示，**没有报告库、没有审批入口、没有时间线视图**，
> 产品化闭环在 UI 层断了一环。本文档用 opencode 前端优化 skill（frontend-design + ui-ux-pro-max）
> 产出设计方案，把对话页升级为**情报档案台**：左侧案例文件柜（报告库/历史/审批状态）+ 右侧对话工作区，
> 报告渲染为带"盖章式审批徽章"的档案卡，并补齐审批操作与竞品时间线消费。
>
> **范围**：仅改 `static/` 三件套（`index.html` / `style.css` / `app.js`），**后端零改动**——
> 全部复用已有端点（`/api/analyze`、`/api/cancel`、`/api/history`、`/api/reports/{name}`、
> `/api/reports/{name}/status`、`/api/reports/{name}/review`、`/api/timeline/{name}`）。

## 1. 问题现状

### 1.1 已具备（不重复建设）

| 能力 | 现状 |
|------|------|
| 流式对话 | doc 63/64：`text_delta` 打字机 + 分段思考 + `task` todo 清单 + `report` 面板，`app.js` 事件引擎完整 |
| 报告落盘 | doc 22/67：`save_report_markdown` 原子写 `reports/competitor/<竞品>.md`，`report_archiver.py` |
| 审批后端 | doc 67 §3.2：`approval_gate.py` 状态机 `draft→pending_review→approved/rejected` + `/api/reports/{name}/status` + `/api/reports/{name}/review` |
| 历史/时间线 | `/api/history`（归档会话列表）、`/api/history/{name}`、`/api/timeline/{name}`（doc 26 §3.4 事件） |
| 会话日志 | `/api/logs/{sid}` + `/api/logs/stream/{sid}`（doc 21） |

### 1.2 缺口（本文档覆盖）

1. **报告库无入口**：`/api/history`、`/api/reports/{name}`、`/api/reports/{name}/status` 全部已就绪，
   但前端只在"本次分析结束"时渲染一次报告，**历史报告/已落盘报告在 UI 上不可检索、不可重开**。
2. **审批工作流断在数据层**：doc 67 §3.2 说"未 approved 报告前端标'待人工确认'徽章"，
   但当前前端**没有徽章、没有批准/驳回按钮**——Web 审批接口没有消费方（CLI 有 `report --approve`，Web 无）。
3. **时间线未消费**：`/api/timeline/{name}` 就绪但 UI 无视图，竞品"变化轨迹"展示缺失。
4. **视觉为通用默认**：GitHub 系蓝色 + 无产品身份，与"数据管线化 + 产品化闭环"的叙事不匹配；
   无设计 tokens、无组件语言、无响应式策略（仅一个 760px 断点）。

### 1.3 根因链

```
前端只面向"单次分析"（无报告库/审批/时间线）   →  Web 审批接口无消费方
   →  报告产出即"死文件"（生成一次再也找不到）   →  产品化闭环缺最后一环（UI）
```

## 2. 设计（两个前端 skill 产出）

> 用 ui-ux-pro-max `--design-system`（Data-Dense Dashboard 风格，蓝/琥珀信号色 + 等宽数据字体，
> light/dark 双模式）+ frontend-design（主题 grounded：**情报分析台 / 案例档案**，
> signature = 盖章式审批徽章）。

### 2.1 设计 Tokens（`style.css` `:root`）

**色板（深色为主设计面，light 为回退）**：

| Token | 深色 | 用途 |
|-------|------|------|
| `--bg` | `#0A0E14` | 画布（比 GitHub 深，冷调墨） |
| `--surface` / `--surface-2` | `#10151F` / `#161D2A` | 面板 / 次级面 |
| `--border` / `--hairline` | `#232E40` / `#2A3850` | 边框 / 细分隔线 |
| `--text` / `--text-dim` / `--text-faint` | `#E6ECF5` / `#8FA2BC` / `#5C6F8C` | 正文 / 次级 / 弱化 |
| `--blue` | `#3B82F6` | 数据/激活（克制使用） |
| `--amber` | `#E2A13C` | 信号：待审批 / 警告 |
| `--red` | `#D64545` | 盖章红 / 危险（signature） |
| `--green` | `#3FB950` | 已批准 / 成功 |
| `--mono` | `Cascadia Code, ui-monospace, SFMono-Regular, Consolas, monospace` | 数据/标签/文件名 |

light 模式：纸面暖白 `#F7F8FA` + 同构语义色（复用现有 `prefers-color-scheme` 结构）。

**类型**：中文正文走系统栈（`PingFang SC` / `Microsoft YaHei`），数据/标签/眉题全部走等宽 `--mono`
（大写 + letter-spacing 眉题如 `INTEL · BRIEF`）。**不引外网字体**——离线/内网部署，保持自包含
（与 `report_visuals.render_html` 离线内嵌一致）。

**签名元素（Signature）**：报告档案卡上的**盖章式审批徽章**——旋转 2deg 的描边等宽徽章
（`待审批` 琥珀 / `已批准` 绿 / `已驳回` 红），辅以维度置信度条（SVG 内联），一眼认出"这是一份待审档案"。

### 2.2 布局：双栏 shell

```
┌─ shell ─────────────────────────────────────────────┐
│ rail(260px)          │ workspace                    │
│ ┌──────────────────┐ │ ┌──────────────────────────┐ │
│ │ INTEL · CASE FILE │ │ │ topbar: 会话标题 / 抽屉钮 │ │
│ │ [新建分析]         │ │ ├──────────────────────────┤ │
│ │ 报告库            │ │ │ messages（对话流）         │ │
│ │  · Cursor  ● 待审 │ │ │                          │ │
│ │  · Cline   ● 已批 │ │ │ dossier（报告档案卡）      │ │
│ │  · ...            │ │ │  · 盖章徽章 + 元信息       │ │
│ │ 运行中: Cursor…   │ │ │  · 置信度条 + 证据 chips   │ │
│ │                  │ │ │  · 操作栏(复制/下载/批准/驳)│ │
│ └──────────────────┘ │ │  · 变化时间线(可折叠)       │ │
│                      │ ├──────────────────────────┤ │
│                      │ │ composer（底部输入）       │ │
│                      │ └──────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

- 桌面：固定 rail + workspace；rail 可折叠（顶部按钮）。
- 移动（<900px）：rail 变抽屉，顶层遮罩，滑动进入。
- 报告库项 = 竞品名 + 状态点（待审/已批/已驳）+ 最近时间 + 置信度。

### 2.3 交互（`app.js` 扩展，流式引擎原样保留）

1. **实时分析**（现有）：`report` 事件 → 渲染档案卡 + 追加 `report_loaded` 到 rail 头部（含状态点）。
2. **报告库加载**（新增）：`GET /api/history` → 按竞品去重建 rail；点项 → `GET /api/reports/{name}` 取
   markdown → 渲染档案卡（`marked` + `DOMPurify` 同现有消毒链）。
3. **审批工作流**（新增）：档案卡渲染时 `GET /api/reports/{name}/status` → 盖章徽章；
   `批准`/`驳回`（驳回弹注原因）→ `POST /api/reports/{name}/review` → 盖章切换 + rail 状态点刷新。
4. **时间线**（新增）：档案卡"变化时间线"折叠区 → `GET /api/timeline/{name}` → 事件列表
   （type/date/summary，等宽时间戳）。
5. **可达性/响应式**：`:focus-visible` 焦点环、`prefers-reduced-motion` 关闭入场动效、
   按钮 ≥44px 命中区、无 emoji 图标（内联 SVG：+ 新建 / ⟳ 刷新 / ✕ 抽屉）、375/768/900/1440 断点。

### 2.4 约束（回归安全）

- `index.html` **必须保留** `id="send-btn"` / `id="new-btn"` 与 4 个静态/vendor 引用
  （`tests/unit/web/test_web_sse_events.py::TestStaticServing` 断言）。
- `static/` 下 `index.html` / `app.js` / `style.css` / `vendor/marked.min.js` / `vendor/dompurify.min.js` 五个文件必须存在。
- 后端零改动；SSE 事件协议（doc 63/64/66）不动。

## 3. 数据流

```
[实时分析]  /api/analyze(SSE) ── report 事件 ──▶ 档案卡渲染 + rail 头部插入
[报告库]    GET /api/history → rail 列表 → 点击 → GET /api/reports/{name} → 档案卡
[审批]      档案卡 GET /api/reports/{name}/status → 盖章
            POST /api/reports/{name}/review {action: approve|reject, note} → 盖章切换 + rail 刷新
[时间线]    档案卡 GET /api/timeline/{name} → 折叠事件列表
```

## 4. 验证方式

- **静态回归**：`tests/unit/web/test_web_sse_events.py::TestStaticServing` 全绿（index 引用 + 5 文件 + 200）。
- **JS 语法**：`node --check app.js`（本机 node v25）。
- **冒烟**：`python -m competitor_agent.web_app --port 8000` 起服，`curl /`、`/api/history`、`/api/reports/{name}/status` 200；
  手测：实时分析 → 档案卡 + 盖章；库项重开；批准/驳回状态切换；时间线展开。
- **后端回归**：全量 unit suite 绿（本次仅 static/ 变更，Python 零改动）。

## 5. 实现优先级与工作量

- 优先级：**高**（补齐产品化闭环的 UI 最后一环，与 doc 67 形成完整社招叙事）。
- 工作量：约 0.5-1 天（纯静态三件套）。
- 前置依赖：doc 67 已交付（审批接口/状态机），无新增依赖。

## 核心技术点总结

- **纯静态产品化**：不动后端，仅 `static/` 三件套把"对话页"升级为"情报档案台"——
  报告库（`/api/history` + `/api/reports/{name}`）、审批工作流（`/status` + `/review`）、
  时间线（`/api/timeline/{name}`）全部消费既有端点，产品化闭环补齐最后一环。
- **签名式视觉**：深色分析台 + 盖章式审批徽章（旋转描边等宽徽章 + 维度置信度条），
  数据字体/眉题等宽 mono、无外网字体（离线自包含）、light/dark 双模式。
- **可达性底线**：`:focus-visible`、`prefers-reduced-motion`、≥44px 命中区、内联 SVG 图标、4 断点响应式。
- **不引入假亮点**：所有新增 UI 动作都消费真实端点（审批按钮调真实 `/review`，驳回原因回灌 `reviewer_note`），
  空报告库/无时间线事件显式空态提示，不编造数据。
