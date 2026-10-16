"""系统行为不变量评估：跑一批命盘，检查这个系统的承诺有没有守住。

**为什么评的不是「排盘准不准」。** 排盘已经被 ``tests/test_bazi_golden.py``
用 sxtwl 与 lunar-python **两套独立实现交叉确认**过了，比这里能做的任何
评估都严格。再让评估器把金标准案例跑一遍，是重复劳动。

这里评的是**系统在大量命盘上的行为**，也就是那些「单点测试覆盖不到、
只在群体上才显形」的承诺：

1. **证据链不断环** —— 每条命中的规则，它的每个条件都能指向具体命盘要素。
2. **审查通过** —— Critic 在整批上不报问题。
3. **结论不越界引用** —— 结论引用的规则 ID 必须是证据链的子集。
4. **不下确定性判断** —— 结论里不出现必然性措辞。
5. **强度在值域内** —— [0, 1)；它是证据等级，不是事件概率。
6. **可复现** —— 同一输入两次跑出逐字段相同的结果。

第 6 条尤其值得单独评：它单点测不出来，而一旦哪一层悄悄引入了顺序依赖
（比如遍历字典、缓存污染），症状是「偶尔不一样」，靠人工跑几次发现不了。

案例集取 :data:`engines.bazi.golden_cases.GOLDEN_CASES` 的生辰 ——
它们的输入是双实现交叉验证过的，所以**输入本身可信**，评估结果不会被
「输入就是错的」污染。

用法::

    python evaluation/runner.py          # 跑全部案例，打印通过率
    python evaluation/runner.py --json   # 机器可读

按**路径**跑而不是 ``python -m evaluation.runner``：模块方式要求仓库根在
``sys.path`` 上（即必须在仓库根目录执行），而本文件开头已经自己把仓库根
插进去了，所以按路径跑从任何目录都成立 —— 与 ``scripts/`` 下那些脚本同一
约定。退出码非 0 表示有不变量没守住，可直接当回归门禁。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engines.bazi.golden_cases import GOLDEN_CASES
from evaluation.core import EvaluationResult, EvaluationSummary, summarize
from runtime.mingli_service import MingLiService

#: 每个案例问的主题。挑三个覆盖面不同的：结构层（有规则）、主题层（无专属
#: 规则，应如实披露 base_only）、命局（有典籍层规则）。
TOPICS = ("结构", "事业", "命局")


@dataclass(frozen=True)
class Invariant:
    name: str
    promise: str
    check: Callable[[dict[str, Any]], str]


def _evidence(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["analysis"]["evidence"]


def _chain_rule_ids(payload: dict[str, Any]) -> list[str]:
    return [link["rule_id"] for link in _evidence(payload)["chain"]]


def _check_chain_traced(payload: dict[str, Any]) -> str:
    broken = _evidence(payload)["untraced_rules"]
    return f"证据链断环：{broken}" if broken else ""


def _check_critique_passed(payload: dict[str, Any]) -> str:
    critique = payload["critique"]
    return "" if critique["passed"] else f"审查未通过：{critique['issues']}"


def _check_citations_within_chain(payload: dict[str, Any]) -> str:
    cited = set(payload["analysis"]["draft"]["cited_rules"])
    chain = set(_chain_rule_ids(payload))
    outside = sorted(cited - chain)
    return f"结论引用了证据链之外的规则：{outside}" if outside else ""


def _check_no_certainty_language(payload: dict[str, Any]) -> str:
    """结论里不得出现必然性措辞。

    契约层已经有一份禁用词表并会记进 ``certainty_risk``，这里独立复算一遍
    而不是信那个标志 —— 复核的价值全在两条路径独立走完再比对。
    """
    banned = ("一定会", "必将", "必定", "肯定会", "必然会", "绝对会")
    hit = [word for word in banned if word in payload["analysis"]["conclusion"]]
    return f"结论含必然性措辞：{hit}" if hit else ""


def _check_strength_in_range(payload: dict[str, Any]) -> str:
    strength = _evidence(payload)["strength"]
    if not 0.0 <= strength < 1.0:
        return f"证据强度 {strength} 不在 [0, 1) 内"
    return ""


INVARIANTS: tuple[Invariant, ...] = (
    Invariant("chain_traced", "证据链不断环", _check_chain_traced),
    Invariant("critique_passed", "审查通过", _check_critique_passed),
    Invariant("citations_within_chain", "结论不越界引用", _check_citations_within_chain),
    Invariant("no_certainty_language", "不下确定性判断", _check_no_certainty_language),
    Invariant("strength_in_range", "强度在值域内", _check_strength_in_range),
)

REPRODUCIBILITY = Invariant("reproducible", "同一输入结果可复现", lambda _: "")
"""复现性单独一条：它需要**第二次调用**才能判，其余不变量只看第一次的结果。"""

ALL_INVARIANTS = (*INVARIANTS, REPRODUCIBILITY)


def _birth_of(case) -> dict[str, Any]:
    birth = case.birth
    data: dict[str, Any] = {
        "year": birth.year, "month": birth.month, "day": birth.day, "hour": birth.hour,
    }
    gender = getattr(birth, "gender", None)
    if gender:
        data["gender"] = gender
    return data


def evaluate(service: MingLiService | None = None) -> EvaluationSummary:
    """跑全部案例，逐个检查不变量。"""
    active = service if service is not None else MingLiService()
    results: list[EvaluationResult] = []

    for case in GOLDEN_CASES:
        birth = _birth_of(case)
        for topic in TOPICS:
            label = f"{case.case_id}·{topic}"
            try:
                payload = active.analyze(birth, topic).to_dict()
            except Exception as exc:  # 异常也是评估结果，如实带回
                results.append(EvaluationResult(label, False, "全部不变量成立", None, str(exc)))
                continue

            failures = [f"{item.name}（{reason}）"
                        for item in INVARIANTS
                        if (reason := item.check(payload))]

            # 可复现性单独跑一次：它需要第二次调用，其余不变量只看第一次结果。
            again = active.analyze(birth, topic).to_dict()
            if again != payload:
                failures.append(f"{REPRODUCIBILITY.name}（同一输入两次结果不同）")

            results.append(EvaluationResult(
                case_id=label,
                passed=not failures,
                expected="全部不变量成立",
                actual="全部成立" if not failures else "；".join(failures),
            ))

    return summarize(results)


def render(summary: EvaluationSummary) -> str:
    width = max((len(result.case_id) for result in summary.results), default=10)
    lines = [
        f"MingLi 不变量评估 · {len(summary.results)} 案例 "
        f"× {len(ALL_INVARIANTS)} 条不变量",
        "-" * (width + 30),
    ]
    for result in summary.results:
        mark = "通过" if result.passed else "未过"
        lines.append(f"{result.case_id:<{width}}  {mark}  {'' if result.passed else result.actual}")
    lines.append("-" * (width + 30))
    lines.append(f"{summary.passed}/{summary.total} passed （accuracy {summary.accuracy:.4f}）")
    if summary.failed:
        lines.append("")
        lines.append("未过项逐条：")
        for result in summary.results:
            if not result.passed:
                lines.append(f"  {result.case_id}：{result.actual}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args()

    summary = evaluate()
    if args.json:
        print(json.dumps({
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "accuracy": summary.accuracy,
            "failures": [
                {"case_id": result.case_id, "detail": result.actual}
                for result in summary.results if not result.passed
            ],
        }, ensure_ascii=False, indent=2))
    else:
        print(render(summary))

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
