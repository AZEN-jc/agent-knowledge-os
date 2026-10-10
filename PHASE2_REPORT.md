# Phase 2 验收报告

**项目名称**：MingLi Agent（命理智能体）
**阶段**：Phase 2 - Knowledge Engine（规则库）
**完成日期**：2026-10-10
**状态**：⚠️ 工程完成（5 项验收标准 4 项达成，1 项**按计划未执行**，见 §6.2）

---

## 1. 修改了什么

12 个文件修改、9 个文件新增（含本报告），`+965 / −112` 行（不含新增文件）。核心是三件事：

1. **把「不编造命理规则」从文档口号变成代码级守卫**。新增 `knowledge/provenance.py`：`Citation`（典籍 / 底本 / 原文 / 可核验地址）与 `SourceTier`（`structural` 可执行验证 / `classical` 只能靠原文）。`Rule.__post_init__` 里一条硬规则 —— **`classical` 规则想进入 `ACTIVE`，必须带齐引文，缺一项直接抛错**。
2. **规则库从 3 条扩到 68 条**，全部是 `structural` 层：由 `engines.bazi` 的定义表唯一确定、跑一遍代码就能证伪的结构事实。来源诚实写成「结构定义」，不冒充典籍。
3. **补齐规则查询 API、流派注册表、事实词表，并给每条规则配一张「见证命盘」**——把「规则不能是摆设」变成可测试的不变量。

---

## 2. 为什么修改

### 2.1 为什么 68 条规则里**一条典籍断语都没有**

MINGLI_PLAN.md §2.1 要求「优先《滴天髓》」，§2.4 验收标准 1 要求「至少 50 条规则录入」。**这两条我没有按原样执行**，理由如下：

写一条典籍规则需要填 `condition`（什么命盘）和 `conclusion`（断什么）。这两样一填，就等于把某句命理断语写进了系统，而**在拿到可核验的底本之前，我无法确认这句话是否真的是那部书里的原话**。当前环境也验证过：`zh.wikisource.org`、`ctext.org` 在多个出口节点上均不可达（只有 `github.com` 和 `gutenberg.org` 通），原文无从逐字核对。

凭印象写「《滴天髓》云：何知其人贵，官星有理会」——这正是 MINGLI_PLAN.md §1.2 第一条「不做什么」明令禁止的**编造命理规则**。

所以我做了两件事：
- **能做的先做**：录入 68 条 `structural` 层规则。它们不引典籍，来源是「`engines.bazi` 的定义表 + 可执行验证」，诚实且可证伪。这满足了「≥50 条」的**数量**要求，也满足了「每条规则有明确来源和条件」的**质量**要求。
- **不能做的挂账**：新增 `knowledge/classical_backlog.py`，把 7 部典籍/流派的录入任务连同**阻塞原因**和**需要谁做什么**写成可执行清单。其中《滴天髓》优先级 1。

**这是一处需要老板拍板的阻塞点，不是可以自行决定的工程细节。** 详见 §10.1。

### 2.2 为什么用 `SourceTier` 把规则分成两层

`structural` 和 `classical` 的**正确性来源根本不同**：

- `structural`：正确性来自代码。十神是什么、藏干有哪几个、六冲是哪六对——`engines.bazi` 的定义表唯一确定，跑一遍就能证伪。它可以没有典籍引文，但它**不能冒充典籍**。
- `classical`：正确性只来自原文。代码无法验证「官星有理会」是不是《滴天髓》的原话，只有底本可以。

把这两类混在一个 `source` 字符串里，系统就没法区分「可执行验证的事实」和「需要文献背书的断语」，于是两者会被同等权威地引用出去。分层之后，「不编造」这条线才守得住。

### 2.3 为什么 `Citation` 强制要求「底本」

只写书名无法复核。《三命通会》的天乙贵人一项，「甲戊庚牛羊」与「甲戊兼牛羊」两个版本在流传中都存在——差别恰恰在**底本**，不在书名。所以 `Citation.edition` 是必填项，`is_verifiable` 要求**逐字原文 + 可打开的出处地址**两者齐备：只有地址没有原文，无法判断引用是否走样；只有原文没有地址，别人无从复核是不是转抄自二手断语。

### 2.4 为什么冲突用「值级比较」而不是静态 `conflicts_with`

规则库收录了两种**真实存在**的格局命名法：本气定格（`month_branch_ten_god`）与透干定格（`month_branch_extended_ten_god`）。

但它们**只在两法给出不同格局名时才构成分歧**。月支本气是正官、藏干透出的也是正官——两法一致，此时报冲突就是**误报**。静态的 `conflicts_with` 表达不了这个区别（它只能声明「这两条可能对不上」），所以新增 `conflict_slot` / `conflict_value`：同一槽位上**取值不同**才算真冲突。

实测口径：扫描 8064 张命盘，两法分歧在 **324 张命盘上触发 29 次**；而两法一致的命盘一次都不报。

### 2.5 为什么每条规则都要一张「见证命盘」

条件键拼错、或者条件永远不可能成立的规则，**不会报错，只会永远静默地匹配不上**。一条死规则比一条错规则更难发现——它看起来完全正常，只是从不生效。

所以规则库配了一张 `RULE_WITNESS` 表：68 条规则，每条一张**真实命盘**，测试运行时逐条复验「这张命盘确实能命中这条规则」。新增规则时若不补见证，测试直接失败。加上「条件键必须存在于事实词表」的静态校验，两个角度把死规则钉死。

---

## 3. 文件清单

### 新增

| 文件 | 行数 | 作用 |
|------|------|------|
| `knowledge/provenance.py` | 94 | `Citation` / `SourceTier` / `ReviewStatus`；引文可核验性判定 |
| `knowledge/schools.py` | 149 | 流派注册表；`school` 从自由字符串收敛为显式取值域 |
| `knowledge/structural_rules.py` | 301 | 68 条结构层规则 |
| `knowledge/classical_backlog.py` | 142 | 7 条典籍录入任务的阻塞清单（**刻意不含任何 `Rule` 对象**） |
| `engines/bazi/ten_gods.py` | 73 | 十神/五行/阴阳定义表从 provider 适配器里拆出，供证据层复用 |
| `tests/test_provenance.py` | 166 | 引文守卫、枚举收敛、状态流转 |
| `tests/test_schools.py` | 129 | 流派注册、重复拒绝、未注册引用拦截 |
| `tests/test_structural_rules.py` | 345 | 规则库规模/来源/可达性/冲突/证据强度 |

### 修改

| 文件 | 改动 |
|------|------|
| `knowledge/rules.py` | `Rule` 增 `topic`/`source_tier`/`review_status`/`citation`/`version`/`conflict_slot`/`conflict_value`；`__post_init__` 引文守卫 + 枚举收敛；`list()` → `select()`（**原名遮蔽内置 `list`，导致 `list[Rule]` 注解被 mypy 解析成本方法**）；新增 `slot_conflicts`/`condition_keys`/`validate_condition_keys`/`validate_schools`/`production_ready`/`stats` |
| `knowledge/evidence.py` | 事实词表扩到 **37 键**；新增十神透干有根/虚透、藏干十神、月支本气与透干十神、五行计数与缺失/偏旺、关系密度、日主同类多寡；`build_evidence` 接入值级冲突与 `CONFLICT_PENALTY` |
| `knowledge/default_rules.py` | 改为组装 `structural_rules()` + 流派注册表，并做条件键与流派双重校验 |
| `api/server.py` | 新增 5 个规则库端点 |
| `agents/mingli.py` | Critic 新增「引用了未通过校核的规则」检查（`unreviewed_rule_ids` 覆盖所有非 `ACTIVE` 规则，未激活的典籍规则自然包含在内）；Analyst 结论改为按置信度排序后内联前 6 条，其余留在证据链里 |
| `runtime/mingli_service.py` | 暴露 `registry` / `schools` |
| `engines/bazi/sxtwl_provider.py` | 定义表迁出（净 −36 行），行为不变 |
| `engines/bazi/time_engine.py` | 导入路径跟随调整 |
| 4 个测试文件 | `test_api.py` / `test_mingli_agents.py` / `test_rules.py` / `test_bazi_invariants.py` 相应扩展 |

---

## 4. 数据结构

```python
@dataclass(frozen=True)
class Citation:                    # 一条规则的文献出处
    book: str                      # 典籍名（必填）
    edition: str                   # 底本/版本（必填，只写书名无法复核）
    chapter: str = ""
    original_text: str = ""        # 逐字原文
    url: str = ""                  # 可打开的出处
    retrieved_on: date | None = None
    # is_verifiable = 有原文 且 有地址，两者不可省

class SourceTier(StrEnum):  STRUCTURAL | CLASSICAL
class ReviewStatus(StrEnum): UNREVIEWED → REVIEWED → ACTIVE → DEPRECATED
```

`Rule` 在原有字段（`id` / `source` / `school` / `category` / `condition` / `conclusion` / `confidence` / `conflicts_with` / `evidence_required`）之上新增：

```text
topic           主题标签（当前全部为 structure）
source_tier     依据性质：structural / classical
review_status   校核状态
citation        Citation | None
version         规则版本
conflict_slot   结论槽名（如 pattern_name）
conflict_value  该槽上本条规则给出的取值（如 正官格）
```

三条构造期硬约束：

1. `classical` + `ACTIVE` **必须**带可核验 `citation`，否则 `ValueError`。
2. `source_tier` / `review_status` 传字符串会被**收敛成枚举成员**——否则 `"ACTIVE"` 与 `ReviewStatus.ACTIVE` 不相等，`is` 判断为假，**整条引文守卫会被绕过**。
3. `conflict_slot` 与 `conflict_value` 必须成对出现。

---

## 5. API

新增 5 个端点（全部带 summary / description / tags）：

| 端点 | 说明 |
|------|------|
| `GET /api/rules` | 按 `school` / `category` / `topic` / `confidence` / `source_tier` / `review_status` 过滤；返回总数、生效过滤条件与规则列表 |
| `GET /api/rules/stats` | 总数、生产可用条数、按流派/类别/层级/状态的分布、冲突槽数 |
| `GET /api/rules/{rule_id}` | 单条规则完整信息；不存在返回 404 |
| `GET /api/schools` | 已注册流派及其核心方法、代表典籍、已知分歧点 |
| `GET /api/classics/backlog` | 典籍层待录入清单与阻塞原因 |

路由顺序有讲究：`/api/rules/stats` 必须声明在 `/api/rules/{rule_id}` **之前**，否则 `stats` 会被当成规则 ID 吃掉。这一点在代码里写了注释。

---

## 6. 测试结果

**全量：668 → 734 passed**（本轮 +66）。`ruff check` 全树通过。

### 6.1 验证手段

**变异探针**（故意破坏新守卫，确认测试会变红；每轮后校验文件哈希，探针零残留）：

| 变异 | 结果 | 变红断言数 |
|------|------|-----------|
| 引文守卫直接放行（`_guard_classical_citation` 首行 return） | ✅ CAUGHT | 3 |
| 去掉枚举收敛（字符串 `"ACTIVE"` 可绕过守卫） | ✅ CAUGHT | 1 |
| 冲突槽忽略取值差异 | ✅ CAUGHT | 2 |
| 多值事实退回相等判断 | ✅ CAUGHT | 4 |

**可达性扫描**：遍历 1950–2030 年命盘共 **8064 张，0 条死规则**。68 条规则全部有见证命盘。

**静态校验**：规则库出现的全部条件键必须存在于 `FACT_SCHEMA`（37 键），否则构造即报错。

**静态检查**：`mypy` 从 HEAD 基线的 **6 条降到 4 条，零新增**（用 `git worktree` 对 HEAD 逐条核对）。减少的 2 条正是本轮修掉的 `RuleRegistry.list` 遮蔽内置 `list` 引发的问题。

### 6.2 验收标准逐条核对

| # | 标准 | 结果 | 说明 |
|---|------|------|------|
| 1 | 至少 50 条规则录入（**优先《滴天髓》**） | ⚠️ 部分 | 68 条已录入，**但无一条来自《滴天髓》**。理由见 §2.1：无底本，录入即编造。已挂入 backlog 优先级 1 |
| 2 | 每条规则有明确来源和条件 | ✅ | 每条都有 `source_tier` + `source` + `condition`，条件键受词表校验 |
| 3 | 冲突规则已标注 | ✅ | 1 个冲突槽（`pattern_name`），值级比较；静态对 0 条（刻意的：静态声明会误报） |
| 4 | 流派系统可扩展 | ✅ | `SchoolRegistry.register()`；5 个流派已注册；规则挂到未注册流派直接报错 |
| 5 | 规则查询 API 完整 | ✅ | 5 个端点，含过滤、统计、单条、流派、backlog |

### 6.3 规则库构成

```text
总数 68   ·   生产可用 68   ·   全部 structural + ACTIVE

按类别    ten_god 21 │ pattern 18 │ strength 10 │ element 10 │ relation 9
按置信    HIGH 36    │ MEDIUM 32
按流派    structural_common 68（其余 4 个流派 0 条 —— 无底本，见 §2.1）
```

---

## 7. 构建结果

- `.venv`（管理版 Python 3.13.12）正常；无新增第三方依赖。
- 全量测试可重复运行，无 flaky。
- 服务按老板要求**保持停止**，本轮未对外发布任何内容。

---

## 8. 已知问题

1. **典籍层完全空白**。68 条规则全是结构层。这意味着当前系统能回答「命盘里有什么」（正官透干、月支本气为食神、四支见六冲），**不能回答「这意味着什么」**。这不是缺陷，是刻意的边界。

2. **结构层规则不含吉凶判断**。这是设计选择：十神结构本身不蕴含吉凶，把「正官透干」直接映射成「宜从政」是**跳过证据的推断**，正是证据层要防的事。所以结论文案一律写成「结构上称建禄」而非「主贵」。

3. **五行计数与有根口径是流派分歧点**，本实现只选一种并明示：
   - 计数 = 四柱天干 + 四支**本气**共 8 项（藏干是否计入、计几位，各家不同）
   - 有根 = 四支藏干中存在与日主**同五行**者（不要求同阴阳）；更严格的本气根口径尚未录入

   这些已在 `evidence.py` 模块 docstring 与相关规则的 `note` 里写明，**不声称是唯一正确口径**。

4. **`mypy` 4 条既有告警**（均非本轮引入）：`engines/bazi/golden.py` 1 条、`engines/bazi/sxtwl_provider.py` 3 条（`gz: object` 属性访问、`utcoffset()` 可空）。可读性问题，不影响运行。

5. **`test_structural_rules.py` 的见证命盘是硬编码表**。若将来 `engines.bazi` 的排盘结果变化，这张表会整体失效。这是**有意的**：命盘变了，规则的可达性就该被重新验证一遍。

---

## 9. 未实现功能

- **典籍层规则（0 条）**：等底本确认。7 条 backlog 全部处于 `BLOCKED_SOURCE`（5 条）或 `BLOCKED_LEGAL`（2 条）。
- **神煞体系**：事实词表当前不含神煞；《三命通会》的起例需要底本 + 新增神煞计算。
- **调候用神**（《穷通宝鉴》）：需整表录入 + 十二月校核用例。
- **盲派、象法新派**：`BLOCKED_LEGAL` —— 盲派以口传口诀为主，无公有领域文本；象法代表著作在著作权保护期内。
- **条件的表达力边界**：当前 condition 是 `{键: 值}` 的平坦相等/包含匹配。规则一多，可能需要更复杂的条件（与/或/嵌套），但**现在不做** —— 避免条件 DSL 在需求明确前膨胀。
- **证据强度模型**：当前是「置信度均值 − 冲突惩罚」，粒度较粗。Phase 3 待细化。

---

## 10. 下一阶段建议

### 10.1 ⚠️ 阻塞点：需要老板拍板（不宜自行选定）

**典籍规则的底本由谁定、定哪一版？**

项目原则「不编造命理规则」要求每条典籍规则能指向可核验原文。但：

- 同一部书在通行本、注本、各家辑本之间**条文有出入**，只写书名无法复核；
- 当前环境**无法访问**维基文库、ctext 等公版文本站点（已实测：`github.com` 通，`zh.wikisource.org` / `ctext.org` 在多个出口节点均超时）；
- 底本选择会**直接决定**某些规则的取舍表述（例如《子平真诠》是「本气定格」与「透干定格」分歧的关键文献）。

**需要的输入**：一个可获取、可引用页码或章节的**公有领域底本**（注明版本与出处）。拿到后我按卷章逐条录入，并填入 `Citation.url`。

在此之前，典籍层保持 0 条，`classical_backlog.py` 的清单就是交接文档。

### 10.2 可以不阻塞继续做的

1. **Phase 3（Evidence Layer）细化**：事实提取已从 12 键扩到 37 键，但 `build_evidence` 的证据强度模型仍是粗粒度均值。计划要求「能从命盘提取 20+ 事实」——**已达成的部分可以先验收**。
2. **规则库查询能力**：条件 DSL 暂不扩，但可以补「按条件键反查规则」这类只读能力。
3. **Phase 4/5 的 LLM 接入**：Analyst/Critic 契约已在，`classical` 未激活时的行为已有测试守着（Critic 会拦下未激活的典籍规则引用），可以开始接真实 provider。

Phase 2 的核心结论：**规则库从「3 条摆设」变成了「68 条可验证、无死规则、冲突不误报的结构层规则库」，并且把「不编造」这条原则写成了代码级守卫**——现在想往库里塞一条没有出处的典籍断语，构造阶段就会失败。代价是典籍层仍然空白，这一步的输入需要老板确认。
