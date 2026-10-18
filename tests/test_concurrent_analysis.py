"""多主题并发分析测试。

四条验收，对应计划里的四条：

1. N 个主题并发跑通；
2. **并发结果与逐个串行调用逐字段相等** —— 防竞态，这条最关键；
3. 单主题失败不影响其余，失败项如实带回原因；
4. I/O 密集时墙钟更短 —— 用会 sleep 的假 provider 证明，不靠嘴说。

**为什么第 4 条要用假 provider 而不是直接测确定性路径**：确定性路径是
纯 CPU 的，Python 的 GIL 让线程拿不到并行度，墙钟不会变短。那时断言
「墙钟更短」会得到一个假失败。并发的真实收益在 provider 路径（每个主题
一次网络调用），所以用 sleep 模拟 I/O 等待来验证形状是对的。
"""

import time

from fastapi.testclient import TestClient

from agents.llm import LLMRequest
from api.server import app
from runtime.mingli_service import MingLiService

client = TestClient(app)

BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12}
TOPICS = ["事业", "财运", "婚姻", "健康"]


def sequential_results(service: MingLiService, topics):
    """逐个串行调用，作为并发的对照基准。"""
    return {
        topic: service.analyze(BIRTH, topic).to_dict() for topic in topics
    }


def test_multi_analysis_covers_every_topic():
    response = client.post("/api/analyze/multi", json={**BIRTH, "topics": TOPICS})

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == len(TOPICS)
    assert body["failed"] == 0
    assert [r["topic"] for r in body["results"]] == TOPICS


def test_concurrent_results_match_sequential_field_by_field():
    """并发不得改变任何一个字节的结果。

    这条测试存在的唯一理由是防竞态。并发写错不会抛异常，只会偶尔给出
    不同答案 —— 而「偶尔」的 bug 靠人工跑几次是发现不了的。
    """
    service = MingLiService()
    expected = sequential_results(service, TOPICS)

    multi = service.analyze_multi(BIRTH, TOPICS)
    assert multi.succeeded and not multi.failed

    for result in multi.results:
        got = result.analysis.to_dict()
        want = expected[result.topic]
        # chart 两边都有，一并比对
        assert got["chart"] == want["chart"]
        assert got["analysis"]["evidence"]["chain"] == want["analysis"]["evidence"]["chain"]
        assert got["analysis"]["conclusion"] == want["analysis"]["conclusion"]
        assert got["analysis"]["draft"] == want["analysis"]["draft"]
        assert got["critique"] == want["critique"]


def _normalize(value):
    """把服务层返回的 tuple 递归转成 list，好和 JSON 响应逐字段比对。

    API 走的是 JSON，tuple 一律变 list —— 这是序列化的固有差异，不是 bug。
    不归一化的话这条测试永远红，而它本来要抓的是「结论/规则/强度对不上」。
    """
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def test_api_multi_matches_a_direct_call():
    """API 必须是服务层的直通，两层不得各算一遍。

    比对的是**响应模型声明过的字段**。服务层的 ``Evidence.to_dict`` 另外
    带 ``rules`` / ``sources`` / ``rule_provenance`` 三个扁平视图，注释写明
    是「兼容既有调用方」—— 它们与 ``chain`` 内容重复，API 不声明、由
    ``extra="ignore"`` 裁掉，这是刻意的收窄，不算偏差。
    """
    service = MingLiService()
    direct = _normalize(service.analyze_multi(BIRTH, TOPICS).to_dict())

    body = client.post("/api/analyze/multi", json={**BIRTH, "topics": TOPICS}).json()
    assert body["succeeded"] == direct["succeeded"]
    assert body["failed"] == direct["failed"]

    for got, want in zip(body["results"], direct["results"], strict=True):
        assert got["topic"] == want["topic"]
        assert got["ok"] == want["ok"]
        evidence = want["analysis"]["analysis"]["evidence"]
        assert got["analysis"]["analysis"]["conclusion"] == want["analysis"]["analysis"]["conclusion"]
        assert got["analysis"]["analysis"]["evidence"]["chain"] == evidence["chain"]
        assert got["analysis"]["analysis"]["evidence"]["strength"] == evidence["strength"]
        assert got["analysis"]["analysis"]["draft"] == want["analysis"]["analysis"]["draft"]
        assert got["analysis"]["critique"] == want["analysis"]["critique"]


def test_classical_rules_reach_the_api_with_a_citation():
    """古典规则的 urn 与 citation 必须随证据链到达 API。

    这一条不是锦上添花：知识层 ``RuleMatch.to_dict`` 的注释写明这两项是
    「必须」—— 没有它们，模型要么不写出处角标，要么自己编一个，两者都比
    不给更糟。API 早先把它们裁掉了，于是「可验证的出处」在服务层成立、
    在 API 层消失。2026-10-16 补的，这条测试就是防它再被裁掉。
    """
    # 甲辰日甲子时：见证盘 1951-01-04，命中 j8.liujia_ri 的古典原子。
    birth = {"year": 1951, "month": 1, "day": 4, "hour": 0}
    body = client.post(
        "/api/analyze/multi", json={**birth, "topics": ["命局"]}
    ).json()

    classical = [
        link
        for result in body["results"]
        for link in result["analysis"]["analysis"]["evidence"]["chain"]
        if link["source_tier"] == "classical"
    ]
    assert classical, "该命盘应命中至少一条古典规则"

    for link in classical:
        assert link["urn"], f"{link['rule_id']} 缺 urn"
        assert link["citation"], f"{link['rule_id']} 缺 citation"
        citation = link["citation"]
        assert citation["book"], "citation 必须带书名"
        assert citation["edition"], "citation 必须带底本"
        assert citation["original_text"], "citation 必须带逐字原文"
        assert citation["url"], "citation 必须带可打开的出处地址"


def test_one_failing_topic_does_not_sink_the_others():
    """故障隔离：一个主题炸了，其余主题的结果必须完整，失败项如实带回原因。"""
    service = MingLiService()
    # 空问题会触发 AnalystAgent 的入参校验 —— 用它造一个必然失败的主题，
    # 不需要 mock 任何东西。
    broken = [*TOPICS, "   "]

    multi = service.analyze_multi(BIRTH, broken)

    assert len(multi.succeeded) == len(TOPICS), "其余主题必须全部成功"
    assert len(multi.failed) == 1, "只该失败那一个"
    failure = multi.failed[0]
    assert failure.topic == "   "
    assert failure.error, "失败必须带回原因"
    assert failure.analysis is None
    # 成功的主题结果与串行一致 —— 隔离不能以改变结果为代价
    for result in multi.succeeded:
        assert result.analysis.to_dict() == service.analyze(BIRTH, result.topic).to_dict()


def test_api_multi_isolates_a_failing_topic():
    response = client.post(
        "/api/analyze/multi", json={**BIRTH, "topics": [*TOPICS, "   "]}
    )

    assert response.status_code == 200, "单主题失败不该让整个请求 500"
    body = response.json()
    assert body["succeeded"] == len(TOPICS)
    assert body["failed"] == 1
    failure = next(r for r in body["results"] if not r["ok"])
    assert failure["analysis"] is None
    assert failure["error"]


class _CountingCalculator:
    """包一层计算器，数它被调了几次。"""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def calculate_chart(self, birth):
        self.calls += 1
        return self.inner.calculate_chart(birth)


def test_chart_is_computed_once_not_per_topic():
    """命盘只算一次 —— 扇出点在它之后。

    「命盘只算一次」是这条并发路径的承重墙：排盘是这条链上最贵的一步，
    回退成每个主题各算一遍不会报错、不会给出错答案，只会悄悄变慢，
    而没有任何别的测试会发现。所以用计数器把它钉住。
    """
    service = MingLiService()
    counter = _CountingCalculator(service.calculator)
    service.calculator = counter

    service.analyze_multi(BIRTH, TOPICS)

    assert counter.calls == 1, f"命盘被算了 {counter.calls} 次，应为 1 次"


def test_multi_rejects_an_empty_topic_list():
    response = client.post("/api/analyze/multi", json={**BIRTH, "topics": []})

    assert response.status_code == 422


def test_service_rejects_an_empty_topic_list_with_a_clear_message():
    """服务层自己也要拦空列表，且报错要说得清。

    HTTP 路径上 ``Field(min_length=1)`` 已经先拦了，所以这一条**从 API
    不可达** —— 它守的是直接调 ``MingLiService`` 的调用方。去掉服务层守卫
    的话，那边会拿到 ``ValueError: max_workers must be greater than 0``，
    那是线程池的抱怨，不是「你传了空列表」。
    """
    import pytest

    service = MingLiService()
    with pytest.raises(ValueError, match="topics 不能为空"):
        service.analyze_multi(BIRTH, [])


class _SlowProvider:
    """每次调用都睡固定时长的假 provider，用来把 I/O 等待显式化。"""

    name = "slow"
    model = "scripted"
    latency = 0.25

    def __init__(self):
        self.calls = 0

    def complete(self, request: LLMRequest) -> str:
        self.calls += 1
        time.sleep(self.latency)
        # 契约要求的输出形状；内容不重要，这里只测时序。
        return '{"rule_ids": [], "text": "占位"}'


def test_concurrency_pays_off_when_the_bottleneck_is_io():
    """I/O 密集时并发必须真的更快。

    这条是并发的**存在理由**。确定性路径下 GIL 让线程拿不到并行度，
    墙钟不会变短；而 provider 路径每个主题是一次阻塞调用，线程池这时
    才真正并行。用 sleep 把等待显式化，四个主题各睡 0.25 秒：
    串行约 1 秒，并发应显著小于它。
    """
    provider = _SlowProvider()
    service = MingLiService(provider=provider)
    assert provider.calls == 0

    started = time.monotonic()
    multi = service.analyze_multi(BIRTH, TOPICS)
    elapsed = time.monotonic() - started

    assert provider.calls >= len(TOPICS), "每个主题都应真的调用过 provider"
    assert multi.failed == (), f"并发路径下不应有失败：{multi.failed}"

    serial_estimate = provider.latency * provider.calls
    assert elapsed < serial_estimate * 0.7, (
        f"并发耗时 {elapsed:.2f}s，串行约 {serial_estimate:.2f}s —— 并发没有收益"
    )


def test_openapi_documents_the_multi_endpoint():
    schema = client.get("/openapi.json").json()

    assert "/api/analyze/multi" in schema["paths"]
    assert "MultiAnalysisResponse" in schema["components"]["schemas"]
    results = schema["components"]["schemas"]["TopicResultResponse"]["properties"]
    assert "ok" in results
    assert "error" in results


# ── Phase 2.3：线程池硬顶 ─────────────────────────────────────────────


def test_the_thread_pool_has_a_hard_cap(monkeypatch):
    """``max_workers`` 有封顶，不随主题数无限增长。

    服务层是公开入口：API 层有 ``MAX_TOPICS`` 拦着，直接调
    ``analyze_multi`` 的调用方不受那道约束。没有封顶时，一次调用就能开出
    任意多个线程 —— 那不是支持并发，是把调度权交给调用方。

    这条测试**真的观测** ``max_workers``：把模块里的 ``ThreadPoolExecutor``
    换成一个记录构造参数的壳，跑一次 40 主题的调用，再看壳收到了什么。
    只断言「两个常量相等」是不够的 —— 那证明不了 ``min()`` 真的生效了。
    """
    import runtime.mingli_service as service_module

    seen: dict[str, int] = {}

    class _RecordingPool:
        def __init__(self, max_workers: int) -> None:
            seen["max_workers"] = max_workers

        def __enter__(self):
            from concurrent.futures import ThreadPoolExecutor
            self._real = ThreadPoolExecutor(max_workers=seen["max_workers"])
            return self._real

        def __exit__(self, *exc):
            return self._real.__exit__(*exc)

    monkeypatch.setattr(service_module, "ThreadPoolExecutor", _RecordingPool)

    service = MingLiService()
    topics = [f"主题{i}" for i in range(40)]  # 远超封顶值
    multi = service.analyze_multi(BIRTH, topics)

    assert len(multi.results) == 40, "每个主题都应有结果"
    assert seen["max_workers"] == service_module.MAX_ANALYSIS_WORKERS, (
        f"40 个主题时 max_workers 应为封顶值 "
        f"{service_module.MAX_ANALYSIS_WORKERS}，实得 {seen['max_workers']}"
    )


def test_small_topic_lists_do_not_open_extra_threads():
    """主题数少于封顶值时，不开多余的线程。

    这条守的是另一半：``min()`` 写反成恒取封顶值的话，上面那条照样绿，
    但每次两个主题的分析都会开出 8 个线程。
    """
    import runtime.mingli_service as service_module

    seen: dict[str, int] = {}

    class _RecordingPool:
        def __init__(self, max_workers: int) -> None:
            seen["max_workers"] = max_workers

        def __enter__(self):
            from concurrent.futures import ThreadPoolExecutor
            self._real = ThreadPoolExecutor(max_workers=seen["max_workers"])
            return self._real

        def __exit__(self, *exc):
            return self._real.__exit__(*exc)

    service = MingLiService()
    original = service_module.ThreadPoolExecutor
    service_module.ThreadPoolExecutor = _RecordingPool
    try:
        service.analyze_multi(BIRTH, TOPICS)
    finally:
        service_module.ThreadPoolExecutor = original

    assert seen["max_workers"] == len(TOPICS), (
        f"{len(TOPICS)} 个主题应只开 {len(TOPICS)} 个线程，实得 {seen['max_workers']}"
    )


def test_service_and_api_caps_agree():
    """服务层封顶与 API 上限必须一致。

    服务层**不 import** API 层 —— 依赖方向是 API → 服务，反了会让服务层
    依赖 HTTP 框架。所以两边各定一个常量，用这条测试保证它们不越漂越远。
    """
    from api.server import MAX_TOPICS
    from runtime.mingli_service import MAX_ANALYSIS_WORKERS

    assert MAX_ANALYSIS_WORKERS == MAX_TOPICS
