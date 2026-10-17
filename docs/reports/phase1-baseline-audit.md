# Phase 1 验收报告：仓库治理与基线审计

目标不是扩展功能，是给 MingLi Agent V1.0 建立一个**可信的开发基线**：
弄清这个仓库到底是什么、四条分支之间什么关系、质量门禁现在真实处于什么状态，
然后把能低风险修的东西修掉，且每一处都有理由和验证证据。

**执行分支**：`hardening/mingli-v1`（基于 `f108040`）
**基线 HEAD**：`f10804064cbf1bb479a4d656751318ba9f103c2b`
**本报告状态**：Phase A / B / C 均已完成，验收见 §11。

---

## 1. 当前 HEAD 与执行环境

### 1.1 HEAD 与漂移检查

按要求先检查远端最新 HEAD 是否仍是 `f108040`。

| 项 | 值 |
|---|---|
| 本地 HEAD | `f10804064cbf1bb479a4d656751318ba9f103c2b` |
| 远端 `origin/master` | `f108040`（**同一提交，无漂移**） |
| 工作区 | 干净（`git status --porcelain` 为空） |
| stash | 空 |

**结论：远端未变化，不存在需要记录的差异，也未做任何覆盖性更新。**
后续所有操作都在 `f108040` 之上新建 `hardening/mingli-v1` 分支进行。

### 1.2 执行环境

按要求建立**隔离的 Python 3.12 环境**（放在仓库外，不污染工作区）：

| 项 | 值 |
|---|---|
| 解释器 | `/tmp/mingli-venv312/bin/python` → CPython 3.12.13 |
| 创建方式 | `python3.12 -m venv`，依赖用 `uv pip install` |
| 仓库根 | `/Users/admin/WorkBuddy AI/2026-10-09-13-03-55/agent-knowledge-os` |
| 网络出口 | Clash 代理 `127.0.0.1:7890`（`HTTPS_PROXY`/`HTTP_PROXY`） |

**环境重建过程中踩到两个坑，如实记录：**

1. **`pip install -r requirements.txt` 失败**（`OSError: EEXIST ... mkdir '.../pip-install-.../lunar-python_...'`）——
   沙箱的 `sitecustomize` shim 拦住了 pip 的临时目录创建。`lunar_python` 是 sdist 需要解包构建，正好撞上。
   改用 `uv pip install` 成功（uv 自己处理临时目录，不经 pip 那条路径）。
2. **`/tmp/mingli-venv312` 在会话中断后被沙箱清理**。本轮重启后重建了环境，
   并顺便用它验证了新写的 `requirements-dev.txt` 可用（见 §7）。这本身是个发现：
   **任何写在 `/tmp` 里的环境都不可跨会话依赖**，报告中的命令都能在干净机器上复现。

### 1.3 仓库规模（`git ls-files` 实测）

| 项 | 值 |
|---|---|
| 被跟踪文件总数 | 245 |
| 其中 `.py` | 181 |
| `tests/` 下测试函数 | 929 |
| 目录行数 | `tests` 14183 · `runtime` 8526 · `knowledge` 3309 · `agents` 2781 · `docs` 1930 · `scripts` 1606 · `engines` 1017 · `api` 667 · `static` 435 · `evaluation` 283 |

---

## 2. 仓库真实架构

### 2.1 一个仓库，两套系统

这是本次审计**最重要的结构性发现**。README 与 `pyproject.toml` 都把它描述成一套系统，
实际是两套几乎独立的系统共处：

| | MingLi Agent | CreatorOS / Personal Media OS |
|---|---|---|
| 定位 | 命理推理（确定性排盘 + 规则证据链） | 内容流水线（选题 → 产出 → 发布） |
| 核心目录 | `engines/` `knowledge/` `corpus/` `evaluation/` `api/` `static/` | `agents/`（11 个 CreatorOS agent）<br>`runtime/`（大半） `workflows/` |
| 关键文件 | `agents/mingli.py` `agents/prompt.py` `agents/llm.py`<br>`runtime/mingli_service.py` | `agents/base_agent.py` `agents/planner.py` `agents/x_workflow.py`…<br>`runtime/orchestrator.py`（9 阶段**串行**） |
| 状态 | 可运行：1027 测试通过、12 接口、30/30 评估 | 未评估（本轮只读审计，未跑其测试） |
| 依赖方向 | 不依赖 CreatorOS | 不依赖 MingLi |

`pyproject.toml` 的 `description` 至今仍写着 CreatorOS 的话（「把 EverOS、Arbiter、Obsidian 和 Codex 工作流连接起来」），
进一步说明**文档层面从未承认过这是两个项目**。这是风险 R2，见 §5。

### 2.2 MingLi 侧的运行时链路

```
BirthInput → SxtwlBaziProvider（排盘，sxtwl 2.0.7）
           → knowledge.facts.extract_facts（事实提取）
           → RuleRegistry.match（规则匹配，带条件追踪）
           → EvidenceBuilder（证据链 + 强度）
           → AnalystAgent（出稿）+ CriticAgent（契约审查）
           → api.server（12 个接口）/ static/index.html（单页 UI）
```

**贯穿全链路的三条设计红线**（审计中确认它们都有测试守着）：
1. 模型不算命盘，只解释证据 —— provider 接口刻意收窄成 `complete(request) -> str`
2. 不做预测 —— 输出结构信号与证据等级，禁用词表由契约层维护且评估器独立复算
3. 诚实留白 —— 无核验底本时拒绝录入规则，`coverage_status=base_only` 如实披露

### 2.3 引证体系（README 原一字未提，这是最大的文档缺失）

`corpus/canonical/` 下三个底本角色：`base`（《三命通會》卷八）、`collation`（同书异本）、`reserve`（《紫微斗數全書》卷一）。
配 Canonical Citation URN、两级哈希、五条加载期守卫与完整性自查。这是本项目最硬的差异化设计，
README 已在本轮之前补上，此处仅登记其存在与位置。

---

## 3. 旧模块依赖关系

用 AST 扫描全部被跟踪的 `.py`，按目录归类统计跨模块 import 边。

### 3.1 结论：两套系统在**文件层已经隔离**

| 方向 | import 边数 |
|---|---|
| MingLi → CreatorOS | **0** |
| CreatorOS → MingLi | **0** |

也就是说，**拆分在文件层面早已完成**，不需要删任何文件。

### 3.2 但包层有一处耦合：`agents/__init__.py` 是急切导入

```
agents/__init__.py → 无条件 import 全部 11 个 CreatorOS agent
```

Python 导入 `agents.mingli` 时会**先执行** `agents/__init__.py`。实测：

```
import agents.mingli
→ sys.modules 里多出 37 个非 MingLi 模块
（agents.analytics / agents.base_agent / agents.briefing / agents.coder / agents.content
  / agents.planner / runtime.orchestrator / runtime.aihot_bridge / workflows.* …）
```

**这解释了为什么 MingLi 的 API 服务会拉着整条内容流水线一起启动**，
也决定了 Phase 2 的拆分手段（见 §9）：正确做法是把 `__init__` 改成惰性，
**而不是**像 `mingli-split` 分支那样靠删除文件来拆（那违反本阶段硬性约束 2）。

另有 `runtime/orchestrator.py` 3 条边指向 CreatorOS，但它本身属于 CreatorOS 侧，不算耦合。

---

## 4. 历史 PR 差异分析

### 4.1 分支拓扑（三条线是**堆叠/平行**关系，不是超集）

```
a00c066（2026-10-04 共同分叉点）
   ├── origin/master ──────────────── f108040   （38 提交）
   ├── origin/mingli-split ────────── 90e1629   （领先 master 40 / 落后 38）
   ├── origin/multi-school-strategy-kernel  69c22c8   （领先 35 / 落后 38）
   └── origin/fix/mingli-four-regressions-20261008  cbf1923   （领先 37 / 落后 38）
```

`02c84fc` 是 `mingli-split` 与 `fix/` 的共同祖先，`69c22c8`（= PR #1 的 HEAD）
出现在 `fix/` 的历史里 —— **说明分支之间是堆叠关系**。

两个 PR 都是 `CONFLICTING`：

| PR | 方向 | 状态 | 内容 |
|---|---|---|---|
| #1 | `multi-school-strategy-kernel` → `master` | CONFLICTING | 新增多流派策略核、`engines/ziwei/`、Web UI、benchmarks（+6352 行，几乎不删） |
| #2 | `fix/mingli-four-regressions-20261008` → `mingli-split` | CONFLICTING | 删 CreatorOS 模块（−20239 行）+ 四项回归修复 |

### 4.2 PR #1 与现架构的关系

- **互补，不冲突**：多流派策略核、紫微引擎、Web UI 都是 master 上没有的能力。
- **但 `engines/ziwei/` 与现有 `SchoolRegistry` 的流派枚举是两套概念**，接入前需要先统一
  （master 的 `schools` 是命理流派，PR #1 的策略核是「同一流派内的取用策略」，名字撞了含义没撞）。
- **结论**：可作为 Phase 3 的候选输入，但**必须先解冲突再逐项评审**，不整体合入。

### 4.3 PR #2 与现架构的关系（重点：它修的东西 master 上没有）

逐项核对 PR #2 里四个回归修复的代码在 master 中是否存在：

| PR #2 的修复对象 | master 中是否存在 |
|---|---|
| `liu_month_contexts`（流月） | **不存在**（`git grep` 无命中） |
| `engines/bazi/event_window.py` | **不存在** |
| `branch_relation` | **不存在** |
| `api/server.py` 的 `year` 边界 | 代码在，但**问题在 master 中同样存在**（见 §4.4） |

**结论：PR #2 是对另一条线（基于 `mingli-split`）的修复，与 master 基本无关。**
它的价值不在补丁本身，而在它**独立地发现了同一个 API 边界缺陷** —— 两条线的人都撞到了
`year` 无约束这一问题，说明这是真问题而不是某条线的偶发。

另外发现：`mingli-split` 上的 `6c0b229` 与 `fix/` 上的 `cbf1923` **标题完全相同**，
但 `git patch-id` 不同 —— 同一个修复在两条分叉上各做了一遍，实现不同。这是重复劳动的直接证据。

### 4.4 PR #2 触发的边界探测 → Phase C 的失败用例来源

按「对当前明显缺少限制的 API 参数编写失败用例」的要求，先实测 master 的真实行为
（`TestClient` 直连，`raise_server_exceptions=False`）：

| 输入 | 状态码 | `detail` 内容 | 契约是否满足 |
|---|---|---|---|
| `year=0` / `-1` / `10000` | 422 | `出生日期时间无效：year 0 is out of range` | ✗ 中文前缀 + Python 内部英文混排 |
| `question=""` | 422 | `string_too_short`（pydantic 原始英文） | ✗ |
| `month=0` / `day=32` / `hour=24` | 422 | pydantic 原始英文 | ✗ |
| `question="   "` | 422 | `问题不能为空。` | ✓ |
| `gender="其他"` | 422 | `gender 只能是 男、女…` | ✓ |

**发现**：`api/server.py` 文档字符串承诺错误 `detail` 是「可直接展示给用户的中文说明」，
但 pydantic 层校验失败时返回的是英文技术消息。**文档契约与实际行为不符**。
这正是 Phase C 要落失败用例的地方（§7.4）。

---

## 5. 风险清单和优先级

| 编号 | 风险 | 优先级 | 依据 | 本阶段处置 |
|---|---|---|---|---|
| **R1** | `mypy .` 有 **4 个既有错误**（`engines/bazi/golden.py:44`、`sxtwl_provider.py:65/66/122`） | **P0** | §6 实测 exit=1 | 已登记清单；CI 设为非阻塞并写明清零路径（§7.2）。**未修**——修类型错误会碰 `engines/` 业务代码，超出本阶段「低风险配置与文档修复」范围 |
| **R2** | 仓库身份认知错误：README/pyproject 把一个两系统仓库描述成一套系统 | **P0** | §2.1 | README 已在本轮之前重写修正；`pyproject.toml` 的 description **仍未改**（§8.2） |
| **R3** | `agents/__init__.py` 急切导入 → MingLi 启动连带 37 个 CreatorOS 模块 | **P1** | §3.2 实测 | 已记录拆分方案（§9），**未改代码**（属业务行为变更） |
| **R4** | `ruff`/`mypy` 在 `pyproject.toml` 配了却**未在任何依赖清单声明** | **P1** | §6.3 | **已修**：新增 `requirements-dev.txt`，CI 改为安装它（§7.3） |
| **R5** | `remote.origin.fetch` 只跟踪 master，其他分支拿不到跟踪引用 | **P1** | §4 实测 `+refs/heads/master:...` | 已记录；**未改配置**（改 fetch refspec 影响后续所有 fetch 行为，需老板确认，§8.3） |
| **R6** | API 边界参数无约束，错误消息违反自身文档契约 | **P1** | §4.4 实测 | **已加失败用例**（2 条 xfail strict），未改业务校验逻辑（§7.4） |
| **R7** | 三个开放 PR 全部 CONFLICTING，且 PR #2 与 master 基本无关 | **P2** | §4 | 已书面记录差异；**未合并、未关闭**（硬性约束 3） |
| **R8** | `mingli-split` 分支靠**删除** CreatorOS 拆分，违反硬性约束 2 | **P2** | §4.2 | 已记录；该分支不作为拆分方案来源 |
| **R9** | 我此前对外声明的「mypy 3 errors」是错的 | **P1** | §6.3 | **已修正** README 数字；根因与教训写进 §6.3，这是本阶段最该记住的一条 |

**R9 单独说明，因为它不是代码缺陷而是我的测量错误**：
之前我一直跑 `mypy knowledge agents runtime api evaluation`（**不含 `engines/`**），
而 `engines/bazi/golden.py` 不被被检查集合里任何模块 import，于是被静默漏掉。
README 与多条提交信息据此写了「3 errors 全在未改动的 sxtwl_provider.py」。
全量 `mypy .` 实测是 **5 errors in 3 files**（含我自己写的 `scripts/atom_checklist.py:194`），
修掉我那个之后是 **4 errors in 2 files**。
教训：**子集调用会静默漏检，声明的数字必须由与被声明命令完全等价的跑法得出。**

---

## 6. 实际执行的测试命令与退出码

环境：`/tmp/mingli-venv312`（Python 3.12.13，非仓库内 `.venv`）。
四条命令的执行形式与任务要求**完全等价**（`mypy .` / `ruff check .` 均在仓库根下执行）。

### 6.1 汇总

| # | 命令 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | `python -m pytest tests/ -q` | **0** | `1027 passed, 2 xfailed in 229.94s` |
| 2 | `python evaluation/runner.py --json` | **0** | `{"total":30,"passed":30,"failed":0,"accuracy":1.0}` |
| 3 | `ruff check .` | **0** | `All checks passed!` |
| 4 | `mypy .` | **1** | `Found 4 errors in 2 files (checked 108 source files)` |

**没有任何一条被跳过或当作通过。** 命令 4 的失败原因与处置见 §6.2。

### 6.2 命令 4 的 4 个错误（全部既有，均在 `engines/bazi/`）

```
engines/bazi/golden.py:44:            Incompatible types in assignment
                                     (expression has type "Any | None",
                                      variable has type "list[dict[str, str]]")
engines/bazi/sxtwl_provider.py:65:    "object" has no attribute "tg"
engines/bazi/sxtwl_provider.py:66:    "object" has no attribute "dz"
engines/bazi/sxtwl_provider.py:122:   Item "None" of "timedelta | None"
                                     has no attribute "total_seconds"
```

归因（`git log --diff-filter=A`）：

| 文件 | 引入提交 | 性质 |
|---|---|---|
| `engines/bazi/golden.py` | `17269cd`（2026-10-04） | 金标准案例数据加载，`Any` 来源未收窄 |
| `engines/bazi/sxtwl_provider.py` | `27b22ca` | sxtwl C 扩展无类型存根，`tg`/`dz` 推断为 `object`；`timedelta` 可空未判 |

**处置方案（明确，不含「以后再说」）**：
1. `sxtwl_provider.py:65/66` —— 加 `cast(GanZhi, ...)` 或 `assert ... is not None`，把 C 扩展返回值收窄；
2. `sxtwl_provider.py:122` —— 对可空 `timedelta` 判空后取 `.total_seconds()`；
3. `golden.py:44` —— 给案例数据加显式类型标注，不要靠推断。
三条都是**纯类型收窄，不改运行行为**，可配一条「修完后行为不变」的对拍测试。
属 Phase 2 第一批，工作量估计半小时以内。

### 6.3 执行过程中三个必须如实记录的插曲

1. **`exit=2` 的假警报**：本阶段早期我曾用 `mypy --config-file=... <仓库绝对路径>`（cwd 在 `/tmp`）跑，
   得到 `exit=2` 与 `Source file found twice under different module names`（`scripts/create_aihot_review.py`）。
   **从仓库根跑 `mypy .` 没有这个问题。** 原因是 mypy 的模块根取 cwd，
   把仓库当绝对路径传进来与「在仓库根跑 `.`」不等价。已在 §7.2 的 CI 配置中按仓库根写死 `working-directory`。
   这条插曲的教训：**调用方式不等价时，两次结果不可比。**
2. **`pip install` 被沙箱拦**（§1.2 已记），改用 `uv pip`。
3. **`/tmp/mingli-venv312` 被沙箱清理后重建**，并用重建的环境反向验证了 `requirements-dev.txt` 可用。

---

## 7. 文件变更和原因

### 7.1 变更清单

| 文件 | 动作 | 行数 | 原因 |
|---|---|---|---|
| `AGENTS.md` | **新增** | 135 | 根目录缺少给 agent/新人的入口说明。写清两套系统的边界、三条设计红线、常用命令，以及「`mypy` 必须用 `mypy .`」这一条踩过坑的教训 |
| `.github/workflows/ci.yml` | **新增** | 70 | 无任何 CI。按基线四条命令配置，门禁语义与本地一致 |
| `requirements-dev.txt` | **新增** | 17 | 修 R4：`ruff`/`mypy` 配了却没声明为依赖，新克隆后装不到 |
| `tests/test_api_boundaries.py` | **新增** | 168 | 按 Phase C 要求为缺少限制的 API 参数写失败用例 |
| `scripts/atom_checklist.py` | **改** | +7/−6 | 修 mypy 错误：`day` 变量被复用（前半是 `datetime.date`，后半在解包里当 `int`），重命名为 `cursor` |
| `README.md` | **改** | +4/−1 | 修正 mypy 数字（3 → 4，且写明是 `mypy .`）；补 `requirements-dev.txt` 安装步骤 |

**未新增文档目录下的模块拆分方案文件** —— 拆分方案写在本报告 §9，不另立文件，
避免同一件事两处维护（`docs/` 已有 1930 行，再加一份拆分方案只会加速腐烂）。

### 7.2 `AGENTS.md` 写了什么

四节：仓库构成（两套系统 + 各自目录）、三条设计红线（模型不算命盘 / 不做预测 / 诚实留白）、
常用命令、以及一段专门的「已知坑」。最后这段是本文件最实用的部分，包含：

- `mypy` 要用 `mypy .`，**不能用文件子集** —— 子集会静默漏掉不在依赖图上的文件（R9 的根因）
- 以仓库目录为 cwd 会被 SIGTERM（本机沙箱特性）
- localhost 的 curl 会被 Clash 拦成 502，要加 `--noproxy '*'`
- 终端推 GitHub 必须显式设 `HTTPS_PROXY`
- 每个新典籍原子要同步动四处

### 7.3 `.github/workflows/ci.yml` 的关键决策

```
pytest tests/ -q          → 阻塞（exit code 门禁）
evaluation/runner.py      → 阻塞
ruff check .              → 阻塞
mypy .                    → **非阻塞**（continue-on-error）
```

**mypy 为什么非阻塞而不是修成阻塞**：基线有 4 个既有错误，设成阻塞会让 CI 从第一天起就是红的，
而「永远红的门禁等于没有门禁」。`continue-on-error` 让它在界面上仍可见、可点开看差异，
同时不阻塞合并。注释里写明了清单（`golden.py:44`、`sxtwl_provider.py:65/66/122`）与清零后的翻转方法。

**另一个决策**：CI 安装 `requirements-dev.txt` 而不是在 workflow 里裸装 `ruff==x mypy==y`。
后者是 R4 的延续 —— 把版本钉在 CI 文件里，仓库外又有一份真相。

### 7.4 `tests/test_api_boundaries.py` 的设计

按「对当前明显缺少限制的 API 参数编写失败用例」写，分成两类：

**绿的（当前就该守住，5 条）**：越界输入必须返回 422 而不是 500，
覆盖 `year=0/-1/10000/999999999`、`month=0`、`day=32`、`hour=24`、`question=""`、
`question="\t\n"`、`gender="其他"`，并断言失败主题不波及其他（`/api/analyze/multi` 的故障隔离）。

**xfail(strict) 的（记录当前不成立，2 条）**：
- `test_error_detail_is_always_a_chinese_string` —— 承诺 `detail` 是中文说明，实际 pydantic 给英文
- `test_year_is_constrained_at_the_request_model` —— `year` 未声明 `ge/le`，越界靠 `datetime()` 抛错后再包装，消息混了英文内部信息

**为什么用 `xfail(strict=True)` 而不是红着或删掉**：红着会让套件永远红（同 §7.3 的理由）；
删掉等于隐瞒已知问题。`strict=True` 保证它**修好后会自动变 XPASS 并报错**，提醒有人回来翻这条用例。
这是把「已知缺陷」变成「有人修就会响的闹钟」，而不是一段烂在注释里的说明。

---

## 8. 尚未解决的问题

1. **`mypy .` 的 4 个既有错误未修**（R1）。属 `engines/` 业务代码，超出本阶段「低风险配置与文档修复」范围。
   处置方案已写进 §6.2，工作量估计半小时以内，建议作 Phase 2 第一件事。
2. **`pyproject.toml` 的 `description` 仍写着 CreatorOS 的话**（「把 EverOS、Arbiter、Obsidian 和 Codex
   工作流连接起来」）。改它风险为零但会影响打包元数据与任何按 description 检索的索引，
   且它是否仍是 CreatorOS 项目的归属声明需要老板确认，故未擅改。
3. **`remote.origin.fetch` 只跟踪 master**（R5）。改它的收益是 `git fetch` 能直接拿到其他分支的跟踪引用；
   代价是改变后续所有 fetch 的行为（`--prune` 语义也会跟着变）。这是仓库级配置变更，需老板确认后再动。
   本阶段用显式 refspec 绕开，未改配置。
4. **CreatorOS 侧的测试与质量状态未知**。本轮只跑了 MingLi 的 `tests/`（含 CreatorOS 导入路径的间接覆盖），
   没有单独评估 CreatorOS。老板若要求「整个仓库可运行」，需要单独一轮。
5. **PR #1 / #2 未处置**（硬性约束 3）：未合并、未关闭、未评审到可合入程度。冲突原因已定位
   （平行分叉 + 共享 `__init__`），解法见 §9。
6. **`tests/` 与 `scripts/` 缺 `__init__.py`**。本阶段实测从仓库根跑 `mypy .` 不受影响，
   但如果有人在子目录或用绝对路径跑就会撞上 §6.3 那个 `exit=2`。加 `__init__.py` 是零风险变更，
   但会改变 pytest 的 import 模式，需要单独一轮验证，故未在本阶段顺手做。
7. **`docs/reports/` 此前不存在**，历史报告散在仓库根（`PHASE0..6_REPORT.md` 共 7 个）。
   本轮未移动它们（移动 = 改 16 个 README 引用，属中风险），仅把新报告放进新目录。
   建议下一轮统一归档。

---

## 9. 下一阶段建议

### 9.1 Phase 2 第一批：清零 mypy（最小、最该先做）

按 §6.2 的三条方案改 `engines/bazi/`，改完在 CI 里把 mypy 从 `continue-on-error` 翻成阻塞。
**这一项做完，四条基线命令全部 exit 0，才算真正「基线干净」。**

### 9.2 Phase 2 第二批：拆包，但**不删文件**

约束 2 排除「删除 CreatorOS」，所以 `mingli-split` 那条路不能走。正确做法：

1. 把 `agents/__init__.py` 改成惰性（`__getattr__` 延迟导入），
   使 `import agents.mingli` 不再连带 37 个模块；
2. 用一条测试钉住这件事：断言 `import agents.mingli` 后 `sys.modules` 里
   没有 `agents.planner` / `runtime.orchestrator` / `workflows.*`；
3. 文件一个都不动，只是让导入变成「用时才拉」。

第 2 步是关键 —— 没有它，第 1 步随时可能被无意回退，而**没有任何测试会响**。

### 9.3 Phase 2 第三批：给三个 PR 一个明确结论

按 §4 的分析，建议：
- **PR #2**：核心修复在 master 中无对应代码，可关闭并在描述里指向 §4.3 的核对结果；
  唯一可移植的是 `year` 边界问题，但已由 §7.4 的失败用例覆盖，不需要它的补丁。
- **PR #1**：有真实增量（多流派策略核、紫微引擎），但需先解冲突，且 `engines/ziwei/`
  与 `SchoolRegistry` 的命名撞车要先统一。建议拆成「先统一流派命名」和「再接入」两步，
  由老板决定是否值得投入。
- **`mingli-split`**：作为「曾经试过的拆分思路」保留，但其删除式手法不应采用。

### 9.4 Phase 3+

CreatorOS 单独评估（§8.4）、PR #1 增量接入、API 边界契约修好（把 §7.4 两条 xfail 转绿）。
**在这些之前，不建议动任何排盘算法、规则语义、证据计算与公开 API 契约** ——
本阶段一行都没碰，希望保持到 mypy 清零之后。

---

## 10. 回滚方式

### 10.1 本阶段改动的回滚

一切都在 `hardening/mingli-v1` 分支上，`master` 未被触碰（未合并、未强推、未 reset）。
三种回滚路径，按需选：

**路径 A —— 整个分支作废（最干净）**：
```bash
git checkout master
git branch -D hardening/mingli-v1     # 删除本地分支，不动任何远程
```

**路径 B —— 只回滚部分文件**：
```bash
git checkout hardening/mingli-v1
git checkout master -- README.md scripts/atom_checklist.py   # 还原这两个已跟踪文件的修改
rm -f AGENTS.md requirements-dev.txt tests/test_api_boundaries.py
rm -rf .github docs/reports                                  # 移除全部新增文件
```

**路径 C —— 保留文件但撤销内容**：`git revert` 对应的提交即可（提交后再做，见下）。

### 10.2 每条改动的独立回滚

| 改动 | 回滚动作 | 回滚后影响 |
|---|---|---|
| `AGENTS.md` | `rm` | 无代码影响 |
| `requirements-dev.txt` | `rm` | CI 会回到装不到 ruff/mypy 的状态（R4 复现） |
| `.github/workflows/ci.yml` | `rm -rf .github` | 回到无 CI 状态；不影响本地任何命令 |
| `tests/test_api_boundaries.py` | `rm` | 5 条绿的边界用例 + 2 条 xfail 消失；**API 行为不变**（该文件只做断言，不改产品代码） |
| `scripts/atom_checklist.py` | `git checkout master -- scripts/atom_checklist.py` | 恢复 `mypy .` 报 5 errors（含我这一个）；`atom_checklist` 功能不变（纯重命名） |
| `README.md` | `git checkout master -- README.md` | mypy 数字回到错误的「3 errors」 |

### 10.3 需要特别说明的一点

**本阶段没有任何改动修改产品运行行为。** 六个变更里：四个是新增文件（不影响现有导入路径）、
一个是诊断脚本内的局部变量重命名、一个是文档数字修正。
`tests/test_api_boundaries.py` 新增了 2 条 xfail，它们在 `pytest -q` 汇总里显示为 `2 xfailed`
而不是 `passed`，**不会让任何既有测试的结果发生变化** —— 基线 1022 passed → 现在 1027 passed，
多出的 5 条全部来自新文件，零既有失败。

---

## 11. Phase 1 验收对账

| 验收条件 | 状态 | 证据 |
|---|---|---|
| 原有测试无新增失败 | ✅ | 基线 `1022 passed, exit=0` → 现在 `1027 passed, 2 xfailed, exit=0`。5 条新增全绿，2 条按设计 xfail；零失败、零既有测试被跳过 |
| Ruff 没有新增错误 | ✅ | `ruff check .` → exit=0，`All checks passed!`（基线与现在一致） |
| mypy 错误有明确处置方案 | ✅ | 4 个既有错误的逐行归因与三条修改方案见 §6.2；我自己引入的第 5 个已修（`scripts/atom_checklist.py` 的变量重命名） |
| 当前分支和历史 PR 的差异有书面记录 | ✅ | §4：分支拓扑、`patch-id` 比对、四项修复在 master 中的存在性逐项核对 |
| 每个变更都有理由和验证证据 | ✅ | §7.1 逐文件给原因；§6 给四条命令的退出码；§7.4 说明 xfail 的设计取舍 |
| 输出 Git diff 与变更文件清单 | ✅ | §7.1 表格 + 下方 §12 完整清单 |
| 不向 master 合并，不自动推送 | ✅ | `master` 仍指向 `f108040`，与 `origin/master` 一致；`hardening/mingli-v1` 仅存在于本地，**未推送** |
| 硬性约束 1–7 逐条 | ✅ | 未碰 master/`mingli-split`；未删任何模块；未合 PR；未改排盘/规则/证据/API 契约；未改无关业务代码；未伪造任何测试通过或环境配置；不同分支的结果未混用（§6 全在隔离 3.12 环境单次跑出） |

**唯一未达成的验收项**：`mypy .` 不是 exit 0。这是**有意识的边界选择** ——
修它要改 `engines/` 业务代码，超出「仅实施低风险、可验证的配置与文档修复」。
方案已写明、工作量已估、CI 已留好翻转开关。Phase 1 可以验收通过，条件是 **Phase 2 第一件事就是清零 mypy**。

---

## 12. Git diff 与变更文件清单

### 12.1 已跟踪文件的修改（`git diff --stat`）

```
 README.md                 |  5 ++++-     修正 mypy 数字；补 requirements-dev.txt 安装步骤
 scripts/atom_checklist.py | 13 ++++++++--- 修 mypy：day 变量复用，重命名为 cursor
 2 files changed, 12 insertions(+), 6 deletions(-)
```

`scripts/atom_checklist.py` 的实际改动（唯一一处代码变更）：

```diff
-    day = start
-    while day < end and len(found) < want * 8:
-        chart = PROVIDER.calculate(BirthInput(day.year, day.month, day.day, 0))
+    # 扫描游标叫 ``cursor`` 而不是 ``day``：下面解包候选时 ``day`` 是**日号整数**，
+    # 同名复用会让 mypy 报「int 赋给 date」——那是真会看错的地方，改名字而不是
+    # 加 type: ignore。
+    cursor = start
+    while cursor < end and len(found) < want * 8:
+        chart = PROVIDER.calculate(BirthInput(cursor.year, cursor.month, cursor.day, 0))
         got = {match.rule.id for match in registry.match(extract_facts(chart))}
         if rule_id in got:
             facts = group_facts(extract_facts(chart))
             extra = tuple(sorted(same_group & got - {rule_id}))
-            found.append((len(extra), (day.year, day.month, day.day, 0), extra,
+            found.append((len(extra), (cursor.year, cursor.month, cursor.day, 0), extra,
                           (facts.get("month_pillar"), facts.get("day_pillar"))))
-        day += dt.timedelta(days=1)
+        cursor += dt.timedelta(days=1)
```

选它而不是加 `# type: ignore`：`day` 在前半段是 `datetime.date`、后半段解包里是日号整数，
同名复用是真会看错的地方，压掉报警只会让下一个人继续看错。

### 12.2 新增文件（此前均未被跟踪）

```
 AGENTS.md                          135 行
 requirements-dev.txt                17 行
 tests/test_api_boundaries.py       168 行
 .github/workflows/ci.yml            70 行
 docs/reports/phase1-baseline-audit.md   本文件
```

### 12.3 未触碰的内容（明确声明）

- `master` 与 `origin/master`：仍为 `f108040`，未合并、未重置、未强推
- `mingli-split`、`multi-school-strategy-kernel`、`fix/mingli-four-regressions-20261008`：未检出、未合并、未删除
- PR #1 / PR #2：未合并、未关闭、未评论
- `engines/` `knowledge/` `api/` `runtime/mingli_service.py` `agents/mingli.py`：**零改动**
- CreatorOS / EverOS / 自媒体模块：**零删除、零移动**
- 未接入新模型、未增加命理规则、未开发新前端框架


