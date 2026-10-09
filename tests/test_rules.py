"""Phase 2：规则模型、注册表和条件匹配测试。"""

import pytest

from knowledge.default_rules import default_registry
from knowledge.rules import Rule, RuleRegistry, condition_holds


def rule(**overrides) -> Rule:
    values = {
        "id": "R1",
        "source": "local fixture",
        "school": "fixture",
        "category": "structure",
        "condition": {"x": 1},
        "conclusion": "结构事实",
    }
    values.update(overrides)
    return Rule(**values)


def test_rule_requires_traceable_metadata():
    with pytest.raises(ValueError, match="source"):
        rule(source="")
    with pytest.raises(ValueError, match="confidence"):
        rule(confidence="GUESS")


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


def test_registry_filters_by_school_and_category():
    registry = default_registry()

    assert len(registry.list(school="zi_ping_structural", category="relation")) == 2
    assert registry.list(school="missing") == ()


# ── 多值事实：同类型事实有多条时按「包含」判断 ──────────────────────────


def test_registry_matches_multi_valued_facts_by_membership():
    matches = default_registry().match({"has_relation": ("六合", "自刑")})

    assert [match.rule.id for match in matches] == ["STRUCT_RELATION_002"]


def test_condition_holds_keeps_scalars_and_avoids_substring_hits():
    assert condition_holds("六合", "六合") is True
    assert condition_holds("自刑", "六合") is False
    assert condition_holds(("自刑", "六合"), "六合") is True
    assert condition_holds(("自刑",), "六合") is False
    # 字符串不是多值容器：不能因为「六合六冲」含有子串就误命中
    assert condition_holds("六合六冲", "六合") is False


def test_conflicts_are_explicit_and_deduplicated():
    registry = RuleRegistry()
    registry.add(rule(id="A", conflicts_with=()))
    registry.add(rule(id="B", conflicts_with=("A",)))

    assert registry.conflicts(["A", "B"]) == (("A", "B"),)
