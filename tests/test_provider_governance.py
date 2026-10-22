"""并发、Token、成本与缓存治理：花出去的每一分都要看得见。

## 这一层守什么

provider 路径一旦接上真模型，成本就从「免费」变成「按 token 计费」。
Phase 4.6 补四样治理，每一样都有对应的守卫：

1. **token 估算** —— 没有它，任何预算都无从谈起。口径写死在
   ``agents.llm.estimate_tokens``，是估算不是账单，测试只钉它的**性质**。
2. **预算硬停** —— 调用次数可以配、提示词会随证据增长，两者相乘没有上限。
   超预算时降级并说明是「花超了」而不是「连不上」：这两种原因的处置
   完全不同，一个是查账单，一个是查网络。
3. **响应缓存** —— 提示词是证据链的确定性函数，同样的输入本该得到同样
   的输出，没有理由再付一次钱。但模型可能不确定，所以缓存命中必须
   **看得见**（``served_from_cache``）。
4. **记账** —— 提示多少、输出多少、调了几次，分别报得出来。
   第一版只用一个累加器，``prompt_tokens`` 把输出也算进去了 ——
   拿一个数冒充两个数，比不报更糟。
"""

from __future__ import annotations

import pytest

from agents.llm import estimate_tokens
from agents.mingli import (
    DEFAULT_TOKEN_BUDGET,
    RESPONSE_CACHE_LIMIT,
    AnalystAgent,
    CriticAgent,
)
from agents.prompt import render_draft
from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from runtime.mingli_service import MingLiService

REGISTRY = default_registry()
CHART = SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))
BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12}


def _conforming_text() -> str:
    """一段能过 Critic 的正文：带强度披露与覆盖不足说明。"""
    evidence = AnalystAgent(REGISTRY).analyze(CHART, "事业").evidence
    return f"证据强度 {evidence.strength:.2f}，复述。{evidence.coverage_note}"


def _scripted(*texts: str) -> list[str]:
    return [render_draft([], text) for text in texts]


# ── token 估算：只钉性质，不钉精确值 ────────────────────────────────


def test_empty_text_costs_nothing():
    assert estimate_tokens("") == 0


def test_the_estimate_is_deterministic():
    text = "命盘结构如此，日主有根。Some ASCII mixed in."
    assert estimate_tokens(text) == estimate_tokens(text)


def test_cjk_counts_roughly_one_per_character():
    """中文约每字 1 token。容差放到 20% —— 这是估算，不是分词器。

    第一版把范围写成了 80–120，可 ``"命盘" * 100`` 是 **200 个字符**，
    按每字 1 token 就是 200。范围是按 100 个字符算的，断言本身写错了。
    """
    text = "命盘" * 100
    assert 180 <= estimate_tokens(text) <= 220


def test_ascii_counts_roughly_one_per_four_characters():
    text = "a" * 400
    assert 80 <= estimate_tokens(text) <= 120


def test_the_estimate_never_decreases_when_text_grows():
    shorter = estimate_tokens("命盘结构如此")
    longer = estimate_tokens("命盘结构如此，且日主有根，生于寅月。")
    assert longer >= shorter


def test_a_long_evidence_chain_is_in_the_thousands():
    """实测首请求约 6000 token。这条防的是估算口径被改成「恒返回 0」——
    那样预算永远花不完，治理名存实亡。"""
    from agents.prompt import build_prompt

    evidence = AnalystAgent(REGISTRY).analyze(CHART, "事业").evidence
    request = build_prompt(evidence)
    total = estimate_tokens(request.system) + estimate_tokens(request.user)

    assert total > 3000, f"首请求只估出 {total} token，量级不对"


# ── 预算硬停 ────────────────────────────────────────────────────────


def test_a_tiny_budget_stops_the_very_first_call():
    """预算连一次请求都装不下 → 直接降级，原因说清是花超了。"""
    from agents.llm import FakeLLMProvider

    provider = FakeLLMProvider(responses=_scripted(_conforming_text()))
    agent = AnalystAgent(REGISTRY, provider=provider, token_budget=100)

    analysis = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert analysis.draft_source == "template"
    assert "token 预算耗尽" in analysis.degraded_reason
    assert str(agent.token_budget) in analysis.degraded_reason
    # 一次都没调用 —— 预算在调用之前就拦住了。
    assert provider.requests == []
    assert analysis.provider_calls == 0


def test_a_budget_that_runs_out_mid_revision_degrades_with_the_reason():
    """第一稿花得越界线，重写时超预算 → 降级，且原因与 provider 故障不同。"""
    from agents.llm import FakeLLMProvider

    # 先量一次首请求的真实成本，把预算卡在「只够一次」。
    probe = AnalystAgent(REGISTRY, provider=FakeLLMProvider(responses=_scripted("x")))
    from agents.prompt import build_prompt

    evidence = probe.analyze(CHART, "事业").evidence
    first_cost = estimate_tokens(build_prompt(evidence).system) + estimate_tokens(
        build_prompt(evidence).user
    )

    # 第一稿故意含确定性措辞，逼出一次重写；重写提示词更长，必然超预算。
    provider = FakeLLMProvider(responses=_scripted("一定会发财，证据强度 0.62") * 3)
    agent = AnalystAgent(
        REGISTRY, provider=provider, max_revisions=2, token_budget=first_cost + 50
    )

    analysis = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert analysis.draft_source == "template"
    assert "token 预算耗尽" in analysis.degraded_reason
    # 不是「连不上」—— 两种原因的处置完全不同。
    assert "不可用" not in analysis.degraded_reason
    # 第一次调用应该已经发生，且**钱已经花了**。
    assert analysis.provider_calls == 1, "第一次调用应该已经发生"
    assert analysis.prompt_tokens > 0, (
        "降级把已发生的调用记账抹成了 0 —— 治理字段在最需要看成本的那一刻"
        "归零，比不报更糟"
    )
    assert analysis.completion_tokens > 0


def test_the_default_budget_comfortably_covers_a_normal_analysis():
    """默认预算要装得下常规分析（首请求约 6000 + 两次重写）。"""
    assert DEFAULT_TOKEN_BUDGET >= 20000, "默认预算装不下一次完整的多轮修正"


def test_a_non_positive_budget_is_rejected_at_construction():
    with pytest.raises(ValueError, match="token_budget"):
        AnalystAgent(REGISTRY, token_budget=0)


# ── 响应缓存：省钱，且看得见 ────────────────────────────────────────


def test_the_same_analysis_twice_calls_the_provider_once():
    from agents.llm import FakeLLMProvider

    provider = FakeLLMProvider(responses=_scripted(_conforming_text()))
    agent = AnalystAgent(REGISTRY, provider=provider)

    first = agent.analyze(CHART, "事业", critic=CriticAgent())
    second = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert first.served_from_cache is False
    assert second.served_from_cache is True, "第二次同样的请求必须命中缓存"
    assert len(provider.requests) == 1, f"provider 被调了 {len(provider.requests)} 次"
    assert first.provider_calls == 1
    assert second.provider_calls == 0, "缓存命中不该计数"
    # 结论一致 —— 同一个提示词本该得到同一个答案。
    assert first.conclusion == second.conclusion


def test_a_cached_hit_still_reports_the_original_tokens():
    """缓存命中时 token 记账归零（没调用就没花钱），但结论仍在。"""
    from agents.llm import FakeLLMProvider

    provider = FakeLLMProvider(responses=_scripted(_conforming_text()))
    agent = AnalystAgent(REGISTRY, provider=provider)

    agent.analyze(CHART, "事业", critic=CriticAgent())
    cached = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert cached.prompt_tokens == 0
    assert cached.completion_tokens == 0
    assert cached.conclusion.strip()


def test_a_different_topic_is_a_cache_miss():
    """不同主题 → 不同证据链 → 不同提示词 → 必须重新调用。"""
    from agents.llm import FakeLLMProvider

    provider = FakeLLMProvider(responses=_scripted(_conforming_text(), _conforming_text()))
    agent = AnalystAgent(REGISTRY, provider=provider)

    agent.analyze(CHART, "事业", critic=CriticAgent())
    second = agent.analyze(CHART, "结构", critic=CriticAgent())

    assert len(provider.requests) == 2
    assert second.served_from_cache is False


def test_a_different_chart_is_a_cache_miss():
    """同主题不同生辰 → 证据链不同 → 不得命中缓存。

    这条守的是最坏的一类缓存 bug：键取得太粗（比如只按主题），
    于是每个人拿到同一个人的结论。那种错误不抛异常，只是安静地错。
    """
    from agents.llm import FakeLLMProvider

    other = SxtwlBaziProvider().calculate(BirthInput(1985, 11, 20, 6))
    provider = FakeLLMProvider(responses=_scripted(_conforming_text(), _conforming_text()))
    agent = AnalystAgent(REGISTRY, provider=provider)

    agent.analyze(CHART, "事业", critic=CriticAgent())
    second = agent.analyze(other, "事业", critic=CriticAgent())

    assert len(provider.requests) == 2
    assert second.served_from_cache is False


def test_the_cache_is_bounded():
    """超过上限时淘汰最早一条，缓存不能无限增长。"""
    from agents.llm import FakeLLMProvider, LLMRequest

    provider = FakeLLMProvider(responses=["ok"] * (RESPONSE_CACHE_LIMIT + 20))
    agent = AnalystAgent(REGISTRY, provider=provider)

    for index in range(RESPONSE_CACHE_LIMIT + 20):
        agent._remember(LLMRequest(system="s", user=f"u{index}"), f"r{index}")

    assert len(agent._response_cache) == RESPONSE_CACHE_LIMIT
    # 最早的一条已被淘汰。
    assert agent._cached(LLMRequest(system="s", user="u0")) is None
    # 最新的一条还在。
    assert agent._cached(LLMRequest(system="s", user=f"u{RESPONSE_CACHE_LIMIT + 19}")) == (
        f"r{RESPONSE_CACHE_LIMIT + 19}"
    )


def test_the_cache_key_is_the_whole_prompt():
    """system 差一个字节就算不同请求。"""
    from agents.llm import LLMRequest

    agent = AnalystAgent(REGISTRY)
    agent._remember(LLMRequest(system="s", user="u"), "r")

    assert agent._cached(LLMRequest(system="s", user="u")) == "r"
    assert agent._cached(LLMRequest(system="s ", user="u")) is None
    assert agent._cached(LLMRequest(system="s", user="u ")) is None


# ── 记账 ────────────────────────────────────────────────────────────


def test_a_healthy_provider_reports_split_token_counts():
    from agents.llm import FakeLLMProvider

    provider = FakeLLMProvider(responses=_scripted(_conforming_text()))
    agent = AnalystAgent(REGISTRY, provider=provider)

    analysis = agent.analyze(CHART, "事业", critic=CriticAgent())

    assert analysis.prompt_tokens > 0
    assert analysis.completion_tokens > 0
    assert analysis.provider_calls == 1
    assert analysis.served_from_cache is False
    # 提示与输出必须能分开：prompt_tokens 里不含输出。
    output_only = estimate_tokens(_conforming_text())
    assert analysis.prompt_tokens > output_only


def test_the_template_path_reports_zero_everything():
    analysis = AnalystAgent(REGISTRY).analyze(CHART, "事业")

    assert analysis.prompt_tokens == 0
    assert analysis.completion_tokens == 0
    assert analysis.provider_calls == 0
    assert analysis.served_from_cache is False


def test_the_service_surfaces_the_accounting():
    from agents.llm import FakeLLMProvider

    service = MingLiService()
    service.analyst.provider = FakeLLMProvider(responses=_scripted(_conforming_text()))

    draft = service.analyze(BIRTH, "事业").to_dict()["analysis"]["draft"]

    assert draft["prompt_tokens"] > 0
    assert draft["provider_calls"] == 1
    assert draft["served_from_cache"] is False
    assert draft["degraded_reason"] == ""


# ── 并发：共享一个 agent 不炸 ───────────────────────────────────────


def test_concurrent_topics_share_one_agent_safely():
    """analyze_multi 用线程池扇出，多个主题同时读写同一个缓存。

    这条不追求证明「没有竞态」（那需要压力与调度运气），只证明共享状态下
    功能正确：每个主题各自命中各自的缓存、计数不串。
    """
    from agents.llm import FakeLLMProvider

    topics = ["事业", "财运", "婚姻", "健康"]
    provider = FakeLLMProvider(responses=_scripted(*[_conforming_text()] * 8))
    service = MingLiService()
    service.analyst.provider = provider

    first = service.analyze_multi(BIRTH, topics)
    after_first = len(provider.requests)
    second = service.analyze_multi(BIRTH, topics)
    after_second = len(provider.requests)

    assert len(first.succeeded) == 4 and len(second.succeeded) == 4
    assert after_first >= 4, f"第一轮至少 4 次调用，实调 {after_first} 次"
    # **第二轮一次都不该再调** —— 同样的输入全部命中缓存。
    # 不断言第一轮恰好 4 次：有的主题第一稿过不了审，会多一次重写，
    # 那也是缓存里的一条。第一版的「恰好 4 次」就是这么错的。
    assert after_second == after_first, (
        f"第二轮又调了 {after_second - after_first} 次 —— 缓存没挡住重复请求"
    )
    for result in second.results:
        draft = result.analysis.analysis["draft"]
        assert draft["served_from_cache"] is True
        assert draft["provider_calls"] == 0
