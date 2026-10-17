# AGENTS.md — 在本仓库工作的约定

给所有在本仓库工作的 AI agent 与人类协作者。**先读完再动手。**

---

## 1. 这个仓库里有两套系统

| 系统 | 目录 | 状态 |
|---|---|---|
| **MingLi Agent**（命理推理） | `engines/` `knowledge/` `corpus/` `api/` `static/` `evaluation/` `agents/mingli.py` `agents/prompt.py` `agents/llm.py` `runtime/mingli_service.py` | **当前唯一在推进的系统** |
| **Personal Media OS**（内容流水线） | `runtime/` 其余文件、`workflows/`、`agents/` 其余文件、`scripts/` 中的 aihot/briefing 类脚本 | 冻结，不删不改 |

**改动前先确认你动的是哪一套。** 两套在导入层面已经隔离（MingLi → CreatorOS 0 条依赖），
唯一的耦合是 `agents/__init__.py` 与 `runtime/orchestrator.py`。

> ⚠️ `agents/__init__.py` 是**急切导入**：`import agents.mingli` 会连带加载 37 个
> CreatorOS 模块。这是已知问题，拆分方案见 `docs/reports/phase1-baseline-audit.md`。
> **不要在没确认的情况下把它改成惰性导入** —— 那会改变所有 `from agents import X` 的行为。

---

## 2. 四条不可越过的红线

1. **模型不算命盘。** 排盘是 `engines/bazi` 的确定性计算（sxtwl）。LLM 只解释证据。
2. **不做预测。** 输出结构信号与证据等级，不输出必然性判断。禁用词表在契约层，
   `evaluation/runner.py` 会独立复算一遍。
3. **没有可核验底本就不录规则。** 典籍断语必须能在 `corpus/canonical/` 的底本里
   逐字找到；找不到就留白并说明卡在哪一步。
4. **不伪造结果。** 测试没跑就说没跑，环境缺依赖就记录缺失。`skipped` 不等于 `passed`。

---

## 3. 常用命令

```bash
# 依赖：运行时
pip install -r requirements.txt
# 依赖：开发/CI（ruff 与 mypy —— 它们不在 requirements.txt 里）
pip install -r requirements-dev.txt

# 全量测试（约 4 分钟）
python -m pytest tests/ -q

# 评估门禁：10 案例 × 3 主题 × 6 条行为不变量，退出码非 0 表示有未过项
python evaluation/runner.py
python evaluation/runner.py --json

# 静态检查
ruff check .
mypy .

# 起服务与 Web 界面（需在仓库根目录执行）
python -m api.server        # → http://127.0.0.1:8000
```

**`mypy` 要用 `mypy .`，不要用文件子集。** 子集调用会静默漏掉不在依赖图上的文件 ——
`mypy knowledge agents runtime api` 报 3 个错误，而 `mypy .` 报 4 个，漏掉的是
`engines/bazi/golden.py`（它不被任何被检查模块 import）。

**当前 `mypy .` 有 4 个存量错误**（全在 `engines/bazi/`），因此 CI 里它是不阻塞项。
处置方案见 `docs/reports/phase1-baseline-audit.md` §7。**不要用 `# type: ignore` 抹掉。**

---

## 4. 新增一条典籍规则要同步动四处

| # | 位置 | 内容 |
|---|---|---|
| 1 | `corpus/canonical/*/atoms/*.json` | 原子本身（URN、逐字引文、条件、转述） |
| 2 | `knowledge/facts.py` | 若引入新条件键，事实提取要产出它 |
| 3 | `tests/test_evidence_audit.py` 的 `audit_fact_map` | 独立复核要覆盖新键 |
| 4 | `tests/test_structural_rules.py` 的 `RULE_WITNESS` | 每条规则要有一张真实命盘能命中 |

**后三处都在测试文件里，而改原子的人盯着的是第一个。** 先跑：

```bash
python scripts/atom_checklist.py                       # 四处状态一览
python scripts/atom_checklist.py --suggest-witness ID  # 为规则找见证命盘
```

---

## 5. 验证纪律

### 测试要能被证伪

写完测试后问：**把被测的那行代码改坏，这条测试会红吗？** 不会红就等于没测。
本仓库用**变异探针**做这件事：撤掉一个守卫 → 确认有测试变红 → 还原 → 确认零残留。

探针脚本的三条硬要求：

1. **开跑前先验基线干净。** 基线红着时「抓住」没有意义 —— 分不清红是变异造成的
   还是本来就在红。
2. **变异落地检查。** `replace` 之后确认变异文本真的在文件里。往重复键上替换会
   静默无效，报出来的 MISS 是假的。
3. **残留逐条核对原文**，不要信任何形式的启动快照。

### 样本要能区分两种实现

验证一条口径差异时，先确认你的样本能让两种实现给出**不同**答案。
用一张「两种实现都答对」的命盘去测口径差异，测了等于没测。

### 数字要有出处

报告与文档里写的数字（测试数、规则数、错误数）必须来自实际执行的命令输出，
不能靠上一轮的记忆。

---

## 6. 验收报告格式

每个 Phase 完成后输出十节：修改了什么 / 为什么修改 / 文件清单 / 数据结构 / API /
测试结果 / 构建结果 / 已知问题 / 未实现功能 / 下一阶段建议。

历史报告见 `PHASE0_REPORT.md` … `PHASE6_REPORT.md`。

---

## 7. 提交约定

- 提交信息用中文，说清**为什么**改，不只是改了什么。
- **不要把「未运行」写成「通过」。**
- 不强制推送、不直接推 `master`；改动走分支 + PR。
- `requirements.txt` 与 `pyproject.toml` 的依赖必须一致（两份清单各写一遍会漂）。

---

## 8. 环境注意事项

- 项目目标 Python **3.12**（`pyproject.toml` 的 `target-version = "py312"`）。
- `lunar_python` **只用于差分测试**交叉校验，不参与生产排盘；生产走
  `SxtwlBaziProvider`（sxtwl 2.0.7）。
- 沙箱/CI 里跑 `pytest` 若报 `PermissionError: EEXIST`，加 `--basetemp=<可写路径>`。
- 用 `pip install -r requirements.txt` 时若遇到临时目录 `EEXIST`，改用 `uv pip install`。
