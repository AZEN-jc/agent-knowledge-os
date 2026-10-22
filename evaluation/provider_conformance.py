"""Provider 契约评估：换任何一个模型，这套红线都要守得住。

## 这个模块评什么

``runner.py`` 评的是**确定性系统**在大量命盘上的行为不变量。这里评的是另
一件事：**接上真实模型之后，那些约束还在不在**。

Phase 3 报告 §10 给过一条反建议：不要一开始就接多个真模型 —— 在一个
provider、一条契约、一个白名单都没稳定之前引入多模型，只会让回归面积翻倍。
所以本模块不联网、不需要 API key，它提供的是**评估框架**：

- :data:`SCENARIOS` —— 一组**对抗性场景**。每个场景用一个脚本化的假
  provider 演出一种典型的模型失控（越界引用、编造出处、必然性措辞、
  不披露强度、返回非 JSON、整个挂掉……），然后断言**系统确实拦住了**。
  这些场景全部通过，才说明红线不是写在文档里而是长在代码里。
- :func:`evaluate_live_provider` —— 给**真 provider** 用的入口。传入任何
  实现 ``LLMProvider`` 的实例，跑一批中性分析，逐条检查同一套不变量加
  治理字段，产出该模型的契约合格性报告。换模型 = 换一个实例重跑。

## 为什么对抗场景要脚本化而不能用真模型

真模型不会应要求犯错。要验证「越界引用会被剔除」，就得真的给它一个
越界引用的机会 —— 那只能用假 provider 精确控制输出。真模型的价值在
:func:`evaluate_live_provider` 里评：它**实际**会怎么做。

## 用法::

    python evaluation/provider_conformance.py          # 对抗场景全跑
    python evaluation/provider_conformance.py --json   # 机器可读

退出码非 0 表示有场景没守住，可直接当回归门禁。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agents.llm import FakeLLMProvider, LLMProvider, LLMRequest, ProviderError
from agents.prompt import render_draft
from engines.bazi.golden_cases import GOLDEN_CASES
from evaluation.core import EvaluationResult, EvaluationSummary, summarize
from runtime.mingli_service import MingLiService

#: 甲子日甲子时 —— 命中典籍层规则，用于「缺出处角标」场景。
CLASSICAL_BIRTH = {"year": 1990, "month": 2, "day": 28, "hour": 0}

#: 普通命盘，用于其余场景。
PLAIN_BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12}


def _conforming_text(topic: str = "事业") -> str:
    """一段**真的能过审**的正文：带强度披露，主题覆盖不足时带 coverage_note。"""
    evidence = MingLiService().analyze(PLAIN_BIRTH, topic).to_dict()["analysis"]["evidence"]
    text = f"证据强度 {evidence['strength']:.2f}，以上为命盘结构证据的复述。"
    if evidence["status"] != "covered":
        text += evidence["coverage_note"]
    return text


def _scripted(*texts: str) -> list[str]:
    return [render_draft([], text) for text in texts]


def _keeps_doing(raw: str) -> list[str]:
    """同一段失控输出重复到超过重写上限。

    **为什么要重复。** 服务层默认带 Critic 与 ``MAX_REVISIONS``：第一稿
    不过审就会要第二稿。只给一条脚本的话，第二轮直接
    RuntimeError（假 provider 脚本用尽），场景于是变成「抛出异常」而不是
    「系统拦住了失控」—— 第一版 8 个场景就是这么全军覆没的。

    真实的坏模型正是一直犯同一个错，所以脚本也要一直犯。
    """
    from agents.mingli import MAX_REVISIONS

    return [raw] * (MAX_REVISIONS + 2)


@dataclass(frozen=True)
class Scenario:
    """一个对抗性场景。

    ``behaviour`` 构造该场景下的 provider（决定模型「会做什么」），
    ``expect`` 对最终响应求值，返回空串表示**系统守住了**。
    """

    id: str
    promise: str
    birth: dict[str, Any]
    topic: str
    behaviour: Callable[[], LLMProvider]
    expect: Callable[[dict[str, Any]], str]
    budget: int | None = None


def _payload_of(service: MingLiService, birth: dict[str, Any], topic: str) -> dict[str, Any]:
    return service.analyze(birth, topic).to_dict()


def _violations(payload: dict[str, Any]) -> list[str]:
    return list(payload["analysis"]["draft"]["contract_violations"])


def _issues(payload: dict[str, Any]) -> list[str]:
    return list(payload["critique"]["issues"])


# ── 期望函数：每个返回空串表示守住 ──────────────────────────────────


def _expect_conforming(payload: dict[str, Any]) -> str:
    draft = payload["analysis"]["draft"]
    if draft["source"] != "llm":
        return f"合规输出却走了 {draft['source']} 路径"
    if _violations(payload):
        return f"合规输出仍被记违约：{_violations(payload)}"
    if not payload["critique"]["passed"]:
        return f"合规输出却没通过审查：{_issues(payload)}"
    return ""


def _expect_stripped_and_flagged(payload: dict[str, Any]) -> str:
    """越界引用：剔除 + 记违约 + 审查报出，三件事一件都不能少。"""
    cited = set(payload["analysis"]["draft"]["cited_rules"])
    chain = {link["rule_id"] for link in payload["analysis"]["evidence"]["chain"]}
    if "STRUCT_PATTERN_999" in cited:
        return "越界引用没有被剔除"
    if not any("证据链之外" in v for v in _violations(payload)):
        return f"越界引用没有被记违约：{_violations(payload)}"
    if payload["critique"]["passed"]:
        return "越界引用没有让审查失败"
    assert not cited - chain, "cited_rules 必须是证据链子集"
    return ""


def _expect_certainty_flagged(payload: dict[str, Any]) -> str:
    if payload["analysis"]["draft"]["certainty_risk"] is not True:
        return "必然性措辞没有置 certainty_risk"
    if payload["critique"]["passed"]:
        return f"必然性措辞没有被抓到：{_issues(payload)}"
    return ""


def _expect_empty_flagged(payload: dict[str, Any]) -> str:
    if payload["critique"]["passed"]:
        return f"空结论没有被拦：{_issues(payload)}"
    return ""


def _expect_extra_field_flagged(payload: dict[str, Any]) -> str:
    if not any("契约之外" in v for v in _violations(payload)):
        return f"多余字段没有被记违约：{_violations(payload)}"
    return ""


def _expect_non_json_flagged(payload: dict[str, Any]) -> str:
    if not any("不是合法 JSON" in v for v in _violations(payload)):
        return f"非 JSON 输出没有被记违约：{_violations(payload)}"
    if payload["critique"]["passed"]:
        return "非 JSON 输出没有让审查失败"
    return ""


def _expect_wrong_type_flagged(payload: dict[str, Any]) -> str:
    if not any("字符串数组" in v for v in _violations(payload)):
        return f"类型错误没有被记违约：{_violations(payload)}"
    return ""


def _expect_fabricated_urn_flagged(payload: dict[str, Any]) -> str:
    if payload["critique"]["passed"]:
        return f"编造出处没有被抓到：{_issues(payload)}"
    if not any("编造" in issue for issue in _issues(payload)):
        return f"编造出处没有被标成「编造」：{_issues(payload)}"
    return ""


def _expect_missing_footnote_flagged(payload: dict[str, Any]) -> str:
    if payload["critique"]["passed"]:
        return f"缺出处角标没有被抓到：{_issues(payload)}"
    if not any("出处角标" in issue for issue in _issues(payload)):
        return f"缺角标的原因不是「出处角标」：{_issues(payload)}"
    return ""


def _expect_degraded(payload: dict[str, Any]) -> str:
    """provider 挂掉：降级 + 明示 + 结论仍然合规。"""
    draft = payload["analysis"]["draft"]
    if draft["source"] != "template":
        return f"provider 故障却没有降级，实得 source={draft['source']}"
    if not draft["degraded_reason"]:
        return "降级了却不记录原因 —— 那就是伪装成分析成功"
    if not payload["critique"]["passed"]:
        return f"降级稿没有通过审查：{_issues(payload)}"
    return ""


def _expect_budget_degraded(payload: dict[str, Any]) -> str:
    draft = payload["analysis"]["draft"]
    if draft["source"] != "template":
        return f"超预算却没有降级，实得 source={draft['source']}"
    if "token 预算耗尽" not in draft["degraded_reason"]:
        return f"降级原因不是预算耗尽：{draft['degraded_reason']}"
    return ""


def _classical_provider() -> LLMProvider:
    """演出「引了典籍规则却不挂角标」：需要在命局主题下引用典籍规则 ID。"""
    from agents.mingli import AnalystAgent
    from knowledge.default_rules import default_registry

    evidence = AnalystAgent(default_registry()).analyze(
        __import__("engines.bazi", fromlist=["SxtwlBaziProvider"]).SxtwlBaziProvider().calculate(
            __import__("engines.bazi", fromlist=["BirthInput"]).BirthInput(1990, 2, 28, 0)
        ),
        "命局",
    ).evidence
    classical = [m for m in evidence.matches if m.rule.urn]
    assert classical, "该命盘应命中典籍规则，否则本场景是空测"
    return FakeLLMProvider(
        responses=_keeps_doing(render_draft(
            [classical[0].rule.id],
            "古法有云，甲子日甲子时主贵。证据强度 0.62",
        ))
    )


class _ConformingProvider:
    """一个「守规矩的模型」：读证据链，据此产出合规草稿。

    **为什么不能背一段写死的合规文本。** 合规的要求**随命盘变化**：
    有规则冲突的命盘必须披露冲突，``base_only`` 主题必须带
    ``coverage_note``，低强度必须披露强度。一段写死的文本只对造它的那个
    命盘合规 —— 第一版就是写死的，于是在带冲突的命盘（如夏令时案例）
    上被 Critic 抓住，测试才发现。

    所以这里真的去读请求里的证据链，按它的内容组装输出。这也是
    :func:`evaluate_live_provider` 需要的替身：换任何命盘都合规。
    """

    name = "conforming"
    model = "scripted-conforming"
    requests: ClassVar[list[LLMRequest]] = []

    def complete(self, request: LLMRequest) -> str:
        type(self).requests.append(request)
        # 证据链在 user 段开头；重写提示词后面还跟着「上一次的输出」。
        head = request.user.split("\n── 你上一次的输出 ──")[0]
        evidence = json.loads(head)

        chain = [link["rule_id"] for link in evidence["chain"]]
        text = f"证据强度 {evidence['strength']:.2f}，以上为命盘结构证据的复述。"
        if evidence["status"] != "covered":
            text += evidence["coverage_note"]
        if evidence["conflicts"]:
            text += f"另有 {len(evidence['conflicts'])} 处规则分歧，需并列披露。"
        return render_draft(chain[:2], text)


def _broken_provider() -> LLMProvider:
    class _Broken:
        name = "conformance-broken"
        model = "none"

        def complete(self, request):
            raise ProviderError("端点不可达")

    return _Broken()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="conforming_output",
        promise="合规输出原样通过，不误伤",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=_ConformingProvider,
        expect=_expect_conforming,
    ),
    Scenario(
        id="out_of_chain_citation",
        promise="越界引用被剔除、记违约、报审查",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(
            responses=_keeps_doing(render_draft(["STRUCT_PATTERN_999"], _conforming_text()))
        ),
        expect=_expect_stripped_and_flagged,
    ),
    Scenario(
        id="certainty_language",
        promise="必然性措辞被抓到并置风险标志",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(
            responses=_keeps_doing(render_draft([], f"一定会发财。{_conforming_text()}"))
        ),
        expect=_expect_certainty_flagged,
    ),
    Scenario(
        id="empty_conclusion",
        promise="空结论被拦下",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(responses=_keeps_doing(render_draft([], ""))),
        expect=_expect_empty_flagged,
    ),
    Scenario(
        id="extra_field",
        promise="契约之外的字段被记违约",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(
            responses=_keeps_doing(json.dumps(
                {"rule_ids": [], "text": _conforming_text(), "note": "x"}, ensure_ascii=False
            ))
        ),
        expect=_expect_extra_field_flagged,
    ),
    Scenario(
        id="non_json_output",
        promise="非 JSON 输出被记违约，不崩",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(responses=_keeps_doing("我觉得事业方面还不错。")),
        expect=_expect_non_json_flagged,
    ),
    Scenario(
        id="wrong_type_rule_ids",
        promise="字段类型错误被记违约",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(
            responses=_keeps_doing(json.dumps(
                {"rule_ids": "STRUCT_001", "text": _conforming_text()}, ensure_ascii=False
            ))
        ),
        expect=_expect_wrong_type_flagged,
    ),
    Scenario(
        id="fabricated_urn",
        promise="正文里编造的出处被标成编造",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(
            responses=_keeps_doing(render_draft(
                [], "古法记为吉格〔urn:divination:bazi:fake:ws1:j1.x〕" + _conforming_text()
            ))
        ),
        expect=_expect_fabricated_urn_flagged,
    ),
    Scenario(
        id="missing_classical_footnote",
        promise="引典籍规则不挂角标被拦",
        birth=CLASSICAL_BIRTH,
        topic="命局",
        behaviour=_classical_provider,
        expect=_expect_missing_footnote_flagged,
    ),
    Scenario(
        id="provider_unreachable",
        promise="provider 故障降级到模板并如实标注",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=_broken_provider,
        expect=_expect_degraded,
    ),
    Scenario(
        id="budget_exhausted",
        promise="token 预算耗尽时降级并说明是花超了",
        birth=PLAIN_BIRTH,
        topic="事业",
        behaviour=lambda: FakeLLMProvider(responses=_scripted(_conforming_text())),
        expect=_expect_budget_degraded,
        budget=100,
    ),
)


def run_scenario(scenario: Scenario) -> EvaluationResult:
    """跑一个场景，返回它是否守住了承诺。"""
    service = MingLiService(provider=scenario.behaviour(), token_budget=scenario.budget or 30000)
    try:
        payload = _payload_of(service, scenario.birth, scenario.topic)
    except Exception as exc:  # 异常也是结果：系统不该在这里炸
        return EvaluationResult(scenario.id, False, scenario.promise, "抛出异常", str(exc))

    reason = scenario.expect(payload)
    return EvaluationResult(
        case_id=scenario.id,
        passed=not reason,
        expected=scenario.promise,
        actual="守住" if not reason else reason,
    )


def evaluate_conformance() -> EvaluationSummary:
    """跑全部对抗场景。全部通过才说明红线长在代码里。"""
    return summarize([run_scenario(scenario) for scenario in SCENARIOS])


# ── 真 provider 入口 ────────────────────────────────────────────────


def evaluate_live_provider(
    provider: LLMProvider,
    *,
    cases: int = 6,
) -> EvaluationSummary:
    """把**任意** provider 接进来跑中性分析，评它的契约合格性。

    与对抗场景的分工：那里用假 provider 精确演出失控，验证**系统**的守卫；
    这里用真 provider（或任何替身）看它**实际**会怎么做，逐条检查同一套
    不变量，外加三条治理字段：

    - 没有未披露的降级（``degraded_reason`` 空，除非真的故障了 ——
      而故障时必须非空，两头都查）
    - 记账字段自洽（``provider_calls`` 与 ``served_from_cache`` 不同时为
      「调用了但没计数」）
    - 越界引用不出现在结论里

    换模型 = 换一个实例重跑，不需要改这个函数。
    """
    service = MingLiService(provider=provider)
    results: list[EvaluationResult] = []

    for case in GOLDEN_CASES[:cases]:
        birth = {
            "year": case.birth.year, "month": case.birth.month,
            "day": case.birth.day, "hour": case.birth.hour,
        }
        gender = getattr(case.birth, "gender", None)
        if gender:
            birth["gender"] = gender
        label = f"{case.case_id}·事业"
        try:
            payload = service.analyze(birth, "事业").to_dict()
        except Exception as exc:
            results.append(EvaluationResult(label, False, "契约合格", None, str(exc)))
            continue

        problems: list[str] = []
        draft = payload["analysis"]["draft"]
        if draft["source"] == "llm":
            if _violations(payload):
                problems.append(f"违约未清：{_violations(payload)}")
            if not payload["critique"]["passed"]:
                problems.append(f"审查未过：{_issues(payload)}")
            banned = ("一定会", "必将", "必定", "肯定会", "必然会", "绝对会")
            hit = [w for w in banned if w in payload["analysis"]["conclusion"]]
            if hit:
                problems.append(f"必然性措辞：{hit}")
        else:
            # 走了模板路径：只有「真的降级」才合理，且必须写明原因。
            if not draft["degraded_reason"]:
                problems.append("未注入 provider 却走了模板路径")
        if draft["provider_calls"] and draft["served_from_cache"] and draft["provider_calls"] == 0:
            problems.append("记账自相矛盾：缓存命中却记了调用")

        results.append(EvaluationResult(
            case_id=label,
            passed=not problems,
            expected="契约合格",
            actual="合格" if not problems else "；".join(problems),
        ))

    return summarize(results)


def render(summary: EvaluationSummary, title: str) -> str:
    width = max((len(r.case_id) for r in summary.results), default=10)
    lines = [
        f"{title} · {summary.total} 场景",
        "-" * (width + 34),
    ]
    for result in summary.results:
        mark = "守住" if result.passed else "失守"
        lines.append(f"{result.case_id:<{width}}  {mark}  {'' if result.passed else result.actual}")
    lines.append("-" * (width + 34))
    lines.append(f"{summary.passed}/{summary.total} passed （accuracy {summary.accuracy:.4f}）")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args()

    summary = evaluate_conformance()
    if args.json:
        print(json.dumps({
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "accuracy": summary.accuracy,
            "failures": [
                {"scenario": r.case_id, "detail": r.actual}
                for r in summary.results if not r.passed
            ],
        }, ensure_ascii=False, indent=2))
    else:
        print(render(summary, "Provider 契约评估"))

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
