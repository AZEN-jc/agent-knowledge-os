"""Provider 契约评估的测试：评人的工具，自己先要被验。

## 为什么评估器本身需要测试

一个永远返回「通过」的评估器比没有评估器更糟 —— 它给人「守住了」的
错觉。所以这里除了跑场景，还要做两件反自证的事：

1. **有牙**：把某个守卫临时撤掉，对应的场景必须变红。十一条场景各自
   守住一类失控，任何一类抓不住，都说明红线只是写在文档里。
2. **真 provider 入口两边都测**：合规的替身全部通过；失控的替身必须
   被报出来。只测前者的话，「评估器从来不报失败」这种故障发现不了。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from evaluation.provider_conformance import (
    SCENARIOS,
    evaluate_conformance,
    evaluate_live_provider,
    run_scenario,
)

REPO = Path(__file__).resolve().parent.parent


# ── 对抗场景：全部守住 ──────────────────────────────────────────────


def test_every_scenario_holds():
    summary = evaluate_conformance()

    assert summary.failed == 0, "\n".join(
        f"{r.case_id}: {r.actual}" for r in summary.results if not r.passed
    )


def test_the_scenario_set_covers_every_guard():
    """场景必须覆盖每一类失控，缺一类就是一条没人守的红线。"""
    ids = {scenario.id for scenario in SCENARIOS}

    required = {
        "conforming_output",           # 合规的不被误伤
        "out_of_chain_citation",       # 越界引用
        "certainty_language",          # 必然性措辞
        "empty_conclusion",            # 空结论
        "extra_field",                 # 契约外字段
        "non_json_output",             # 非 JSON
        "wrong_type_rule_ids",         # 类型错误
        "fabricated_urn",              # 编造出处
        "missing_classical_footnote",  # 缺典籍角标
        "provider_unreachable",        # provider 故障
        "budget_exhausted",            # 预算耗尽
    }
    assert required <= ids, f"缺少场景：{sorted(required - ids)}"


# ── 有牙：撤掉守卫，场景必须红 ──────────────────────────────────────


def test_the_suite_has_teeth_when_the_critic_is_neutered(monkeypatch):
    """把 Critic 改成永远放行，「必然性措辞」等场景必须失守。

    这条守的是评估器自己：如果它测不出守卫失效，那 11/11 就只是装饰。
    """
    import agents.mingli as mingli_module

    monkeypatch.setattr(
        mingli_module.CriticAgent, "critique", lambda self, analysis: _always_pass(analysis)
    )

    summary = evaluate_conformance()

    assert summary.failed > 0, "Critic 被 neutered 之后全部场景仍然守住 —— 评估器没有牙"
    failed_ids = {r.case_id for r in summary.results if not r.passed}
    assert "certainty_language" in failed_ids
    assert "fabricated_urn" in failed_ids


def test_the_suite_has_teeth_when_the_allowlist_is_removed(monkeypatch):
    """白名单改成「什么都允许」时，越界引用场景必须失守。"""
    import agents.prompt as prompt_module

    monkeypatch.setattr(prompt_module, "_parse_rule_ids", _allow_everything)

    summary = evaluate_conformance()

    failed_ids = {r.case_id for r in summary.results if not r.passed}
    assert "out_of_chain_citation" in failed_ids, (
        f"白名单失效却没被任何场景抓到：失守的是 {failed_ids}"
    )


def _always_pass(analysis):
    from agents.mingli import Critique

    return Critique(True, ())


def _allow_everything(data, allowed_rule_ids, violations):
    """冒充 _parse_rule_ids：不做白名单过滤，原样返回。"""
    raw = data.get("rule_ids") if isinstance(data, dict) else []
    return tuple(item for item in raw if isinstance(item, str))


# ── 真 provider 入口 ────────────────────────────────────────────────


def test_a_conforming_provider_passes_the_live_evaluation():
    """守规矩的模型在任何命盘上都该合格。

    用的是 ``_ConformingProvider``（读证据链再组装输出）而不是一段写死的
    文本 —— 写死的文本只对造它的那个命盘合规，换到带规则冲突的命盘
    （夏令时案例）上就会被 Critic 抓住。第一版就是这么失败的。
    """
    from evaluation.provider_conformance import _ConformingProvider

    summary = evaluate_live_provider(_ConformingProvider(), cases=4)

    assert summary.failed == 0, "\n".join(
        f"{r.case_id}: {r.actual}" for r in summary.results if not r.passed
    )


def test_a_misbehaving_provider_is_reported_not_swallowed():
    """失控的 provider：评估必须报出来，而不是安静地全绿。

    替身**只犯一种错**（加一句必然性措辞），其余都按合规来。这样报出来的
    失败原因才能确定是「必然性」—— 如果它同时漏披露冲突，就分不清是哪个
    守卫在响了。
    """
    from evaluation.provider_conformance import _ConformingProvider

    class _CertaintyLoving(_ConformingProvider):
        name = "certainty-loving"
        model = "scripted-bad"

        def complete(self, request):
            raw = super().complete(request)
            data = json.loads(raw)
            data["text"] = "一定会发财。" + data["text"]
            return json.dumps(data, ensure_ascii=False)

    summary = evaluate_live_provider(_CertaintyLoving(), cases=3)

    assert summary.failed > 0, "必然性措辞没有被 live 评估报出来"
    assert any("必然性" in r.actual for r in summary.results if not r.passed)


def test_a_dead_provider_is_reported_as_a_failure_not_a_crash():
    """provider 整个挂掉时，live 评估给出的是「降级」判定而不是异常。"""
    from agents.llm import ProviderError

    class _Dead:
        name = "dead"
        model = "none"

        def complete(self, request):
            raise ProviderError("连不上")

    summary = evaluate_live_provider(_Dead(), cases=2)

    # 走了模板路径但 degraded_reason 非空 —— 那是合理的降级，不是失守。
    assert summary.failed == 0, "\n".join(
        f"{r.case_id}: {r.actual}" for r in summary.results if not r.passed
    )


# ── 命令行入口 ──────────────────────────────────────────────────────


def test_the_cli_exits_zero_on_a_clean_run():
    completed = subprocess.run(
        [sys.executable, str(REPO / "evaluation" / "provider_conformance.py")],
        cwd="/tmp", capture_output=True, text=True, timeout=600,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "11/11" in completed.stdout


def test_the_cli_json_output_is_machine_readable():
    completed = subprocess.run(
        [sys.executable, str(REPO / "evaluation" / "provider_conformance.py"), "--json"],
        cwd="/tmp", capture_output=True, text=True, timeout=600,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["total"] == len(SCENARIOS)
    assert payload["failed"] == 0
    assert payload["accuracy"] == 1.0


# ── 单个场景可单独跑（便于定位）────────────────────────────────────


def test_a_single_scenario_can_be_run_in_isolation():
    """``run_scenario`` 暴露出来，是为了失败时能单独复现那一条。"""
    scenario = next(s for s in SCENARIOS if s.id == "out_of_chain_citation")

    result = run_scenario(scenario)

    assert result.passed is True, result.actual
