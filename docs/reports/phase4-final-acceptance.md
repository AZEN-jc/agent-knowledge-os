# Phase 4 总验收报告：AI Agent 生产化

**授权范围**：Phase 4 全部子阶段（4.1–4.8）+ 4.9 总验收。
**执行分支**：`hardening/mingli-v1`

| 项 | 值 |
|---|---|
| 起始 SHA（Phase 3 结束） | `6764601` |
| 结束 SHA（Phase 4 工作） | `3e17b49` |
| 分支最终 HEAD（含本报告回填） | `3ed2e27` |
| `master` / `origin/master` | `f108040`，**全程未动** |

本轮八个提交，一个子阶段一个：

```
3e17b49  4.8 prompt injection 与数据泄露测试（含一次真泄露修复）
51ba5af  4.7 provider 契约评估：11 个对抗场景进 CI 门禁
7b537ac  4.6 token 估算、预算硬停、响应缓存与调用记账
a119c59  4.5 provider 故障降级到模板并如实标注
e62f698  4.4 Critic 独立性与证据链断环守卫；API 补两个指纹字段
99850af  4.3 契约指纹——提示词内容与版本号从此能对上
74886dd  4.2 schema 真正被执行，出处白名单提成显式概念
d65b3e1  4.1 接入真实 HTTP provider，契约在传输层重新验一遍
```

---

## 1. 各子阶段做了什么

### 4.1 LLM Provider 契约与接入

新增 `agents/llm.py: HttpLLMProvider`（urllib 实现，**不引 requests** ——
MingLi 运行时只依赖 sxtwl/fastapi/uvicorn/pydantic，不为一个 POST 多加一个
依赖）。测试用本地回环服务器驱动它：不访问外网，但走真实 socket 路径，
因此超时、非 200、非 JSON、连接被拒这些**只在真实传输下出现**的失败
都被覆盖到了 —— 假 provider 验不了这些。

`ProviderError` 把两件事分开：**provider 故障**（该降级）与**代码 bug**
（该响亮地炸）。只捕前者，调用方不用匹配异常消息。

两个本机踩过的坑写进了代码注释：urllib 默认读 `http_proxy`，回环地址走
代理会被拦成连接失败（显式装空 `ProxyHandler`）；以及传输层与模型输出
**两层 JSON 共用 `text` 键名**，直接 `json.dumps(reply)` 会让 `parse_draft`
收到一句中文。

### 4.2 Schema 约束与引用白名单

`DRAFT_SCHEMA` 此前是**装饰**：契约里写着 JSON Schema，`parse_draft` 用的
却是手写的一串 if/else。两份实现各写一遍，改一个忘另一个，契约就悄悄松了。
现在 `schema_issues()` 是唯一的形状校验实现，`parse_draft` 改调它。

出处白名单提成显式概念 `citation_allowlist(evidence)`：此前它只是
`CriticAgent._provenance_issues` 里的一个局部变量，没有任何地方能拿到
「合法 URN 集合」本身。提出来之后白名单内容可以直接断言，且天然是双向的
（证据链里有 URN 的规则必须在集合里；集合里每一项都必须能在证据链里找到）。

### 4.3 Prompt 版本管理

`CONTRACT_VERSION = "2"` 是人手抄的字符串。改了 `SYSTEM_PROMPT`却忘了改
版本号，`contract()["version"]` 照样返回 "2"，而两次分析用的提示词已经
不同了 —— 用户看到同一版本号，实际拿到的是不同的东西。

现在两个版本概念分工：**语义版本**人维护给人看，**内容指纹**机器算给机器看。
指纹覆盖**全部**影响模型行为的输入：提示词正文、schema、边界规则、禁用
词表、强度标记、角标配置、语义版本本身。漏一项，那一项就成了「改了也没人
知道」的暗门 —— 测试逐项验敏感度（monkeypatch 改一个字段 → 指纹必须变）。

`Analysis` 带上两个指纹，模板与 LLM 两条路径都带（模板同样受契约与规则库
影响）。两个指纹一起回答「两次分析结论为什么不同」的第一个问题：输入变了吗。

### 4.4 Critic 独立审查

**逮到一个真缺陷**：`RuleMatch.is_fully_traced` 只写
`all(trace.sources for trace in self.traces)`，空元组会让 `all()` 返回
True —— 「一条 trace 都没有」反而算「完全可追溯」。手工拼一个没有追踪的
`RuleMatch` 就能让 `untraced_rule_ids` 静默为空，证据链看着完整，实际上一环
都没有。已修（`bool(self.traces) and all(...)`）。

15 条测试钉四件事：Critic 构造签名不接受 provider 且实例上没有任何状态；
provider 整个坏掉时审查照样能跑；四类最常见的垃圾各有一条对应检查
（空结论、确定性措辞、低强度不披露、无证据却声称有据）外加越界引用、
编造 URN、缺出处角标、证据链断环；多轮修正有上限，到上限带着未解决的
问题返回，不凑合放行。

顺手补一个 API 缺口：`DraftResponse` 没声明两个指纹字段，被
`extra="ignore"` 静默裁掉 —— 服务层产出了，API 侧却看不到。补进响应模型
后 API 响应与服务层响应逐字段一致。这是本轮唯一一处公开响应变更：**纯增
字段**，既有消费者不受影响。

### 4.5 Provider 故障恢复与降级

provider 抛 `ProviderError` 时降级到确定性模板出稿，原因写进
`degraded_reason`。**不伪装成分析成功**：用户看得见这次没走模型，也看得见
为什么。反过来只捕 `ProviderError` —— 把代码 bug 降级成「provider 故障」
是最坏的失败模式，用户看到一次正常的降级，而真正的 bug 再也没有人发现。

### 4.6 并发、Token、成本与缓存治理

- **token 估算**：CJK 每字约 1 token，其余每 4 字符约 1。**是估算不是
  账单** —— provider 契约只取 text，响应里没有用量字段。实测首请求约
  6067 token。
- **预算硬停**：`DEFAULT_TOKEN_BUDGET = 30000`。超预算时降级，原因说清是
  「花超了」而不是「连不上」—— 两种原因的处置完全不同。意义不是省这
  一次，是**给失控一个硬停**：调用次数可以配、提示词会随证据增长，
  两者相乘没有上限。
- **响应缓存**：按 `(system, user)` 全量命中。提示词是证据链的确定性
  函数，同样的输入本该得到同样的输出。模型可能不确定，所以缓存命中必须
  **看得见**（`served_from_cache`）。上限 256 条 FIFO；`analyze_multi`
  用线程池扇出，「淘汰最早一条」是读-改-写三步，所以有锁。
- **记账**：`prompt_tokens` / `completion_tokens` / `provider_calls`
  分别报得出来，缓存命中不计。

**逮到一个真缺陷**：第一版 `_template_analysis` 不带记账参数，于是
「第 2 轮超预算降级」时返回的 Analysis 里 `provider_calls=0`、
`prompt_tokens=0` —— 可第一次调用真的发生了、真的花了 6085 token。
**治理字段在最需要看成本的那一刻归零，比不报更糟。**

### 4.7 多模型契约评估

按 Phase 3 报告 §10 的反建议（不要在一个 provider、一条契约、一个白名单
都没稳定之前引入多模型），本模块**不联网、不需要 API key**，提供的是
评估框架：

- **11 个对抗场景**：每个用脚本化假 provider 演出一种典型模型失控
  （越界引用、编造出处、必然性措辞、空结论、契约外字段、非 JSON、
  类型错误、缺典籍角标、provider 故障、预算耗尽），断言系统确实拦住了。
- **`evaluate_live_provider`**：给真 provider 的入口。传入任何
  `LLMProvider` 实例，跑中性分析，逐条检查同一套不变量加治理字段。
  换模型 = 换一个实例重跑，函数不用改。

**评估器自己也要被验**（反自证）：两条「有牙」测试把 Critic neutered、
把白名单改成什么都允许，对应场景必须失守。测不出守卫失效的 11/11
只是装饰。已进 CI 作为第五道门禁。

### 4.8 Prompt injection 与数据泄露测试

防御立场：**不指望模型抵抗注入，只保证它被劫持也做不了恶**。用户的
问题原样进入提示词（证据链 JSON 的 `topic` 字段）—— 那是数据不是指令，
但数据里可以写「忽略以上指令」。所以注入用例演的全是「模型**真的听话
了**」，然后断言三道闸仍然拦得住。

**顺手修一个真泄露口**：provider 的连接失败会变成 `degraded_reason`
显示给**终端用户**，而有些 API 把密钥放在 URL 查询参数里。原来消息带
完整 endpoint —— 一次连接失败就把运营方的密钥摆到用户眼前。新增
`_redact_endpoint`：报错里只留 `scheme://host:port`。削的是显示不是
连接。构造期那条「endpoint 必须是 http(s) 地址」**故意不削**：它的
受众是运营方自己，报错要能照着改配置。

泄露边界按**字节**验，且只查能真正标识生辰的形态（完整日期、结构化
字段的值与键名）—— 第一版把 `year/month/day/hour` 也列进禁用词，
全数命中，因为证据链的事实键本来就叫 `day_master` / `month_branch` /
`hour_pillar`，那是命盘语义不是出生数据。

---

## 2. 文件变更与原因

| 文件 | 动作 | 原因 |
|---|---|---|
| `agents/llm.py` | +150 | `HttpLLMProvider`、`ProviderError`、`estimate_tokens`、`_redact_endpoint` |
| `agents/prompt.py` | +120 | `schema_issues` 单一实现、`citation_allowlist`、`contract_fingerprint` |
| `agents/mingli.py` | +260 | 降级路径、记账、缓存、预算；`is_fully_traced` 修复 |
| `runtime/mingli_service.py` | +25 | `token_budget` 透传、治理字段进响应 |
| `api/server.py` | +40 | `DraftResponse` 补四个治理字段；docstring 补降级说明 |
| `evaluation/provider_conformance.py` | **新增** 517 | 契约评估框架 |
| `tests/test_llm_provider_http.py` | **新增** | provider 真实传输行为 |
| `tests/test_llm_end_to_end.py` | **新增** | 三层各司其职的端到端 |
| `tests/test_citation_allowlist.py` | **新增** | 白名单双向断言 |
| `tests/test_prompt_versioning.py` | **新增** | 指纹敏感度逐项验 |
| `tests/test_critic_independence.py` | **新增** | Critic 独立性与四类垃圾 |
| `tests/test_provider_degradation.py` | **新增** | 降级与「不该降级的不降」 |
| `tests/test_provider_governance.py` | **新增** | token/预算/缓存/记账 |
| `tests/test_provider_conformance.py` | **新增** | 评估器的反自证 |
| `tests/test_prompt_injection.py` | **新增** | 注入与泄露 |
| `.github/workflows/ci.yml` | 改 | 契约门禁进 CI |
| `AGENTS.md` | 改 | 契约门禁命令与两个门禁的分工 |

测试数从 Phase 3 末的 1204 增至 **1331**（+127），零既有失败被改坏。

---

## 3. 关键技术决策

1. **不接真 API，先固化评估框架。** 真 provider 的接线需要密钥与运营方
   决策，而框架（对抗场景 + live 入口）不依赖它们就能把红线钉住。
   Phase 3 §10 的反建议在这里兑现为具体形态。
2. **降级而不是抛异常。** 排盘、规则、证据链全是确定性的，它们没坏；
   坏的只是复述那一步。让用户什么都拿不到，比让他拿到一份标明「本次
   未走模型」的分析更糟。
3. **指纹代替手抄版本号。** 人抄的字符串必然漂移；内容指纹让「改了
   提示词却忘了改版本」这类漂移有机器能发现。
4. **schema 只有一份实现。** 两份校验必然漂移，而漂移不报错。
5. **缓存命中必须看得见。** 模型可能不确定，同一个提示词两次调用可能
   得到不同输出；把旧结果当新结果交付而不说明，是一种隐蔽的不诚实。
6. **治理字段在降级时不许归零。** 花了钱的那一次调用，记账必须活下来。

---

## 4. 五道门禁实测

环境：隔离的 Python 3.12.13（`/tmp/mingli-venv312`）。`ruff .` / `mypy .`
均在仓库根下执行。

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `python -m pytest tests/ -q` | **0** | `1331 passed in 476.59s` |
| 2 | `python evaluation/runner.py --json` | **0** | `{"total":30,"passed":30,"failed":0,"accuracy":1.0}` |
| 3 | `python evaluation/provider_conformance.py --json` | **0** | `{"total":11,"passed":11,"failed":0,"accuracy":1.0}` |
| 4 | `ruff check .` | **0** | `All checks passed!` |
| 5 | `mypy .` | **0** | `no issues found in 110 source files` |

**五道全部 exit 0，零失败、零 xfail。**

---

## 5. 已知问题与回归风险

### 5.1 已知限制（如实声明）

1. **没有接真 provider。** `HttpLLMProvider` 就绪但未对任何真实端点跑过 ——
   那需要密钥与运营方决策。接上后的第一件事应是跑
   `evaluate_live_provider` 拿一份该模型的契约合格性报告。
2. **token 是估算不是账单。** 口径写在 `estimate_tokens` 的 docstring 里，
   只用于预算触发，不用于对账。
3. **问题原文会进提示词**（作为证据链 JSON 的 `topic` 字段）。模型需要
   知道问的是什么，所以这是必要的；但意味着**不要把口令、密钥写进问题
   框**。上限 200 字已由 API 层强制。
4. **响应缓存是进程内的。** 多 worker 部署时每个 worker 各有一份缓存，
   命中率下降但正确性不受影响（键是完整提示词，不存在串数据）。
5. **Phase 3 的已知限制全部继承**：1583 年前月柱按前推格里高利历解释、
   `year` 策略边界 2–9997、`BirthInput` 分钟精度、大运八步上限、
   时间轴层不做冲突检测、典籍层仍 13 条。

### 5.2 回归风险

本轮运行行为变化有五处，全部有测试钉住：

1. `is_fully_traced` 要求 traces 非空（原为空也算「完全可追溯」）——
   这是**修缺陷**，回滚它会让 4.4 的测试重新变红，那是预期的。
2. provider 故障从「异常上抛」变成「降级 + 标注」。API 的 422 路径仍在，
   但只有降级本身也失败时才走。
3. 治理字段进入响应（四个新字段，纯增）。
4. 预算默认 30000 token，正常分析（约 6000/次）不受影响。
5. 缓存使命重复请求的结果来自上一次调用 —— `served_from_cache` 让这
   一点可见。

---

## 6. 远端 CI

### 6.1 推送结果

本轮**全部 9 个提交**一次推送成功（8 个子阶段 + 本报告自己）：

```
6764601..3ed2e27  hardening/mingli-v1 -> hardening/mingli-v1
```

远端 `refs/heads/hardening/mingli-v1` = `3ed2e27`，与本地 HEAD 一致。
`master` / `origin/master` 仍为 `f108040`，**全程未动**。

### 6.2 GitHub Actions

推送触发 run `39764528306`（对应 `3ed2e27`），**结论 success**：

```
JOB: 测试 · 评估 · 静态检查 | success
   4. 安装依赖                        → success
   5. ruff check .                   → success
   6. pytest                         → success   ← 1331 passed
   7. 评估门禁（行为不变量）          → success   ← 30/30
   8. 契约门禁（provider 对抗场景）   → success   ← 11/11，Phase 4.7 新增
   9. mypy .                         → success   ← 阻塞门禁
```

运行链接：https://github.com/AZEN-jc/agent-knowledge-os/actions/runs/39764528306

**第 8 步是本轮新增的门禁**，它失败会直接让整个 run 变红 —— 也就是说
「provider 契约被破坏」从「测试可能没覆盖」变成了 CI 事实上的拦截项。

分支上最近三次运行全部 success：

| Run ID | SHA | 结论 |
|---|---|---|
| [39764528306](https://github.com/AZEN-jc/agent-knowledge-os/actions/runs/39764528306) | `3ed2e27` | success |
| [39549874384](https://github.com/AZEN-jc/agent-knowledge-os/actions/runs/39549874384) | `6764601` | success |
| [39549498351](https://github.com/AZEN-jc/agent-knowledge-os/actions/runs/39549498351) | `84ddb43` | success |

### 6.3 两个 SHA 的说明

**Phase 4 工作的结束 SHA 是 `3e17b49`**（4.8 提交）；本节的回填本身也是
一次提交（`3ed2e27`），同样通过 CI。与 Phase 3 报告同一约定。

---

## 7. 回滚方案

分支已推送，以下都以**不复写已推送历史**为前提。

```bash
git checkout hardening/mingli-v1
git revert 3e17b49   # 4.8 注入与泄露（含 _redact_endpoint 安全修复）
git revert 51ba5af   # 4.7 契约评估
git revert 7b537ac   # 4.6 治理
git revert a119c59   # 4.5 降级
git revert e62f698   # 4.4 Critic 独立性 + API 指纹字段
git revert 99850af   # 4.3 契约指纹
git revert 74886dd   # 4.2 schema 与白名单
git revert d65b3e1   # 4.1 HTTP provider
```

**三处不建议单独回滚**，它们修的是真缺陷/真泄露：`is_fully_traced`
（4.4）、降级记账（4.6）、`_redact_endpoint`（4.8）。回滚它们对应测试会
重新变红 —— 那是守卫在说话。

验证回滚是否干净：

```bash
git status --porcelain                    # 应为空
python -m pytest tests/ -q                # 应回到回滚目标的状态
python evaluation/runner.py --json        # 30/30
python evaluation/provider_conformance.py --json   # 11/11
ruff check . && mypy .                    # 均应 exit 0
```

---

## 8. 未完成工作

按任务书，Phase 4 范围内的八项子阶段已全部完成。以下**不在 Phase 4
范围**，未做：

1. **Phase 5 全部**（用户流程与信息架构、生辰输入体验、命盘可视化、
   证据链与典籍来源浏览器、多主题分析工作台、时间轴交互、PDF/JSON
   导出、隐私删除与数据保留、移动端无障碍 E2E 与视觉回归）。
2. **Phase 6 全部**（可复现构建、密钥配置、部署、健康检查、性能压测
   安全、备份恢复演练、版本管理、文档、V1.0 发布验收）。
3. **真 provider 的接线与试运行**（需要密钥；框架已就绪）。
4. **多流派策略核与紫微子系统**（RFC 已判搁置，条件见
   `docs/reports/phase3-8-multischool-ziwei-rfc.md`）。
5. **扩大典籍录入范围**（仍 13 条，资料问题不是工程问题）。

---

## 9. 下一阶段建议：Phase 5 从哪儿起

Phase 5 的主题是产品体验。按当前系统的形状，建议顺序：

1. **先接一个真 provider 试跑，再动前端。** Phase 4 把契约、守卫、
   降级、治理全部做完了，唯一没验过的就是「真模型在这套闸门前表现
   如何」。拿 `evaluate_live_provider` 跑一份报告，比先做三个页面
   更能决定 Phase 5 的重点。这是运营方决策（密钥），不是工程阻塞。
2. **生辰输入体验优先于命盘可视化。** 输入是唯一会把错误传导到全部
   下游的地方（年份边界 2–9997、历史日期、时区、性别可选），而
   Phase 2.3 已经把约束做成了可展示的中文消息 —— 前端要做的只是
   把这些消息显示对。
3. **证据链浏览器是差异化功能，也是复杂度最高的一屏。** 它直接暴露
   `evidence.chain`（每条规则的条件、命盘出处、强度算式、冲突），
   建议单独一个子阶段做，不要和「多主题工作台」混在一起。
4. **PDF/JSON 导出应带上两个指纹**（`contract_fingerprint` /
   `rule_fingerprint`）与 `degraded_reason` —— 否则一份导出报告无法
   回答「这是用什么版本的提示词和规则库生成的」。

**一条反建议**：不要在 Phase 5 引入前端框架迁移。现有 `static/`
单页已能跑通全链路；任务书也要求「如需迁移先提交技术决策 RFC」。

---

## 10. 验收对账

| 任务书条款 | 状态 | 证据 |
|---|---|---|
| 4.1 真实 LLM Provider 接入 | ✅ | `HttpLLMProvider` + 三层测试；契约先行 |
| 4.2 Schema 约束与引用白名单 | ✅ | `schema_issues` 单一实现 + `citation_allowlist` |
| 4.3 Prompt 版本管理 | ✅ | 契约指纹 + 逐项敏感度测试 |
| 4.4 Critic 独立审查 | ✅ | 15 条测试 + `is_fully_traced` 缺陷修复 |
| 4.5 Provider 故障恢复与降级 | ✅ | 降级 + 明示；只捕 `ProviderError` |
| 4.6 并发、Token、成本、缓存治理 | ✅ | 估算/预算/缓存/记账四项齐全 |
| 4.7 多模型契约评估 | ✅ | 11 场景 + live 入口 + 有牙测试 + 进 CI |
| 4.8 Prompt injection 与数据泄露 | ✅ | 15 条测试 + `_redact_endpoint` 泄露修复 |
| 真实模型只解释证据，不计算命盘 | ✅ | 4.8：问题改不动证据链；提示词无出生信息 |
| 无法验证的引用必须拒绝或标注 | ✅ | 白名单 + 编造 URN 拦截（Phase 3 起） |
| 不把 Provider 失败伪装成分析成功 | ✅ | 4.5 降级明示 + 4.7 `provider_unreachable` 场景 |
| 四条质量门禁 exit 0 | ✅ | §4：五道全 0 |
| 生成 `phase4-final-acceptance.md` | ✅ | 本文件 |
| 提交并推送，核验该 SHA 对应远端 CI | ✅ | §6：9 个提交推送成功，run `39764528306` success，含新增契约门禁 |
| 不自动进入 Phase 5 | ✅ | Phase 5 一行代码未动 |
