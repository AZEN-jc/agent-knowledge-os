# Phase 5 验收报告：典籍底本固化与规则原子

Phase 5 不在 `MINGLI_PLAN.md` 的原有分期里 —— 它是老板在一次架构提案里提出的
「确定性解耦」三段式（底本基准源 → 规则原子 → 特征对齐）的第一段落地。
报告仍按计划 §八 的十节写。

---

## 1. 修改了什么

一句话：**把「典籍断语」从一句可以随便写的字符串，变成一条能在底本里逐字找到的引用。**

- 底本固化：`corpus/canonical/` 下三卷公有领域文本，`manifest.json` 记两级哈希与永久链接。
- 规范标识：`knowledge/urn.py` 实现 Canonical Citation URN。
- 引证守卫：`knowledge/corpus.py` 逐字定位 + 完整性自查；`knowledge/rule_atoms.py` 加载时走四条守卫。
- 规则库装配：`knowledge/default_rules.py` 从原子目录动态加载典籍层，规则数 68 → **74**。
- 溯源协议：`agents/prompt.py` 契约升到 v2，`agents/mingli.py` Critic 做双向 URN 校验。
- 主题层：`knowledge/topics.py` 新增 `destiny` 主题，从「一条规则都没有」变成 6 条真实断语。

---

## 2. 为什么修改

### 2.1 为什么 URN 比老板给的示例多一段「版本」

老板的示例是五段：`urn:divination:bazi:sanming:v8.liujia_ri.jiazi_jiazi_01`。
实现时改成了六段：`<系统>:<底本代码>:<版本>:<卷>.<篇>.<条>`。

理由不是「更严谨」，而是**五段会给出错的答案**。同一个底本代码可以对应多个版本
（明万历刻本 / 文渊阁四库全书本 / 维基文库转录本），条文不同。URN 的用途是
「反查出完整出处元数据」—— 两版共用一个 URN，反查回来的元数据就是错的，
而且错得看不出来。版本必须是 URN 的一部分，这不是设计偏好，是正确性要求。

这条决定由 `test_urn_carries_a_version_segment` 钉住：谁想「简化」回五段，测试会红。

### 2.2 为什么引文对不上必须报错，而不是警告

`Corpus.locate()` 在底本里找不到引文时抛 `CorpusError`，不留降级路径。

一条引文如果在底本里找不到，它就不是引文，是编的。放行等于把「不编造命理规则」
这条红线交给运气。这条守卫的爆破半径由变异探针 P1 量出来了：撤掉它，
**6 条测试同时变红**。

### 2.3 为什么对照本（collation）不可供引用

同一部书录了两份：四库全書本（`role=base`）和维基文库转录本（`role=collation`）。
后者的正文也在 corpus 里、引文同样找得到，所以**不拦的话一条引文可以「核验通过」
却指向一份「所据底本未標註」的文本** —— 那正是「底本未定」本身。

`Corpus.citation()` 因此只接受 `role="base"`。探针 P3 撤掉它，3 条测试红。

### 2.4 为什么两本都要固化，而不是只固四库本

只固一份，就没法回答「这份转录本身可不可信」。两份都在，才能核异文。
实际核出：甲午日甲子时条，四库本有 52 处「（一云）」异读，转录本 0 处 ——
这是个真实的传本差异，`collation_note` 与 `test_the_documented_collation_divergence_is_real`
把它固定成可查事实，而不是注释里的一句话。

### 2.5 为什么「典籍断语优先」排在结构规则前面

`_ordered()` 原来纯按置信度排，典籍断语的 `MEDIUM` 排在结构层一大片 `HIGH` 后面，
被挤进「另有 N 条规则命中，详见证据链」。用户问「命局」，典籍断语才是答案，
结构层是背景 —— **把答案藏在「详见证据链」后面，等于没给答案**。现在主题层优先。

---

## 3. 文件清单

新增：

| 文件 | 行数 | 作用 |
|---|---:|---|
| `knowledge/urn.py` | 153 | Canonical Citation URN 解析与构造 |
| `knowledge/corpus.py` | 377 | 底本语料库、逐字定位、完整性自查、URN 反查 |
| `knowledge/rule_atoms.py` | 319 | 规则原子加载器（四条守卫的落点） |
| `scripts/fetch_corpus.py` | 491 | 底本抓取 / 固化 / 校验 |
| `scripts/extract_atoms.py` | 209 | 机械抽取候选（只产出待审队列） |
| `corpus/canonical/manifest.json` | — | 三卷底本的版本与哈希记录 |
| `corpus/canonical/bazi_sanmingtonghui/{juan8.txt, juan8_collation.txt, chapters.json}` | — | 四库本 + 对照本 + 篇章表 |
| `corpus/canonical/bazi_sanmingtonghui/atoms/juan8_liujia_ri.json` | — | 6 条人工校验过的规则原子 |
| `corpus/canonical/zwds_qianshuchongzhen/juan1.txt` | — | 紫微斗数备存本 |
| `tests/test_corpus_citation.py` | 571 | 引证体系的直接测试（58 条） |

修改：`knowledge/{provenance,rules,topics,schools,default_rules,classical_backlog}.py`、
`agents/{prompt,mingli}.py`、`runtime/mingli_service.py`、`api/server.py`，以及 10 个测试文件。

---

## 4. 数据结构

**CorpusEntry** —— 一卷已固化的底本。关键在两级哈希：
`text_sha256`（我们规范化后的文本，防本地篡改）与 `source_revision_sha1`
（上游该修订版本的哈希，防上游漂移）。两者守的不是同一件事，都要。

**DivinationUrn** —— `system / edition / version / juan / chapter / entry` 六段。
段位限定 `[a-z0-9_]`：中文放元数据，不放 URN。

**Rule Atom**（作者格式）与 **Rule**（运行格式）分开。原子只给 `urn` +
`exact_quote`；`book / edition / chapter / url / retrieved_on` **全部由 corpus 反查生成**，
不从原子文件抄。这样「元数据与底本不一致」在结构上就不可能发生。

**Rule 新增字段** —— `polarity`（positive/negative/neutral）、`keywords`、`urn`。

---

## 5. API

- `GET /api/llm/contract` —— 契约本身作为数据，含 v2 的出处角标要求。
- `AnalystAgent(provider=...)` / `CriticAgent` —— 契约校验与双向 URN 校验。
- `python scripts/fetch_corpus.py --verify` —— 本地校验，不联网。
- `python scripts/fetch_corpus.py --fetch` —— 重新固化（会警告 revid 变化）。

---

## 6. 测试结果

| 指标 | Phase 4 | Phase 5 |
|---|---:|---:|
| 测试总数 | 879 | **937**（+58） |
| 新增测试文件 | — | `test_corpus_citation.py`（58 条） |
| ruff | 干净 | 干净 |
| mypy | 4 errors | 4 errors（**同 HEAD 基线**，全在 `engines/bazi/`） |
| 变异探针 | 5/5 | **10/10** |

探针明细（撤掉守卫 → 几条测试红）：

| 编号 | 撤掉的守卫 | 结果 |
|---|---|---|
| P1 | `locate` 找不到时放行 | 红 6 条 |
| P2 | `entry_for_urn` 不比版本段 | 红 6 条 |
| P3 | `citation` 不查 role 门禁 | 红 3 条 |
| P4 | `problems` 不校验 sha256 | 红 1 条 |
| P5 | `problems` 不校验篇章表标签 | 红 1 条 |
| P6 | 原子加载跳过逐字定位 | 导入期失败 |
| P7 | 跳过出处元数据交叉核对 | 红 2 条 |
| P8 | `to_urn` 丢版本段 | 导入期失败 |
| P9 | Rule 不要 canonical URN | 红 1 条 |
| P10 | Citation 不校验 URN 格式 | 红 1 条 |

---

## 7. 构建结果

全量 `pytest`：**937 passed, exit=0**。
`ruff check .`：All checks passed。
`mypy .`：4 errors in 2 files，与 Phase 4 的 HEAD 基线完全一致，零新增。

---

## 8. 已知问题

1. **上游维基文库的四库本页面自己丢了天干。** `六甲日壬申時斷` / `癸酉` / `甲戌`
   在页面上被录成 `六甲日申時斷` / `酉` / `戌`（六乙、六丙等组同样有）。
   **不是我们的规范化问题**（`normalize()` 忠实展开 `{{SK anchor|X}}`）。
   不影响当前唯一登记的篇章 `j8.liujia_ri`（标题完好），但后续登记别的时辰篇会踩上。
   已由 `test_upstream_dropped_stems_from_three_jia_headings` 钉住。

2. **P4 / P5 各只有 1 条测试覆盖。** sha256 校验和篇章表校验都只被一条测试钉着，
   比 locator 那条（6 条）薄。它们不复杂，但 1 条意味着改写其中一半逻辑可能仍然全绿。

3. **变异探针的第一版报了假「零残留」。** 详见 §10.3 —— 这是本阶段最值得记住的教训。

---

## 9. 未实现功能

1. **紫微斗数 42 条 MVP 没做。** `engines/` 下**只有 `bazi/`**，没有紫微排盘引擎。
   老板提案的冷启动选的是《紫微斗數全書·諸星問答論》十四主星 × 三宫 = 42 条；
   没有引擎，规则的条件无处落地。本次改做**八字冷启动**（6 条），
   并把《紫微斗數全書》卷一固化下来挂 `role=reserve`，等引擎到位。

2. **`ctext.org` 不可用。** 三个不同 URL（`searchbooks.pl`、`/sanmingtonghui`、
   `/wiki.pl?if=gb`）返回**逐字节相同的 2781 字节拦截页**；且该站许可证
   明确禁止非商业以外的使用，不能算公版源。国图 `read.nlc.cn` 在本机超时。
   （`gutenberg.org` 作为对照组可达。）

3. **刻本归属仍未证实。** 现在是「欽定四庫全書本（明 萬民英 撰）」，
   解决了「所据底本未标註」的问题；但老板提到的「明万历刻本 / 明崇祯刻本」
   **无法从维基文库页面证实**，需要另外的刻本著录。

4. **甲辰日甲子时暂缓。** 该条全部断语都依赖年月条件（「若水位年月，水泛木浮」
   「申月，煞星㑹印，俱貴」），当前事实词表表达不了。这是 `BLOCKED_SCHEMA`，
   不是遗漏 —— 硬录进去等于把有条件的断语当无条件的用。

5. **神煞体系未录。** 底本已定，卡在事实词表不含神煞起例。

---

## 10. 下一阶段建议

### 10.1 优先：补厚 P4 / P5 的测试覆盖

`problems()` 的两类校验各只有 1 条测试。补到 3 条以上的成本很低，
而它们守的是「原文不可被无痕篡改」—— 这是整套引证体系的地基。

### 10.2 需要老板拍板

- **紫微斗数要不要做排盘引擎**：不做，那 42 条 MVP 就一直停在 reserve；
  做，需要先定引擎（`iztro` 是 TS，`engines/` 是 Python，要移植）。
- **《滴天髓》《渊海子平》的本子裁定**：两者维基文库都有全文，
  但同一部书多个本子、条文有出入，只写书名无法复核。
  老板指定一个本子（注明版本与出处），就能照《三命通會》的路子走。

### 10.3 写给下一个人的：变异脚本的残留判定

本次探针第一版被超时 SIGTERM 打断在 P7/P10 上，`finally` 没执行；
第二版启动时拿「本次启动时的快照」当基线判定残留，**而快照已经被污染**，
于是报了个假的「零残留」。实际残留靠逐条核对守卫原文才发现。

规则：**变异测试的残留判定必须逐条核对守卫原文，不能信任何形式的启动快照。**
