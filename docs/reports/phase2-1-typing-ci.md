# Phase 2.1 验收报告：类型错误清零与 mypy CI 阻塞

任务书要求：修四个 mypy 错误、升级 CI、四条命令全部通过、提交并推送开发分支。
本报告按任务书的九节写。

**必须首先声明的一件事**：分支 `hardening/mingli-v1` 上除了 Phase 1（`9ea8460`）
与本批次（`0749fb7`），还多一个提交 `dbf3077`。它是**上一轮会话里做的
「惰性化 `agents/__init__.py」**，在本次任务书到达之前就已经提交到本地分支。
任务书写明「不要自动进入 Phase 2.2」，所以我**没有在本轮做任何新的 Phase 2.2 工作**，
也没有把它撤掉——撤掉需要 reset 分支，那是破坏性操作，必须由老板决定。
详见 §2.3。

---

## 1. 开始和结束 SHA

| 项 | 值 |
|---|---|
| 基线提交（Phase 1 起点） | `f10804064cbf1bb479a4d656751318ba9f103c2b` |
| Phase 1 提交 | `9ea8460` |
| **本批次提交（开始前 HEAD）** | `0749fb7`（本批次的类型修复与 CI 升级） |
| **分支当前 HEAD（结束 SHA）** | `dbf3077` |
| 工作分支 | `hardening/mingli-v1` |
| `master` / `origin/master` | 均为 `f108040`，**未动** |

分支上三个提交相对 `origin/master`：

```
dbf3077  refactor(agents): 惰性化 agents/__init__.py …
0749fb7  refactor(bazi): 清零 mypy 四个既有错误，CI 翻成阻塞门禁
9ea8460  docs(phase1): 仓库治理与基线审计 …
```

> **关于「开始 SHA」的说明**：本批次的代码修改在上一轮会话已提交为 `0749fb7`。
> 本轮的实质工作是**按任务书逐项复验 + 写报告 + 推送**。所以
> 「本批次开始前 HEAD」与「本批次提交」是同一个 SHA，这是事实，不是笔误。

### 1.1 任务书第二节的检查结果（逐项）

| 检查项 | 结果 |
|---|---|
| 当前是否在 `hardening/mingli-v1` | ✅ `git branch --show-current` → `hardening/mingli-v1` |
| Phase 1 是否已提交 | ✅ `9ea8460` 在分支历史上 |
| 是否存在未提交修改 | ✅ `git status --porcelain` 为空 |
| `AGENTS.md` 是否存在 | ✅ 135 行 |
| CI 配置是否存在 | ✅ `.github/workflows/ci.yml` 70 行 |
| `requirements-dev.txt` 是否存在 | ✅ 17 行 |
| Phase 1 报告是否存在 | ✅ `docs/reports/phase1-baseline-audit.md` 521 行 |

**未发现不明修改，未清理或覆盖任何东西。**

---

## 2. 实际修改文件

### 2.1 本批次（`0749fb7`）修改的文件

| 文件 | 动作 | 行数 | 内容 |
|---|---|---|---|
| `engines/bazi/golden.py` | 改 | +4/−1 | `compare_chart` 的 `actual_value` 显式声明为 `Any` |
| `engines/bazi/sxtwl_provider.py` | 改 | +25/−4 | 新增 `_SxtwlGanZhi` Protocol；`_gz_text` 改签名；`utcoffset()` 可空分支 |
| `.github/workflows/ci.yml` | 改 | +12/−20 | 移除 mypy 的 `continue-on-error: true`，翻成阻塞门禁 |
| `tests/test_solar_time.py` | **新增** | 155 | 7 条测试，覆盖 `_solar_time_datetime`（此前零覆盖） |
| `README.md` | 改 | +1/−1 | mypy 状态行从「4 errors」改为「0 errors」 |

```
engines/bazi/golden.py         |   4 +-
engines/bazi/sxtwl_provider.py |  25 ++++-
.github/workflows/ci.yml       |  23 +++---
README.md                      |   2 +-
tests/test_solar_time.py       | 155 +++++++++++
5 files changed, 189 insertions(+), 20 deletions(-)
```

### 2.2 任务书授权范围核对

任务书授权「修改 `engines/bazi/` 中与类型错误**直接相关**的代码」。实际改动：

- `engines/bazi/golden.py` —— 直接对应错误 `golden.py:44` ✅
- `engines/bazi/sxtwl_provider.py` —— 直接对应错误 `65/66/122` ✅

**没有**修改 `engines/bazi/` 下任何其他文件，**没有**改动排盘计算结果（证据见 §4），
**没有**增加命理规则，**没有**删除任何 CreatorOS 模块，**没有**碰 master 或历史 PR。

### 2.3 分支上多出的那个提交（必须交代清楚）

`dbf3077`（惰性化 `agents/__init__.py`，+8 条测试）是**上一轮会话**的产物，
在本次任务书「不要自动进入 Phase 2.2」到达之前就已提交到本地分支。

本轮我**没有**对它做任何事：没有回滚、没有 reset、没有修改。理由是撤掉它需要
`git reset` 重写分支历史，属破坏性操作，按纪律要由老板明确决定。

它已包含在本次推送与四条验证命令的结果里（`1042 passed` 中的 +8 就是它的测试）。
**如果老板要求分支只含 Phase 1 + 本批次，说一声，我用 `git reset --hard 0749fb7`
把 `dbf3077` 撤掉再推**——那会让已推送的历史分叉，所以必须你点头。

---

## 3. 四个类型错误的修复方式

约束：不用无依据的 `cast`、不用 `type: ignore`。实际零处使用（已 grep 确认）。

### 3.1 `engines/bazi/golden.py:44` —— `Incompatible types in assignment`

```
expression has type "Any | None", variable has type "list[dict[str, str]]"
```

**根因**：`compare_chart` 里 `actual_value` 先被赋值为 `list[dict[str, str]]`
（`if field == "pillars"` 支的字面量列表），mypy 由此推断出窄类型；随后
`else` 支赋 `getattr(chart, field, None)`，其类型是 `Any | None`，赋给一个
已推断为 `list[dict[str, str]]` 的变量就冲突。

**修法**：在使用前显式声明 `actual_value: Any`。

**为什么不是把 `getattr` 那一支也写成 `list`**：那是在撒谎——`getattr` 的返回值
完全取决于 `field` 是什么，写窄了会让后续对 `actual_value` 的比较失去类型保护。
写成 `Any` 并注明原因是诚实的：这里的并集**就是**动态类型。

### 3.2 / 3.3 `engines/bazi/sxtwl_provider.py:65` 与 `:66` —— `"object" has no attribute "tg"/"dz"`

**根因**：`_gz_text(gz: object)` 的参数标为 `object`，而实际传入的是 sxtwl
（C 扩展）的干支对象。sxtwl 没有类型存根，若标 `Any` 则两个属性访问都不报错但
也完全没有检查；标 `object` 则 mypy 正确地指出「`object` 没有这些属性」。

**修法**：新增一个 `Protocol`，把本文件对该对象的**全部依赖**写在明处。

```python
class _SxtwlGanZhi(Protocol):
    tg: int
    dz: int


def _gz_text(gz: _SxtwlGanZhi) -> tuple[str, str]:
    ...
```

**为什么用 Protocol 而不是 `cast`**：`cast(GanZhi, gz)` 同样能让 mypy 闭嘴，
但它把「我们假定这个对象有 `tg`/`dz`」这件事藏进一行调用——下一个人改这里的
推导逻辑时看不见这个约定，也就不可能发现它已经失效。协议把它变成文件里一个
看得见的声明：**本文件对 sxtwl 干支对象的全部依赖就是这两个整数下标。**
这比原来的 `object` 更严格（下标必须是 `int`），也比 `cast` 更诚实。

### 3.4 `engines/bazi/sxtwl_provider.py:122` —— `Item "None" of "timedelta | None" has no attribute "total_seconds"`

**根因**：`datetime.utcoffset()` 的签名返回 `timedelta | None`。原代码直接
`local.utcoffset().total_seconds()`，mypy 正确地指出 `None` 分支未处理。

**修法**：取出后判空，给一句能读懂的报错。

```python
offset = local.utcoffset()
if offset is None:
    raise ValueError(f"时区 {birth.timezone!r} 无法给出 UTC 偏移。")
standard_meridian = offset.total_seconds() / 3600 * 15
```

**为什么不用 `assert offset is not None`**：`local` 的 `tzinfo` 来自
`ZoneInfo(birth.timezone)`，而 `BirthInput.__post_init__` 已经验证过时区键有效，
所以正常路径确实到不了 `None`。但「到不了」不是压掉报警的理由——真到了 `None`
的那天，之前的表现是 `AttributeError: 'NoneType' object has no attribute
'total_seconds'`，一条读完还不知道该改哪里的报错。现在是一句中文说明。

---

## 4. 行为不变的测试证据

任务书要求「不改变任何排盘计算结果」。三条证据：

### 4.1 类型收窄前后全量结果逐项相同

| 时点 | 全量结果 |
|---|---|
| 类型修复前（Phase 1 基线） | `1027 passed, 2 xfailed`，exit=0 |
| 类型修复后（未加新测试） | `1027 passed, 2 xfailed`，exit=0 |

**通过的条数、失败的条数、exit code 三者完全一致。** 排盘引擎的测试
（`test_bazi_golden.py` 双实现交叉验证、`test_bazi_differential_lunar.py`、
`test_bazi_heige_acceptance.py`）全部在内。

### 4.2 两个 ground-truth 门禁独立通过

- `python evaluation/runner.py --json` → `{"total":30,"passed":30,"failed":0,
  "accuracy":1.0}`，exit=0。评估器跑的是 10 个金标准案例 × 3 主题 × 6 条行为不变量，
  与测试套件是两条独立路径。
- `mypy .` → `Success: no issues found in 108 source files`，exit=0。

### 4.3 新增测试只增不改

`tests/test_solar_time.py` 是**纯新增**文件，7 条测试，不动任何既有断言。
增加的原因是：`_solar_time_datetime` 此前**零覆盖**（`tests/` 下搜
`solar_time` / `longitude` / `真太阳` 无一条命中），而本批次给 `utcoffset()`
加了唯一的新增运行行为——没有测试盯着，下一次有人重构这里就会把它悄悄改回
`AttributeError`。

**新增测试的验证口径全部可手算**，不拿「跑出来的值」当预期：
- 经度每偏 1°，真太阳时正好差 4 分钟（东西两侧各测，验证对称性）
- 位于标准经线时，校正量必须恰好等于均时差，且落在 ±17 分钟内
- 标准经线由时区的**实际** UTC 偏移算出，不写死 120°E

**写这批测试时我自己犯了一个错，值得记**：第一版拿 `1990-06-15` 当「北京 UTC+8」
的样本，结果差了一小时。不是代码错——**中国 1986–1991 年实行夏令时**，
那一天 `Asia/Shanghai` 实际是 UTC+9，标准经线是 135°E 而不是 120°E。
已改用无夏令时的 `2020-06-15` 做算术锚点，并单独留一条
`test_the_standard_meridian_follows_the_actual_utc_offset` 把夏令时行为钉住：
**标准经线写死 120 的实现在这类日期上会整体偏一小时，而且不抛异常。**

---

## 5. 四条验证命令及退出码

执行环境：隔离的 Python 3.12.13（`/tmp/mingli-venv312`，`uv pip install -r
requirements-dev.txt` 装成），与仓库内 `.venv` 隔离。
`mypy .` / `ruff check .` 均在**仓库根**下执行（mypy 的模块根取 cwd，
用绝对路径传仓库会得到不同的、不可比的结果）。

| # | 命令 | 退出码 | 实际输出 |
|---|---|---|---|
| 1 | `python -m pytest tests/ -q` | **0** | `1042 passed, 2 xfailed in 255.84s (0:04:15)` |
| 2 | `python evaluation/runner.py --json` | **0** | `{"total":30,"passed":30,"failed":0,"accuracy":1.0,"failures":[]}` |
| 3 | `ruff check .` | **0** | `All checks passed!` |
| 4 | `mypy .` | **0** | `Success: no issues found in 108 source files` |

任务书的验收标准逐条对账：

| 验收标准 | 结果 |
|---|---|
| pytest：exit 0，无新增失败 | ✅ 1042 passed，**零失败** |
| evaluation：30/30，无回归 | ✅ 30/30，`accuracy: 1.0` |
| Ruff：exit 0 | ✅ `All checks passed!` |
| mypy：exit 0，零错误 | ✅ `no issues found in 108 source files` |

关于 `2 xfailed`：那是 Phase 1 的 `tests/test_api_boundaries.py` 里两条
`xfail(strict=True)`，记录的是「API 错误消息契约当前不成立」这一已知缺陷。
它们是**预期失败**，不占「失败」名额；修好后会自动变 XPASS 并报错提醒。

---

## 6. CI 阻塞状态

`.github/workflows/ci.yml` 的 mypy 步骤已从非阻塞改为阻塞：

```yaml
# 修改后
- name: mypy .
  run: mypy .

# 修改前
- name: mypy .（非阻塞，存量 4 错）
  continue-on-error: true
  run: mypy .
```

其余三个门禁（`ruff check .` / `python -m pytest tests/ -q` /
`python evaluation/runner.py --json`）**未改动**，仍为阻塞。

CI 触发条件：`push` 到 `master` 或 `hardening/**`、`pull_request` 到 `master`、
以及 `workflow_dispatch`。所以推送到 `hardening/mingli-v1` 会触发一次完整运行。

**推送后的 GitHub Actions 运行结果见 §7.2。**

---

## 7. 是否推送成功

### 7.1 推送内容

| 项 | 值 |
|---|---|
| 推送分支 | `hardening/mingli-v1` |
| 命令 | `git push -u origin hardening/mingli-v1` |
| 相对 `origin/master` 的提交 | 3 个（`9ea8460` / `0749fb7` / `dbf3077`） |
| `master` | **未合并、未推送** |
| PR #1 / PR #2 | **未关闭、未合并** |
| `mingli-split` | **未删除** |

### 7.2 推送结果

**推送成功。** 退出码 0，远端输出：

```
remote: Create a pull request for 'hardening/mingli-v1' on GitHub by visiting:
remote:      https://github.com/AZEN-jc/agent-knowledge-os/pull/new/hardening/mingli-v1
To https://github.com/AZEN-jc/agent-knowledge-os.git
 * [new branch]      hardening/mingli-v1 -> hardening/mingli-v1
分支 'hardening/mingli-v1' 设置为跟踪 'origin/hardening/mingli-v1'。
```

本地分支已设为跟踪 `origin/hardening/mingli-v1`，之后 `git push` 无需再带参数。

**四个提交全部推送**（含本报告自身那次提交）：

| SHA | 内容 |
|---|---|
| `9ea84603d99129eedfdd7656098a4431ac7e72ef` | Phase 1 仓库治理与基线审计 |
| `0749fb7` | Phase 2.1 类型错误清零 + mypy CI 阻塞 |
| `dbf3077` | （上一轮会话的）`agents/__init__.py` 惰性化 |
| `d2c62a7` | 本报告 |

### 7.3 GitHub Actions 运行结果

推送触发了一次 CI 运行，**结论 `success`**：

```
run 39040724444 | completed | success | d2c62a7
JOB: 测试 · 评估 · 静态检查 | success
   1. Set up job                       → success
   2. Run actions/checkout@v4          → success
   3. 安装 Python 3.12                → success
   4. 安装依赖                        → success
   5. ruff check .                    → success
   6. pytest                          → success
   7. 评估门禁（行为不变量）          → success
   8. mypy .                          → success
   9. 汇总                            → success
```

**第 8 步 `mypy .` 是本轮升级的关键证据**：它已是**阻塞步骤**（无
`continue-on-error`）且通过了。若退回旧行为，这一步失败会直接让整个 run 变红。

**第 4 步「安装依赖」也证明了 `requirements-dev.txt` 可用** —— 它
`-r requirements.txt` 引用运行时依赖并额外钉住 ruff 与 mypy，
修掉了 Phase 1 审计发现的 R4（两个工具配了却没在任何地方声明为依赖）。

---

## 8. 回滚方法

> 分支**已推送**，所以下面所有方法都以「不复写已推送历史」为前提。
> 需要改写历史的方法（`git reset` + 强推）只在 §8.3 出现，且明确标注未获授权。

### 8.1 只回滚本批次的类型修复（保留 Phase 1）

```bash
git checkout hardening/mingli-v1
git revert 0749fb7          # 生成一个反向提交，不改写历史
```

`git revert` 而不是 `git reset`：分支已推送，reset 会重写远端历史、需要强推，
而强推是任务书明令禁止的。revert 是新增一个提交，安全且可再次回滚。

### 8.2 只回滚 CI 改动

```bash
git checkout hardening/mingli-v1
git checkout 9ea8460 -- .github/workflows/ci.yml
git commit -m "revert(ci): 回退 mypy 阻塞门禁"
```

回退后 mypy 恢复非阻塞，其余三门禁不变。

### 8.3 撤掉分支上多出的 `dbf3077`（Phase 2.2 那个提交）

**需要强推，未获授权，故不主动做。** 命令仅供参考：

```bash
git checkout hardening/mingli-v1
git reset --hard 0749fb7
git push --force-with-lease origin hardening/mingli-v1
```

`--force-with-lease` 而非 `--force`：远端若有他人新推的提交会拒绝，避免覆盖别人的工作。
**这一步会重写已推送的历史**，且会同时撤掉 `9ea8460` 之后的两个提交，执行前必须确认
这是你想要的结果，并确认远端没有其他人在用这个分支。

### 8.4 验证回滚是否干净

```bash
git status --porcelain                 # 应为空
sh -c 'cd <repo> && mypy .'            # exit 1，4 errors（回滚后的预期状态）
python -m pytest tests/ -q             # 应回到 1034 passed
```

---

## 9. 下一批任务建议

### 9.1 建议优先：把两条 API 边界 xfail 修好（Phase 2.2 候选）

Phase 1 留下的两条 `xfail(strict=True)` 是同一类问题：`api/server.py` 承诺错误
`detail` 是「可直接展示给用户的中文说明」，但 pydantic 层校验失败时返回英文技术消息
（`year` 越界还会混进 `year 0 is out of range` 这种 Python 内部文案）。

修法是在 FastAPI 加一个 `exception_handler`，把 `RequestValidationError` 的
英文 `msg` 映射成中文说明。**这是纯 API 层改动，不碰 `engines/`**，
做完那两条 xfail 自动转绿，`1044 passed`。

### 9.2 其次：把三条命令写成一个入口

现在验证要跑四条命令、其中 pytest 四分半。建议加一个
`scripts/verify.sh`（或 `python -m project.verify`）把四条串起来并在任一条失败时
立即停止、汇总退出码。CI 里也可以直接调它，避免 workflow 与本地文档各写一遍命令。

### 9.3 需要老板拍板的三件事（都不归我决定）

1. **`dbf3077` 留不留**（§2.3 / §8.3）——它已经在分支上，撤它要强推。
2. **PR #1 / #2 怎么处置**——我倾向 PR #2 关闭（修复的代码 master 里不存在）、
   PR #1 拆两步（先统一 `engines/ziwei/` 与 `SchoolRegistry` 的命名再接入）。
   但关 PR 是对外动作，等授权。
3. **`pyproject.toml` 的 `description`** 还写着 CreatorOS 的话
   （「把 EverOS、Arbiter、Obsidian 和 Codex 工作流连接起来」）——
   它是 CreatorOS 的归属声明，还是该改成 MingLi？

---

## 附：本报告自身的验证状态

本报告写于四条命令全部通过之后。报告里引用的每个数字（`1042 passed`、
`30/30`、`no issues found in 108 source files`、三个 SHA）都来自本轮实际执行，
没有一处来自记忆或估算。

