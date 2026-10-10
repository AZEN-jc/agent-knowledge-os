"""Evidence Layer 第一版测试。"""

from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.evidence import build_evidence
from knowledge.facts import extract_facts, group_facts


def chart():
    return SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))


def multi_relation_chart():
    """1990-06-15 14:30：四支同时有六合（午未）和自刑（午），共 4 条地支关系。"""
    return SxtwlBaziProvider().calculate(BirthInput(1990, 6, 15, 14, 30))


def test_extract_facts_contains_only_calculated_values():
    facts = extract_facts(chart())

    assert any(fact.type == "day_master" for fact in facts)
    assert all(fact.source.startswith("chart.") for fact in facts)


def test_build_evidence_links_facts_to_rules():
    evidence = build_evidence(chart(), default_registry(), topic="general")

    assert evidence.topic == "general"
    assert evidence.strength >= 0
    assert all(match.rule.source for match in evidence.matches)
    assert "facts" in evidence.to_dict()


# ── 回归：同类型事实不能互相覆盖 ────────────────────────────────────────


def test_group_facts_keeps_every_relation_value():
    """多值事实全部保留；单值事实仍保持标量，不改变既有形状。"""
    grouped = group_facts(extract_facts(multi_relation_chart()))

    assert grouped["has_relation"] == ("六合", "六合", "自刑", "自刑")
    assert grouped["day_master"] == "辛"


def test_relation_rules_match_when_multiple_relations_exist():
    """存在多条地支关系时，靠前的那条也要能被规则看到。

    旧实现用 {fact.type: fact.value} 建字典，has_relation 只剩最后一条「自刑」，
    六合规则 STRUCT_RELATION_002 永远匹配不上，strength 恒为 0.0。
    """
    evidence = build_evidence(multi_relation_chart(), default_registry())

    matched = {match.rule.id for match in evidence.matches}

    assert "STRUCT_RELATION_002" in matched       # 六合：该盘确实有
    assert "STRUCT_RELATION_001" not in matched   # 六冲：该盘没有，不能误报
    assert evidence.strength > 0
