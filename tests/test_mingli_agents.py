"""Analyst/Critic 的本地契约测试。"""

from dataclasses import replace

import pytest

from agents.llm import FakeLLMProvider
from agents.mingli import (
    CONCLUSION_LIMIT,
    DRAFT_LLM,
    DRAFT_TEMPLATE,
    AnalystAgent,
    CriticAgent,
)
from agents.prompt import render_draft
from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.provenance import ReviewStatus
from knowledge.rules import Rule, RuleRegistry
from knowledge.schools import STRUCTURAL_SCHOOL
from knowledge.topics import STRUCTURAL_TOPIC


def chart():
    return SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))


def conflicted_chart():
    """已知会触发格局命名法分歧的命盘（两法给出不同格局名）。"""
    return SxtwlBaziProvider().calculate(BirthInput(2024, 2, 4, 16, 45))


def one_rule_registry() -> RuleRegistry:
    """只有一条规则 → 证据强度必然偏低（raw 1.0 → 1/(1+3) = 0.25）。"""
    registry = RuleRegistry()
    registry.add(Rule(
        id="LOW_001",
        source="测试用来源",
        school=STRUCTURAL_SCHOOL,
        category="ten_god",
        topic=STRUCTURAL_TOPIC,
        condition={"day_master_root": "有根"},
        conclusion="日主在四支有根。",
        confidence="HIGH",
        review_status=ReviewStatus.ACTIVE,
    ))
    return registry


def evidence(question: str = "事业"):
    """模板路径下的证据层输出，供 provider 测试构造合规草稿。"""
    return AnalystAgent(default_registry()).analyze(chart(), question).evidence


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
        topic=STRUCTURAL_TOPIC,
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


# ── Phase 4：provider 路径 ─────────────────────────────────────────────


def test_analyst_without_provider_keeps_the_deterministic_path():
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")

    assert analysis.draft_source == DRAFT_TEMPLATE
    assert analysis.provider == ""
    assert analysis.model == ""
    assert analysis.revisions == 0
    assert analysis.contract_violations == ()
    assert analysis.cited_rule_ids, "模板路径也要报出引用了哪几条规则"
    assert analysis.certainty_risk is False


def test_provider_path_reports_where_the_draft_came_from():
    provider = FakeLLMProvider(responses=[render_draft([], "证据强度 0.79。")])
    analysis = AnalystAgent(default_registry(), provider=provider).analyze(chart(), "命盘结构")

    assert analysis.draft_source == DRAFT_LLM
    assert analysis.provider == "fake"
    assert analysis.model == "scripted"
    assert analysis.revisions == 0
    assert analysis.conclusion == "证据强度 0.79。"
    assert len(provider.requests) == 1


def test_provider_path_skips_the_critic_when_none_is_given():
    provider = FakeLLMProvider(responses=[render_draft([], "证据强度 0.79。")])
    AnalystAgent(default_registry(), provider=provider).analyze(chart(), "命盘结构")

    assert len(provider.requests) == 1


def test_out_of_chain_rule_is_stripped_and_the_critic_says_so():
    """越界引用不会被静默丢弃：剔除、记名、由 Critic 披露。

    这是 Phase 4 验收标准 2「不引用不存在的规则」的落点。如果解析层只是
    「过滤掉就算了」，模型编造规则 ID 这件事就永远没人知道。
    """
    provider = FakeLLMProvider(
        responses=[render_draft(["GHOST_RULE_999"], "证据强度 0.79。")] * 3
    )
    analysis = AnalystAgent(
        default_registry(), provider=provider, max_revisions=2
    ).analyze(chart(), "命盘结构", critic=CriticAgent())

    assert analysis.cited_rule_ids == ()
    assert any("GHOST_RULE_999" in item for item in analysis.contract_violations)
    critique = CriticAgent().critique(analysis)
    assert critique.passed is False
    assert any("GHOST_RULE_999" in issue for issue in critique.issues)


def test_critic_recomputes_cited_rules_without_trusting_the_parser():
    """独立复算：不信任「解析时已经过滤过」。

    解析层的保证只对「走 parse_draft 的路径」成立。换 provider 适配层时若漏掉
    那一步，``contract_violations`` 会是空的 —— 复算仍然拦得住。
    """
    analysis = AnalystAgent(default_registry()).analyze(chart(), "事业")
    bypassed = replace(
        analysis, cited_rule_ids=("GHOST_RULE_999",), contract_violations=()
    )

    critique = CriticAgent().critique(bypassed)

    assert critique.passed is False
    assert any("证据链之外" in issue and "GHOST_RULE_999" in issue for issue in critique.issues)


def test_multi_round_revision_rewrites_until_the_critic_passes():
    """初稿漏披露 → Critic 拦下 → 回灌重写 → 通过。"""
    item = evidence("事业")
    ids = [match.rule.id for match in item.matches][:2]
    provider = FakeLLMProvider(responses=[
        render_draft(ids, "证据强度 0.79。"),
        render_draft(ids, f"证据强度 0.79。{item.coverage_note}"),
    ])

    analysis = AnalystAgent(default_registry(), provider=provider).analyze(
        chart(), "事业", critic=CriticAgent()
    )

    assert analysis.revisions == 1
    assert len(provider.requests) == 2
    assert item.coverage_note in analysis.conclusion
    assert analysis.contract_violations == ()
    assert CriticAgent().critique(analysis).passed


def test_revision_prompt_carries_the_previous_draft_and_the_issue():
    item = evidence("事业")
    ids = [match.rule.id for match in item.matches][:2]
    provider = FakeLLMProvider(responses=[
        render_draft(ids, "证据强度 0.79。"),
        render_draft(ids, f"证据强度 0.79。{item.coverage_note}"),
    ])
    AnalystAgent(default_registry(), provider=provider).analyze(
        chart(), "事业", critic=CriticAgent()
    )

    revision = provider.requests[1].user
    assert "你上一次的输出" in revision
    assert "证据强度 0.79。" in revision
    assert "审查意见" in revision
    assert "未披露主题覆盖不足" in revision


def test_revision_stops_at_the_limit_and_reports_what_is_left():
    """到上限就带着未解决的问题返回，不做「最后一次凑合放行」。

    假装修好了比明说没修好危险得多：前者会让读者以为审查通过了。
    """
    provider = FakeLLMProvider(responses=[render_draft([], "证据强度 0.79。")] * 5)
    analysis = AnalystAgent(
        default_registry(), provider=provider, max_revisions=1
    ).analyze(chart(), "事业", critic=CriticAgent())

    assert analysis.revisions == 1
    assert len(provider.requests) == 2, "上限 1 轮 = 初稿 + 1 次重写"
    critique = CriticAgent().critique(analysis)
    assert critique.passed is False
    assert any("未披露主题覆盖不足" in issue for issue in critique.issues)


def test_analyst_rejects_a_negative_revision_limit():
    with pytest.raises(ValueError, match="max_revisions"):
        AnalystAgent(default_registry(), provider=FakeLLMProvider(responses=[]), max_revisions=-1)


def test_certainty_risk_is_recorded_from_the_draft():
    provider = FakeLLMProvider(responses=[render_draft([], "你一定会成功。")])
    analysis = AnalystAgent(default_registry(), provider=provider).analyze(chart(), "命盘结构")

    assert analysis.certainty_risk is True


def test_critic_flags_a_draft_that_is_not_valid_json():
    provider = FakeLLMProvider(responses=["我基于命盘认为……"] * 3)
    analysis = AnalystAgent(
        default_registry(), provider=provider, max_revisions=0
    ).analyze(chart(), "命盘结构", critic=CriticAgent())

    assert analysis.conclusion == ""
    critique = CriticAgent().critique(analysis)
    assert critique.passed is False
    assert any("违反提示契约" in issue for issue in critique.issues)
    assert any("结论为空" in issue for issue in critique.issues)


# ── Phase 4：强度与冲突的披露口径 ──────────────────────────────────────


def test_low_strength_must_disclose_the_strength():
    low = AnalystAgent(one_rule_registry()).analyze(chart(), "事业")
    assert low.evidence.strength < 0.5

    undisclosed = replace(low, conclusion="日主在四支有根，命盘结构清晰。")
    critique = CriticAgent().critique(undisclosed)

    assert critique.passed is False
    assert any("未披露强度" in issue for issue in critique.issues)


def test_low_strength_with_disclosure_passes():
    low = AnalystAgent(one_rule_registry()).analyze(chart(), "事业")

    assert "证据强度" in low.conclusion
    assert CriticAgent().critique(low).passed, CriticAgent().critique(low).issues


def test_high_strength_does_not_require_the_strength_marker():
    """阈值只在低强度下生效 —— 不是「任何结论都必须带强度」。"""
    analysis = AnalystAgent(default_registry()).analyze(chart(), "命盘结构")
    assert analysis.evidence.strength >= 0.5

    stripped = replace(analysis, conclusion="基于已匹配的结构规则：日主有根。")

    assert CriticAgent().critique(stripped).passed


def test_critic_blocks_conflicts_that_are_not_disclosed():
    analysis = AnalystAgent(default_registry()).analyze(conflicted_chart(), "事业")
    assert analysis.evidence.conflicts, "该命盘应当触发格局命名法分歧"

    undisclosed = replace(analysis, conclusion="基于已匹配的结构规则：月支本气为正官。")

    critique = CriticAgent().critique(undisclosed)

    assert critique.passed is False
    assert any("规则冲突" in issue for issue in critique.issues)


def test_disclosed_conflicts_are_not_an_error():
    """Phase 3 的检查是「有冲突就拦」，拦的却是冲突本身。

    冲突是命盘的真实情况，不是缺陷。正确口径和主题覆盖一致：
    **查披露，不查存在**。这条测试钉住这个口径。
    """
    analysis = AnalystAgent(default_registry()).analyze(conflicted_chart(), "事业")

    assert analysis.evidence.conflicts
    assert "分歧" in analysis.conclusion
    assert CriticAgent().critique(analysis).passed


def test_critic_flags_an_empty_conclusion():
    analysis = AnalystAgent(default_registry()).analyze(chart(), "命盘结构")

    critique = CriticAgent().critique(replace(analysis, conclusion="   "))

    assert critique.passed is False
    assert any("结论为空" in issue for issue in critique.issues)


# ── Phase 5：典籍断语的位置与出处角标 ─────────────────────────────────


def destiny_chart():
    """日柱甲子、时柱甲子 —— 命中《三命通會》卷八「甲子日甲子时」。"""
    return SxtwlBaziProvider().calculate(BirthInput(1980, 2, 21, 0))


def destiny_analysis():
    return AnalystAgent(default_registry()).analyze(destiny_chart(), "命局")


def the_classical_match(analysis):
    """本盘命中的那条典籍规则（当前底本下只有一条）。"""
    assert analysis.evidence.domain_matches
    return analysis.evidence.domain_matches[0]


def test_classical_verdict_leads_the_conclusion():
    """问「命局」时，典籍断语是答案，结构层是背景。

    回归：排序若只看置信度，典籍断语（MEDIUM）会被结构层命中（HIGH）挤到
    后面，落进「另有 N 条规则命中，详见证据链」里。用户问命局，答案却藏在
    「详见」后面 —— 那等于没给答案。
    """
    analysis = destiny_analysis()
    urn = the_classical_match(analysis).rule.urn

    assert analysis.conclusion.startswith("典籍断语")
    assert f"〔{urn}〕" in analysis.conclusion
    # 典籍断语整段必须排在结构层那一段之前，而不是被夹在中间
    assert analysis.conclusion.index(urn) < analysis.conclusion.index("结构规则")


def test_classical_rule_is_cited_first():
    """引用顺序也要跟着排序走，否则 API 消费者按 cited_rule_ids 渲染时又是错的。"""
    analysis = destiny_analysis()

    assert analysis.cited_rule_ids[0] == the_classical_match(analysis).rule.id


def test_deterministic_destiny_analysis_passes_the_critic():
    """模板路径自己就要挂对角标 —— 否则 Critic 会拦下自家产出。"""
    critique = CriticAgent().critique(destiny_analysis())

    assert critique.passed is True, critique.issues


def test_critic_flags_a_classical_verdict_without_a_footnote():
    """模型说了「古法记为子遥巳格」却不说是哪本书哪一卷 —— 必须拦下。

    不挂出处的典籍断语和道听途说没有区别：读者无法回查，只能选择信或不信，
    而「信或不信」正是这套系统要消灭的东西。
    """
    analysis = destiny_analysis()
    match = the_classical_match(analysis)
    unfootnoted = replace(
        analysis,
        draft_source=DRAFT_LLM,
        conclusion=f"古法记为子遥巳格。证据强度 {analysis.evidence.strength:.2f}。",
        cited_rule_ids=(match.rule.id,),
    )

    critique = CriticAgent().critique(unfootnoted)

    assert critique.passed is False
    assert any("出处角标" in issue and match.rule.urn in issue for issue in critique.issues)


def test_critic_accepts_a_classical_verdict_with_its_footnote():
    """同一份草稿，补上角标就通过 —— 否则这条检查只是「一律拦下」。"""
    analysis = destiny_analysis()
    match = the_classical_match(analysis)
    footnoted = replace(
        analysis,
        draft_source=DRAFT_LLM,
        conclusion=(
            f"古法记为子遥巳格〔{match.rule.urn}〕。"
            f"证据强度 {analysis.evidence.strength:.2f}。"
        ),
        cited_rule_ids=(match.rule.id,),
    )

    assert CriticAgent().critique(footnoted).passed is True


def test_critic_flags_a_footnote_that_is_not_in_the_evidence_chain():
    """编造出处比不挂出处更糟：它伪装成可核验的样子。

    这里换上的 URN 是**真实存在**的原子（甲午日那条），只是本盘没命中它。
    所以「URN 格式合法」「底本里查得到」都拦不住 —— 只有跟证据链比对才行。
    """
    analysis = destiny_analysis()
    real_urn = the_classical_match(analysis).rule.urn
    foreign_urn = "urn:divination:bazi:sanmingtonghui:ws845354:j8.liujia_ri.jiawu_jiazi"

    assert foreign_urn != real_urn
    tampered = replace(
        analysis, conclusion=analysis.conclusion.replace(real_urn, foreign_urn)
    )

    critique = CriticAgent().critique(tampered)

    assert critique.passed is False
    assert any("编造" in issue and foreign_urn in issue for issue in critique.issues)


def test_structural_rules_do_not_need_a_footnote():
    """要求不能扩到结构层 —— 它的出处是条件追踪，不是文本。

    过度要求会让 Critic 对一份完全合规的结构层结论报错。误报的代价比漏报更重：
    一旦 Critic 的意见里混进噪音，人就不再逐条读了。
    """
    analysis = AnalystAgent(default_registry()).analyze(chart(), "命盘结构")

    assert "〔urn:" not in analysis.conclusion
    assert CriticAgent().critique(analysis).passed is True

