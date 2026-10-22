"""Provider 故障恢复与降级：坏掉的不许伪装成好的。

## 这一层守什么

任务书的硬性要求：**不得把 Provider 网络调用失败伪装成分析成功**。

Phase 4.5 的处置分两步：服务层捕获 ``ProviderError`` 后降级到确定性模板
出稿，并把原因写进 ``draft.degraded_reason``。降级不是隐瞒 —— 用户看得见
这次没走模型，也看得见为什么。

反过来同样要守：**不该降级的时候不许降级**。代码 bug（传了 None、拼错了
字段）必须响亮地炸；把 bug 降级成一次「故障」，比崩溃难查得多。
所以这里只捕 ``ProviderError``，别的异常一律放过。

## 为什么降级而不是抛给调用方

排盘、规则、证据链全是确定性的，它们没坏。坏掉的只是「把证据复述成自然
语言」这一步，而模板本来就能做。让用户什么都拿不到，比让他拿到一份标明
「本次未走模型」的分析更糟。
"""

from __future__ import annotations

import pytest

import api.server as server_module
from agents.llm import FakeLLMProvider, HttpLLMProvider, ProviderError
from agents.mingli import DRAFT_TEMPLATE, AnalystAgent, CriticAgent
from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from runtime.mingli_service import MingLiService

REGISTRY = default_registry()
CHART = SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))
BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12}


def _broken_provider(message: str = "端点不可达", name: str = "broken", model: str = "none"):
    """一个必然抛 ProviderError 的 provider。"""

    class _Broken:
        def complete(self, request):  # 测试替身，签名随意
            raise ProviderError(message)

    provider = _Broken()
    provider.name = name
    provider.model = model
    return provider


def _boom_provider(exc: BaseException):
    """抛任意指定异常的 provider —— 用来验「不是 ProviderError 不许捕」。"""

    class _Boom:
        name = "boom"
        model = "none"

        def complete(self, request):  # 测试替身，签名随意
            raise exc

    return _Boom()


# ── 降级本身 ────────────────────────────────────────────────────────


def test_a_dead_provider_degrades_to_the_template_and_says_so():
    """provider 整个不可用 → 模板出稿 + 中文原因。"""
    agent = AnalystAgent(REGISTRY, provider=_broken_provider("连接被拒绝"))

    analysis = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert analysis.draft_source == DRAFT_TEMPLATE
    assert analysis.degraded_reason, "降级了却不记录原因 —— 那就是伪装"
    assert "连接被拒绝" in analysis.degraded_reason
    # 结论与纯模板路径逐字一致：降级不改变确定性部分。
    plain = AnalystAgent(REGISTRY).analyze(CHART, "事业")
    assert analysis.conclusion == plain.conclusion
    assert analysis.cited_rule_ids == plain.cited_rule_ids
    assert analysis.contract_fingerprint == plain.contract_fingerprint


def test_the_degraded_analysis_still_passes_the_critic():
    """降级稿必须过审 —— 模板本来就该合规，故障不能让它变不合规。"""
    agent = AnalystAgent(REGISTRY, provider=_broken_provider())

    analysis = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert CriticAgent().critique(analysis).passed is True


def test_the_reason_names_the_provider_and_the_stage():
    """原因要能定位到「哪个 provider、哪一轮」—— 只写「出错了」没法排查。"""
    agent = AnalystAgent(REGISTRY, provider=_broken_provider("超时 30s", "http", "gpt-x"))

    analysis = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert "http" in analysis.degraded_reason
    assert "gpt-x" in analysis.degraded_reason
    assert "首次出稿" in analysis.degraded_reason
    assert "超时 30s" in analysis.degraded_reason


def test_a_failure_mid_revision_is_reported_as_a_revision_failure():
    """第一稿成功、重写时挂掉 → 原因要写明是第几轮重写。"""
    from agents.prompt import render_draft

    # 让第二轮开始抛错：FakeLLMProvider 脚本用尽抛的是 RuntimeError
    # （测试夹具自己的错误），不是 ProviderError，所以这里用手动控制的
    # 假 provider，精确指定「第几轮之后开始失败」。
    class _FailsOnRevision:
        name = "flaky"
        model = "m"
        calls = 0

        def complete(self, request):  # 测试替身，签名随意
            type(self).calls += 1
            if type(self).calls == 1:
                return render_draft([], "一定会发财，证据强度 0.62")
            raise ProviderError("第二轮开始断网")

    analysis = AnalystAgent(
        REGISTRY, provider=_FailsOnRevision(), max_revisions=2
    ).analyze(CHART, "事业", critic=CriticAgent())

    assert analysis.draft_source == DRAFT_TEMPLATE
    assert "第 1 轮重写" in analysis.degraded_reason
    assert "第二轮开始断网" in analysis.degraded_reason


def test_a_healthy_provider_records_no_degradation():
    """没故障时 degraded_reason 必须是空串 —— 不能有任何默认噪音。"""
    from agents.prompt import render_draft

    evidence_note = AnalystAgent(REGISTRY).analyze(CHART, "事业").evidence.coverage_note
    provider = FakeLLMProvider(
        responses=[render_draft([], f"证据强度 0.62，复述。{evidence_note}")]
    )

    analysis = AnalystAgent(REGISTRY, provider=provider).analyze(
        CHART, "事业", critic=CriticAgent()
    )

    assert analysis.draft_source == "llm"
    assert analysis.degraded_reason == ""


# ── 不该降级的不许降级 ──────────────────────────────────────────────


@pytest.mark.parametrize("exc", [
    TypeError("provider 返回了 None"),
    ValueError("注册表没初始化"),
    KeyError("topic_id"),
    RuntimeError("假 provider 脚本用尽"),  # 测试夹具自己的错误，必须响亮
])
def test_a_bug_is_not_swallowed_as_a_provider_failure(exc):
    """非 ProviderError 一律上抛。

    把代码 bug 降级成「provider 故障」是最坏的失败模式：用户看到一次正常
    的降级，而真正的 bug 再也没有人发现。
    """
    agent = AnalystAgent(REGISTRY, provider=_boom_provider(exc))

    with pytest.raises(type(exc)):
        agent.analyze(CHART, "事业", critic=CriticAgent())


def test_a_template_only_service_has_no_degradation():
    """没有 provider 的服务：本来就走模板，degraded_reason 为空。"""
    analysis = AnalystAgent(REGISTRY).analyze(CHART, "事业")

    assert analysis.draft_source == DRAFT_TEMPLATE
    assert analysis.degraded_reason == "", "没故障却被标成降级了"


# ── 服务层与 API ────────────────────────────────────────────────────


def test_the_service_reports_the_degradation_in_the_draft():
    service = MingLiService()
    service.analyst.provider = _broken_provider("连接被拒绝")

    payload = service.analyze(BIRTH, "事业").to_dict()

    draft = payload["analysis"]["draft"]
    assert draft["source"] == DRAFT_TEMPLATE
    assert "连接被拒绝" in draft["degraded_reason"]
    assert payload["critique"]["passed"] is True


def test_one_dead_topic_does_not_take_down_the_others():
    """多主题并发下一个主题的 provider 故障不波及其余（故障隔离）。"""
    from agents.prompt import render_draft

    note = AnalystAgent(REGISTRY).analyze(CHART, "事业").evidence.coverage_note

    # 按**主题**决定成败，不按调用计数。analyze_multi 用线程池扇出，
    # 一个 `seen += 1` 的计数器在并发下是竞态的：四个线程谁先谁后不确定，
    # 「奇数号失败」会退化成随机两个失败，测试时红时绿。
    # 证据链里带主题名，按它分流是确定性的。
    failing = {"事业", "婚姻"}

    class _Alternating:
        name = "alternating"
        model = "m"

        def complete(self, request):  # 测试替身，签名随意
            if any(f'"{topic}"' in request.user for topic in failing):
                raise ProviderError("指定主题网络不通")
            return render_draft([], f"证据强度 0.62，复述。{note}")

    service = MingLiService()
    service.analyst.provider = _Alternating()
    multi = service.analyze_multi(BIRTH, ["事业", "财运", "婚姻", "健康"])

    # succeeded/failed 是 TopicResult 元组，不是计数。
    assert len(multi.succeeded) == 4, "每个主题都应有结果，哪怕降级"
    assert multi.failed == (), "降级不是失败，任何一个主题都不该进 failed"

    def draft_of(result):
        # TopicResult.analysis 是 AnalysisResponse，不是 dict。
        return result.analysis.analysis["draft"]

    degraded = [r for r in multi.results if draft_of(r)["degraded_reason"]]
    healthy = [r for r in multi.results if not draft_of(r)["degraded_reason"]]

    assert {r.topic for r in degraded} == failing
    assert len(healthy) == 2
    for result in degraded:
        assert result.ok is True, "降级不是失败，仍然是一次成功的分析"
        assert "指定主题网络不通" in draft_of(result)["degraded_reason"]
    for result in healthy:
        assert draft_of(result)["source"] == "llm"


def test_the_api_surfaces_the_degradation_end_to_end():
    """经 HTTP 端到端：端点不存在 → 200 + 降级标注，不是 500 也不是伪装。"""
    from fastapi.testclient import TestClient

    # 一个没人监听的端口：连接会被立刻拒绝。
    # **必须 patch 模块级 service**：端点函数直接引用模块全局，
    # 往 app.state 上挂是没用的（第一版就挂错了，响应一切正常 ——
    # 因为请求打到的还是原来那个健康 service）。
    dead = HttpLLMProvider(endpoint="http://127.0.0.1:9/v1", model="e2e", timeout=2.0)
    original = server_module.service.analyst.provider
    server_module.service.analyst.provider = dead
    try:
        client = TestClient(server_module.app, raise_server_exceptions=False)
        response = client.post("/api/analyze", json={**BIRTH, "question": "事业"})
    finally:
        server_module.service.analyst.provider = original

    assert response.status_code == 200, response.text[:200]
    body = response.json()
    draft = body["analysis"]["draft"]
    assert draft["source"] == DRAFT_TEMPLATE
    assert draft["degraded_reason"], "API 响应里看不到降级原因"
    assert "无法连接" in draft["degraded_reason"]
    assert body["critique"]["passed"] is True
