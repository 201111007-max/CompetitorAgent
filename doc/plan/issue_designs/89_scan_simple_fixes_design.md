# 设计文档 89 —— 第三十九轮：/scan 简单项修复（CI dev 依赖锁定 + 断网测试隔离 + 备份恢复文档）

> 第三十九轮。来源：`doc/tech_review_2026-09-12.md`（全量 /scan 评审）中**无需用户决策**
> 的简单项——本文档覆盖三项：评审 #3（CI dev 环境依赖锁定）、评审 #7（断网环境测试
> 家族失败 → 网络依赖测试显式标记 + 无网自动 skip）、评审 #10（数据备份/恢复命令进
> deployment.md）。
>
> **明确非目标（需用户决策或已有 ADR，本文档不做）**：
> - 评审 #4（双引擎收敛）——**doc 86 ADR 已决策保留双引擎**，评审时未知该 ADR 存在，
>   此项撤销，不再列为问题。
> - 评审 #8（fallback_models 空）——fallback 模型名取决于用户可用的模型端点与成本
>   偏好，属用户决策，不在本轮。
> - 评审 #9（evals/golden 位置）——**doc 76 有意设计**（仓库根人工维护区，断言集与
>   代码资产解耦），非缺陷，撤销。
> - Docker 镜像依赖锁定——镜像三 target 各装不同 extras 组合，锁定工程量 ×3，且
>   CI 对镜像只做 build 验证不发布（doc 55 Q4），漂移风险低，列为后续项。
> - 评审 #1/#2/#5/#6——P0/P1 主项，需专项设计与用户输入，另行立项。
>
> **实施修正（与本文档原始表述的差异，以代码为准，2026-09-12）**：
> ① §2 断网复跑实测 20 failed，根因实为**两类**而非一类——11 个是真网络依赖
> （url_guard SSRF 防护做**直接 DNS 解析**，不经 http 代理；trafilatura 可用性探测
> 触网），9 个（test_session_archive_vectors 全家）是**时间炸弹测试**：硬编码
> 2026-08-01/08-10 会话日期 vs 30 天 TTL 惰性老化，2026-09-09 起套件必红（含 CI），
> 与网络无关——commit 907a8f1 把整族误归为"断网环境性"。前者按原方案打 network 标记，
> 后者改为相对日期（`_days_ago`）修复，此项从"测试基建"升级为**真实 bug 修复**。
> ② 探针由 urllib HTTP 探测改为 `socket.getaddrinfo`——标记家族的真实依赖是直接 DNS
> 解析，代理环境 HTTP 可用但 DNS 不直连时用例仍失败，探针必须测 DNS。
> ③ 其余文件（test_report_visuals/test_scheduler/test_timeline_memory 等 7 个）也含
> 2026-07/08 硬编码日期，当前未爆（不与 TTL 路径交互），列为 P2 审计项，见评审文档。
> ④ lock 按 pypi.org 解析；内部镜像（mirrors.tools.huawei.com）版本滞后会导致
> `pip install -r` 缺版——本机/内部环境消费 lock 需 `-i https://pypi.org/simple`，
> CI（GitHub runner 默认 pypi.org）不受影响。本机验证到 dry-run 可解析为止
> （避免 pin 升降级冲击当前在用的测试环境），真实安装由 CI 首跑验收。

---

## 1. 评审 #3：CI dev 环境依赖锁定

### 1.1 问题现状

`pyproject.toml` 全部依赖为 `>=` 区间，仓库无任何 lock 文件。CI（ruff/mypy/pytest/
benchmark gate）每次 `pip install -e ".[dev]"` 解析到的依赖树随上游发布漂移——
今天绿明天红，且无法回答"哪次依赖升级导致退化"。

### 1.2 方案

- 用 `uv pip compile` 生成 **pip 兼容**的 lock 文件 `competitor_agent/requirements-dev.lock`
  （main + `dev` extra；`--universal` 跨 Python 3.10/3.11/3.12 生效，匹配 CI 矩阵）。
- CI 安装步骤改为：
  ```
  pip install -r competitor_agent/requirements-dev.lock
  pip install -e competitor_agent --no-deps
  ```
  （lock 只钉第三方依赖；包自身仍 editable 安装，`--no-deps` 防止 pip 重新解析区间
  覆盖 lock。）
- lock 刷新为**显式动作**：文档记录刷新命令（uv 可用环境执行），依赖要升级时人为主动
  重新生成并走 PR，CI 漂移从此可见可归因。
- 不引入 uv 作为 CI 依赖：lock 是纯 pip 格式，`pip install -r` 即可消费。

### 1.3 验收

- `requirements-dev.lock` 入库；CI 安装步骤引用它。
- 本地 `pip install -r requirements-dev.lock && pip install -e . --no-deps` 后
  `pytest -q`（有网）全绿，ruff/mypy 版本与 lock 一致。

## 2. 评审 #7：断网测试隔离

### 2.1 问题现状

commit 907a8f1 记录断网沙箱全量重跑 19 failed（"环境性家族"）——套件内存在依赖真实
网络的用例，无网环境（新机器/离线沙箱）全红，且失败与真实回归无法区分。

### 2.2 方案

- `pyproject.toml` markers 增加 `network: 需要真实网络的用例（无网自动 skip）`。
- `tests/conftest.py` 增加 autouse 机制：对打了 `network` 标记的用例，运行前做一次
  轻量网络探测（连 `pypi.org:443`，超时 2s，结果会话级缓存），不可达则
  `pytest.skip("无网络环境")`。
- 标记来源：用 `unshare -n`（网络命名空间隔离）跑全量套件，把实际失败的用例家族
  逐一打上 `network` 标记（**以实测失败清单为准，不凭猜测标记**）。

### 2.3 验收

- `unshare -n python -m pytest -q` 全绿（skip 不计 fail）。
- 有网 `pytest -q` 无新增 skip 家族（标记只落在真实依赖网络的用例上）。

## 3. 评审 #10：备份/恢复命令进 deployment.md

### 3.1 问题现状

四层记忆、知识库向量、报告归档、traces 全部落盘 `~/.competitor_agent`（或容器卷
`competitor-data`），`docs/deployment.md` §5 只写了"删卷即清空"，无任何备份/恢复
路径——误删即丢全部历史与评测基线。

### 3.2 方案

deployment.md §5 增补一小节，给出两条可直接执行的命令：
- 本机：`tar czf competitor-agent-backup-$(date +%F).tar.gz -C ~ .competitor_agent`
  及对应恢复命令；
- Docker 卷：用一次性 alpine 容器把 `competitor-data` 卷打包到宿主当前目录的标准做法
  （`docker run --rm -v competitor-data:/data -v $PWD:/backup alpine tar czf /backup/...`）
  及恢复命令。
- 一行 cron 示例（可选），明确"个人项目手动即可，无需备份系统"。

### 3.3 验收

- deployment.md §5 含本机与 Docker 两条备份 + 两条恢复命令，命令可直接复制执行。

---

## 4. 实施顺序

1. §2 断网隔离（先跑 `unshare -n` 拿实测失败清单 → 打标记 → 双环境验证）。
2. §1 依赖锁定（生成 lock → 改 CI → 本地按 lock 重装验证全量测试）。
3. §3 文档增补。
4. 回写 `doc/tech_review_2026-09-12.md`：#3/#7/#10 标记已修，#4/#9 标注撤销原因
   （ADR 86 / doc 76）。

## 5. 风险权衡

- lock 过期僵化：接受——个人项目依赖少，刷新命令文档化，漂移可控优于最新。
- `--universal` lock 在边缘平台（非 linux x86_64）可能含不适用标记：CI 与开发机均为
  linux，接受。
- 网络探测误伤（有网但 pypi 不可达）：探测目标选 pypi.org 是因为测试依赖安装即来自
  pypi；若探测失败但个别用例实际可达其他站点，最坏结果多 skip 几个用例，可接受，
  且探测仅作用于显式打了 network 标记的用例。

> **实施修正⑤（2026-09-12，CI 首跑发现）**：初版 lock 在本机 3.11 下编译，
> `--universal` 未产生 python_version 分叉——websockets==17.1（requires>=3.11，
> uvicorn 间接依赖）在 CI 3.10 job 安装步骤即失败（c628a5c run 34677573363 红，
> 3.11/3.12 fail-fast 被取消）。修正：重生成时加 `--python-version 3.10` 声明矩阵
> 下限，uv 正确分叉 `websockets==16.1.1 ; python_full_version < '3.11'` +
> `17.1 ; >= '3.11'`；全量 71 项复查无其他 3.10 不兼容（httpx2-jsfetch 仅
> emscripten 标记，CI CPython 不安装）。教训：universal lock 的"universal"以
> `--python-version` 声明为准，不声明则按编译解释器解析。

> **实施修正⑥（2026-09-14，用户拍板）**：`-n auto` 从 CI 命令行迁入 pyproject
> `addopts`——当初"addopts 有意不动"的顾虑（未装 xdist 环境全灭）已不成立：
> xdist 在 dev lock 内（CI/本机均装）；另实测发现本机长期无 xdist 的真因是
> 华为内网镜像无该包（`from versions: none`），需 `-i https://pypi.org/simple`
> 安装。本机 tests/unit 并行实测 95s→28s（3.4×）。
