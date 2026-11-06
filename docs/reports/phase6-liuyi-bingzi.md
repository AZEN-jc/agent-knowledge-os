# 卷八第 13 节与门禁修复验收（Phase 6.14）

**结论先行**：卷八录入推进到六乙日头一节，典籍规则从 202 条涨到 **229 条**，
13/60 节完成，事实词表仍是 60 个键、零新增。同时修掉两个会**误报或拖垮门禁**
的真实缺陷：清单脚本重复构建注册表（107 次 × 4.9 秒，在本机直接被杀），
以及真起服务的测试写死 8000 端口、连到了老板另一个项目的页面上。

本报告按项目约定的十节写。

---

## 1. 修改了什么

三件事，按影响面排序：

1. **录入第 13 节「六乙日丙子時斷」**：27 条 ACTIVE 原子、1 条章节登记、
   27 张见证盘、21 条同组重叠登记。
2. **修清单脚本**：`scripts/atom_checklist.py` 的重叠复核循环里每条登记都重建
   一次 `default_registry()`，107 条就是约 9 分钟。改成模块级复用后，
   **从「被系统杀掉」降到 5.9 秒**（实测），并补两条守卫测试钉住这件事。
3. **修真实服务测试**：`tests/test_web_ui.py` 改用内核分配的空闲端口，
   `api/server.py` 新增 `MINGLI_PORT` 环境变量（缺省仍是 8000）。
4. **补章节级账本**：`scripts/chapter_ledger.py` 把 60 节的录入状态集中成一张表，
   生成 `docs/reports/juan8-chapter-ledger.md`，并加 6 条守卫测试。
   当前读数：**60 节 / 360 条 / 已录 13 节 / 229 原子 / 暂缓 73 处 / 待录 47 节**。

另外把上一轮遗留的两处改动一并入账：见证测试的注册表 `lru_cache` 复用，
以及 `phase6-liujia-complete.md` 六甲日收口报告。

---

## 2. 为什么

老板定的四项里「内容深度优先」与「先吃透手头这一本」都落在卷八这个长跑项上。
六甲日十二时上一轮已收口，本轮按计划进入 C2（六乙→六癸 48 节），先录一节
验证词表够不够用：**够用，27 条原子一个新键都没加**。

门禁的两个缺陷不是顺手改的，是这轮真踩出来的：清单脚本连续三次以
SIGTERM(137) 退出，一开始以为是沙箱重活，读代码才发现是循环内重建注册表；
全量测试报「页面里没有 MingLi Agent」，查端口发现 8000 上跑的是
`/Users/admin/Documents/ChatGPT/New project` 的服务 —— 那是老板另一个项目，
**没有杀它**，改的是测试自己的端口假设。

---

## 3. 文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `corpus/.../atoms/juan8_liuyi_bingzi.json` | 新增 | 第 13 节 27 条原子 |
| `corpus/.../chapters.json` | 改 | 登记 `j8.liuyi_bingzi` |
| `tests/test_structural_rules.py` | 改 | 27 见证盘 + 21 重叠；上一轮的注册表缓存 |
| `scripts/atom_checklist.py` | 改 | `shared_registry()` 复用，5 处调用点 |
| `tests/test_atom_pipeline.py` | 改 | 两条复用守卫（含构建次数探针） |
| `tests/test_web_ui.py` | 改 | 动态端口 + 子进程存活检查 |
| `api/server.py` | 改 | `MINGLI_PORT` 环境变量 |
| `scripts/chapter_ledger.py` | 新增 | 60 节账本生成与不变量检查 |
| `tests/test_chapter_ledger.py` | 新增 | 6 条账本守卫（含两条变异探针） |
| `docs/reports/juan8-chapter-ledger.md` | 新增 | 生成的一页式账本表格 |
| `docs/reports/phase6-liujia-complete.md` | 新增 | 上一轮六甲日收口报告（补交） |
| `docs/reports/phase6-liuyi-bingzi.md` | 新增 | 本报告 |

底本 `juan8.txt` **一个字没改**。

---

## 4. 数据结构

| 项 | 数值 |
|---|---|
| 卷八已录章节 | 13 / 60 |
| 典籍原子 / 规则 | 229 |
| 事实键 | 60（本轮零新增） |
| 本节原子条件分布 | `month_pillar` 14、`year_month_branches` 5、`month_branch` 2、纯日时 6 |
| 本节置信 | MEDIUM 18、LOW 9 |
| 本方向标签 | negative 14、positive 9、neutral 4 |
| 暂缓从句 | 12（逐条列在 `deferred_note`） |
| 见证盘 / 重叠登记 | 累计 229 / 107，缺见证 0、过期 0 |

LOW 的 9 条全部有具体原因：原文另有否定条件、限定语，或同一句还依赖大运/岁运，
本系统只录可判定的那一层并在 `conclusion` 里写明「未录」。**不是拍脑袋降权。**

12 处暂缓里有一处值得单独说：乙巳日「若己午年月壽促」的「己」是天干，与
「午」不构成地支对，疑为「巳」的转录误字。按诚实留白，**不替底本改字**，暂缓。

---

## 5. API

无新增端点。新规则经 `RuleRegistry` 自动进入 `/api/analyze`、
`/api/analyze/multi`、`/api/rules` 与报告导出。

端到端实测：`POST /api/analyze`（1950-01-30 00:00，问题「命局」）返回
**HTTP 200**，响应里能查到 `yichou_bingzi` 规则 ID、「乙丑日丙子」、「身弱」
转述与 `covered` 主题状态 —— 新原子不是只通过静态守卫，它真的进了证据链。

`python -m api.server` 默认仍是 8000；端口被占时可用
`MINGLI_PORT=8123 python -m api.server`。

---

## 6. 测试结果

| 检查 | 结果 |
|---|---|
| `scripts/atom_checklist.py` | 229 条规则 / 0 缺见证 / 107 重叠 / 0 过期，5.9 秒 |
| `test_atom_integrity.py` + `test_corpus_citation.py` | 96 passed |
| `test_atom_pipeline.py` + `test_atom_integrity.py` | 29 passed（含两条新守卫） |
| `test_structural_rules.py`（见证核对） | 29 passed，12.46 秒 |
| `test_web_ui.py`（真起 uvicorn） | 10 passed |
| `test_report_export.py`（单独复跑） | 10 passed |
| `test_chapter_ledger.py` + `test_corpus_manifest.py` + `test_atom_integrity.py` | 34 passed |
| `scripts/chapter_ledger.py --check` | 账本自洽，退出 0 |
| `pstack verify all` | 三项门禁全绿 |
| `ruff check` | All checks passed |
| `mypy`（项目配置，89 文件） | Success: no issues found |
| 端到端 `/api/analyze` | HTTP 200，新断语在链上 |
| 本地全量测试（提交后） | **1579 passed / 2 skipped / 0 failed，25m48s，exit 0** |
| GitHub Actions | 最新 run **42253170762**（headSha `3e8de84`）查询时 in_progress；前两次被后续 push 自动 cancel，不是失败。上一轮 42064247051 已确认 success |

全量测试是在账本守卫文件落盘**之前**启动的，所以那 1579 条不含
`test_chapter_ledger.py` 的 6 条；后者单独跑 6 passed，并与 manifest/integrity
合跑 34 passed。CI 的最终 run 会把它们一起收进去。

**变异探针**：撤掉 `shared_registry` 复用、只复核 4 条重叠，构建次数从 1 变 6；
撤到底直接被 SIGTERM。守卫不是摆设。

上一轮全量测试的 3 个 F 已全部查清，都不是产品缺陷：

- `test_report_export` 的指纹不一致、`test_structural_rules` 的「27 条死规则」，
  是**测试进程启动后又往磁盘写入新原子**造成的进程内新旧混读；单独复跑均绿。
- `test_web_ui` 连到别人页面的，是 8000 端口占用；已改成动态端口，复跑绿。

---

## 7. 构建结果

零依赖单页前端，无构建步骤。报告 PDF 仍走 reportlab CID 字体，
`REPORT_FORMAT_VERSION` 未变。

---

## 8. 已知问题

1. **全量测试仍慢**（上一轮 29 分 06 秒）。根因与清单脚本同源：约 20 个测试文件
   各自调用 `default_registry()`，每个函数重建一次。已修的是见证测试与清单脚本，
   **其余文件没动** —— 因为它们里有「新建注册表与基线同指纹」这类故意重建的断言，
   全局缓存会把这类守卫悄悄变成永真。要推广得逐个文件判断，不是全局替换。
2. ~~章节级账本还没有~~ —— 本轮已补：`chapter_ledger.py` + 6 条守卫 +
   一页式表格，60 节状态集中可读。注意它是**派生产物**，生成在
   `docs/reports/` 而不是语料目录，避免多出的文件干扰 corpus manifest。
3. 8000 端口仍被老板另一个项目占用。测试已不依赖它，但手工 `python -m api.server`
   在这个环境下要用 `MINGLI_PORT` 换端口。

---

## 9. 未实现功能

- 卷八剩余 **47 节**（六乙日余 11 节、六丙至六戊 36 节）。
- 时间轴规则化：见证口径需另建「盘 + 年份」，不能塞进现有 `RULE_WITNESS`。
- 事业、财运、婚姻、健康四个主题仍无专属规则。卷八是「日时断」，天生属
  `destiny`；不为凑覆盖率把「主富」「妻賢」硬映射成财婚主题。

---

## 10. 下一阶段建议

1. 继续第 14 节「六乙日丑時斷」。标题只写地支，按原文首句「六乙日生時丁丑」
   补全时柱为**丁丑**，与卷八第 9~11 节同样处理。
2. ~~补章节级账本~~ —— 已完成。后续每录一节跑
   `python scripts/chapter_ledger.py --check --write`，让账本与原子文件同步，
   不要手抄状态。
3. 注册表复用推广只做「明确只读」的那几个文件，并给每个改动配一条
   「新建与缓存口径一致」的断言，防止把守卫变成永真。

**一句话**：这一节证明词表够用，剩下 47 节是产能问题，不是表达力问题。
