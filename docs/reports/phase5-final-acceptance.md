# Phase 5 验收报告：完整产品体验

子任务：5.1 用户流程与信息架构 → 5.9 移动端、无障碍、E2E 与视觉回归。
本报告按阶段统一执行流程的九节要求写，另附逐项验收表。

**先说一句必要的背景**：Phase 5.1/5.2 的第一版（2026-10-22 深夜，提交
`6c5eaa6`）只存在于当时的工作副本，未推送即随沙箱清理销毁，内容不可恢复。
本阶段的 5.1 与 5.2 是**从远程权威状态 `081f6dc` 重新做的一版**，不是
对旧版的修订。旧版做过什么已不可考；本报告里的每个数字都来自本轮实际
执行的命令。

---

## 1. 起始与结束 SHA

| 项 | 值 |
|---|---|
| 起始 SHA（Phase 5 开始前） | `081f6dc`（Phase 4 总验收回填） |
| 5.1 用户流程与信息架构 | `7650084` |
| 5.2 后端：真太阳时贯通 | `036b6a3` |
| 5.2 后端：422 字段级错误 | `6b606c7` |
| 5.2 前端：输入体验 | `845b37a` |
| 5.2 测试：契约 + E2E + CI | `6ef8fb1` |
| 5.3 命盘可视化 | `8a25ed5` |
| 5.4 典籍来源浏览器 | `38f628a` |
| 5.5 多主题工作台 | `b004950` |
| 5.6 时间轴交互 | `0484010` |
| 5.7 报告导出 | `2bba4ee` |
| 5.8 隐私与保留策略 | `f37f804` |
| 5.9 移动端/无障碍/视觉回归 | `29e7d76` |
| **Phase 5 结束 SHA** | **`29e7d76`** |
| 工作分支 | `hardening/mingli-v1` |
| `master` / `origin/master` | `f108040`，**全程未动** |

---

## 2. 修改文件与变更原因

### 2.1 后端（8 个文件）

| 文件 | 变更 | 原因 |
|---|---|---|
| `api/server.py` | `true_solar_time` 字段与校验、`_birth_fields`、422 `fields` 数组、`RuleResponse.urn`、`/api/report` | 5.2/5.4/5.7 的三处缺口：口径开关没暴露、错误无法定位到输入框、URN 在 API 层被静默裁掉 |
| `runtime/mingli_service.py` | `_calculator_for`、三个方法加 `true_solar_time` 关键字参数 | 口径是请求级的，服务实例要同时服务两种口径 |
| `runtime/report.py` | 新增：组报 + JSON/PDF 渲染 | 5.7 的导出层；只做组报与排版两件事 |
| `engines/bazi/ten_gods.py` | `ELEMENT_NAMES`、`DOMINANT_THRESHOLD`、`element_census` | 五行普查收成单一事实源 |
| `engines/bazi/sxtwl_provider.py` | 版本后缀 `+tst`、`chart.elements` 带普查 | 口径可复现；UI 读的键必须真实存在 |
| `knowledge/facts.py` | 改用 `element_census`，删掉自己数一遍的实现 | 两份实现对不上只是时间问题 |
| `knowledge/structural_rules.py` | 直引 `ten_gods.ELEMENT_NAMES` | 转口链每多一环多一处会断的地方 |
| `requirements.txt` / `pyproject.toml` | `reportlab==5.1.0` | PDF 导出 |

### 2.2 前端（1 个文件，改动最大）

`static/index.html`：分钟与真太阳时输入、字段级错误、柱名本地化、四列
命盘排布、五行计数行、典籍库、多主题页签、时间轴主题/平移/大运分组、
导出按钮、隐私声明、响应式断点、无障碍属性、焦点样式。**仍是零依赖
单页**，没有引入构建链。

### 2.3 测试与工程（11 个文件）

新增 `test_api_true_solar_time.py`（12）、`test_frontend_contract.py`（10）、
`test_e2e_frontend.py`（14）、`test_element_census.py`（8）、
`test_report_export.py`（10）、`test_privacy_disclosure.py`（6）、
`test_frontend_snapshot.py`（1）、`tests/conftest.py`（E2E 脚手架）、
`tests/snapshots/frontend_chrome.txt`（视觉基线）；改 `test_api.py`、
`test_web_ui.py`、`test_dependency_declaration.py`；CI 加 Playwright 与快照步骤。

### 2.4 文档（3 个文件）

`docs/reports/phase5-1-user-flow.md`、`phase5-8-privacy-retention.md`、本报告。

---

## 3. 关键技术决策

1. **不迁移 React**（5.1 决策，全程遵守）。差距全是组件级，没有一条是
   单页结构做不到的；`textContent` 渲染纪律与框架无关，重写时弄丢的
   概率不小。
2. **真太阳时是显式开关**，不做「有经度就自动校正」。命理界对取用有
   分歧，自动切换会让结果取决于用户填没填经纬度。开关打开时算法版本
   带 `+tst`，两张不同口径的盘不共用一个版本号。
3. **422 的 `detail` 保留、`fields` 新增**。只加不改 —— 破坏响应形状是
   API 层的重决策。`fields` 只在请求模型层出现；服务层 422 只有 `detail`，
   因为那一层的问题是整请求的，不是哪个输入框。
4. **五行普查单一事实源**。`element_census` 同时喂 facts 层与
   `chart.elements`；`tests/test_evidence_audit` 的独立副本刻意保留
   （审计实现与被测同源就失去复核意义）。
5. **契约测试用静态提取 + 真实响应对账**，不引 JS 运行时。剥注释、
   方法调用负向先行、别名归一化三件事保证提取无歧义；JS 里因此避开
   同名歧义（DOM 锚元素叫 anchor、卡片叫 card），由测试钉住。
6. **导出不新增判断**。报告 = 服务层输出的 JSON 化 + 七个信封字段；
   API 视图是它的子集。PDF 用 CID 字体，不随包裹发字体文件。
7. **不做 DELETE 接口**。没有存储就没有删除对象；加一个只会制造
   「我们有你的数据」的错觉。
8. **视觉回归用文本快照而非像素比对**。中文字体渲染差异会让像素基线
   永远红，团队学会「重新生成基线」等于关掉回归。快照只钉骨架
   （标签/标题/声明），分析结果区不进快照（随规则库合法变化）。
9. **E2E 的跳过是环境事实**：包没装 → `importorskip`；浏览器没下载 →
   fixture `pytest.skip`。缺浏览器变红只会训练人忽略红测试。

---

## 4. 实际测试命令、退出码与结果

全部在本机隔离环境（Python 3.13.12 venv）执行，2026-10-25：

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python -m pytest tests/ -q` | 0 | **1398 passed**（约 3 分 38 秒） |
| `ruff check .` | 0 | All checks passed |
| `mypy .` | 0 | Success: no issues found in 111 source files |
| `python evaluation/runner.py --json` | 0 | **30 / 30**，failures 空 |
| `python evaluation/provider_conformance.py --json` | 0 | **11 / 11**，failures 空 |
| `pytest tests/test_e2e_frontend.py tests/test_frontend_snapshot.py -q` ×5 | 0 | 17 passed ×5（压测，无 flake） |
| `pytest tests/test_frontend_contract.py -q` | 0 | 10 passed |

**变异探针**（关键守卫撤掉后必须有测试变红）：

| 探针 | 结果 |
|---|---|
| 前端字段名漂移（`pillar.na_yin` → `pillar.nayin`） | 契约测试抓住 |
| 前端路径漂移（`chart.day_master` → `chart.dayMaster`） | 契约测试抓住 |
| 后端字段漂移（`topic_name` → `topicName`） | 契约测试抓住 |
| 页签点击不切主题 | E2E 抓住 |
| 默认不选中任何主题 | E2E 抓住（修正断言精度后） |
| 改一个表单标签 | 快照测试抓住 |
| 时间轴分组头初值用 null（真 bug） | E2E 抓住（已修） |

---

## 5. 远端 CI 链接及对应 SHA

| 提交 | SHA | CI |
|---|---|---|
| 5.2 收口 | `6ef8fb1` | run 40100117138 ✅ |
| 5.3 | `8a25ed5` | run 40101769043 ✅ |
| 5.4 | `38f628a` | run 40102996184 ✅ |
| 5.5 | `b004950` | run 40103877446 ✅ |
| 5.6 | `0484010` | run 40104789686 ❌ |
| 5.7 | `2bba4ee` | run 40147413186（被后续推送取消） |
| 5.8 | `f37f804` | run 40147532111 ❌ |
| **5.9（Phase 5 结束）** | **`29e7d76`** | **run 40149096057 ✅**（3m14s，含 E2E 与骨架快照） |

**两次红的原因与处置**：5.6 与 5.8 的 CI 红是**同一个测试**
（`test_timeline_shift_moves_the_window_by_its_own_span`）的竞态 ——
平移后 `#out-timeline` 早已可见，`wait_for(state="visible")` 立即返回，
断言读到的是上一段的内容。这是测试侧的缺陷，不是产品缺陷；已改为
`expect(...).to_contain_text(...)` 的自动重试，并在本机压测 5 轮确认。
5.7 的 run 因后续推送触发 `cancel-in-progress` 而取消，不是失败。

---

## 6. 逐项验收（5.1–5.9）

| 子任务 | 差距项 | 结果 | 证据 |
|---|---|---|---|
| 5.1 用户流程与信息架构 | — | ✅ | `phase5-1-user-flow.md`（G1–G16 清单） |
| 5.2 生辰输入与校验 | G1–G5 | ✅ | 分钟/真太阳时/字段级错误/柱名/`[hidden]`；12 条 API 测试 + 10 条契约 |
| 5.3 命盘可视化 | G6–G7 | ✅ | 五行普查（8 条测试）+ 四列排布；E2E 断言表头与计数行 |
| 5.4 典籍来源浏览器 | G8 | ✅ | 按底本聚合、URN、逐字原文、可打开链接、待录入披露（7 条） |
| 5.5 多主题工作台 | G9 | ✅ | 每主题一页签，失败主题占位；探针 2/2 抓住 |
| 5.6 时间轴交互 | G10 | ✅ | 主题选择、按跨度平移、大运分组（缺性别时明说不分） |
| 5.7 PDF / JSON 导出 | G11 | ✅ | `/api/report`；JSON ⊆ API 契约；PDF 5.9KB 真实产物 |
| 5.8 隐私与保留 | G12 | ✅ | 页面三条声明 + 文档六项数据清单 + 反漂移测试 |
| 5.9 移动端/无障碍/回归 | G13–G16 | ✅ | 390px 无页面级溢出、触屏目标 ≥40px、`role=alert`、`:focus-visible`、表格 caption、`aria-pressed`、骨架快照 |

---

## 7. 已知问题与回归风险

1. **证据链在移动端很长**：11 条规则全展开约 3 屏，没有折叠。桌面端
   可接受，移动端建议下一轮做「默认折叠、点开逐条」。
2. **视觉方向是克制的编辑风，不是奖项级艺术指导**。本轮做了字号节奏
   （15→16px）、间距体系、卡片层级、焦点态、复选框尺寸、表格排布与
   移动断点；没有做定制插画、动效编排、非常规栅格 —— 那需要一次
   美术方向的重设计，与「优先维护现有前端、不扩大变更范围」的阶段
   约束冲突。要推翻这个方向，应当作为独立提案评审，不在 5.9 里顺手做。
3. **5.6/5.8 的 CI 红**已修（测试竞态），但这两条历史运行记录会一直
   是红的 —— 看 CI 状态时以最新 SHA 为准。
4. **主题层规则仍稀薄**：六个主题里五个是 `base_only`。这是知识层
   问题，产品层只负责如实披露（`status` + `coverage_note`）。
5. **时间轴 50 年上限**下一次渲染最多 50 个块，未做虚拟化。实测可接受
   （每块约 6 个节点），暂不优化。

---

## 8. 回滚方案

无数据库、无迁移、无外部状态，回滚就是 revert 提交：

```bash
git revert --no-commit 7650084^..HEAD   # Phase 5 全部提交
git commit -m "revert: Phase 5 完整产品体验"
```

或把分支指回 `081f6dc`（需老板确认 —— 那是改写历史，不是普通回滚）。
`master` 全程未动，最坏情况下 master 就是干净基线。

---

## 9. 未完成工作与下一阶段建议

**Phase 5 范围内没有未完成项**（5.1–5.9 逐项关闭）。留给 Phase 6 的：

1. 部署文档里把「部署方日志策略」列为必读 —— 隐私声明的边界在部署侧。
2. 生产环境要装 `playwright` 吗？不需要 —— 它是 dev 依赖，E2E 只在
   CI 跑。部署镜像装 `requirements.txt` 即可（含 reportlab）。
3. 若要做多租户，5.8 的缓存结论要重审：那时缓存会成为跨用户的数据面。
4. 视觉方向若要升级到奖项级，单独开提案（含美术方向、动效规范、
   性能预算），不要混在功能阶段里。
