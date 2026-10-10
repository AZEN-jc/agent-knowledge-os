"""Phase 2：规则模型、注册表和条件匹配测试。"""

import pytest

from knowledge.default_rules import default_registry
from knowledge.evidence import FACT_SCHEMA
from knowledge.provenance import ReviewStatus, SourceTier
from knowledge.rules import Rule, RuleMatch, RuleRegistry, condition_holds
from knowledge.schools import STRUCTURAL_SCHOOL


def rule(**overrides) -> Rule:
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


def test_rule_requires_traceable_metadata():
    with pytest.raises(ValueError, match="source"):
        rule(source="")
    with pytest.raises(ValueError, match="confidence"):
        rule(confidence="GUESS")


def test_rule_requires_category_topic_and_non_empty_condition():
    with pytest.raises(ValueError, match="category"):
        rule(category="")
    with pytest.raises(ValueError, match="topic"):
        rule(topic=" ")
    with pytest.raises(ValueError, match="condition"):
        rule(condition={})
    with pytest.raises(ValueError, match="空条件键"):
        rule(condition={"": 1})


def test_registry_rejects_duplicate_and_unknown_conflict():
    registry = RuleRegistry()
    registry.add(rule())
    with pytest.raises(ValueError, match="已存在"):
        registry.add(rule())
    with pytest.raises(ValueError, match="未知冲突"):
        registry.add(rule(id="R2", conflicts_with=("R404",)))


def test_registry_matches_only_complete_conditions():
    registry = RuleRegistry()
    registry.add(rule(condition={"x": 1, "y": "yes"}))

    assert registry.match({"x": 1}) == ()
    matches = registry.match({"x": 1, "y": "yes"})
    assert len(matches) == 1
    assert matches[0].matched_conditions == ("x", "y")


# ── 过滤与门禁 ─────────────────────────────────────────────────────────


def test_registry_filters_by_school_and_category():
    registry = default_registry()

    assert registry.select(school="missing") == ()
    assert len(registry.select(school=STRUCTURAL_SCHOOL, category="relation")) == 9
    assert {
        item.id for item in registry.select(school=STRUCTURAL_SCHOOL, category="pattern")
    } >= {"STRUCT_PATTERN_001", "STRUCT_JIANLU_001", "STRUCT_YUEREN_001"}


def test_registry_filters_by_topic_status_and_tier():
    registry = default_registry()

    assert registry.select(topic="structure")
    assert registry.select(topic="不存在的主题") == ()
    assert len(registry.select(review_status=ReviewStatus.ACTIVE)) == len(registry.select())
    assert registry.select(review_status=ReviewStatus.UNREVIEWED) == ()
    assert registry.select(source_tier=SourceTier.CLASSICAL) == ()
    assert len(registry.select(source_tier=SourceTier.STRUCTURAL)) == len(registry.select())
    assert registry.select(confidence="HIGH")


def test_registry_rejects_condition_keys_outside_the_fact_schema():
    registry = RuleRegistry()
    registry.add(rule(condition={"typo_key": 1}))

    with pytest.raises(ValueError, match="事实词表里不存在"):
        registry.validate_condition_keys(set(FACT_SCHEMA))


def test_production_only_matching_skips_unreviewed_rules():
    registry = RuleRegistry()
    registry.add(rule(id="LIVE", review_status=ReviewStatus.ACTIVE))
    registry.add(rule(id="DRAFT", review_status=ReviewStatus.UNREVIEWED))

    assert [m.rule.id for m in registry.match({"x": 1})] == ["LIVE", "DRAFT"]
    assert [m.rule.id for m in registry.match({"x": 1}, production_only=True)] == ["LIVE"]
    assert [item.id for item in registry.production_ready()] == ["LIVE"]


def test_registry_stats_describe_the_library():
    stats = default_registry().stats()

    assert stats["total"] == len(default_registry().select())
    assert stats["production_ready"] == stats["total"]
    assert stats["by_school"] == {STRUCTURAL_SCHOOL: stats["total"]}
    assert stats["conflict_slots"] >= 1


# ── 多值事实：同类型事实有多条时按「包含」判断 ──────────────────────────


def test_registry_matches_multi_valued_facts_by_membership():
    matches = default_registry().match({"has_relation": ("六合", "自刑")})

    assert [match.rule.id for match in matches] == ["STRUCT_RELATION_002", "STRUCT_RELATION_005"]


def test_condition_holds_keeps_scalars_and_avoids_substring_hits():
    assert condition_holds("六合", "六合") is True
    assert condition_holds("自刑", "六合") is False
    assert condition_holds(("自刑", "六合"), "六合") is True
    assert condition_holds(("自刑",), "六合") is False
    # 字符串不是多值容器：不能因为「六合六冲」含有子串就误命中
    assert condition_holds("六合六冲", "六合") is False


# ── 冲突 ───────────────────────────────────────────────────────────────


def test_conflicts_are_explicit_and_deduplicated():
    registry = RuleRegistry()
    registry.add(rule(id="A", conflicts_with=()))
    registry.add(rule(id="B", conflicts_with=("A",)))

    assert registry.conflicts(["A", "B"]) == (("A", "B"),)


def _match(rule_id: str, slot: str, value: str) -> RuleMatch:
    return RuleMatch(
        rule=rule(id=rule_id, conflict_slot=slot, conflict_value=value),
        matched_conditions=("x",),
    )


def test_slot_conflicts_fire_only_when_values_actually_differ():
    """同一槽位取值相同不算冲突。

    静态 ``conflicts_with`` 会在两法结论一致时误报 —— 本气定格与透干定格都
    给出「正官格」时，它们没有分歧。值级比较才是对的。
    """
    registry = default_registry()
    agreed = (_match("A", "pattern_name", "正官格"), _match("B", "pattern_name", "正官格"))
    disagreed = (_match("A", "pattern_name", "正官格"), _match("B", "pattern_name", "七杀格"))

    assert registry.slot_conflicts(agreed) == ((), ())
    pairs, notes = registry.slot_conflicts(disagreed)
    assert pairs == (("A", "B"),)
    assert notes and "pattern_name" in notes[0]


def test_slot_conflicts_ignore_rules_without_a_slot():
    registry = default_registry()

    assert registry.slot_conflicts((_match("A", "", ""), _match("B", "", ""))) == ((), ())
