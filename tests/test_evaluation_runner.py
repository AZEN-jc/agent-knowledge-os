"""评估器的测试。

评估器是**测量工具**，所以它自己要能被证伪：如果每条不变量都不会因为
违规而变红，那它跑出来的「30/30 passed」就只是一句安慰。

这里的做法是给每条不变量喂一份**故意违规**的 payload，断言它报出问题；
再喂一份合规的，断言它不报。两头都钉住，才叫真的在测。
"""

import subprocess
import sys
from pathlib import Path

from evaluation.runner import (
    ALL_INVARIANTS,
    INVARIANTS,
    REPRODUCIBILITY,
    _check_chain_traced,
    _check_citations_within_chain,
    _check_critique_passed,
    _check_no_certainty_language,
    _check_strength_in_range,
    evaluate,
    render,
)

REPO = Path(__file__).resolve().parent.parent


def payload(**overrides):
    """一份合规的 payload，按需覆盖某几处来造违规。"""
    base = {
        "analysis": {
            "conclusion": "本命局结构层证据如下。",
            "evidence": {
                "untraced_rules": [],
                "strength": 0.5,
                "chain": [{"rule_id": "STRUCT_ROOT_001"}],
            },
            "draft": {"cited_rules": ["STRUCT_ROOT_001"]},
        },
        "critique": {"passed": True, "issues": []},
    }
    for path, value in overrides.items():
        node = base
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return base


# ── 每条不变量都要能抓到违规 ───────────────────────────────────────────


def test_chain_traced_catches_a_broken_link():
    assert _check_chain_traced(payload()) == ""
    assert "断环" in _check_chain_traced(
        payload(**{"analysis.evidence.untraced_rules": ["STRUCT_ROOT_001"]})
    )


def test_critique_catches_a_failed_review():
    assert _check_critique_passed(payload()) == ""
    assert "审查未通过" in _check_critique_passed(
        payload(**{"critique.passed": False, "critique.issues": ["越界引用"]})
    )


def test_citations_within_chain_catches_an_outside_reference():
    """结论引用了证据链里没有的规则 —— 这是最该被抓的一种。"""
    assert _check_citations_within_chain(payload()) == ""
    assert "证据链之外" in _check_citations_within_chain(
        payload(**{"analysis.draft.cited_rules": ["STRUCT_ROOT_001", "编造的规则"]})
    )


def test_certainty_language_catches_a_prediction():
    assert _check_no_certainty_language(payload()) == ""
    assert "必然性措辞" in _check_no_certainty_language(
        payload(**{"analysis.conclusion": "2028年你一定会发财。"})
    )


def test_strength_range_catches_an_out_of_range_value():
    assert _check_strength_in_range(payload()) == ""
    assert "不在 [0, 1)" in _check_strength_in_range(
        payload(**{"analysis.evidence.strength": 1.0})
    )
    assert "不在 [0, 1)" in _check_strength_in_range(
        payload(**{"analysis.evidence.strength": -0.1})
    )


def test_every_invariant_has_a_name_and_a_promise():
    """每条不变量都要说清它守的是哪个承诺 —— 没写清就没法判断该不该存在。"""
    for item in ALL_INVARIANTS:
        assert item.name
        assert item.promise
    assert len(ALL_INVARIANTS) == len(INVARIANTS) + 1
    assert REPRODUCIBILITY not in INVARIANTS, "复现性要单独跑，不能混进单次检查"


# ── 真跑一遍 ───────────────────────────────────────────────────────────


def test_evaluate_covers_every_golden_case_and_passes():
    from engines.bazi.golden_cases import GOLDEN_CASES

    summary = evaluate()

    assert summary.total == len(GOLDEN_CASES) * 3, "每个案例应问三个主题"
    assert summary.failed == 0, render(summary)
    assert summary.accuracy == 1.0


def test_render_lists_failures_when_there_are_any():
    """报告必须把未过项逐条列出来，不能只给一个通过率。"""
    from evaluation.core import EvaluationResult, summarize

    summary = summarize([
        EvaluationResult("a", True, "全部不变量成立", "全部成立"),
        EvaluationResult("b", False, "全部不变量成立", "critique_passed（审查未通过）"),
    ])
    text = render(summary)

    assert "1/2 passed" in text
    assert "未过项逐条" in text
    assert "critique_passed" in text


def test_cli_exits_zero_on_a_clean_run():
    """命令行入口要真的能跑通 —— 那是验收标准里的那条命令。"""
    completed = subprocess.run(
        [sys.executable, str(REPO / "evaluation" / "runner.py")],
        cwd="/tmp", capture_output=True, text=True, timeout=600,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "passed" in completed.stdout


def test_cli_json_output_is_machine_readable():
    completed = subprocess.run(
        [sys.executable, str(REPO / "evaluation" / "runner.py"), "--json"],
        cwd="/tmp", capture_output=True, text=True, timeout=600,
    )

    assert completed.returncode == 0, completed.stderr
    import json

    payload_data = json.loads(completed.stdout)
    assert payload_data["failed"] == 0
    assert payload_data["accuracy"] == 1.0
    assert payload_data["failures"] == []
