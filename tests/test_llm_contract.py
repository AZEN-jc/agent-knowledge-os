"""提示契约的测试：输入边界、输出形状、越界处理。

这一层不接任何真实模型 —— 「契约能不能被绕过」和「模型强不强」是两件事。
模型再强，也不该被允许引用证据链之外的规则；模型再弱，越界也必须被记名。
"""

from __future__ import annotations

import inspect
import json

import pytest

from agents import prompt
from agents.prompt import (
    CERTAINTY_WORDS,
    CONTRACT_VERSION,
    DRAFT_KEYS,
    LOW_STRENGTH_CEILING,
    STRENGTH_MARKER,
    SYSTEM_PROMPT,
    build_prompt,
    build_revision_prompt,
    contract,
    evidence_payload,
    parse_draft,
    render_draft,
)
from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.evidence import build_evidence

CHAIN_SUBSET = ("STRUCT_ROOT_001", "STRUCT_ROOT_002")


def evidence(question: str = "事业"):
    chart = SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))
    return build_evidence(chart, default_registry(), topic=question)


def allowed(question: str = "事业") -> set[str]:
    return {match.rule.id for match in evidence(question).matches}


# ── 输入层：模型只能看到证据链 ─────────────────────────────────────────


def test_prompt_user_is_exactly_the_evidence_payload():
    item = evidence()
    request = build_prompt(item)

    assert request.user == evidence_payload(item)
    assert json.loads(request.user) == json.loads(
        json.dumps(item.to_dict(), ensure_ascii=False)
    )


def test_prompt_carries_no_chart_data():
    """命盘原始数据不在提示词里。

    事实的 ``source`` 形如 ``chart.pillars[*].earthly_branch`` —— 那是**路径**，
    不是取值。所以这里查的是「键」而不是「字符串」：真正要挡住的是命盘的
    结构本身（四柱对象、出生信息、大运），只要它们在提示词里，模型就有材料
    去「自己重算一遍命盘」，而那正是 MINGLI_PLAN.md §1.2 禁止的事。
    """
    keys = _all_keys(json.loads(evidence_payload(evidence())))

    for forbidden in (
        "birth", "pillars", "dayun", "na_yin", "heavenly_stem",
        "earthly_branch", "hidden_stems", "ten_god", "elements",
        "algorithm_version", "longitude", "latitude", "timezone",
    ):
        assert forbidden not in keys, f"提示词里出现了命盘字段：{forbidden}"


def test_source_paths_are_paths_not_chart_data():
    """把「路径 vs 取值」的区别钉下来。

    否则后人看到提示词里出现 ``earthly_branch`` 会以为命盘泄漏了，
    然后去「修」一个不存在的问题，把证据链的最后一跳删掉。
    """
    payload = evidence_payload(evidence())

    assert "chart.pillars[*].earthly_branch" in payload
    assert "earthly_branch" not in _all_keys(json.loads(payload))


def _all_keys(value) -> set[str]:
    """递归收集 JSON 结构里出现过的全部键名。"""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


def test_build_prompt_cannot_receive_a_chart():
    """签名里没有 Chart，模型就**在结构上**拿不到命盘。

    这条测试查的是类型系统，不是运行时行为：只要有人给 build_prompt 加上
    ``chart`` 参数，这里立刻失败 —— 加参数的人会先看到这条测试。
    """
    signature = inspect.signature(build_prompt)

    assert list(signature.parameters) == ["evidence"]
    assert "Chart" not in str(signature)


def test_system_prompt_states_every_hard_requirement():
    for word in CERTAINTY_WORDS:
        assert word in SYSTEM_PROMPT, f"系统提示词没有禁用 {word}"
    assert STRENGTH_MARKER in SYSTEM_PROMPT
    assert "rule_ids" in SYSTEM_PROMPT
    assert "证据链" in SYSTEM_PROMPT
    assert "coverage_note" in SYSTEM_PROMPT
    assert "conflicts" in SYSTEM_PROMPT


def test_evidence_payload_serializes_for_a_range_of_charts():
    """证据链里的值必须全部可 JSON 化。

    事实取值可以是元组（``ten_god_with_root`` 就是），条件里的 ``expected``
    也可能是列表。任何一处漏掉转换都会让提示词构造直接抛错 —— 与其在生产
    路径上炸，不如在这里把所有主题都跑一遍。
    """
    provider = SxtwlBaziProvider()
    for year in (1955, 1968, 1984, 1990, 2000, 2010, 2024):
        chart = provider.calculate(BirthInput(year, 6, 15, 8, 30))
        for question in ("命盘结构", "事业", "婚姻", "健康", "财运", "风水"):
            payload = evidence_payload(build_evidence(chart, default_registry(), topic=question))
            assert json.loads(payload)


def test_evidence_payload_refuses_to_stringify_unknown_values():
    """宁可响亮失败，也不要把无法序列化的值悄悄变成字符串。

    ``json.dumps(..., default=str)`` 会让「证据链里混进了不该有的东西」
    表现成「提示词里多了一串乱码」，然后被静默送给模型。
    """
    with pytest.raises(TypeError, match="无法序列化"):
        prompt._jsonable(object())


# ── 输出层：形状必须完全符合契约 ──────────────────────────────────────


def test_parse_draft_accepts_a_conforming_draft():
    draft = parse_draft(render_draft(CHAIN_SUBSET, "证据强度 0.79。"), set(CHAIN_SUBSET))

    assert draft.is_conforming
    assert draft.cited_rule_ids == CHAIN_SUBSET
    assert draft.text == "证据强度 0.79。"


def test_parse_draft_keeps_only_in_chain_rule_ids():
    draft = parse_draft(
        render_draft(["STRUCT_ROOT_001", "NOT_IN_CHAIN"], "正文"), {"STRUCT_ROOT_001"}
    )

    assert draft.cited_rule_ids == ("STRUCT_ROOT_001",)
    assert not draft.is_conforming


def test_parse_draft_records_every_out_of_chain_id():
    """越界引用要**逐条**记名，不能只报个数量。

    报告里说不出是哪个 ID 越了界，就没法定位是提示词没写清还是模型跑偏。
    """
    draft = parse_draft(
        render_draft(["A_FAKE", "B_FAKE", "STRUCT_ROOT_001"], "正文"), {"STRUCT_ROOT_001"}
    )

    assert len(draft.violations) == 2
    assert any("A_FAKE" in item for item in draft.violations)
    assert any("B_FAKE" in item for item in draft.violations)


def test_parse_draft_rejects_extra_fields():
    raw = json.dumps(
        {"rule_ids": [], "text": "正文", "confidence": "high"}, ensure_ascii=False
    )
    draft = parse_draft(raw, set())

    assert any("契约之外的字段" in item and "confidence" in item for item in draft.violations)


def test_parse_draft_rejects_missing_fields():
    draft = parse_draft(json.dumps({"text": "正文"}, ensure_ascii=False), set())

    assert any("缺少必需字段" in item and "rule_ids" in item for item in draft.violations)


def test_parse_draft_reports_non_json():
    draft = parse_draft("我基于命盘认为……", set())

    assert draft.text == ""
    assert any("不是合法 JSON" in item for item in draft.violations)


def test_parse_draft_reports_non_object_top_level():
    draft = parse_draft(json.dumps(["rule_ids", "text"], ensure_ascii=False), set())

    assert any("顶层必须是 JSON 对象" in item for item in draft.violations)


def test_parse_draft_reports_non_string_rule_ids():
    draft = parse_draft(json.dumps({"rule_ids": [1, 2], "text": "正文"}, ensure_ascii=False), set())

    assert any("必须是字符串数组" in item for item in draft.violations)
    assert draft.cited_rule_ids == ()


def test_parse_draft_reports_empty_text():
    draft = parse_draft(render_draft([], "   "), set())

    assert draft.text == ""
    assert any("text 为空" in item for item in draft.violations)


def test_parse_draft_reports_empty_rule_id():
    draft = parse_draft(json.dumps({"rule_ids": ["  "], "text": "正文"}, ensure_ascii=False), set())

    assert any("含空字符串" in item for item in draft.violations)


def test_parse_draft_dedupes_repeated_ids():
    draft = parse_draft(render_draft(["STRUCT_ROOT_001"] * 3, "正文"), {"STRUCT_ROOT_001"})

    assert draft.cited_rule_ids == ("STRUCT_ROOT_001",)
    assert draft.is_conforming


def test_parse_draft_strips_markdown_fences():
    """围栏是模型的书写习惯，不是内容 —— 剥掉它不放宽边界。

    这是唯一一处宽容处理。它不碰 ``rule_ids``，所以越界校验照旧。
    """
    fenced = "```json\n" + render_draft(CHAIN_SUBSET, "证据强度 0.79。") + "\n```"
    draft = parse_draft(fenced, set(CHAIN_SUBSET))

    assert draft.is_conforming
    assert draft.cited_rule_ids == CHAIN_SUBSET


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "{", "null", "[]", '"字符串"', "123", "```\n```", "{'a': 1}"],
)
def test_parse_draft_never_raises(raw):
    """解析失败必须走「记违约」这条路，不能抛异常。

    抛异常会让调用方只剩两个选择：整个失败，或静默放行。而正确做法是第三条
    路 —— 把违约当作可披露的事实带下去，让 Critic 把它变成用户看得见的意见。
    """
    draft = parse_draft(raw, set(CHAIN_SUBSET))

    assert not draft.is_conforming
    assert draft.text == ""


def test_render_and_parse_round_trip():
    text = "证据强度 0.79。存在 1 处规则分歧。"
    draft = parse_draft(render_draft(CHAIN_SUBSET, text), set(CHAIN_SUBSET))

    assert draft.text == text
    assert draft.cited_rule_ids == CHAIN_SUBSET


# ── 契约本身可审计 ────────────────────────────────────────────────────


def test_contract_exposes_the_whole_boundary():
    data = contract()

    assert data["version"] == CONTRACT_VERSION
    assert data["system_prompt"] == SYSTEM_PROMPT
    assert data["draft_schema"]["required"] == list(DRAFT_KEYS)
    assert data["draft_schema"]["additionalProperties"] is False
    assert data["forbidden_certainty_words"] == list(CERTAINTY_WORDS)
    assert data["low_strength_ceiling"] == LOW_STRENGTH_CEILING
    assert len(data["boundary"]) == 6
    assert data["notes"]


def test_contract_is_json_serializable():
    """契约要能直接经 API 返回；里面有不可序列化的值就会在响应层炸。"""
    assert json.loads(json.dumps(contract(), ensure_ascii=False))


def test_revision_prompt_repeats_the_evidence_and_the_issues():
    """重试只追加审查意见，不追加新证据 —— 否则「多轮修正」变成「多轮加料」。"""
    item = evidence()
    request = build_revision_prompt(
        item, parse_draft(render_draft([], "初稿"), set()), ("结论为空。", "缺少强度披露。")
    )

    assert evidence_payload(item) in request.user
    assert "结论为空。" in request.user
    assert "缺少强度披露。" in request.user
    assert request.system == SYSTEM_PROMPT
