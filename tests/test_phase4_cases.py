"""Phase 4 验收案例：10 个命盘 × 问句，走两条出稿路径。

案例数据在 ``tests/cases/mingli_phase4_cases.json``。这里断言的是**管道行为**：
匹配到多少条规则、主题覆盖状态是什么、强度有没有到下限、该披露的东西有没有
披露。**不**断言任何一条命理结论正确 —— 那需要典籍断语和外部基准，Phase 4
一样给不出。

两条路径共用同一份证据层：模板路径（默认）与 provider 路径（假 provider）。
同一份输入在两条路径下必须给出**同样的结构结论**，差别只在措辞由谁组织。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents.llm import FakeLLMProvider
from agents.mingli import AnalystAgent, CriticAgent
from agents.prompt import render_draft
from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.evidence import Evidence, build_evidence

CASES_PATH = Path(__file__).parent / "cases" / "mingli_phase4_cases.json"


def _load() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return data["defaults"], data["cases"]


DEFAULTS, CASES = _load()
IDS = [case["id"] for case in CASES]


def _evidence(case: dict[str, Any]) -> Evidence:
    chart = SxtwlBaziProvider().calculate(BirthInput(**case["birth"]))
    return build_evidence(chart, default_registry(), topic=case["question"])


def _chart(case: dict[str, Any]):
    return SxtwlBaziProvider().calculate(BirthInput(**case["birth"]))


def _conforming_draft(item: Evidence) -> str:
    """按契约生成一份**合规**草稿，供假 provider 使用。

    内容全部从证据里抄：强度、冲突条数、覆盖说明。这样「模型」本身不引入
    任何新信息，测试验的就是管道而不是模型的措辞水平。
    """
    parts = [f"证据强度 {item.strength:.2f}。"]
    if item.conflicts:
        parts.append(f"存在 {len(item.conflicts)} 处规则分歧，并列呈现，不做取舍。")
    if str(item.status) != "covered":
        parts.append(item.coverage_note)
    return render_draft([match.rule.id for match in item.matches][:3], " ".join(parts))


def test_case_file_covers_ten_cases():
    assert len(CASES) == 10
    assert len(set(IDS)) == 10


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_template_path_satisfies_the_case(case: dict[str, Any]):
    item = _evidence(case)
    analysis = AnalystAgent(default_registry()).analyze(_chart(case), case["question"])

    assert len(item.matches) >= DEFAULTS["min_rules"]
    assert item.strength >= DEFAULTS["min_strength"]
    assert str(item.status) == case["expect_status"]
    assert len(item.conflicts) >= case["min_conflicts"]

    chain_ids = {match.rule.id for match in item.matches}
    assert set(analysis.cited_rule_ids) <= chain_ids
    assert analysis.draft_source == "template"
    assert analysis.contract_violations == ()
    assert "证据强度" in analysis.conclusion
    if case["expect_status"] != "covered":
        assert item.coverage_note in analysis.conclusion
    assert CriticAgent().critique(analysis).passed, CriticAgent().critique(analysis).issues


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_provider_path_satisfies_the_case(case: dict[str, Any]):
    item = _evidence(case)
    provider = FakeLLMProvider(responses=[_conforming_draft(item)])
    analyst = AnalystAgent(default_registry(), provider=provider)

    analysis = analyst.analyze(_chart(case), case["question"], critic=CriticAgent())

    chain_ids = {match.rule.id for match in item.matches}
    assert analysis.draft_source == "llm"
    assert analysis.provider == "fake"
    assert analysis.model == "scripted"
    assert analysis.revisions == 0, "合规草稿不该触发重写"
    assert set(analysis.cited_rule_ids) <= chain_ids
    assert analysis.contract_violations == ()

    critique = CriticAgent().critique(analysis)
    assert critique.passed, critique.issues


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_first_request_carries_exactly_the_evidence(case: dict[str, Any]):
    """两条路径共用同一份证据；provider 首次拿到的就是它的 JSON，不多不少。"""
    item = _evidence(case)
    provider = FakeLLMProvider(responses=[_conforming_draft(item)])
    AnalystAgent(default_registry(), provider=provider).analyze(
        _chart(case), case["question"], critic=CriticAgent()
    )

    assert len(provider.requests) == 1
    assert json.loads(provider.requests[0].user) == json.loads(
        json.dumps(item.to_dict(), ensure_ascii=False)
    )
