"""引用白名单：能挂出去的出处角标，必须且只能来自证据链。

## 这一层守什么

「不编造」这条红线在生成侧的落点。模型输出里每一个 ``〔urn:...〕`` 都必须
能在证据链里找到出处；反过来，证据链里每条 classical 规则的 URN 都必须
出现在白名单里（否则那条规则永远无法被合法引用，等于白录）。

Phase 4.2 之前白名单只是 ``CriticAgent._provenance_issues`` 里的一个局部
变量。提成 :func:`agents.prompt.citation_allowlist` 之后，它成为可以
直接断言的显式概念。

## 一个容易漏的方向

**结构层规则没有 URN**，所以它们的 ID 不在白名单里。模型如果把
``STRUCT_PATTERN_001`` 这种结构层 ID 包在 ``〔...〕`` 里当典籍出处挂出去，
是另一种编造 —— 它伪装成「这是某本书上的话」。这条方向此前没人测。
"""

from __future__ import annotations

import json

import pytest

from agents.llm import FakeLLMProvider
from agents.prompt import citation_allowlist, parse_draft
from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from knowledge.default_rules import build_registry, default_schools
from knowledge.evidence import build_evidence

REGISTRY = build_registry(schools=default_schools())
CALCULATOR = BaziCalculator(SxtwlBaziProvider())

#: 一张会命中典籍层规则的命盘。
#:
#: **为什么是 1990-02-28 00:00。** Phase 3 录入的 13 条典籍断语全部出自
#: 《三命通會》卷八「六甲日甲子**時**斷」，条件同时要求
#: **day_pillar == 甲子 且 hour_pillar == 甲子**。
#:
#: 第一版测试选了两个都不对的日子：1990-02-01 是丁酉日（日柱不符），
#: 换成 1990-02-28 后又忘了时辰 —— 12 点时柱是庚午，命局主题下依然一条
#: 典籍规则都不命中，白名单断言直接空测。子时（00:00）时柱才是甲子，
#: 四柱庚午/戊寅/甲子/甲子，命中 rule_bazi_sanmingtonghui_j8_jiazi_jiazi。
MINGJU_BIRTH = BirthInput(1990, 2, 28, 0)


def evidence_for(topic: str = "命局"):
    chart = CALCULATOR.calculate_chart(MINGJU_BIRTH)
    return build_evidence(chart, REGISTRY, topic)


# ── 白名单的内容 ──────────────────────────────────────────────────────


def test_the_allowlist_contains_every_classical_rules_urn():
    evidence = evidence_for()
    classical_urns = {
        match.rule.urn
        for match in evidence.matches
        if match.rule.urn
    }
    allowlist = citation_allowlist(evidence)

    assert classical_urns, "这张盘应当命中至少一条带 URN 的典籍规则，否则本节是空测"
    assert classical_urns <= allowlist


def test_the_allowlist_holds_nothing_that_is_not_in_the_chain():
    """反向：白名单里不能有证据链之外的 URN。"""
    evidence = evidence_for()
    chain_urns = {
        match.rule.urn
        for match in evidence.matches
        if match.rule.urn
    }

    assert citation_allowlist(evidence) == chain_urns


def test_structural_rule_ids_are_never_in_the_allowlist():
    """结构层规则没有 URN，其 ID 不能被当成典籍出处引用。"""
    evidence = evidence_for("structure")
    allowlist = citation_allowlist(evidence)

    structural_ids = {
        match.rule.id
        for match in evidence.matches
        if not match.rule.urn
    }
    assert structural_ids, "结构层应有命中"
    assert allowlist.isdisjoint(structural_ids), (
        "结构层规则 ID 出现在 URN 白名单里 —— 那会让模型把结构层规则"
        "包装成典籍出处挂出去"
    )


def test_a_topic_without_classical_rules_has_an_empty_allowlist():
    """「事业」主题没有专属典籍规则，白名单应为空。"""
    evidence = evidence_for("事业")

    assert citation_allowlist(evidence) == frozenset()


# ── 白名单被执行：越界 URN 被 Critic 记名 ──────────────────────────────


def _analyse_with_text(text: str, rule_ids: list[str]):
    """用假 provider 让模型输出指定正文，跑完整分析。"""
    from runtime.mingli_service import MingLiService

    # max_revisions=0：只出稿一次，不让 Critic 触发重写。
    # 这里要验的是「这一稿是否被记违约」，重写会多消耗一条脚本，
    # 把断言对象变成第二轮输出。
    provider = FakeLLMProvider(
        responses=[json.dumps({"rule_ids": rule_ids, "text": text}, ensure_ascii=False)]
    )
    service = MingLiService(registry=REGISTRY, provider=provider, max_revisions=0)
    birth = {
        "year": MINGJU_BIRTH.year, "month": MINGJU_BIRTH.month,
        "day": MINGJU_BIRTH.day, "hour": MINGJU_BIRTH.hour,
    }
    return service.analyze(birth, "命局")


def test_a_urn_outside_the_allowlist_is_flagged_as_fabrication():
    """编一个证据链里没有的 URN，必须被判「疑似编造」。"""
    # 故意用一个**版本段不同**的 URN：edition 与卷都对得上，只有 ws 段是编的。
    # 这比整个 URN 都乱编更接近真实失败 —— 模型会「记得」大概的出处格式。
    fake_urn = "urn:divination:bazi:sanmingtonghui:ws9999999:j8.liujia_ri.jiazi_jiazi"

    result = _analyse_with_text(f"古法记为吉格〔{fake_urn}〕", [])

    assert result.critique["passed"] is False
    assert any("编造" in issue for issue in result.critique["issues"])


def test_a_real_urn_from_the_chain_is_not_flagged():
    """白名单里的 URN 不该被误报。"""
    evidence = evidence_for()
    classical = [
        match for match in evidence.matches
        if match.rule.urn and match.rule.source_tier.value == "classical"
    ]
    assert classical, "命局主题应命中典籍规则"

    result = _analyse_with_text(
        f"{classical[0].rule.conclusion}〔{classical[0].rule.urn}〕证据强度 0.50",
        [classical[0].rule.id],
    )

    stray = [issue for issue in result.critique["issues"] if "编造" in issue]
    assert not stray, f"白名单内的 URN 被误报为编造：{stray}"


def test_a_structural_rule_id_wrapped_as_a_urn_is_flagged():
    """结构层规则 ID 被包成出处角标，也是编造。"""
    evidence = evidence_for("structure")
    structural = [match for match in evidence.matches if not match.rule.urn]
    assert structural, "结构层应有命中"

    bogus = f"〔urn:divination:bazi:{structural[0].rule.id}〕"
    result = _analyse_with_text(f"古法记为{bogus}，证据强度 0.50", [])

    assert result.critique["passed"] is False
    assert any("编造" in issue for issue in result.critique["issues"])


# ── schema 与 parse_draft 不再各写一份 ─────────────────────────────────


@pytest.mark.parametrize("payload", [
    {"rule_ids": [], "text": "正文", "extra": 1},
    {"rule_ids": []},
    {"text": "正文"},
    {"rule_ids": "not-a-list", "text": "正文"},
    {"rule_ids": [1], "text": "正文"},
    {"rule_ids": ["  "], "text": "正文"},
    {"rule_ids": [], "text": ""},
    {"rule_ids": [], "text": 5},
])
def test_schema_issues_and_parse_draft_agree_on_every_shape(payload: dict):
    """同一份输入，schema 报的错必须出现在 parse_draft 的 violations 里。

    这条防的是「两份实现漂移」：schema 说有问题而 parse_draft 放行，
    契约就出现了一个谁都不知道的缺口。
    """
    from agents.prompt import schema_issues

    draft = parse_draft(json.dumps(payload, ensure_ascii=False), set())
    issues = schema_issues(payload)

    assert issues, f"{payload} 应当被 schema 判为有问题"
    for issue in issues:
        assert any(issue[:8] in violation for violation in draft.violations), (
            f"schema 报了「{issue}」但 parse_draft 的 violations 里没有："
            f"{draft.violations}"
        )


def test_a_conforming_draft_has_no_schema_issues():
    from agents.prompt import schema_issues

    assert schema_issues({"rule_ids": ["A"], "text": "正文"}) == []
    assert parse_draft(
        json.dumps({"rule_ids": ["A"], "text": "正文"}, ensure_ascii=False), {"A"}
    ).is_conforming
