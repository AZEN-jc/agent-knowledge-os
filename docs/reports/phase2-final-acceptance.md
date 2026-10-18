# Phase 2 总验收报告：质量基线

任务书授权范围：**只做 Phase 2 剩余部分**（2.1 复核、2.2 惰性导入验收、
2.3 API 边界治理、2.4 工程一致性、2.5 总验收），不进入 Phase 3。

**执行分支**：`hardening/mingli-v1`
**起始 SHA**：`f11be100a89cb72b040faaf3d5557b2a8a1bd173`（Phase 2.1 时的 HEAD）
**结束 SHA**：见 §7

---

## 1. 起始与结束 SHA

| 项 | 值 |
|---|---|
| 基线（Phase 2.1 起点） | `f10804064cbf1bb479a4d656751318ba9f103c2b` |
| Phase 2.1 起点 HEAD | `f11be10` |
| **Phase 2 结束 HEAD** | `21518a5` |
| `master` / `origin/master` | `f108040`，**全程未动** |

本轮三个提交：

```
21518a5  docs(phase2): 工程一致性——依赖清单、模块边界与本地 git 配置
0616855  feat(api): API 边界治理，两条 strict xfail 转正；补 2.2 惰性导入验收缺口
0749fb7  refactor(bazi): 清零 mypy 四个既有错误，CI 翻成阻塞门禁   ← 上一轮已推
```

`0749fb7` 是上一轮（Phase 2.1）完成的，本轮按任务书 §2.1 只做**复核**，
没有重复实现 —— 复核结果见 §2。

---

## 2. 2.1 复核已完成部分

任务书要求复核 mypy 修复、CI 阻塞配置与远端 CI 结果，**不重复实现**。
复核方式：在当前 HEAD 上重跑四条命令 + 读 CI 运行明细。

| 复核项 | 结果 |
|---|---|
| `mypy .` | exit **0**，`no issues found in 108 source files` |
| CI 的 mypy 步骤 | 已无 `continue-on-error`，是阻塞步骤 |
| 远端 CI（`f11be10`） | run `39041653405` → **success**，四个门禁逐步 success |
| 四个错误是否真的修了 | 是。`golden.py:44` 用显式 `Any`；`sxtwl_provider.py:65/66` 用 `_SxtwlGanZhi` Protocol；`:122` 对可空 `utcoffset()` 判空 |
| 有没有用 `type: ignore` / `cast` 掩盖 | grep 确认**零处** |

**一处需要更正的记录**：`AGENTS.md` 此前写着「当前 `mypy .` 有 4 个存量错误，
CI 里它是不阻塞项」。这句在 `0749fb7` 之后就已过期，本轮已改为
「Phase 2.1 已清零，当前 exit 0，CI 里是阻塞门禁」。

---

## 3. 2.2 惰性导入验收（`dbf3077`）

用**独立子进程**验证五项。全部通过：

| 验收项 | 测试 | 结果 |
|---|---|---|
| ① `import agents.mingli` 不加载无关 CreatorOS 模块 | `test_importing_mingli_does_not_pull_in_creatoros`<br>`test_importing_the_birth_engine_does_not_pull_in_creatoros` | ✅ 实测连带 **0** 个（改动前 37 个） |
| ② CreatorOS 原有公开导入方式继续工作 | `test_exported_names_still_resolve_to_the_right_classes`<br>`test_each_export_lands_in_the_module_it_belongs_to` | ✅ 11 个导出全部解析为真正的类，`__module__` 逐一对上 |
| ③ 模块重复导入无异常 | `test_repeated_imports_are_harmless`<br>`test_submodule_import_before_and_after_package_attribute` | ✅ 含「先子模块后包属性」与反向两种顺序 |
| ④ 不引入循环依赖 | `test_the_package_does_not_introduce_a_circular_import` | ✅ 14 个模块逐个独立导入 |
| ⑤ 不改变 MingLi 输出 | `test_lazy_import_does_not_change_mingli_output` | ✅ 子进程跑完整分析，日主/证据链/强度/结论/审查五项与预期一致 |

**原有测试缺 ③④⑤ 三项**，本轮补齐。③ 之所以重要：`__getattr__` 每次触发都会
`import_module`，只有 import 系统的缓存在生效时才不会重复执行模块体 ——
这个缓存是否真在生效，必须有测试盯着。

④ 防的是未来：`agents/__init__.py` 现在不导入任何子模块所以不可能成环，
但谁加一行普通 import 就可能让 `agents.X → agents → agents.X` 成环，
而症状是「只在某些入口下才崩」，极难定位。

`tests/test_agents_package_isolation.py` 共 **12 条**。

---

## 4. 2.3 API 边界治理

### 4.1 修好的契约缺口

`api/server.py` 的模块 docstring 早就写着「`detail` 为可直接展示给用户的
中文说明」，但 pydantic 在请求模型层拦下的错误原样返回**英文技术消息的 dict
列表**。状态码那一半一直对，`detail` 那一半不成立。

新增 `on_validation_error`（`RequestValidationError` 处理器）把错误翻成中文，
配一张可复核的映射表 `FIELD_LABELS` + `ERROR_TEMPLATES`（约 20 种 pydantic
错误类型）。

实测前后的差别：

| 输入 | 之前 | 现在 |
|---|---|---|
| `year=10000` | `[{"loc":[…],"msg":"Input should be less than or equal to 9999",…}]`（英文 + dict 列表） | `公历年不能大于9997` |
| `question=""` | `string_too_short` | `问题长度不足（至少1个字符）` |
| 多余字段 `foo` | `Extra inputs are not permitted` | `foo不是可填的字段` |
| 重复主题 | 无校验，重复分析两遍 | `主题重复：事业` |
| 时间轴跨 76 年 | 无校验，服务端循环 76 次 | `起始年与结束年最多相差 50 年…请分段查询` |

pydantic v2 会给自定义 validator 的消息加 `Value error, ` 前缀，
处理器里剥掉了 —— 那是给开发者看的类型标注，不该出现在给用户的文本里。

### 4.2 新增的输入约束（全部实测后定，不是常识）

| 参数 | 约束 | 依据 |
|---|---|---|
| `year` / `start_year` / `end_year` | `ge=2, le=9997` | 全量扫 1–9999 |
| `question` | max 200 字 | 问句不需要一篇作文 |
| 主题名 | max 20 字 | 主题是「事业」「财运」这类短词 |
| `topics` 条数 | max 8，且拒绝重复 | 线程池硬顶同值 |
| 时间轴跨度 | 起止最多相差 50 年 | 更长应分段 |
| 查询参数（school/category/…） | max 64 字 | 同上 |
| `timezone` / `gender` | max 64 / 16 字 | 同上 |
| 服务层 `ThreadPoolExecutor` | `MAX_ANALYSIS_WORKERS = 8` 硬顶 | API 拦不住直接调用方 |

### 4.3 **本轮最重要的发现：引擎支持范围不是我写的那个**

第一版 `year` 我按常识填了 `ge=1, le=9999`，**两条都错**：

```
year=1      → "year 0 is out of range"
year=9998   → "year 10000 is out of range"
year=9999   → "year 10000 is out of range"
```

是我自己写的「边界内年份应可用」那条测试逮到的（`9999` 返回 422）。
全量扫 1–9999 后确认：

- **真实可用区间是 2–9997**
- 另有个失败年夹在区间中部：**899–901 与 999–1001**（共 6 年，与月日无关），
  报的是误导性的 `"day is out of range for month"` —— 而 2 月 1 日明明合法

中间那 6 个放不进 `ge`/`le`，由 `_to_user_message` 包一层中文框架
（`排盘失败：day is out of range for month`）。**引擎的原始英文消息保留
在框架后面**而不是藏掉：排查时需要它，隐瞒内部错误比显示它更难查。

**根因留给 Phase 3.1「排盘边界与独立基准验证」。** 本测试不假装它不存在，
只钉住「对外不出现裸英文」这一条。

→ 教训写进了 `AGENTS.md`：**收边界的默认值必须扫出来，不能按常识填。**

### 4.4 两条 strict xfail 按设计报警并转正

Phase 1 留下的两条 `xfail(strict=True)` 在修复完成后变成了
`XPASS(strict)` 并**报错**——这正是当初写 `strict=True` 的目的：
修好了必须有人回来删标记，否则它就一直挂着。

现已转为正常测试，并把「曾经是 xfail」的历史写进 docstring：
删掉 `on_validation_error` 的人会让它们重新变红。

**全量结果里的 `2 xfailed` 已清零**：Phase 2 起点是 `1042 passed, 2 xfailed`，
现在是 `1066 passed`，零 xfail。

### 4.5 一处我自己的测试写错，也记下来

第一版「空白主题」断言 422，实际是 **200 + `ok=false` + 中文原因** ——
`analyze_multi` 的契约本就是故障隔离（「单个主题失败不影响其余，
失败项以 ok=false 如实带回原因」）。是我读错了契约。

已改成断言真实契约，并把「为什么不是 422」写进 docstring，
免得下一个人再改错方向。

---

## 5. 2.4 工程一致性

### 5.1 依赖清单：两份一致，但发现三个零 import 的包

`requirements.txt` 与 `pyproject` 的 `[project.dependencies]` **逐项一致**
（含版本约束）—— 这条已经是对的，无需修。

但 AST 扫全仓（含 `tests/`）发现三个包**没有任何文件 import**：
`everos`、`python-dotenv`、`rich`。

**没有删。** 删依赖是破坏性变更，且 `everos` 可能服务于尚未接线的
CreatorOS 功能（任务书硬性约束含「不删除 CreatorOS」）。改为在
`requirements.txt` 末尾**登记**，并加测试防止静默增长。

新增 `tests/test_dependency_declaration.py` 6 条，钉四件事：

1. 两份运行时清单逐项一致（含版本约束）
2. `ruff` / `mypy` 必须在 dev 清单里且钉版本（审计报告 §5 的 R4）
3. dev 清单必须 `-r requirements.txt` 而不是重抄一份
4. **声明 = 被 import，或登记在 `DECLARED_BUT_UNUSED` 里并写明理由**

第 4 条是重点：没有约束时，「加一个依赖但没人 import」没有任何测试会发现，
清单会越积越长，而每一条都是新克隆时的一次下载和一个潜在安全面。

**反向也钉了**：登记为「未使用」的包其实已被 import 时，测试报警 ——
谁给 CreatorOS 接上了 `everos`，会有人提醒他删登记。

测试里踩了个自己的坑：依赖名用连字符（`lunar-python`）、import 用下划线
（`lunar_python`），且 `python-dotenv` 的模块名是 `dotenv`。不统一口径就会
报出一堆假阳性。已加 `MODULE_TO_DISTRIBUTION` 映射与 `_canonical()`。

### 5.2 模块边界写进 AGENTS.md

把 Phase 1 的实测结论固化成文档，三个层面都写清：

- **导入层**：MingLi ↔ CreatorOS 双向 **0 条**
- **包层**：`agents/__init__.py` 已惰性化，实测连带 **37 → 0**
- **依赖层**：MingLi 只用 `sxtwl` / `fastapi` / `uvicorn` / `pydantic`

并明确警告：`agents/__init__.py` 不要再改回急切导入；要加导出名请加进
`_EXPORTS` 表 —— `tests/test_agents_package_isolation.py` 会红。

同时把 `AGENTS.md` 里那句已过期的「当前 mypy 有 4 个存量错误、CI 里是
非阻塞项」改成了实际状态。

### 5.3 `remote.origin.fetch` 改为全分支跟踪

这是 Phase 1 记为 R5 的坑：`fetch` 只跟踪 `master`，推送新分支后
`git rev-parse origin/<branch>` 报「需要一个单独的版本」，而分支其实已在远端。
**Phase 2.1 真的被骗过一次。**

```bash
git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
```

改后 `git fetch --prune` 自动建全部 5 个分支的跟踪引用，
`origin/hardening/mingli-v1` 直接可查（返回 `f11be10`）。

**这是本机 `.git/config`，未进仓库代码**（任务书明确要求），
只把坑和修法写进 `AGENTS.md` §8。

### 5.4 README

「已知边界」补两条硬事实：年份支持范围 2–9997 + 6 个中部失败年。
新增「输入上限」表，把 API 约束作为**公开契约**列出，
并说明「错误消息一律是中文」由哪个处理器保证、由哪条测试钉住。

---

## 6. 四条质量门禁实测

执行环境：隔离的 Python 3.12.13（`/tmp/mingli-venv312`）。
`ruff .` / `mypy .` 均在**仓库根**下执行（mypy 的模块根取 cwd，
用绝对路径传仓库会得到不同的、不可比的结果）。

| # | 命令 | 退出码 | 输出 |
|---|---|---|---|
| 1 | `python -m pytest tests/ -q` | **0** | `1066 passed in 293.29s (0:04:53)` |
| 2 | `python evaluation/runner.py --json` | **0** | `{"total":30,"passed":30,"failed":0,"accuracy":1.0,"failures":[]}` |
| 3 | `ruff check .` | **0** | `All checks passed!` |
| 4 | `mypy .` | **0** | `Success: no issues found in 108 source files` |

**四条全部 exit 0，零失败、零 xfail、零 skipped 计入通过。**

对比 Phase 2 起点（`f11be10` 时，即 Phase 2.1 完成后）：

| 指标 | Phase 2 起点 | 现在 |
|---|---|---|
| pytest | 1042 passed, **2 xfailed** | **1066 passed, 0 xfailed** |
| 新增测试 | — | +24（`test_api_boundaries` +8、`test_agents_package_isolation` +4、`test_dependency_declaration` +6、`test_concurrent_analysis` +3、`test_solar_time` +7 中归属本轮的部分） |
| mypy | 0 errors | 0 errors |
| ruff | 干净 | 干净 |
| evaluation | 30/30 | 30/30 |

---

## 7. 文件变更与原因

### 7.1 本轮变更清单

| 文件 | 动作 | 行数 | 原因 |
|---|---|---|---|
| `api/server.py` | 改 | +289/−55 | 中文错误处理器、字段约束、模型级 validator、引擎错误包装 |
| `runtime/mingli_service.py` | 改 | +14/−4 | `ThreadPoolExecutor` 加 `MAX_ANALYSIS_WORKERS` 硬顶 |
| `tests/test_api_boundaries.py` | 改 | +222/−55 | 两条 xfail 转正 + 新增 8 条治理用例 |
| `tests/test_agents_package_isolation.py` | 改 | +99 | 补 2.2 缺的三项（重复导入 / 循环依赖 / 输出不变） |
| `tests/test_concurrent_analysis.py` | 改 | +90 | 线程池硬顶的三条测试（真观测 `max_workers`） |
| `tests/test_dependency_declaration.py` | **新增** | 185 | 依赖声明一致性与未使用登记 |
| `AGENTS.md` | 改 | +68 | 模块边界、API 边界口径、本地 git 配置、mypy 状态更正 |
| `README.md` | 改 | +20 | 已知边界补年份范围；新增「输入上限」公开契约表 |
| `requirements.txt` | 改 | +20 | 登记三个零 import 的依赖 |

```
 api/server.py                          | 289 ++++++++++++++++++++++++++++++---
 runtime/mingli_service.py              |  14 +-
 tests/test_agents_package_isolation.py |  99 ++++++++++
 tests/test_api_boundaries.py           | 222 +++++++++++++++++++++-----
 tests/test_concurrent_analysis.py      |  90 ++++++++++
 tests/test_dependency_declaration.py  | 185 +++++++++++++++++++
 AGENTS.md                              |  68 ++++++++--
 README.md                              |  20 +++
 requirements.txt                       |  20 ++++-
```

### 7.2 关键技术决策

1. **`year` 边界扫出来而不是按常识填。** 第一版 `ge=1, le=9999` 两条都错，
   是全量扫 1–9999 后才定下 2–9997。这是本轮最重要的方法论收获。
2. **引擎的英文原文保留在中文框架后面**（`排盘失败：day is out of range for
   month`）而不是藏掉。隐瞒内部错误比显示它更难查。
3. **重复主题明确拒绝而非静默去重。** 去重之后调用方不会知道自已少问了
   一个，那份意图就无声消失了。
4. **`xfail(strict=True)` 转正而不是删除。** 它按设计报了 XPASS，
   逼人回来更新；删标记的同时把「曾经是 xfail」写进 docstring，
   让删处理器的人重新踩红。
5. **线程池测试真的观测 `max_workers`**（用记录构造参数的壳包住
   `ThreadPoolExecutor`），而不是只断言两个常量相等 ——
   后者证明不了 `min()` 真的生效。
6. **未使用的依赖登记而非删除。** 删依赖是破坏性变更且涉 CreatorOS 归属，
   但必须写明，否则没有任何测试会发觉清单在变长。

---

## 8. 已知问题与回归风险

1. **引擎在 6 个年份上失败（899–901、999–1001）**，根因在
   `engines/bazi` 的节气换算，报的是误导性的
   `"day is out of range for month"`。属 **Phase 3.1「排盘边界与独立基准
   验证」**的首要对象。当前只保证对外包了中文框架，**没有修根因**。
2. **三个依赖零 import 但仍在清单里**（`everos` / `python-dotenv` / `rich`）。
   待确认 CreatorOS 是否真需要它们；确认后可删。
3. **`pyproject.toml` 的 `description` 仍写着 CreatorOS 的话**
   （「把 EverOS、Arbiter、Obsidian 和 Codex 工作流连接起来」）。
   它是 CreatorOS 的归属声明还是该改成 MingLi，**需要老板拍板**。
4. **PR #1 / PR #2 仍未处置**（任务书禁止自动合并/关闭）。分析见
   `docs/reports/phase1-baseline-audit.md` §4：PR #2 的核心修复在 master 里
   没有对应代码，唯一共通的 `year` 边界问题已被本轮覆盖。
5. **回归风险低**：本轮改动的运行时行为只有两处 —— 输入约束变严
   （原会 200 的极端输入现在 422）与线程池封顶。两者都有测试钉住，
   且 `analyze_period` / `analyze` / `analyze_multi` 的正常路径结果未变
   （1066 passed 里含全部既有测试）。

---

## 9. 未完成工作

按任务书，以下**明确不在 Phase 2 范围内**，未做：

1. **Phase 3 全部**（3.1 排盘边界与独立基准验证、3.2 事实提取审计、
   3.3 规则匹配与冲突治理、3.4 典籍底本与异文校勘、3.5 证据链与强度算法、
   3.6 流年大运流月边界、3.7 差分/变异/独立评估、3.8 多流派与紫微 RFC）。
2. **Phase 4 全部**（真 LLM provider 接入、Schema 约束、Prompt 版本管理、
   Critic 独立审查、provider 故障恢复、并发/Token/成本治理、多模型契约评估、
   prompt injection 与数据泄露测试）。
3. **Phase 5 全部**（用户流程、生辰输入体验、命盘可视化、证据链浏览器、
   多主题工作台、时间轴交互、PDF/JSON 导出、隐私删除策略、移动端无障碍
   E2E 与视觉回归）。
4. **Phase 6 全部**（可复现构建、密钥配置、部署、健康检查、性能压测安全、
   备份恢复演练、版本管理、用户/开发/维护文档、V1.0 发布验收）。
5. **引擎 6 个失败年的根因修复**（Phase 3.1 的首要对象）。
6. **三个 PR 的最终处置**（等授权）。
7. **`pyproject.toml` description 的归属**（等拍板）。

---

## 10. 下一阶段建议：Phase 3 的正确起点

任务书规定只有 Phase 2 验收通过才能开始 Phase 3。若老板准予进入，
**3.1 的第一个动作应该就是本报告 §8.1 那个引擎缺陷**：先修
`899–901` / `999–1001` 这 6 年，再谈独立基准。

理由：那 6 年是当前唯一已知的**计算错误**（不是体验问题），
且症状会误导用户（合法日期被告知「day is out of range for month」）。
在它修好之前建「独立基准」没有意义 —— 基准会把这 6 年标成失败，
而失败的根因不在基准侧。

建议顺序：

1. **修 6 个失败年**（`engines/bazi` 节气换算），修完
   `tests/test_api_boundaries.py` 的 `test_engine_failure_years_…`
   会自动从「包中文框架」变成可以验收真实修复 —— 那条测试已经在那里等着。
2. **扩年份扫描到全区间**：把扫 1–9999 的脚本固化成测试
   （现在只钉了 6 个已知失败年 + 边界值），让任何新增的失败年立刻现身。
3. **再做 3.2–3.8**，其中 3.8 的 RFC 要单独产出文档，
   未通过 RFC 的多流派/紫微功能不得接入 V1.0（任务书明确要求）。

---

## 11. 回滚方式

分支已推送，所以以下方法都以**不复写已推送历史**为前提。

### 11.1 只回滚本轮的某一项

```bash
git checkout hardening/mingli-v1
git revert 21518a5        # 2.4 工程一致性
git revert 0616855        # 2.3 API 边界治理 + 2.2 补测
```

`git revert` 而非 `git reset`：分支已推送，reset 需强推，而强推未被授权。

### 11.2 只回滚 API 约束（保留其余）

若某些输入上限收得太紧、误伤了真实调用方：

```bash
git checkout hardening/mingli-v1
git checkout 0749fb7 -- api/server.py     # 回到类型修复后的版本
git commit -m "revert(api): 回退输入约束，保留 mypy 修复"
```

注意这会同时退掉中文错误处理器，`test_api_boundaries.py` 的两条
「detail 必须是中文」会重新变红 —— 那是预期的。

### 11.3 验证回滚是否干净

```bash
git status --porcelain                    # 应为空
python -m pytest tests/ -q                # 应回到回滚目标的状态
mypy . 和 ruff check .                    # 应仍 exit 0
```

---

## 12. 验收对账

| 任务书条款 | 状态 | 证据 |
|---|---|---|
| 2.1 复核已完成部分，不重复实现 | ✅ | §2：四条命令重跑 + CI 明细 + 无 `type: ignore` |
| 2.2 惰性导入五项验收 | ✅ | §3：五项全过，测试 12 条 |
| 2.3 API 边界全面检查 | ✅ | §4：七类输入全部覆盖 |
| 2.3 逐条修复 strict xfail 并转正 | ✅ | §4.4：两条转正，`2 xfailed` 清零 |
| 2.3 不破坏公开接口契约 | ✅ | 只**收紧**输入校验并补全承诺过的中文消息；响应结构未动 |
| 2.4 同步 AGENTS.md / README / CI | ✅ | §5.2 / §5.4，并更正一处过期描述 |
| 2.4 明确模块边界 | ✅ | §5.2：导入/包/依赖三层，全部实测 |
| 2.4 依赖一致性 | ✅ | §5.1：两份一致 + 三个零 import 包登记 |
| 2.4 fetch 全分支跟踪，不作仓库代码 | ✅ | §5.3：改的是 `.git/config`，只把坑写进 AGENTS.md |
| 2.5 四条门禁 exit 0 | ✅ | §6：四条全 0 |
| 2.5 生成 phase2-final-acceptance.md | ✅ | 本文件 |
| 2.5 提交并推送，核验 SHA 对应 CI | ⏳ | 见 §13 |
| 不进入 Phase 3 | ✅ | 未动 Phase 3 任何内容 |
| 不合并 master / 不自动关 PR / 不删 mingli-split | ✅ | `master` 仍 `f108040`；PR #1/#2 仍 OPEN；分支仍在 |

**唯一未完成项是 §12 最后第二行的「推送与 CI 核验」** ——
报告写于推送之前，推送结果与 CI 运行号见 §13。
