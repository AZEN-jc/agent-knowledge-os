"""Phase 3.5：证据链完整性与强度算法。

## 这一层要守的两件事

**一、证据链不能断环。** 从「结论」到「命盘要素」是一条四跳的路：
结论 → 规则 → 条件 → 事实 → 命盘字段。前三跳有 ``ConditionTrace`` 兜着，
最后一跳此前只是一串字符串，没人验证它到底指不指得到东西。Phase 3.2 加了
:func:`knowledge.facts.resolve_source`，这里用它把整条链**端到端**走一遍：
每一条 trace 的每一个 source 都必须能在命盘对象上解析出值。

**二、强度不是概率。** 算式是「支持量凹饱和 − 冲突扣减」，
见 :func:`knowledge.evidence.score_support`。它是证据等级，不是事件概率。
这里用数学性质把它钉死：单调、有界、永远到不了 1.0、扣减不会变成负数。
性质比具体数字重要 —— 具体数字会随规则库变，性质不该变。
"""

from __future__ import annotations

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.evidence import (
    CONFIDENCE_SCORES,
    CONFLICT_PENALTY,
    SATURATION_K,
    build_evidence,
    score_strength,
    score_support,
)
from knowledge.facts import extract_facts, resolve_source
from knowledge.rules import ConditionTrace, Rule, RuleMatch
from knowledge.time_windows import analyze_period
from knowledge.topics import STRUCTURAL_TOPIC

PROVIDER = SxtwlBaziProvider()
REGISTRY = default_registry()

#: 端到端样本：跨年代、跨时辰。
CHARTS = tuple(
    PROVIDER.calculate(BirthInput(year, month, day, hour))
    for year, month, day, hour in (
        (1990, 2, 1, 12),
        (1976, 6, 15, 6),
        (2003, 11, 7, 23),
        (2024, 3, 20, 0),
        (1950, 8, 8, 18),
    )
)

TOPICS = ("structure", "career", "wealth")


def make_match(confidence: str = "LOW", slot: str = "", value: str = "") -> RuleMatch:
    rule = Rule(
        id=f"R_{confidence}_{len(slot)}{value}",
        source="fixture",
        school="fixture",
        category="structure",
        condition={"x": 1},
        conclusion="结构事实",
        confidence=confidence,
        conflict_slot=slot,
        conflict_value=value,
    )
    return RuleMatch(rule=rule, traces=(ConditionTrace("x", 1, 1, ("chart.pillars",)),))


# ── 算式的性质：单调、有界、可复算 ────────────────────────────────────


def test_the_breakdown_can_be_recomputed_from_its_own_fields():
    """暴露出来的每一项都必须能互相验算。

    只给一个分数的强度模型，用户除了相信没有别的选择。既然把
    ``raw_support`` / ``after_saturation`` / ``conflict_penalty`` 都暴露了，
    它们就必须真的能算出 ``final`` —— 否则暴露的是装饰品。
    """
    for support in ((), (0.4,), (0.4, 0.7), (1.0,) * 5):
        for conflicts in (0, 1, 3):
            breakdown = score_support(support, conflicts)

            expected_raw = sum(support)
            expected_after = expected_raw / (expected_raw + SATURATION_K) if expected_raw else 0.0
            expected_penalty = CONFLICT_PENALTY * conflicts
            expected_final = max(0.0, min(1.0, expected_after - expected_penalty))

            assert breakdown.raw_support == pytest.approx(expected_raw, abs=1e-4)
            assert breakdown.after_saturation == pytest.approx(expected_after, abs=1e-4)
            assert breakdown.conflict_penalty == pytest.approx(expected_penalty, abs=1e-4)
            assert breakdown.final == pytest.approx(expected_final, abs=1e-4)
            assert breakdown.supporting_rules == len(support)


def test_strength_is_monotonic_in_the_number_of_supporting_rules():
    """多一条支持，强度只能升不能降（同置信度下）。

    这条守的是「证据厚度确实被计入」。若有人把算式换成置信度均值，
    3 条与 20 条会给出同一个分数，这条测试立刻红。
    """
    previous = -1.0
    for count in range(0, 15):
        score = score_support((0.7,) * count, 0).final
        assert score > previous or count == 0, f"{count} 条时强度没有上升"
        previous = score


def test_strength_never_reaches_one():
    """结构层证据再厚，也不该被读成「结论几乎确定」。

    凹饱和函数永远小于 1。这不是数值精度问题，是刻意的：强度是证据等级，
    不是概率。若哪天有人「顺手归一化」到 1.0，这条会红。
    """
    huge = score_support((1.0,) * 500, 0)

    assert huge.final < 1.0
    assert huge.final > 0.99  # 但确实接近上限，不是被截断在别处


def test_conflict_penalty_never_pushes_strength_below_zero():
    """冲突再多也不能给出负强度 —— 负值会被下游读成「反向证据」。"""
    breakdown = score_support((0.4,), 100)

    assert breakdown.final == 0.0
    assert breakdown.conflicts == 100


def test_no_support_means_no_strength():
    """零证据必须是 0，而不是某个「基础分」。"""
    assert score_support((), 0).final == 0.0
    assert score_support((), 3).final == 0.0


def test_score_strength_uses_the_confidence_mapping():
    """规则版的强度必须真的按 confidence 折算，不是按条数直接算。"""
    low = score_strength((make_match("LOW"),), ())
    high = score_strength((make_match("HIGH"),), ())

    assert low.raw_support == pytest.approx(CONFIDENCE_SCORES["LOW"])
    assert high.raw_support == pytest.approx(CONFIDENCE_SCORES["HIGH"])


# ── 证据链：端到端能走回命盘要素 ──────────────────────────────────────


def test_every_trace_source_resolves_to_a_chart_value():
    """**本文件最重要的一条**：证据链的最后一跳必须真的走得到。

    一条 trace 写着 ``chart.pillars.month.hidden_stems``，那这个路径就必须能在
    命盘对象上取出东西来。此前没人验证过 —— 路径拼错时字符串照样好看，
    而用户看到的「来源」其实指向一片虚空。
    """
    checked = 0
    for chart in CHARTS:
        for topic in TOPICS:
            evidence = build_evidence(chart, REGISTRY, topic)
            for match in evidence.matches:
                for trace in match.traces:
                    assert trace.sources, f"{match.rule.id} 的 {trace.key} 没有来源"
                    for source in trace.sources:
                        if not source.startswith("chart."):
                            # 时间轴事实的 time.* 来源不在命盘上，跳过。
                            continue
                        resolve_source(chart, source)
                        checked += 1

    assert checked > 0, "一个来源都没验到，说明样本没命中任何规则"


def test_every_condition_of_a_match_has_a_trace():
    """命中的规则，条件数与 trace 数必须一致。

    少一条 trace，就等于有一条条件「不知道凭什么成立」—— 而它仍然在
    结论里生效。
    """
    for chart in CHARTS:
        evidence = build_evidence(chart, REGISTRY, "structure")
        for match in evidence.matches:
            assert set(match.matched_conditions) == set(match.rule.condition), (
                f"{match.rule.id} 的条件与追踪对不上"
            )
            assert match.is_fully_traced


def test_real_evidence_is_fully_traced_and_has_no_unreviewed_rules():
    """真实命盘的证据链不能断环；当前规则库全部已校核。"""
    for chart in CHARTS:
        evidence = build_evidence(chart, REGISTRY, "structure")
        assert evidence.is_fully_traced
        assert evidence.unreviewed_rule_ids == ()


def test_evidence_to_dict_is_internally_consistent():
    """序列化后的扁平视图与证据链视图必须是同一批规则。

    兼容字段（``rules`` / ``sources``）是给老调用方的，它们与 ``chain``
    各算一遍；两份不一致时，一个调用方看到 5 条依据、另一个看到 3 条。
    """
    chart = CHARTS[0]
    evidence = build_evidence(chart, REGISTRY, "career")
    payload = evidence.to_dict()

    chain_ids = [item["rule_id"] for item in payload["chain"]]
    assert payload["rules"] == chain_ids
    assert len(payload["sources"]) == len(chain_ids)
    assert payload["strength"] == payload["strength_breakdown"]["final"]
    assert payload["unreviewed_rules"] == list(evidence.unreviewed_rule_ids)
    assert payload["untraced_rules"] == []

    # 基础层与主题层必须正好切分命中集合。
    assert set(payload["base_rules"]) | set(payload["domain_rules"]) == set(chain_ids)
    assert set(payload["base_rules"]) & set(payload["domain_rules"]) == set()


def test_the_conflict_count_in_the_breakdown_matches_the_reported_pairs():
    """强度里扣的冲突数，必须等于证据里列出来的冲突对数。

    两处各算一遍时，很容易一边扣了 2 处、另一边只报 1 处 —— 用户看到的
    「为什么强度被扣了」就解释不通。
    """
    for chart in CHARTS:
        evidence = build_evidence(chart, REGISTRY, "structure")
        assert evidence.strength_breakdown.conflicts == len(evidence.conflicts)


def test_evidence_strength_stays_below_one_on_real_charts():
    """真实命盘上也必须 < 1.0 —— 强度不是概率。"""
    for chart in CHARTS:
        for topic in TOPICS:
            evidence = build_evidence(chart, REGISTRY, topic)
            assert 0.0 <= evidence.strength < 1.0


# ── 时间轴复用同一个算式 ──────────────────────────────────────────────


def test_time_windows_reuse_the_same_saturation_constant():
    """时间轴层与命盘层必须用同一个 K，否则两层的强度数字不可比。

    用户最需要能比较的地方正是「本命局 0.62，2028 年 0.48」。两层各写一个
    常数，这个比较就没有意义。
    """
    chart = CHARTS[0]
    windows = analyze_period(chart, 2024, 2026, "财运")

    assert windows, "时间轴没有产出窗口"
    for window in windows:
        assert window.breakdown.saturation_k == SATURATION_K
        # 同样必须能由暴露的字段复算。
        expected = max(
            0.0,
            window.breakdown.after_saturation - window.breakdown.conflict_penalty,
        )
        assert window.breakdown.final == pytest.approx(expected, abs=1e-4)
        assert 0.0 <= window.strength < 1.0


def test_time_windows_report_zero_conflicts_because_they_do_not_detect_any():
    """时间轴当前不做冲突检测，这一点要写在测试里而不是靠读代码发现。

    不是「没问题」，是**尚未实现**：流年层只累加信号，不判断两个信号是否
    互相矛盾。把这条钉住，将来实现时它会红，提醒改这里而不是当它一直成立。
    """
    chart = CHARTS[0]
    windows = analyze_period(chart, 2024, 2026, "财运")

    assert all(window.breakdown.conflicts == 0 for window in windows)


# ── 事实层与证据层的边界 ──────────────────────────────────────────────


def test_evidence_facts_are_the_same_facts_the_chart_produces():
    """证据里带的事实必须是 ``extract_facts`` 的同一批，不是重新挑过的子集。

    证据层如果自己筛事实，用户看到的「命盘里有什么」就会与规则匹配时用的
    不是同一份数据 —— 解释与判定脱节。
    """
    chart = CHARTS[0]
    evidence = build_evidence(chart, REGISTRY, STRUCTURAL_TOPIC)

    assert evidence.facts == extract_facts(chart)
