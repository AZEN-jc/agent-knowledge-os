"""Critic 的独立性：它不许有 provider，也不许被 provider 拖下水。

## 为什么单独一层测这个

Critic 是这套系统里唯一的**独立审查**。它的价值全在「与被审对象无关」：
如果 Critic 自己也调 provider，那它审的就是「另一个模型的输出」，
而两个模型犯同一类错（比如都爱下确定性判断）时，审查形同虚设。

所以这里钉四件事：

1. **CriticAgent 没有 provider 字段** —— 构造签名里不接受，实例上也不存在；
2. **Analyst 的 provider 故障不影响 Critic** —— 审察看的是证据与结论文本，
   不碰网络；
3. **provider 返回垃圾时，Critic 每一样都能抓到** —— 这是 4.5 故障恢复的
   前置条件：先证明「垃圾能被识别」，才谈得上「识别之后怎么降级」；
4. **多轮修正有上限，且不凑合放行** —— 到上限带着未解决的问题返回，
   而不是「最后一次算了」。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import replace

import pytest

from agents.llm import FakeLLMProvider, ProviderError
from agents.mingli import (
    DRAFT_TEMPLATE,
    MAX_REVISIONS,
    AnalystAgent,
    CriticAgent,
)
from agents.prompt import render_draft
from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.models import Chart
from knowledge.default_rules import default_registry

REGISTRY = default_registry()
CHART = SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))

#: 「事业」主题的覆盖不足说明。重试测试要用它构造**真的能过审**的第二稿 ——
#: 只改掉确定性措辞不够，base_only 主题不披露覆盖不足同样过不了。
COVERAGE_NOTE = AnalystAgent(REGISTRY).analyze(CHART, "事业").evidence.coverage_note


def analyse(
    text: str,
    rule_ids: list[str] | None = None,
    revisions: int = 0,
    chart: Chart | None = None,
    topic: str = "事业",
):
    """让假 provider 输出指定正文，跑一轮分析。

    ``chart`` / ``topic`` 决定**证据链**，也就决定了白名单：在 A 主题下引
    B 主题的规则 ID，出稿阶段就会被当越界剔除。第一版「缺出处角标」那条
    测试就栽在这里 —— 在事业主题下引命局的典籍规则，cited_rule_ids 里
    根本没有它，出处角标检查自然看不到。
    """
    provider = FakeLLMProvider(
        responses=[render_draft(rule_ids or [], text)]
    )
    # **必须传 critic**：不传就走不到多轮修正，所有「重试」相关的断言
    # 都会变成只跑了第一轮。第一版就漏了它。
    agent = AnalystAgent(REGISTRY, provider=provider, max_revisions=revisions)
    return agent.analyze(chart if chart is not None else CHART, topic, critic=CriticAgent())


# ── 独立性：Critic 不碰 provider ──────────────────────────────────────


def test_the_critic_has_no_provider_parameter():
    """构造签名里不接受 provider。

    这条不是风格检查：签名是**第一道**防线。``CriticAgent(provider=...)``
    能写出来，就说明有人打算让它调模型，而那一行就是审查失效的起点。
    """
    parameters = inspect.signature(CriticAgent.__init__).parameters

    assert "provider" not in parameters
    assert not any(
        "llm" in name.lower() or "model" in name.lower() for name in parameters
    ), f"CriticAgent 的构造参数里出现了模型相关字段：{list(parameters)}"


def test_a_critic_instance_carries_no_model_at_all():
    critic = CriticAgent()
    attributes = [name for name in vars(critic)]

    assert attributes == [], f"CriticAgent 实例上不该有任何状态，实得 {attributes}"


def test_the_critic_works_while_the_provider_is_broken():
    """provider 整个坏掉时，审查照样能跑。

    构造一个必然抛 ``ProviderError`` 的 provider，Analyst 出稿会失败，
    但 ``CriticAgent.critique`` 直接对一份 Analysis 求值，不该碰网络。
    """
    class _BrokenProvider:
        name = "broken"
        model = "none"

        def complete(self, request):
            raise ProviderError("端点不可达")

    base = AnalystAgent(REGISTRY).analyze(CHART, "事业")
    analysis = replace(
        base,
        evidence=base.evidence,
        # 「事业」是 base_only 主题，结论必须带上 coverage_note 才算合规 ——
        # 否则这条测的是「Critic 无理由抓人」，不是「provider 坏了它仍工作」。
        conclusion=(
            f"证据强度 {base.evidence.strength:.2f}，以上为命盘结构证据的复述。"
            + base.evidence.coverage_note
        ),
    )

    # 关键：Critic 不接受 provider，也就不可能被它影响。
    critique = CriticAgent().critique(analysis)

    assert critique.passed is True, critique.issues


# ── provider 返回垃圾时，每一样都能被抓到 ──────────────────────────────


@pytest.mark.parametrize("label, text, expected_marker, premise", [
    ("空结论", "", "结论为空", None),
    ("确定性措辞", "一定会发财，证据强度 0.62", "确定性预测措辞", None),
    ("低强度不披露", "命盘结构如此。", "未披露强度", "low_strength"),
    ("无证据却声称有据", "基于已匹配的结构规则，日主有根。", "证据为空", "no_matches"),
])
def test_the_critic_catches_every_common_kind_of_garbage(
    label, text, expected_marker, premise
):
    """provider 最常见的四类垃圾，各有一条对应的检查。

    后两类的**前提要显式构造**，这点值得说明：

    - 「低强度不披露」要求 ``evidence.strength < LOW_STRENGTH_CEILING``。
      但本样例命盘强度 0.793，高于阈值 —— 这条分支对本盘永远不触发。
      强度算式本身是 Phase 3.5 的事，这里只验 Critic 的分支，所以用
      ``replace`` 造一份低强度证据。**不构造就等于空测**：它永远绿。
    - 「无证据却声称有据」要求 ``evidence.matches`` 为空。而结构层 13 条
      基础规则对任何命盘都命中，真实证据永远非空。同理构造空 matches。

    空测比失败更危险：失败会红，空测永远绿，还给人「这条守住了」的错觉。
    """
    analysis = analyse(text)
    if premise == "low_strength":
        analysis = replace(analysis, evidence=replace(analysis.evidence, strength=0.2))
    elif premise == "no_matches":
        analysis = replace(analysis, evidence=replace(analysis.evidence, matches=()))
    critique = CriticAgent().critique(analysis)

    assert critique.passed is False, f"「{label}」本该被拦下"
    assert any(expected_marker in issue for issue in critique.issues), (
        f"「{label}」被抓了，但原因不是「{expected_marker}」：{critique.issues}"
    )


def test_the_critic_catches_an_out_of_chain_rule_reference():
    """越界引用：剔除 + 记违约 + Critic 复算，三道都要有。"""
    analysis = analyse("证据强度 0.62", rule_ids=["STRUCT_PATTERN_999"])
    critique = CriticAgent().critique(analysis)

    assert critique.passed is False
    assert any("证据链之外" in issue for issue in critique.issues)
    assert any(
        "STRUCT_PATTERN_999" in violation
        for violation in analysis.contract_violations
    )


def test_the_critic_catches_a_fabricated_urn_in_the_text():
    """正文里编造出处角标。"""
    analysis = analyse("古法记为吉格〔urn:divination:bazi:fake:ws1:j1.x〕，证据强度 0.62")
    critique = CriticAgent().critique(analysis)

    assert critique.passed is False
    assert any("编造" in issue for issue in critique.issues)


def test_the_critic_catches_a_missing_classical_footnote():
    """引了典籍规则却不挂出处角标。"""
    # 甲子日甲子时：命中《三命通會》卷八的典籍断语。
    chart = SxtwlBaziProvider().calculate(BirthInput(1990, 2, 28, 0))
    evidence = AnalystAgent(REGISTRY).analyze(chart, "命局").evidence
    classical = [m for m in evidence.matches if m.rule.urn]
    assert classical, "该命盘应命中典籍规则，否则本节空测"

    # **必须在命局主题下出稿。** 第一版在「事业」主题下引命局的规则 ID，
    # 那个 ID 不在事业证据的白名单里，出稿阶段就被当越界剔除，
    # cited_rule_ids 里根本没有它 —— 出处角标检查看不到，报出来的是
    # 「越界引用」而不是「缺角标」，测的就不是想测的那条分支。
    analysis = analyse(
        "古法有云，甲子日甲子时主贵。证据强度 0.62",
        [classical[0].rule.id],
        chart=chart,
        topic="命局",
    )
    critique = CriticAgent().critique(analysis)

    assert critique.passed is False
    assert any("出处角标" in issue for issue in critique.issues)


def test_the_critic_catches_an_untraced_evidence_chain():
    """证据链断环：有人绕过匹配器手工拼了一个没有来源的 RuleMatch。"""
    from knowledge.rules import RuleMatch

    evidence = AnalystAgent(REGISTRY).analyze(CHART, "事业").evidence
    broken = replace(
        evidence,
        matches=tuple(
            RuleMatch(rule=match.rule, traces=()) for match in evidence.matches
        ),
    )
    analysis = replace(AnalystAgent(REGISTRY).analyze(CHART, "事业"), evidence=broken)

    critique = CriticAgent().critique(analysis)

    assert critique.passed is False
    assert any("断环" in issue for issue in critique.issues)


def test_a_conforming_draft_passes_the_critic():
    """该放行的要放行 —— 只测「能拦」是半截守卫。"""
    evidence = AnalystAgent(REGISTRY).analyze(CHART, "事业").evidence
    text = (
        f"证据强度 {evidence.strength:.2f}，以上为命盘结构证据的复述。"
        + evidence.coverage_note
    )
    analysis = analyse(text, [m.rule.id for m in evidence.matches][:2])

    critique = CriticAgent().critique(analysis)

    assert critique.passed is True, critique.issues


# ── 多轮修正：有上限，不凑合放行 ──────────────────────────────────────


def test_revisions_stop_at_the_cap_and_report_the_unresolved_issues():
    """模型一直不改，重写必须停下来，并把问题带回去。

    「改到通过为止」会把一次失败放大成 N 次调用；而「到上限就假装通过」
    是把审查失效藏起来。正确做法是到上限带着问题返回。
    """
    # 永远返回同一段含确定性措辞的文本 —— 永远过不了。
    provider = FakeLLMProvider(
        responses=[render_draft([], "一定会发财，证据强度 0.62")] * (MAX_REVISIONS + 2)
    )
    agent = AnalystAgent(REGISTRY, provider=provider, max_revisions=MAX_REVISIONS)

    # 不传 critic 就没有修正循环，revisions 恒为 0 —— 第一版就漏了它，
    # 于是这条测的是「没有循环」而不是「循环到上限会停」。
    analysis = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert analysis.revisions == MAX_REVISIONS
    assert "一定" in analysis.conclusion
    assert CriticAgent().critique(analysis).passed is False


def test_revision_prompts_carry_only_the_evidence_and_the_issues():
    """重试只回灌证据链与审查意见，不追加新信息。

    否则「多轮修正」会变成「多轮加料」—— 越修离证据越远，
    而每一轮都看起来是在回应上一轮的问题。
    """
    seen: list[str] = []
    provider = FakeLLMProvider(
        responses=[
            render_draft([], "一定会发财，证据强度 0.62"),
            # 第二稿必须**真的能过审**：除了改掉确定性措辞，还要带上
            # coverage_note —— 「事业」是 base_only 主题，不披露覆盖不足
            # 同样过不了。第一版只改了措辞，第三轮脚本用尽直接 RuntimeError。
            render_draft([], f"证据强度 0.62，命盘结构证据的复述。{COVERAGE_NOTE}"),
        ]
    )
    agent = AnalystAgent(REGISTRY, provider=provider, max_revisions=2)
    agent.analyze(CHART, "事业", critic=CriticAgent())

    for request in provider.requests:
        seen.append(request.user)

    assert len(seen) >= 2
    # 第二轮的 user 里必须出现审查意见，且仍然是同一份证据链。
    assert "审查意见" in seen[1]

    # 证据链是 indent=2 的多行 JSON，首行只是 "{" —— 按行切再 loads 会炸。
    # 正确切法是按分隔符：证据链在「你上一次的输出」之前，且首次请求的
    # user **就是**证据链本身（一个字节都不多）。
    head, separator, _ = seen[1].partition("\n── 你上一次的输出 ──")
    assert separator, "第二轮请求里找不到上一次输出的分隔符"
    assert json.loads(seen[0]) == json.loads(head), (
        "两轮的证据链必须一致 —— 重试不加料"
    )
    # 上一轮的输出也要原样带回，模型才知道要改什么。
    assert "一定会发财" in seen[1]


def test_the_template_path_is_not_sent_through_revision():
    """模板路径没有 provider，也就不该有 revisions。"""
    analysis = AnalystAgent(REGISTRY).analyze(CHART, "事业")

    assert analysis.draft_source == DRAFT_TEMPLATE
    assert analysis.revisions == 0
    assert analysis.contract_violations == ()
