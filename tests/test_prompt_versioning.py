"""Prompt 版本管理：提示词内容与版本号必须能对上。

## 这一层守什么

``CONTRACT_VERSION = "2"`` 是人手抄的字符串。改了 ``SYSTEM_PROMPT`` 却忘了
改版本号，``contract()["version"]`` 照样返回 "2"，而两次分析用的提示词
已经不同了 —— 用户看到同一版本号，实际拿到的是不同的东西。
这类漂移不报错、不告警，只能靠**指纹**发现。

所以这里有两个版本概念，分工明确：

- ``CONTRACT_VERSION`` —— 语义版本，人维护，给人看；
- ``contract_fingerprint()`` —— 内容指纹，机器算，给机器看。

测试的任务是证明后者真的对**每一项**影响模型行为的输入敏感。
漏一项，那一项就成了「改了也没人知道」的暗门。
"""

from __future__ import annotations

import pytest

import agents.prompt as prompt_module
from agents.llm import FakeLLMProvider
from agents.prompt import contract, contract_fingerprint
from knowledge.rules import Rule, RuleRegistry
from runtime.mingli_service import MingLiService

BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12}


# ── 指纹的稳定性 ──────────────────────────────────────────────────────


def test_the_fingerprint_is_stable_across_calls():
    assert contract_fingerprint() == contract_fingerprint()


def test_the_fingerprint_is_short_and_hex():
    fingerprint = contract_fingerprint()
    assert len(fingerprint) == 16
    int(fingerprint, 16)  # 不是十六进制会抛


def test_the_contract_exposes_both_the_version_and_the_fingerprint():
    payload = contract()

    assert payload["version"]
    assert payload["fingerprint"] == contract_fingerprint()
    assert payload["fingerprint"] != payload["version"], "两个字段不该是同一个值"


# ── 敏感度：每一项影响模型的输入改了，指纹都必须变 ────────────────────


@pytest.mark.parametrize("attribute, new_value", [
    ("SYSTEM_PROMPT", "你是另一个提示词。"),
    ("DRAFT_SCHEMA", {"type": "object", "required": ["rule_ids"]}),
    ("BOUNDARY_RULES", ("只留一条边界。",)),
    ("CERTAINTY_WORDS", ("必然",)),
    ("STRENGTH_MARKER", "证据水平"),
    ("LOW_STRENGTH_CEILING", 0.9),
    ("FOOTNOTE_OPEN", "["),
])
def test_changing_any_contract_input_changes_the_fingerprint(attribute, new_value):
    """漏掉哪一项，哪一项就成了「改了也没人知道」的暗门。"""
    original = getattr(prompt_module, attribute)
    try:
        setattr(prompt_module, attribute, new_value)
        assert contract_fingerprint() != _BASELINE, (
            f"改动 {attribute} 后指纹没变 —— 这一项没有纳入指纹计算"
        )
    finally:
        setattr(prompt_module, attribute, original)


_BASELINE = contract_fingerprint()


def test_changing_the_semantic_version_also_changes_the_fingerprint():
    """语义版本本身也是内容的一部分。

    有人会问「版本号变了但内容没变，指纹该不该变」。该变：版本号的用途正是
    区分两批不同的东西，内容相同而版本号不同时，它们仍然是两次不同的发布。
    """
    original = prompt_module.CONTRACT_VERSION
    try:
        prompt_module.CONTRACT_VERSION = "3"
        assert contract_fingerprint() != _BASELINE
    finally:
        prompt_module.CONTRACT_VERSION = original


# ── 分析结果带上两个指纹 ──────────────────────────────────────────────


def test_an_analysis_carries_both_fingerprints():
    service = MingLiService()
    payload = service.analyze(BIRTH, "事业").to_dict()

    draft = payload["analysis"]["draft"]
    assert draft["contract_fingerprint"] == contract_fingerprint()
    assert draft["rule_fingerprint"]
    assert len(draft["rule_fingerprint"]) == 16


def test_the_template_path_also_carries_them():
    """模板路径同样受契约与规则库影响，不能只有 LLM 路径带指纹。"""
    payload = MingLiService().analyze(BIRTH, "事业").to_dict()

    assert payload["analysis"]["draft"]["source"] == "template"
    assert payload["analysis"]["draft"]["contract_fingerprint"]
    assert payload["analysis"]["draft"]["rule_fingerprint"]


def test_two_services_built_from_the_same_registry_agree():
    """同库重建的两个服务必须给出同一指纹 —— 否则指纹没有可比性。"""
    first = MingLiService().analyze(BIRTH, "事业").to_dict()
    second = MingLiService().analyze(BIRTH, "事业").to_dict()

    assert (
        first["analysis"]["draft"]["rule_fingerprint"]
        == second["analysis"]["draft"]["rule_fingerprint"]
    )


def test_a_different_rule_library_gives_a_different_rule_fingerprint():
    """换一套规则库，指纹必须变。

    这条证明 ``rule_fingerprint`` 真的反映了规则内容，而不是一个常量。
    """
    registry = RuleRegistry()
    registry.add(Rule(
        id="ONLY_RULE", source="fixture", school="fixture", category="structure",
        condition={"day_master": "甲"}, conclusion="日主为甲。",
    ))
    payload = MingLiService(registry=registry).analyze(BIRTH, "结构").to_dict()

    baseline = MingLiService().analyze(BIRTH, "结构").to_dict()

    assert payload["analysis"]["draft"]["rule_fingerprint"] != (
        baseline["analysis"]["draft"]["rule_fingerprint"]
    )
    # 契约指纹不受规则库影响 —— 它只描述提示词。
    assert payload["analysis"]["draft"]["contract_fingerprint"] == (
        baseline["analysis"]["draft"]["contract_fingerprint"]
    )


def test_a_different_provider_does_not_change_the_contract_fingerprint():
    """provider 不影响契约指纹：契约是提示词与 schema，与用哪个模型无关。"""
    # 只出稿一轮：这里要验的是「指纹与 provider 无关」，重写会多消耗脚本。
    with_provider = MingLiService(
        provider=FakeLLMProvider(responses=['{"rule_ids": [], "text": "证据不足"}']),
        max_revisions=0,
    ).analyze(BIRTH, "事业").to_dict()
    without = MingLiService().analyze(BIRTH, "事业").to_dict()

    assert (
        with_provider["analysis"]["draft"]["contract_fingerprint"]
        == without["analysis"]["draft"]["contract_fingerprint"]
    )


def test_the_revision_prompt_reuses_the_same_contract():
    """多轮修正用的是同一个契约 —— 指纹不能因为重写而变化。"""
    from agents.prompt import build_prompt, build_revision_prompt
    from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
    from knowledge.default_rules import build_registry, default_schools
    from knowledge.evidence import build_evidence

    registry = build_registry(schools=default_schools())
    chart = BaziCalculator(SxtwlBaziProvider()).calculate_chart(BirthInput(1990, 2, 1, 12))
    evidence = build_evidence(chart, registry, "事业")

    assert build_prompt(evidence).system == build_revision_prompt(
        evidence, prompt_module.Draft("正文", (), ()), ("问题一",)
    ).system
