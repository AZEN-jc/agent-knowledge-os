# Phase 3 验收报告

**项目名称**：MingLi Agent（命理智能体）
**阶段**：Phase 3 - Evidence Layer（证据层，计划标记为「核心创新」）
**完成日期**：2026-10-10
**状态**：✅ 完成（5 项验收标准全部通过）

---

## 1. 修改了什么

**修掉三个真缺陷**，都不是新功能缺失，而是「说出来的话和实际做的事不一致」：

| # | 缺陷 | 表现 | 根因 |
|---|------|------|------|
| 1 | **主题标签撒谎** | `build_evidence(chart, registry, topic="事业")` 返回一份题为「事业」的报告，内容却是十神与地支结构 | 规则匹配完全没按 `topic` 过滤，`topic` 只是个贴上去的标签 |
| 2 | **证据链不可追溯** | 匹配结果只记「条件键名」，不记**命盘实际取值**和**来自哪个要素**。用户看不到推理路径 | `RuleMatch.matched_conditions` 是 `tuple[str, ...]`，只有键名 |
| 3 | **强度模型不看条数** | 命中 3 条与命中 20 条，只要置信度构成相同，强度完全相同 | `strength = 平均置信度 − 冲突扣减`，均值把条数信息抹掉了 |

**另外在开发过程中被新守卫抓到两个自己写出来的 bug**（见 §2.6）：
- `_sources_for` 用相等判断找事实来源，遇到「事实值本身是多值元组」时永远找不到 → **证据链断环**
- Analyst 忘了披露主题覆盖不足 → 被 Critic 拦下

**新增能力**：条件追踪（`ConditionTrace`）、主题注册表与覆盖状态、可审计的强度算式、独立事实复核。

---

## 2. 为什么修改

### 2.1 为什么「主题」必须真的参与匹配

原实现里 `topic` 只写进证据标签，不参与过滤。后果是：用户问「事业」，系统回一份自称是事业分析的报告，里面全是「月支本气为正官」「四支见六合」。这不是小瑕疵 —— 它是 MINGLI_PLAN.md §1.2 明令禁止的**混淆推测和事实**：把「命盘里有什么」包装成「对事业的判断」。

修法不是「把 topic 拿去过滤」，而是**把主题拆成两层**：

- **基础层**（`structure`）：十神、藏干、五行生克、地支关系。所有主题共享，只说明命盘里有什么。
- **主题层**（`career` / `marriage` / …）：针对该主题的断语规则。**当前一条都没有** —— 断语需典籍原文，底本未确认（Phase 2 的阻塞点）。

`build_evidence` 在全量规则上匹配，再按 `rule.topic` 拆两层，并如实报告主题层是否为空。用户看到的变成「公共结构层证据（13 条），「事业」主题尚无断语规则，不构成对该主题的判断」。

### 2.2 为什么覆盖状态不能按「主题表里有没有这一行」判定

`status_for(topic, domain_match_count)` 刻意**只看主题层的命中条数**。如果按「主题是否已登记」判定，`career` 一登记就会报 `covered` —— 那是「挂个名字就算覆盖」，比不报更糟。登记了名字但一条规则都没有的主题，必须报 `base_only`。

### 2.3 为什么证据链要记「取值」和「出处」

只写「规则 R 命中」的匹配器，和黑盒没有区别。要做到「用户能看到推理路径」，匹配结果必须能回答三个问题：**哪条条件、命盘给的实际取值是什么、这个取值来自命盘哪个要素**。

所以 `RuleMatch` 从 `matched_conditions: tuple[str, ...]` 改成 `traces: tuple[ConditionTrace, ...]`，`ConditionTrace` 带 `key / expected / actual / sources`，`sources` 形如 `chart.pillars.month.hidden_stems`。证据链的最后一跳就此接通：

```text
STRUCT_ROOT_001 → 比肩透于天干且四支藏干中有同类，属有根之透。
    ten_god_with_root  期望 '比肩'  实际 ('食神','比肩','劫财')  来源 ['chart.pillars[*].hidden_stems']
```

顺带删掉了 `RuleMatch.missing_conditions` —— 它是死字段，`match` 只返回条件全满足的规则，那个字段恒为空，留着会让人以为存在「部分匹配」这条路径。

### 2.4 为什么匹配器改吃「事实元组」而不是「归并后的字典」

追踪需要知道每条条件的取值来自哪条事实。归并成 `dict[str, Any]` 之后这层信息就丢了 —— 一个命盘里 `has_relation` 可能有多条事实（六合、自刑），字典里只剩归并后的元组，回溯不到具体来源。

所以 `RuleRegistry.match(facts: tuple[Fact, ...])`，内部自己归并。为此把 `Fact` / `extract_facts` / `group_facts` 从 `knowledge/evidence.py` 拆到新模块 `knowledge/facts.py`，让 `rules.py` 能依赖它而不产生循环（`facts.py` 不依赖 `rules.py`）。

### 2.5 为什么强度模型换成凹饱和

原模型 `strength = 平均置信度 − 0.15 × 冲突数` 有三个问题：**不看命中条数**（命中 3 条和 20 条同分）、**不可解释**（只给一个数字，用户除了相信没有别的选择）、**语义混淆**（1.0 意味着「命中的规则全是 HIGH」，被读成「结论几乎确定」）。

新模型：

```text
raw        = Σ 各命中规则的置信度分值（LOW 0.4 / MEDIUM 0.7 / HIGH 1.0）
after      = raw / (raw + K)            K = 3.0
final      = max(0, min(1, after − 0.15 × 冲突数))
```

性质：对条数单调递增、**边际递减**、对置信度单调、对冲突单调递减、值域 `[0, 1)`、**永远到不了 1.0**。最后一条是刻意的 —— 结构层证据再厚也只是「命盘里有什么」，不该被读成「结论几乎确定」。

算式完整暴露在 `StrengthBreakdown` 里，`/api/analyze` 直接返回。K 与扣减额都注明是**本实现选定的标度，不是典籍规定，也不是概率刻度**。

### 2.6 为什么新守卫一上线就抓到了两个自己写的 bug

这是本阶段最值得记的一件事。两处都不是「测试没覆盖」，而是**逻辑本身错了，但错得很安静**：

1. **证据链断环**。`_sources_for` 里写的是 `fact.value in wanted`。当事实值本身是多值元组时（`ten_god_with_root = ("比肩","食神")`），`("比肩","食神") in ("比肩",)` 恒为假 → 来源回填为空 → 证据链断在最后一跳。`untraced_rule_ids` 检查一上线就把它列了出来，7 条规则受影响。

   修法是**复用 `condition_holds` 作为判据**，而不是另写一个相等判断：决定「条件成不成立」和决定「是哪条事实让它成立」必须是同一个谓词，否则两处判断会各自漂移。

2. **Analyst 漏披露**。加了 Critic 的「未披露主题覆盖不足」检查后，第一次跑测试就被拦下 —— 我在重写 `_summarise` 时把 `coverage_note` 的拼接漏掉了。

### 2.7 关于「匹配准确率」的口径

MINGLI_PLAN.md §3.5 验收标准 2 要求「事实与规则匹配准确率 > 90%」。这个数字很容易被过度解读，所以口径必须写死：

**测的是「管道准确率」，不是「预测准确率」。** 做法是用测试内部**另写一遍**的事实推导路径（不调用 `knowledge.facts` 的任何一行），与产品结果逐条比对，再据此算 precision / recall。

- **证明**：事实提取与规则匹配的管道自洽 —— 没有覆盖、漏项、键名漂移、多值丢失。Phase 2 真出过一个：同类型多值事实互相覆盖，导致「六合」规则永远匹配不上，而测试全绿。
- **不证明**：命理判断的正确性。两边读同一份命盘字段、同一套结构定义；定义本身错了这里发现不了 —— 那需要典籍原文。

另外加了一条约束：**复核必须覆盖规则实际读取的每一个条件键**。新增一条读新键的规则而不扩展复核，测试直接失败。否则新键会静默落在复核范围外，「准确率」就不再代表全部规则。

---

## 3. 文件清单

### 新增

| 文件 | 作用 |
|------|------|
| `knowledge/facts.py` | `Fact` / `FACT_SCHEMA` / `extract_facts` / `group_facts` / `index_facts`；从 evidence.py 拆出以打破循环依赖 |
| `knowledge/topics.py` | 主题注册表、中文别名、`TopicStatus` 覆盖状态判定 |
| `tests/test_topics.py` | 主题覆盖与「结构规则不冒充主题结论」的回归 |
| `tests/test_strength.py` | 强度模型的**性质**测试（不断言具体数值） |
| `tests/test_evidence_audit.py` | 独立事实复核 + 管道准确率实测 |

### 修改

| 文件 | 改动 |
|------|------|
| `knowledge/rules.py` | `RuleMatch` 改为带 `ConditionTrace`；`match()` 改吃事实元组；新增 `_sources_for`；新增 `validate_topics`；删除死字段 `missing_conditions` |
| `knowledge/evidence.py` | 新增 `StrengthBreakdown` / `score_strength`；`Evidence` 增 `topic_id` / `status` / `coverage_note` / `schools` / `strength_breakdown` / `untraced_rule_ids`；`to_dict()` 输出完整证据链 |
| `knowledge/default_rules.py` | 装配期新增主题校验；`FACT_SCHEMA` 改从 `knowledge.facts` 引入 |
| `knowledge/structural_rules.py` | 导入路径跟随调整 |
| `agents/mingli.py` | Analyst 披露主题覆盖与强度算式；Critic 新增「证据链断环」「未披露主题覆盖不足」两项检查 |
| `api/server.py` | `/api/analyze` 加 `response_model` 与证据链文档；新增 `GET /api/topics`；新增 6 个响应模型 |
| 6 个既有测试文件 | 导入路径与断言跟随更新 |

---

## 4. 数据结构

```python
@dataclass(frozen=True)
class ConditionTrace:          # 一条条件被满足的完整依据
    key: str                   # 条件键
    expected: Any              # 规则要求的值
    actual: Any                # 命盘实际给出的值
    sources: tuple[str, ...]   # 该事实的出处，形如 chart.pillars.month

@dataclass(frozen=True)
class RuleMatch:
    rule: Rule
    traces: tuple[ConditionTrace, ...]
    # matched_conditions 改为派生 property；is_fully_traced 判定证据链是否完整

@dataclass(frozen=True)
class StrengthBreakdown:       # 强度算式逐项可核对
    supporting_rules: int
    raw_support: float
    saturation_k: float
    after_saturation: float
    conflicts: int
    conflict_penalty: float
    final: float
```

`Evidence` 新增字段：

```text
topic_id             解析后的规范主题 ID（如 career）
status               covered / base_only / unknown
coverage_note        非 covered 时可直接展示给用户的说明
schools              tuple —— 不是单个 school：典籍层落地后一个命盘会同时命中
                     子平与滴天髓的规则，单值字段会静默选一个
strength_breakdown   强度算式
```

派生属性：`base_matches` / `domain_matches` / `unreviewed_rule_ids` / `untraced_rule_ids` / `is_fully_traced`。

`Topic`：

```python
Topic(id="career", name="事业", aliases=("事业","工作","职业","career"),
      blocked_by="该主题的断语规则需要可核验的典籍原文，底本尚未确认")
```

---

## 5. API

| 端点 | 变化 |
|------|------|
| `POST /api/analyze` | 补 `response_model`；响应新增 `evidence.chain`（完整证据链）、`evidence.strength_breakdown`、`evidence.status` / `coverage_note` / `untraced_rules` |
| `GET /api/topics` | **新增**：主题列表、中文别名、`blocked_by` |

新增响应模型 6 个：`TopicResponse` / `TopicListResponse` / `ConditionTraceResponse` / `RuleChainResponse` / `StrengthBreakdownResponse` / `FactResponse` / `EvidenceResponse` / `AnalysisPayload` / `AnalysisResponse`。

`/api/analyze` 的 `description` 明确写出：`evidence.status` 为 `base_only` 时，结论不构成对该主题的判断，原因在 `coverage_note` 里。

---

## 6. 测试结果

**全量：734 → 768 passed**（本轮 +34）。`ruff check` 全树通过。

### 6.1 验收标准逐条核对

| # | 标准 | 结果 | 证据 |
|---|------|------|------|
| 1 | 能从命盘提取 20+ 事实 | ✅ | 240 张样本命盘实测 **36–44 条**，均值 38.5 |
| 2 | 事实与规则匹配准确率 > 90% | ✅ | **precision 1.0000 / recall 1.0000**（tp=2837, fp=0, fn=0）。口径见 §2.7 |
| 3 | 证据链可追溯（用户能看到推理路径） | ✅ | 每条命中规则带条件追踪；**断环规则 0 条**；`/api/analyze` 直接返回 chain |
| 4 | 冲突规则被正确标注 | ✅ | 值级冲突（Phase 2 已做）+ 本轮补链级披露与强度扣减可审计 |
| 5 | 证据强度计算合理 | ✅ | 13 条**性质**测试：值域、单调性、边际递减、永不饱和、顺序无关、算式自洽 |

### 6.2 验证手段

**变异探针**（每轮后校验文件哈希，零残留）：

| 变异 | 结果 | 变红断言数 |
|------|------|-----------|
| 强度退回「置信度均值」（不看命中条数） | ✅ CAUGHT | 4 |
| 来源回填退回相等判断（复现已修的证据链断环） | ✅ CAUGHT | 3 |
| 主题覆盖退回「登记即覆盖」 | ✅ CAUGHT | 3 |
| 主题覆盖说明置空（不披露「不构成对该主题的判断」） | ✅ CAUGHT | 2 |
| 关系密度阈值漂移（≤2 改成 ≤3） | ✅ CAUGHT | 1 |

**独立事实复核**：240 张命盘，12 个条件键全覆盖，两条独立推导路径零分歧。

**静态检查**：`mypy` 恒为 **4 条既有告警，零新增**（用 `git worktree` 对 HEAD 基线逐条核对）。

### 6.3 强度与覆盖实测

```text
1990-02-01 12:00  structure  covered    13 条  raw 11.5 → 0.7931 − 0.00 = 0.7931
1990-02-01 12:00  事业        base_only  13 条  raw 11.5 → 0.7931 − 0.00 = 0.7931
1990-02-01 12:00  炒股能不能发财  unknown    13 条  raw 11.5 → 0.7931 − 0.00 = 0.7931
1990-06-15 14:30  structure  covered    10 条  raw  9.1 → 0.7521 − 0.00 = 0.7521
2024-02-04 16:45  structure  covered    13 条  raw 11.5 → 0.7931 − 0.30 = 0.4931
```

最后一行是 2024 立春当日的命盘：两法定格分歧触发 2 处冲突，强度从 0.7931 扣到 0.4931。**同一张命盘，问「结构」和问「事业」拿到的基础层证据相同，但覆盖状态不同** —— 这正是本轮要表达的区分。

单盘命中规则数：8–17 条，均值 11.8。

---

## 7. 构建结果

- `.venv`（管理版 Python 3.13.12）正常；无新增第三方依赖。
- 全量测试可重复运行，无 flaky。
- 服务按老板要求**保持停止**，本轮未对外发布任何内容。

---

## 8. 已知问题

1. **主题层仍为空**。`career` / `marriage` / `health` / `wealth` 四个主题一条规则都没有，全部 `base_only`。这是 Phase 2 阻塞点的延续，不是本轮引入的问题 —— 但本轮把它的**可见性**做出来了：以前它会伪装成「事业分析」，现在它老实说「不构成对该主题的判断」。

2. **强度常量是选定的标度**。`SATURATION_K = 3.0`、`CONFLICT_PENALTY = 0.15` 没有典籍或统计依据，是本实现为了满足 §2.5 那组性质选的。性质测试不断言具体数值，就是为了让「调标度」和「模型坏了」可以区分。**它不是概率，不能读成「73% 会发生」。**

3. **管道准确率 100% 不等于命理正确**。口径见 §2.7。这个数字只说明两条独立推导路径一致。

4. **`day_master_same_element_level` 的分档阈值（2 / 4）是本实现选定的**，量级约 13 项。已在 `facts.py` 模块文档里写明，未声称是唯一口径。

5. **`mypy` 4 条既有告警**（均非本轮引入）：`engines/bazi/golden.py` 1 条、`engines/bazi/sxtwl_provider.py` 3 条。可读性问题，不影响运行。

---

## 9. 未实现功能

- **主题层规则（0 条）**：等底本确认。
- **条件表达力**：当前 condition 是 `{键: 值}` 的平坦相等/包含匹配。规则一多可能需要与/或/嵌套，但**现在不做** —— 避免条件 DSL 在需求明确前膨胀。
- **`Evidence.schools` 目前恒为单元素**：典籍层落地后才会出现多流派并列，届时要补「流派分歧」的展示层。
- **事实置信度 `Fact.confidence` 恒为 1.0**：结构事实是确定性的，这个字段留给「需要模糊判断的事实」（如旺衰强弱评分），当前未使用。
- Phase 4（Reasoning Agent 接真实 LLM）、Phase 5（Critic 双模型）、Phase 6（Time Engine）、Phase 7（Evaluation）未开始。

---

## 10. 下一阶段建议

### 10.1 阻塞点仍在：典籍底本需要老板拍板

Phase 2 提出的问题没有变化，且**现在它是系统里唯一挡在「能回答实质问题」前面的东西**：证据层已经能追溯、能解释强度、能如实报告覆盖；主题层没有规则，是因为没有可核验的原文。

需要的输入：一个可获取、可引用页码或章节的**公有领域底本**（注明版本与出处）。

### 10.2 不阻塞、建议优先做的

1. **Phase 4：接真实 LLM provider**。Analyst/Critic 的契约已经稳固，而且现在的约束是**可测试的**：LLM 只能引用 `evidence.chain` 里出现过的规则 ID 与条件，越过边界会被 Critic 拦下。可以先做一个「只用证据链、不许自由发挥」的 prompt 契约 + 假 provider 测试。
2. **Phase 5：Critic 的检查项补全**。计划列了 6 项。当前覆盖 3 项 —— 规则跳跃（结论声称有规则但证据为空 / 无法追溯的规则引用）、确定性表述、流派冲突；本轮另加了 3 项（证据链断环、引用未校核规则、未披露主题覆盖不足）。**仍缺 2 项**：「证据支持度」（现在有 `strength` 和 `strength_breakdown`，可以做成「低强度下禁止确定性表述」的硬检查）与「逻辑矛盾」。「编造命盘数据」目前不在 Critic 里，而是由 `tests/test_evidence_audit.py` 的独立复核守着 —— 要不要把它也搬进 Critic，等接了真实 LLM 再定。
3. **Phase 6：Time Engine 的事件窗口**。大运与流月已可用，证据层已可复用，是自然的下一步。

Phase 3 的核心结论：**证据层从「能匹配规则」变成了「能解释自己」** —— 每条结论可以逐跳走回命盘要素，强度算式可以逐项核对，主题覆盖不足会明说而不是伪装。同时它反过来抓出了两个自己写出来的 bug，这说明这套守卫是有鉴别力的，不只是装饰。

**但也要说清楚：证据层再扎实，它回答的仍然只是「命盘里有什么」。** 系统目前不能回答「这意味着什么」，那需要典籍原文，而底本还没定。
