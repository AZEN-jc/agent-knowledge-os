"""Phase 3：证据强度模型的性质测试。

这里**不断言具体数值**。饱和常数 K、冲突扣减额都是本实现选定的标度，不是
典籍规定也不是概率刻度 —— 把测试钉在 ``0.625`` 这种数字上，只会让「调整
标度」和「模型坏了」变得无法区分。

断言的是**性质**：这些性质就是「强度算得合理」的可证伪定义。破坏任何一条，
都说明模型不再表达它声称表达的东西。
"""

from knowledge.evidence import CONFLICT_PENALTY, SATURATION_K, score_strength
from knowledge.rules import ConditionTrace, Rule, RuleMatch


def _match(rule_id: str, confidence: str) -> RuleMatch:
    rule = Rule(
        id=rule_id,
        source="测试来源",
        school="test_school",
        category="test",
        topic="structure",
        condition={"k": 1},
        conclusion="测试结论。",
        confidence=confidence,
    )
    return RuleMatch(rule=rule, traces=(ConditionTrace("k", 1, 1, ("chart.x",)),))


def matches(*confidences: str) -> tuple[RuleMatch, ...]:
    return tuple(_match(f"R{index}", c) for index, c in enumerate(confidences, start=1))


def conflict_pairs(count: int) -> tuple[tuple[str, str], ...]:
    return tuple((f"A{i}", f"B{i}") for i in range(count))


# ── 边界 ───────────────────────────────────────────────────────────────


def test_no_matches_means_zero_strength():
    breakdown = score_strength((), ())

    assert breakdown.final == 0.0
    assert breakdown.supporting_rules == 0
    assert breakdown.raw_support == 0.0


def test_strength_stays_inside_the_unit_interval():
    for sample in ((), matches("LOW"), matches("HIGH", "HIGH"), matches(*["HIGH"] * 50)):
        for conflicts in ((), conflict_pairs(1), conflict_pairs(20)):
            assert 0.0 <= score_strength(sample, conflicts).final <= 1.0


def test_conflicts_can_never_push_strength_below_zero():
    """扣减额超过饱和值时截断在 0，不能出现负强度。"""
    breakdown = score_strength(matches("LOW"), conflict_pairs(50))

    assert breakdown.conflict_penalty > breakdown.after_saturation
    assert breakdown.final == 0.0


# ── 单调性 ─────────────────────────────────────────────────────────────


def test_more_supporting_rules_never_lower_strength():
    previous = 0.0
    for count in range(1, 15):
        current = score_strength(matches(*["MEDIUM"] * count), ()).final
        assert current > previous, f"{count} 条支持规则的强度没有高于 {count - 1} 条"
        previous = current


def test_higher_confidence_never_lowers_strength():
    low = score_strength(matches("LOW", "MEDIUM"), ()).final
    high = score_strength(matches("HIGH", "MEDIUM"), ()).final

    assert high > low


def test_more_conflicts_never_raise_strength():
    previous = 1.0
    for count in range(4):
        current = score_strength(matches(*["HIGH"] * 8), conflict_pairs(count)).final
        assert current < previous
        previous = current


# ── 形状：边际递减、永不饱和 ────────────────────────────────────────────


def test_gains_diminish_as_support_piles_up():
    """第 2 条规则带来的增益必须大于第 11 条。

    没有这一条，模型可能退化成线性累加 —— 那会让「堆规则条数」变成刷分手段。
    """
    def strength(count: int) -> float:
        return score_strength(matches(*["HIGH"] * count), ()).final

    first_gain = strength(2) - strength(1)
    late_gain = strength(11) - strength(10)

    assert first_gain > late_gain > 0


def test_strength_never_reaches_one():
    """结构层证据再厚也只是「命盘里有什么」，不该被读成「结论几乎确定」。"""
    breakdown = score_strength(matches(*["HIGH"] * 1000), ())

    assert breakdown.final < 1.0
    assert breakdown.after_saturation < 1.0


def test_strength_is_order_invariant():
    forward = score_strength(matches("HIGH", "LOW", "MEDIUM"), ()).final
    backward = score_strength(matches("MEDIUM", "LOW", "HIGH"), ()).final

    assert forward == backward


# ── 可审计：算式必须自洽 ───────────────────────────────────────────────


def test_breakdown_arithmetic_adds_up():
    sample = matches("HIGH", "MEDIUM", "LOW")
    breakdown = score_strength(sample, conflict_pairs(2))

    assert breakdown.supporting_rules == 3
    assert breakdown.raw_support == round(1.0 + 0.7 + 0.4, 4)
    assert breakdown.saturation_k == SATURATION_K
    assert breakdown.after_saturation == round(
        breakdown.raw_support / (breakdown.raw_support + SATURATION_K), 4
    )
    assert breakdown.conflicts == 2
    assert breakdown.conflict_penalty == round(CONFLICT_PENALTY * 2, 4)
    assert breakdown.final == round(
        max(0.0, breakdown.after_saturation - breakdown.conflict_penalty), 4
    )


def test_breakdown_serialises_every_term():
    payload = score_strength(matches("HIGH"), ()).to_dict()

    assert set(payload) == {
        "supporting_rules",
        "raw_support",
        "saturation_k",
        "after_saturation",
        "conflicts",
        "conflict_penalty",
        "final",
    }
