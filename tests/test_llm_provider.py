"""provider 协议与假 provider 的测试。

假 provider 是 Phase 4 全部离线测试的地基，所以它自己也要被钉住：
脚本顺序、脚本用尽时的行为、请求留痕。它出错的方式（静默返回兜底内容）
正是最难发现的那种 —— 测试会很绿，实际什么都没验。
"""

from __future__ import annotations

import pytest

from agents.llm import FakeLLMProvider, LLMProvider, LLMRequest


def test_request_to_dict_has_only_two_channels():
    request = LLMRequest(system="系统", user="用户")

    assert request.to_dict() == {"system": "系统", "user": "用户"}


def test_request_is_frozen():
    request = LLMRequest(system="系统", user="用户")

    with pytest.raises(Exception):
        request.system = "改掉"  # type: ignore[misc]


def test_fake_provider_returns_scripted_responses_in_order():
    provider = FakeLLMProvider(responses=["第一条", "第二条"])

    assert provider.complete(LLMRequest("s", "u")) == "第一条"
    assert provider.complete(LLMRequest("s", "u")) == "第二条"


def test_fake_provider_raises_when_the_script_runs_out():
    """脚本用尽必须抛错。

    返回兜底文案会让「少写了一条脚本」表现成「测试通过」——
    测试看着很绿，实际什么都没验。这是最坏的失败模式。
    """
    provider = FakeLLMProvider(responses=["只有一条"])
    provider.complete(LLMRequest("s", "u"))

    with pytest.raises(RuntimeError, match="脚本已用尽"):
        provider.complete(LLMRequest("s", "u"))


def test_fake_provider_error_names_the_missing_call_index():
    """报出「第几次调用缺脚本」，便于一眼定位是哪一轮重写没配脚本。"""
    provider = FakeLLMProvider(responses=["只有一条"])
    provider.complete(LLMRequest("s", "u"))

    with pytest.raises(RuntimeError, match="第 2 次调用"):
        provider.complete(LLMRequest("s", "u"))


def test_fake_provider_records_every_request():
    provider = FakeLLMProvider(responses=["一", "二"])
    provider.complete(LLMRequest("s1", "u1"))
    provider.complete(LLMRequest("s2", "u2"))

    assert [request.user for request in provider.requests] == ["u1", "u2"]


def test_fake_provider_satisfies_the_protocol():
    provider = FakeLLMProvider(responses=[])

    assert isinstance(provider, LLMProvider)
    assert provider.name == "fake"
    assert provider.model == "scripted"


def test_protocol_rejects_an_object_without_complete():
    class Half:
        name = "half"
        model = "half"

    assert not isinstance(Half(), LLMProvider)
