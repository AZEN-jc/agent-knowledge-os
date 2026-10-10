"""Analyst/Critic 的本地契约测试。"""

from dataclasses import replace

from agents.mingli import CONCLUSION_LIMIT, AnalystAgent, CriticAgent
from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.provenance import ReviewStatus
from knowledge.rules import Rule, RuleRegistry
from knowledge.schools import STRUCTURAL_SCHOOL


def chart():
    return SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))


def test_analyst_returns_evidence_bounded_conclusion():
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")

    assert analysis.question == "事业"
    assert analysis.evidence.topic == "事业"
    assert "不能形成可靠结论" in analysis.conclusion or "结构规则" in analysis.conclusion


def test_analyst_does_not_dump_the_whole_rule_library_into_the_conclusion():
    """规则库扩容后，命中十几条是常态；结论不能变成一堵墙。

    摘要可以短，证据不能少 —— 被截掉的部分在 evidence.matches 里完整保留。
    """
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")

    assert len(analysis.evidence.matches) > CONCLUSION_LIMIT
    assert "另有" in analysis.conclusion
    assert len(analysis.conclusion) < 600


def test_analyst_handles_an_empty_registry():
    analysis = AnalystAgent(RuleRegistry()).analyze(chart(), "事业")

    assert analysis.evidence.matches == ()
    assert "不能形成可靠结论" in analysis.conclusion


def test_critic_passes_a_clean_analysis():
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")

    critique = CriticAgent().critique(analysis)

    assert critique.passed is True, critique.issues


def test_critic_flags_deterministic_language():
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")
    unsafe = replace(analysis, conclusion="你一定会成功")

    critique = CriticAgent().critique(unsafe)

    assert critique.passed is False
    assert any("确定性" in issue for issue in critique.issues)


def test_critic_requires_conflict_disclosure():
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")
    conflict = replace(analysis, evidence=replace(analysis.evidence, conflicts=(("A", "B"),)))

    critique = CriticAgent().critique(conflict)

    assert critique.passed is False
    assert any("冲突" in issue for issue in critique.issues)


def test_critic_flags_rules_that_have_not_passed_review():
    """未校核的规则不许以权威口吻出现在结论里。

    当前规则库全部是 ACTIVE，所以这条检查在默认配置下恒为空；它的价值在于
    以后：谁把一条草稿规则混进证据链，Critic 立刻拦下。
    """
    registry = RuleRegistry()
    registry.add(Rule(
        id="DRAFT_001",
        source="草稿来源",
        school=STRUCTURAL_SCHOOL,
        category="ten_god",
        condition={"day_master_root": "有根"},
        conclusion="草稿结论。",
        review_status=ReviewStatus.UNREVIEWED,
    ))
    analysis = AnalystAgent(registry).analyze(chart(), "事业")

    assert analysis.evidence.unreviewed_rule_ids == ("DRAFT_001",)
    critique = CriticAgent().critique(analysis)

    assert critique.passed is False
    assert any("尚未通过校核" in issue for issue in critique.issues)


def test_critic_flags_untraceable_rule_references():
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")
    broken = replace(analysis, evidence=replace(analysis.evidence, matches=()))

    critique = CriticAgent().critique(broken)

    assert critique.passed is False
    assert any("无法追溯" in issue or "证据为空" in issue for issue in critique.issues)
