"""Phase 2：规则来源治理测试。

这一组测试守的是项目红线 —— 「不编造命理规则」。它要证明的不是「有人记得
写引文」，而是「不写引文的典籍规则在数据模型层面就活不下来」。
"""

from datetime import date

import pytest

from knowledge.provenance import Citation, ReviewStatus, SourceTier
from knowledge.rules import Rule, RuleRegistry, with_status


def citation(**overrides) -> Citation:
    values: dict[str, object] = {
        "book": "《滴天髓》",
        "edition": "测试底本",
        "chapter": "卷一",
        "original_text": "测试原文",
        "url": "https://example.invalid/classic",
    }
    values.update(overrides)
    return Citation(**values)  # type: ignore[arg-type]


def classical_rule(**overrides) -> Rule:
    values: dict[str, object] = {
        "id": "CLASSICAL_TEST_001",
        "source": "《滴天髓》（测试）",
        "school": "di_tian_sui",
        "category": "yong_shen",
        "condition": {"day_master_root": "有根"},
        "conclusion": "测试用典籍断语。",
        "source_tier": SourceTier.CLASSICAL,
    }
    values.update(overrides)
    return Rule(**values)  # type: ignore[arg-type]


# ── Citation 本身 ──────────────────────────────────────────────────────


def test_citation_requires_both_book_and_edition():
    with pytest.raises(ValueError, match="典籍名"):
        citation(book="  ")
    with pytest.raises(ValueError, match="底本或版本"):
        citation(edition="")


def test_citation_is_verifiable_only_with_text_and_url():
    assert citation().is_verifiable is True
    assert citation(original_text="").is_verifiable is False
    assert citation(url="").is_verifiable is False
    assert citation(original_text="", url="").is_verifiable is False


def test_citation_serialises_retrieval_date_as_isoformat():
    payload = citation(retrieved_on=date(2026, 10, 9)).to_dict()

    assert payload["retrieved_on"] == "2026-10-09"
    assert citation().to_dict()["retrieved_on"] is None


# ── 核心守卫：典籍规则不写原文不许激活 ────────────────────────────────


def test_classical_rule_defaults_to_unreviewed_and_not_production_ready():
    rule = classical_rule()

    assert rule.review_status is ReviewStatus.UNREVIEWED
    assert rule.is_production_ready is False


def test_classical_rule_cannot_activate_without_citation():
    with pytest.raises(ValueError, match="必须提供 citation"):
        with_status(classical_rule(), ReviewStatus.ACTIVE)


def test_classical_rule_cannot_activate_with_unverifiable_citation():
    """有书名没原文（或没地址）同样不许激活。

    只写「《滴天髓》云」而拿不出逐字原文和出处地址，正是二手断语的典型形态。
    """
    with pytest.raises(ValueError, match="不可核验"):
        with_status(classical_rule(citation=citation(original_text="")), ReviewStatus.ACTIVE)
    with pytest.raises(ValueError, match="不可核验"):
        with_status(classical_rule(citation=citation(url="")), ReviewStatus.ACTIVE)


def test_classical_rule_activates_once_citation_is_complete():
    rule = with_status(classical_rule(citation=citation()), ReviewStatus.ACTIVE)

    assert rule.review_status is ReviewStatus.ACTIVE
    assert rule.is_production_ready is True


def test_string_status_cannot_bypass_the_citation_guard():
    """把枚举写成字符串也必须被拦下。

    若 ``__post_init__`` 不做枚举收敛，``review_status="ACTIVE"`` 与
    ``ReviewStatus.ACTIVE`` 不相等，``is`` 判断为假，整条引文守卫会被绕过 ——
    守则会变成一道可以随手推开的门。
    """
    with pytest.raises(ValueError, match="必须提供 citation"):
        classical_rule(review_status="ACTIVE")
    with pytest.raises(ValueError, match="必须提供 citation"):
        classical_rule(source_tier="classical", review_status="ACTIVE")

    coerced = classical_rule(review_status="ACTIVE", citation=citation())
    assert coerced.review_status is ReviewStatus.ACTIVE
    assert coerced.source_tier is SourceTier.CLASSICAL
    assert coerced.is_production_ready is True


def test_structural_rule_may_activate_without_citation():
    """结构层规则的依据是可执行验证，不需要文献背书。"""
    rule = classical_rule(
        id="STRUCTURAL_TEST_001",
        source_tier=SourceTier.STRUCTURAL,
        source="命盘结构定义",
        review_status=ReviewStatus.ACTIVE,
    )

    assert rule.is_production_ready is True
    assert rule.citation is None


# ── 其它模型约束 ───────────────────────────────────────────────────────


def test_deprecated_rule_must_explain_why():
    with pytest.raises(ValueError, match="废弃原因"):
        classical_rule(review_status=ReviewStatus.DEPRECATED)
    assert classical_rule(
        review_status=ReviewStatus.DEPRECATED, note="被 002 取代"
    ).review_status is ReviewStatus.DEPRECATED


def test_conflict_slot_and_value_must_be_paired():
    with pytest.raises(ValueError, match="成对出现"):
        classical_rule(conflict_slot="pattern_name")
    with pytest.raises(ValueError, match="成对出现"):
        classical_rule(conflict_value="正官格")


def test_rule_to_dict_exposes_full_provenance():
    payload = with_status(classical_rule(citation=citation()), ReviewStatus.ACTIVE).to_dict()

    assert payload["source_tier"] == "classical"
    assert payload["review_status"] == "ACTIVE"
    assert payload["citation"]["book"] == "《滴天髓》"
    assert payload["citation"]["edition"] == "测试底本"


# ── 生产门禁 ───────────────────────────────────────────────────────────


def test_registry_production_ready_filters_out_unreviewed_rules():
    registry = RuleRegistry()
    registry.add(classical_rule())
    registry.add(with_status(
        classical_rule(id="CLASSICAL_TEST_002", citation=citation()), ReviewStatus.ACTIVE
    ))

    assert [rule.id for rule in registry.production_ready()] == ["CLASSICAL_TEST_002"]
