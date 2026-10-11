# Phase 4 验收报告

**项目名称**：MingLi Agent（命理智能体）
**阶段**：Phase 4 - Reasoning Agent（推理智能体）
**完成日期**：2026-10-11
**状态**：⚠️ **部分完成** —— 契约层与多轮修正已完成并通过验收；**真 provider 未接**（原计划三项交付之一）

---

## 1. 修改了什么

计划里 Phase 4 的交付有三项：**真实 LLM provider、报告生成、多轮修正**。本轮做完的是后两项的**离线部分**，第一项**没做** —— 原因见 §2.1，不接真 provider 是刻意的选择，不是遗漏。

**新增能力**

| # | 能力 | 落点 |
|---|------|------|
| 1 | **提示契约**：模型只能看到证据链，输出只能是 `{rule_ids, text}` | `agents/prompt.py` |
| 2 | **越界引用记名**：chain 之外的规则 ID 被剔除并逐条记入 `contract_violations` | `parse_draft` |
| 3 | **provider 协议 + 假 provider**：脚本队列，脚本用尽**抛错**而非兜底 | `agents/llm.py` |
| 4 | **多轮修正**：Critic 不过 → issues 回灌重写，上限 2 轮，逐轮留痕 | `AnalystAgent._draft` |
| 5 | **契约可审计**：`GET /api/llm/contract` 把系统提示词、schema、边界规则、禁用词表作为数据返回 | `api/server.py` |

**修掉一个 Phase 3 的真缺陷**

Critic 的冲突检查写的是「**有冲突就拦**」，而它拦的不是「没披露」，是「存在冲突」这件事本身 —— 而冲突是命盘的真实情况，不是缺陷。`_summarise` 明明写了「存在 N 处规则分歧，需并列披露，不做取舍」，照样被拦下。实测 10 个验收案例里有 **3 个**因此判不过。

改为与主题覆盖同一口径：**查披露，不查存在**（`CONFLICT_MARKERS = ("分歧", "冲突")`）。这个缺陷是 Phase 3 遗留的，由 Phase 4 的验收案例第一次暴露出来 —— 单元测试没发现它，因为原来的单元测试只验了「有冲突时会被拦」，没有验「披露之后应该放行」。

---

## 2. 为什么修改

### 2.1 为什么不接真 provider（§1 的第一项交付为什么没做）

计划 §3 的验收标准 5 是「通过 10 个测试案例」，标准 1-3 全都能在**离线**条件下验证。而接真 provider 会引入三个我无法在此刻替老板决定的东西：

1. **密钥**：需要老板提供 OpenAI 兼容的 base_url + key。
2. **联网**：本机出网依赖 Clash 处于运行状态（见 Phase 2 报告），CI/测试会因此变得不确定。
3. **口径**：用哪个模型、温度多少、token 上限多少 —— 这些直接决定措辞风格，而措辞风格正是 Critic 检查的对象。

**更关键的是：先接模型会让契约失去焦点。** 契约的价值在于「越界必被拦」，这跟模型强不强无关。模型接上之后再补契约，测试会退化成「跑一遍看看」，而不是「拆掉守卫看它红不红」。先把边界钉死、用假 provider 全量覆盖，再接真模型，是更省事也更可靠的顺序。

所以本轮的交付边界是：**provider 协议 + 契约 + 多轮修正 + 10 个案例**，全部离线、全部确定性、全部可测。

### 2.2 为什么「不许自由发挥」要分三层

只在系统提示词里写「不要编造」是**没有约束力的** —— 它依赖模型配合，而且无法测试。所以拆成三层，每层都落在一个可以失败的地方：

| 层 | 机制 | 失效时会怎样 |
|----|------|-------------|
| 输入层 | `build_prompt(evidence: Evidence)` —— **签名里没有 `Chart`** | 有人加 `chart` 参数，`test_build_prompt_cannot_receive_a_chart` 立刻红 |
| 输出层 | 只接受两个键的 JSON，多键/缺键/类型错都记违约 | `test_parse_draft_rejects_extra_fields` 等 8 条 |
| 边界层 | chain 之外的 ID 剔除 + 逐条记名 + Critic 独立复算 | 变异探针 P1/P2 各 2-3 条红 |

**边界层的「独立复算」不是多余。** `parse_draft` 已经过滤过一次越界引用，但那个保证只对「走 `parse_draft` 的路径」成立。换一个 provider 适配层时若漏掉这一步，`contract_violations` 会是空的 —— 而复算仍然拦得住。两处口径必须一致，所以复算只报「违约记录里没提过」的那些，避免同一件事被说两遍。

### 2.3 为什么越界引用要「剔除 + 记名」而不是抛异常

抛异常会让调用方只剩两个选择：**整个失败**，或**静默放行**。两者都错：

- 整个失败：一次措辞失误就让整份分析拿不到，用户看不到证据。
- 静默放行：模型编造规则 ID 这件事永远没人知道 —— 这是最坏的情况。

正确做法是第三条路：把违约当作**可披露的事实**带下去，让 Critic 把它变成用户看得见的意见。越界引用因此不会消失，只会被记名。

### 2.4 为什么假 provider 脚本用尽要抛错

假 provider 是全部离线测试的地基。如果它在脚本用尽时返回一段兜底文案，「少写了一条脚本」就会表现成「测试通过」—— 测试看着很绿，实际什么都没验。这是最坏的失败模式，所以宁可抛错。

### 2.5 为什么「低强度必须披露强度」

不是「强度低就不许说话」，而是「强度低时不许**不说**强度」。读者看到一句没有强度标注的结论，会默认它很硬；而 0.30 和 0.79 的证据厚度完全不同。

用固定短语 `证据强度` 做判据而不是数值，是因为数值的书写形式（`0.4` / `0.40` / `四成`）无法可靠匹配 —— 而判据一旦不可靠，检查就会变成误报机器。

---

## 3. 文件清单

**新增（5）**

| 文件 | 行数 | 职责 |
|------|------|------|
| `agents/llm.py` | 70 | `LLMRequest` / `LLMProvider` 协议 / `FakeLLMProvider` |
| `agents/prompt.py` | 293 | 契约：`build_prompt` / `build_revision_prompt` / `parse_draft` / `contract` |
| `tests/test_llm_contract.py` | 304 | 契约层测试（32 条） |
| `tests/test_llm_provider.py` | 78 | provider 协议与假 provider（8 条） |
| `tests/test_phase4_cases.py` | 119 | 10 个验收案例 × 两条路径（31 条） |
| `tests/cases/mingli_phase4_cases.json` | 80 | 案例数据 |

**修改（5）**

| 文件 | 变更 |
|------|------|
| `agents/mingli.py` | `Analysis` 加 7 个字段；Analyst 加 provider 路径与多轮修正；Critic 加 4 项检查、修 1 项 |
| `runtime/mingli_service.py` | 支持注入 provider；响应加 `draft` 元信息 |
| `api/server.py` | `DraftResponse` / `LLMContractResponse`；`GET /api/llm/contract` |
| `tests/test_mingli_agents.py` | 7 → 25 条 |
| `tests/test_api.py` | 21 → 25 条 |

`git diff --stat`：**11 files changed, 1529 insertions(+), 19 deletions(-)**。

---

## 4. 数据结构

```python
@dataclass(frozen=True)
class LLMRequest:            # agents/llm.py
    system: str
    user: str

@dataclass(frozen=True)
class Draft:                 # agents/prompt.py
    text: str
    cited_rule_ids: tuple[str, ...] = ()   # 已通过边界校验的
    violations: tuple[str, ...] = ()       # 被拒的引用与结构问题

    @property
    def is_conforming(self) -> bool: return not self.violations

@dataclass(frozen=True)
class Analysis:              # agents/mingli.py —— 新增 7 个字段（均有默认值，向后兼容）
    question: str
    evidence: Evidence
    conclusion: str
    certainty_risk: bool = False
    cited_rule_ids: tuple[str, ...] = ()
    draft_source: str = "template"         # template | llm
    provider: str = ""
    model: str = ""
    revisions: int = 0
    contract_violations: tuple[str, ...] = ()
```

契约常量（`agents/prompt.py`，全部经 `/api/llm/contract` 暴露）：

| 常量 | 值 | 说明 |
|------|-----|------|
| `CONTRACT_VERSION` | `"1"` | |
| `DRAFT_KEYS` | `("rule_ids", "text")` | 多一个少一个都算违约 |
| `CERTAINTY_WORDS` | 7 个（一定/必然/注定/肯定/绝对/毫无疑问/铁定） | Phase 3 只有 2 个 |
| `STRENGTH_MARKER` | `"证据强度"` | 低强度下必须出现 |
| `LOW_STRENGTH_CEILING` | `0.5` | |
| `MAX_REVISIONS` | `2` | |

---

## 5. API

**新增**

```
GET /api/llm/contract
```

返回 `version` / `system_prompt` / `draft_schema` / `boundary`（6 条）/ `forbidden_certainty_words` / `strength_marker` / `low_strength_ceiling` / `notes`。

**变更**：`POST /api/analyze` 的 `analysis` 增加 `draft` 块：

```json
"draft": {
  "source": "template",
  "provider": "", "model": "",
  "revisions": 0,
  "cited_rules": ["STRUCT_DM_ROOT_001", "..."],
  "contract_violations": [],
  "certainty_risk": false
}
```

`draft.cited_rules` 是「结论能追溯到具体规则」这条验收标准的**机器可读形式**：它是 `evidence.chain` 里规则 ID 的子集，可以断言，不用人去读文本比对。

**注意**：API 的默认服务**不注入 provider**，所以线上 `source` 恒为 `template`。这是刻意的 —— 也**没有** `MINGLI_LLM_*` 环境变量开关（原方案里提过，实际没做）。没有开关，就没有「以为开了其实没开」的空间。

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| 全量 pytest | **860 passed**（Phase 3 为 768，**+92**） |
| ruff | `All checks passed!` |
| mypy | **4 errors / 2 files**，与 HEAD 基线**逐条相同**（源文件 97 → 99） |
| 变异探针 | **5/5 CAUGHT，零残留**（逐文件 sha256 复核） |

**变异探针明细**（脚本 `/tmp/ako_p4_mutation.py`，跑完自动还原并复核哈希）

| 探针 | 拆掉的守卫 | 结果 |
|------|-----------|------|
| P1 | 越界 ID 不再过滤（只记名） | CAUGHT — 2 failed |
| P2 | 越界 ID 不再记名（静默丢弃） | CAUGHT — 3 failed |
| P3 | 删掉低强度强制披露 | CAUGHT — 1 failed |
| P4 | 冲突检查退回「有冲突就拦」 | CAUGHT — 10 failed |
| P5 | 多轮修正被短路（一轮都不重写） | CAUGHT — 4 failed |

P4 一次红 10 条，正说明 §1 里那个缺陷的影响面：它会把「有格局分歧」的命盘全部判成审查不通过。

**10 个验收案例**（`tests/cases/mingli_phase4_cases.json`）

| ID | 问句 | 命中规则 | 强度 | 主题状态 | 冲突 | 模板路径 | provider 路径 |
|----|------|---------|------|---------|------|---------|--------------|
| P4-01 | 命盘结构 | 13 | 0.7931 | covered | 0 | ✅ | ✅ |
| P4-02 | 事业 | 13 | 0.7931 | base_only | 0 | ✅ | ✅ |
| P4-03 | 婚姻 | 10 | 0.7391 | base_only | 0 | ✅ | ✅ |
| P4-04 | 健康 | 11 | 0.7656 | base_only | 0 | ✅ | ✅ |
| P4-05 | 财运 | 11 | 0.7600 | base_only | 0 | ✅ | ✅ |
| P4-06 | 事业 | 13 | **0.4931** | base_only | **2** | ✅ | ✅ |
| P4-07 | 风水 | 11 | 0.7656 | **unknown** | 0 | ✅ | ✅ |
| P4-08 | 命盘结构 | 11 | 0.7656 | covered | 0 | ✅ | ✅ |
| P4-09 | 婚姻 | 11 | 0.6156 | base_only | **1** | ✅ | ✅ |
| P4-10 | 事业 | 12 | 0.6227 | base_only | **1** | ✅ | ✅ |

每条案例在两个路径下都断言：命中数 ≥ 8、强度 ≥ 0.4、主题状态与预期一致、冲突数达标、`cited_rules ⊆ chain`、结论披露强度、非 covered 时原样带上 `coverage_note`、Critic 通过。provider 路径额外断言：首次请求的 `user` 逐字节等于证据链 JSON、合规草稿 `revisions == 0`（不该触发重写）。

---

## 7. 构建结果

- `python -c "import api.server"` 正常；`GET /api/health` 返回 `{"status":"ok","provider":"sxtwl"}`。
- 服务按老板要求**保持停止**，项目**未对外发布**。
- 全部测试**离线**运行，不联网、不需要密钥。

---

## 8. 已知问题

1. **真 provider 未接**，`Analysis.provider` 在生产路径下恒为空字符串。
2. **`_strip_fence` 是唯一的宽容处理**：模型用 Markdown 围栏包住 JSON 时会自动剥掉。这是有意为之（围栏是书写习惯，不是内容），但它确实是「对模型输出的一次妥协」。它不碰 `rule_ids`，所以越界校验照旧。
3. **契约的「不许预测」只能靠禁用词表拦**。模型完全可以用「大概率」「倾向于」绕开 7 个禁用词。词表是必要条件，不是充分条件。
4. **多轮修正没有收敛保证**。上限 2 轮，到顶就带着未解决的问题返回 —— 这是刻意的（不做「最后一次凑合放行」），但意味着模型持续不合规时，用户会看到一份带问题的结论。
5. **`certainty_risk` 与 Critic 的检查是两处独立计算**。目前口径一致（同一个词表），但将来改词表时两处都要改。

---

## 9. 未实现功能

| 项 | 说明 |
|----|------|
| 真 LLM provider | 计划 §3 的第一项交付。需要 base_url + key + 联网 |
| 真 provider 的请求构造/响应解析单测 | 依赖上一条 |
| 环境变量开关 | 原方案里提过，实际没做 —— 见 §5 |
| 流式输出 / 重试 / 超时 | provider 接口刻意做窄（只有 `complete`），这些留给接线时再定 |
| Critic 缺的 2 项检查 | 「证据支持度」（已有 `strength` 可做成硬检查）、「逻辑矛盾」—— 属 Phase 5 |

---

## 10. 下一阶段建议

### 10.1 阻塞点仍在：典籍底本需要老板拍板

从 Phase 2 挂到现在，**没有变化，且它仍然是系统里唯一挡在「能回答实质问题」前面的东西**。主题层规则数**仍是 0**。

Phase 4 做的是管道加固：现在模型能看到的只有证据链，越界必被拦。但证据链里装的仍然只是「命盘里有什么」。系统**依然不能回答「这意味着什么」**，那需要典籍断语，而底本还没定。

需要的输入：一个可获取、可引用页码或章节的**公有领域底本**（注明版本与出处）。

### 10.2 不阻塞、建议优先做的

1. **Phase 4B：接真 provider**。契约层已经稳固且**可测试**，接线的风险已经降到最低：模型越界会被记名、会被 Critic 披露、会被变异探针覆盖。需要老板给 base_url + key，并允许联网。
2. **Phase 5：Critic 的检查项补全**。计划列了 6 项，当前覆盖 3 项，本轮另加 4 项（契约违规、结论为空、低强度未披露强度、越界引用复算）。**仍缺 2 项**：「证据支持度」与「逻辑矛盾」。
3. **Phase 6：Time Engine 的事件窗口**。大运与流月已可用，证据层已可复用，是自然的下一步。

Phase 4 的核心结论：**「不许自由发挥」从一句口号变成了三层可以失败的地方** —— 输入层的类型签名、输出层的 schema、边界层的记名与复算。而且它反过来抓出了一个 Phase 3 遗留的缺陷（冲突检查口径错误，影响 3/10 个验收案例），这说明这套守卫有鉴别力，不只是装饰。

**但同样要说清楚：模型现在只能复述证据链，而证据链回答的仍然只是「命盘里有什么」。** 把措辞交给模型，并没有让系统多知道一件命理知识 —— 它只是把同一件事说得更像人话。真正的下一步仍然是底本。

---

## 附：验收标准对照（MINGLI_PLAN.md §3.4）

| # | 计划原文 | 本轮结论 |
|---|---------|---------|
| 1 | 推理结论能追溯到具体规则 | ✅ 机器可验：`draft.cited_rules ⊆ evidence.chain`，两条路径都断言 |
| 2 | 不引用不存在的规则 | ✅ 假 provider 故意返回伪造 ID → 剔除 + 记名 + Critic 拦下（`test_out_of_chain_rule_is_stripped_and_the_critic_says_so`） |
| 3 | 证据强度合理 | ⚠️ **部分**。沿用 Phase 3 的 `score_strength`；新增「低强度必须披露强度」（`< 0.5` 时结论须含 `证据强度`）。**但**「一定/必然/注定」是**任意强度**都禁用，不是只在低强度下禁用 —— 措辞的确定性不该由强度授权 |
| 4 | 回答与问题相关 | ⚠️ **只能验到披露义务**。主题层零规则，「事业」问句必须返回 `base_only` + `coverage_note`，不许伪装成事业判断。**「相关性」本身无法验证** —— 没有规则就没有相关性可言 |
| 5 | 通过 10 个测试案例 | ✅ 10 个案例 × 2 条路径，共 31 条测试 |

第 3、4 条按原计划的口径**做不到**，实际交付的是比原口径更弱但可验证的版本。这一点如实列出，不按「全部通过」记。
