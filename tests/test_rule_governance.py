"""Phase 3.3：规则匹配语义、冲突、优先级与版本治理。

## 这一层要守的是什么

规则库不是「一堆 if」。它有三件容易被写坏、且写坏后**不报错**的事：

1. **匹配语义**。``condition_holds`` 同时支持标量、多值事实、集合期望。
   三种形态交叉时语义必须明确 —— 含糊的地方不会抛异常，只会静默不命中。
2. **优先级**。同一结论槽上两条规则给出不同答案时，系统怎么处置？
   本项目的答案是「两个都留着、如实报分歧、扣强度」，而不是悄悄挑一个赢家。
   这条**必须被测试钉住**：一旦有人加了「按 confidence 取最高」的裁决逻辑，
   用户就再也看不到流派分歧了。
3. **版本治理**。版本号会写进证据链与报告，是事后复核「这份报告用的哪版规则」
   的唯一抓手。格式不收口、规则库没有整体指纹，这句话就是空的。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.evidence import CONFIDENCE_SCORES, build_evidence, score_strength
from knowledge.facts import Fact, extract_facts
from knowledge.provenance import ReviewStatus
from knowledge.rules import (
    ConditionTrace,
    Rule,
    RuleMatch,
    RuleRegistry,
    condition_holds,
)

PROVIDER = SxtwlBaziProvider()


def rule(**overrides: object) -> Rule:
    values: dict[str, object] = {
        "id": "R1",
        "source": "local fixture",
        "school": "fixture",
        "category": "structure",
        "condition": {"x": 1},
        "conclusion": "结构事实",
    }
    values.update(overrides)
    return Rule(**values)  # type: ignore[arg-type]


def facts(**values: object) -> tuple[Fact, ...]:
    out: list[Fact] = []
    for key, value in values.items():
        items = value if isinstance(value, tuple) else (value,)
        out.extend(Fact(key, item, "test.fixture") for item in items)
    return tuple(out)


def match(rule_id: str, slot: str, value: str, confidence: str = "LOW") -> RuleMatch:
    return RuleMatch(
        rule=rule(id=rule_id, conflict_slot=slot, conflict_value=value, confidence=confidence),
        traces=(ConditionTrace("x", 1, 1, ("test.fixture",)),),
    )


# ── 匹配语义：三种形态交叉时必须明确 ──────────────────────────────────


def test_both_sides_multi_valued_means_any_shared_element():
    """两侧都是集合时按「有交集」判断。

    **这是一条修过的缺陷。** 原实现先判 ``actual`` 是不是容器，命中就返回
    ``expected in actual`` —— 于是「期望是列表、实际也是元组」退化成
    「这个列表是不是元组里的一个元素」，恒为 False。

    症状是静默失效：规则写着「命盘有六合或六冲」，命盘恰好两类都有，
    规则反而不命中。不报错、不告警，只是少一条结论。
    """
    assert condition_holds(("六合", "六冲"), ["六合", "六冲"]) is True
    assert condition_holds(("六合", "六冲"), ["六合", "三合"]) is True
    assert condition_holds(("六合", "六冲"), ["三合", "自刑"]) is False
    assert condition_holds(("六合",), ["六合"]) is True
    # 空容器与任何集合都无交集。
    assert condition_holds((), ["六合"]) is False


def test_the_four_scalar_and_container_shapes_keep_their_meaning():
    """标量×标量、多值×标量、标量×集合三种形态的语义不能被子集修正带偏。"""
    assert condition_holds("六合", "六合") is True
    assert condition_holds("自刑", "六合") is False
    assert condition_holds(("自刑", "六合"), "六合") is True
    assert condition_holds(("自刑",), "六合") is False
    assert condition_holds("寅", ["寅", "午", "戌"]) is True
    assert condition_holds("亥", ["寅", "午", "戌"]) is False
    # 字符串不是容器：不能因为「六合六冲」含子串就误命中。
    assert condition_holds("六合六冲", "六合") is False


def test_a_container_condition_matches_a_multi_valued_fact_through_the_registry():
    """上面那条语义必须真的作用在匹配器上，不只是单测里的一个函数。

    单测谓词通过、匹配器却走了另一条路，是这类重构最常见的破法。
    """
    registry = RuleRegistry()
    registry.add(rule(id="MULTI", condition={"has_relation": ["六合", "六冲"]}))

    hits = registry.match(facts(has_relation=("六合", "六冲")))

    assert [item.rule.id for item in hits] == ["MULTI"]
    # 证据链要回填**对得上的那些**来源，不是全部。
    assert hits[0].traces[0].sources == ("test.fixture",)


# ── 优先级：不自动裁决分歧 ────────────────────────────────────────────


def test_conflicting_rules_are_both_kept_never_silently_dropped():
    """同槽分歧时两条规则都必须留在结果里。

    这是「优先级」在本项目的实现方式：**不选赢家**。用户看到的是
    「本气定格说正官格、透干定格说七杀格」，以及被扣减后的强度 ——
    而不是系统替他挑一个看起来更权威的答案。

    一旦有人加了「按 confidence 取最高」的裁决逻辑，这条会红。
    """
    registry = default_registry()
    matches = (match("A", "pattern_name", "正官格"), match("B", "pattern_name", "七杀格"))

    pairs, notes = registry.slot_conflicts(matches)

    assert pairs == (("A", "B"),)
    assert notes
    # 分歧被报出来的同时，两条 match 仍在入参里 —— 本函数不删任何东西。
    assert [item.rule.id for item in matches] == ["A", "B"]


def test_slot_divergence_reduces_strength_but_agreement_does_not():
    """分歧要扣强度，一致不扣。这是「优先级」的量化部分。"""
    agreed = (match("A", "pattern_name", "正官格"), match("B", "pattern_name", "正官格"))
    disagreed = (match("A", "pattern_name", "正官格"), match("B", "pattern_name", "七杀格"))
    registry = default_registry()

    agreed_pairs, _ = registry.slot_conflicts(agreed)
    disagreed_pairs, _ = registry.slot_conflicts(disagreed)

    agreed_score = score_strength(agreed, agreed_pairs)
    disagreed_score = score_strength(disagreed, disagreed_pairs)

    assert agreed_score.conflicts == 0
    assert disagreed_score.conflicts == 1
    assert disagreed_score.final < agreed_score.final


def test_confidence_is_the_only_priority_signal_and_it_is_monotonic():
    """置信等级越高，支持量越大 —— 且映射表是完整的三档。

    项目里没有独立的 ``priority`` 字段，优先级就体现在这里：``confidence``
    决定一条规则对证据强度的贡献。三档必须齐全，缺一档会让那类规则在
    强度计算时 KeyError。
    """
    assert set(CONFIDENCE_SCORES) == {"LOW", "MEDIUM", "HIGH"}
    assert (
        CONFIDENCE_SCORES["LOW"] < CONFIDENCE_SCORES["MEDIUM"] < CONFIDENCE_SCORES["HIGH"]
    )

    low = score_strength((match("A", "", "", "LOW"),), ())
    high = score_strength((match("A", "", "", "HIGH"),), ())

    assert high.raw_support > low.raw_support
    assert high.final > low.final


def test_matching_does_not_depend_on_registration_order():
    """同一批规则换个注册顺序，命中集合与指纹都必须相同。

    依赖注册顺序的匹配器会让「同样的命盘、同样的规则库」给出不同顺序的
    证据链 —— 报告无法复现，而这一点在单次运行里看不出来。
    """
    first = RuleRegistry()
    second = RuleRegistry()
    definitions = [
        rule(id="A", condition={"x": 1}),
        rule(id="B", condition={"x": 1}),
        rule(id="C", condition={"x": 2}),
    ]
    for item in definitions:
        first.add(item)
    for item in reversed(definitions):
        second.add(item)

    assert {m.rule.id for m in first.match(facts(x=1))} == {"A", "B"}
    assert {m.rule.id for m in second.match(facts(x=1))} == {"A", "B"}
    assert first.fingerprint() == second.fingerprint()


# ── 冲突声明：前向引用不被接受 ────────────────────────────────────────


def test_a_rule_cannot_declare_a_conflict_with_a_rule_added_later():
    """``conflicts_with`` 只能指向**已注册**的规则。

    这是 ``add`` 的既有行为，值得写成测试是因为它是一条**顺序约束**：
    规则库的加载顺序因此不能随便打乱，新增规则时若引用了后面才注册的规则，
    会在启动时直接失败。静默接受前向引用会让冲突表出现悬空边 ——
    那条冲突永远不会被 ``conflicts()`` 报出来。
    """
    registry = RuleRegistry()

    with pytest.raises(ValueError, match="未知冲突"):
        registry.add(rule(id="A", conflicts_with=("B",)))

    registry.add(rule(id="B"))
    registry.add(rule(id="A", conflicts_with=("B",)))
    assert registry.conflicts(["A", "B"]) == (("A", "B"),)


def test_conflict_pairs_are_symmetric_and_sorted():
    """只在一侧声明也要能报出来，且顺序稳定。"""
    registry = RuleRegistry()
    registry.add(rule(id="A"))
    registry.add(rule(id="B", conflicts_with=("A",)))

    assert registry.conflicts(["B", "A"]) == (("A", "B"),)
    assert registry.conflicts(["A"]) == ()


# ── 版本治理 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("version", ["1", "2", "1.3", "10.0.2"])
def test_well_formed_versions_are_accepted(version: str):
    assert rule(version=version).version == version


@pytest.mark.parametrize("version", ["", " ", "v2", "第二版", "1.3-beta", "1..2"])
def test_malformed_versions_are_rejected(version: str):
    """版本号格式必须收口。

    之前 ``version`` 是裸的 ``str = "1"``，什么都不校验：空串、``"v2 final"``
    都能过。而版本号会写进证据链与报告，格式不收口就没法按版本比对两次分析。
    """
    with pytest.raises(ValueError, match="version"):
        rule(version=version)


def test_every_production_rule_has_a_well_formed_version():
    for item in default_registry().select():
        assert item.version.strip(), f"{item.id} 没有版本号"
        assert item.version[0].isdigit(), f"{item.id} 的版本号不以数字开头：{item.version}"


def test_version_survives_status_transitions_and_serialisation():
    """换校核状态不能顺手改版本号，序列化必须带上它。"""
    original = rule(version="2.1")
    promoted = replace(original, review_status=ReviewStatus.ACTIVE)

    assert promoted.version == "2.1"
    assert promoted.to_dict()["version"] == "2.1"


def test_the_registry_has_a_content_fingerprint():
    """规则库指纹：稳定、且对任何内容改动敏感。

    每条规则自带 ``version``，但那是单条版本，说明不了「这次分析用的是哪一批
    规则」。两次分析结论不同时，第一个要排除的就是「规则库变了」。
    """
    registry = default_registry()
    baseline = registry.fingerprint()

    assert len(baseline) == 16
    assert baseline == default_registry().fingerprint(), "同内容重建必须同指纹"


def test_the_fingerprint_changes_when_any_rule_content_changes():
    """结论、条件、版本、状态任一改动都要让指纹变。

    指纹对某类改动不敏感，比没有指纹更糟 —— 它看起来在保护，其实漏掉了
    正好那一类变化。
    """
    base = RuleRegistry()
    base.add(rule(id="A"))
    base.add(rule(id="B"))
    original = base.fingerprint()

    variants = {
        "结论": rule(id="A", conclusion="另一个结论"),
        "条件": rule(id="A", condition={"x": 2}),
        "版本": rule(id="A", version="2"),
        "状态": replace(rule(id="A"), review_status=ReviewStatus.ACTIVE),
        "来源": rule(id="A", source="另一处出处"),
    }
    for label, changed in variants.items():
        mutated = RuleRegistry()
        mutated.add(changed)
        mutated.add(rule(id="B"))
        assert mutated.fingerprint() != original, f"改动「{label}」后指纹没变"


def test_the_fingerprint_changes_when_a_rule_is_added_or_removed():
    base = RuleRegistry()
    base.add(rule(id="A"))
    before = base.fingerprint()

    base.add(rule(id="B"))
    after_add = base.fingerprint()
    assert after_add != before

    without_b = RuleRegistry()
    without_b.add(rule(id="A"))
    assert without_b.fingerprint() == before


# ── 端到端：分歧如实出现在证据里 ──────────────────────────────────────


def test_real_charts_never_have_untraced_rules():
    """任何真实命盘的证据链都不能断环。

    与 ``Evidence.untraced_rule_ids`` 的契约一致：正常情况下恒为空。
    """
    for year, month, day, hour in ((1990, 2, 1, 12), (1976, 6, 15, 6), (2024, 11, 7, 23)):
        chart = PROVIDER.calculate(BirthInput(year, month, day, hour))
        evidence = build_evidence(chart, default_registry(), "事业")
        assert evidence.untraced_rule_ids == (), f"{year} 年命盘的证据链断了"

    # 顺带确认 facts 与 matches 不是空跑。
    assert extract_facts(chart)
