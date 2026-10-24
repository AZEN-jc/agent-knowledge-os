"""FastAPI 接口测试。"""

from fastapi.testclient import TestClient

from api.server import app

client = TestClient(app)


def payload():
    return {"year": 1990, "month": 2, "day": 1, "hour": 12}


def test_health_reports_real_provider():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "sxtwl"}


def test_chart_endpoint_returns_structured_chart():
    response = client.post("/api/chart", json=payload())

    assert response.status_code == 200
    assert response.json()["provider"] == "sxtwl"
    assert len(response.json()["pillars"]) == 4


def test_analyze_endpoint_returns_evidence_and_critique():
    response = client.post("/api/analyze", json={**payload(), "question": "事业"})

    assert response.status_code == 200
    assert "evidence" in response.json()["analysis"]
    assert "critique" in response.json()


def test_api_rejects_invalid_birth_input():
    response = client.post("/api/chart", json={**payload(), "month": 13})

    assert response.status_code == 422


def test_api_rejects_unknown_timezone_with_a_readable_message():
    response = client.post("/api/chart", json={**payload(), "timezone": "Not/AZone"})

    assert response.status_code == 422
    assert "未知时区" in response.json()["detail"]


# ── 字段级错误（Phase 5.2：前端要能定位到具体输入框）────────────────────


def test_validation_error_carries_field_items():
    """422 除了 detail 串，还要有 fields 数组 —— 五个输入框，

    用户需要知道错的是哪一个。detail 保留是向后兼容（现有消费者依赖它），
    fields 是加法：``[{"field": "month", "message": "公历月不能大于12"}]``。
    """
    response = client.post("/api/chart", json={**payload(), "month": 13})

    assert response.status_code == 422
    body = response.json()
    fields = body["fields"]
    assert isinstance(fields, list) and fields
    month_items = [item for item in fields if item["field"] == "month"]
    assert month_items, f"fields 应定位到 month：{fields}"
    assert "12" in month_items[0]["message"]


def test_validation_error_fields_are_consistent_with_the_detail_string():
    """两个表示必须同源：fields 里每条 message 都出现在 detail 里。"""
    response = client.post("/api/chart", json={**payload(), "month": 13, "day": 99})

    assert response.status_code == 422
    body = response.json()
    detail = body["detail"]
    assert {"month", "day"} <= {item["field"] for item in body["fields"]}
    for item in body["fields"]:
        assert item["message"] in detail


def test_service_layer_422_keeps_the_plain_detail_string():
    """服务层 422（引擎拒绝）没有 fields —— 那一层的问题是整请求的，

    不是哪个输入框填错了。detail 字符串照旧，前端回退到顶部错误框。
    """
    response = client.post("/api/chart", json={**payload(), "timezone": "Not/AZone"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert "fields" not in response.json()


# ── OpenAPI 文档（Phase 1 验收：API 文档完整）────────────────────────────


def test_openapi_schema_documents_every_endpoint():
    schema = client.get("/openapi.json").json()

    assert schema["info"]["title"] == "MingLi Agent API"
    assert schema["paths"], "至少要有一个端点"

    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            assert operation.get("summary"), f"{method.upper()} {path} 缺少 summary"
            assert operation.get("description"), f"{method.upper()} {path} 缺少 description"


def test_openapi_schema_describes_birth_fields_and_error_case():
    schema = client.get("/openapi.json").json()
    birth = schema["components"]["schemas"]["BirthRequest"]

    assert birth["properties"]["timezone"]["default"] == "Asia/Shanghai"
    assert "经度" in birth["properties"]["longitude"]["description"]
    assert "422" in schema["paths"]["/api/chart"]["post"]["responses"]


# ── 规则库查询 API（Phase 2 验收：规则查询 API 完整）────────────────────


def test_rules_endpoint_lists_the_library_with_provenance():
    response = client.get("/api/rules")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 50
    assert body["total"] == len(body["rules"])

    sample = body["rules"][0]
    for field in ("id", "source", "school", "category", "topic", "condition",
                  "conclusion", "confidence", "source_tier", "review_status"):
        assert field in sample, f"规则缺少 {field}"
    assert sample["source_tier"] == "structural"


def test_rules_endpoint_filters_by_school_category_and_tier():
    response = client.get("/api/rules", params={"category": "relation"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 6
    assert body["filters"] == {"category": "relation"}
    assert all(rule["category"] == "relation" for rule in body["rules"])

    empty = client.get("/api/rules", params={"school": "not_a_school"}).json()
    assert empty["total"] == 0
    assert empty["rules"] == []


def test_rules_endpoint_rejects_an_unknown_review_status():
    response = client.get("/api/rules", params={"review_status": "MAYBE"})

    assert response.status_code == 422


def test_rule_stats_endpoint_is_not_shadowed_by_the_detail_route():
    response = client.get("/api/rules/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 50
    assert body["production_ready"] == body["total"]
    assert "by_school" in body


def test_rule_detail_returns_a_single_rule():
    listed = client.get("/api/rules", params={"category": "relation"}).json()["rules"]
    rule_id = listed[0]["id"]

    response = client.get(f"/api/rules/{rule_id}")

    assert response.status_code == 200
    assert response.json()["id"] == rule_id


def test_rule_detail_returns_404_for_unknown_id():
    response = client.get("/api/rules/NOPE_404")

    assert response.status_code == 404
    assert "未知规则" in response.json()["detail"]


def test_schools_endpoint_marks_schools_without_public_domain_classics():
    response = client.get("/api/schools")

    assert response.status_code == 200
    schools = {item["id"]: item for item in response.json()["schools"]}

    assert "structural_common" in schools
    assert schools["mang_pai"]["classics"] == []
    assert schools["mang_pai"]["note"], "没有典籍的流派必须写明原因"
    assert schools["di_tian_sui"]["classics"] == ["《滴天髓》"]


def test_classics_backlog_endpoint_explains_the_current_blocker():
    response = client.get("/api/classics/backlog")

    assert response.status_code == 200
    body = response.json()

    assert body["total"] >= 5
    assert body["blocked"] == body["total"], "当前所有典籍来源都不可录入"
    assert body["next_action"] == "《滴天髓》"
    assert all(entry["blocker"] for entry in body["entries"])
    assert all(entry["needed_action"] for entry in body["entries"])


# ── 证据层 API（Phase 3 验收：证据链可追溯、强度可解释、覆盖状态透明）───


def test_analyze_exposes_a_traceable_evidence_chain():
    body = client.post("/api/analyze", json={**payload(), "question": "事业"}).json()
    evidence = body["analysis"]["evidence"]

    assert evidence["chain"], "证据链不能为空"
    link = evidence["chain"][0]
    assert link["rule_id"] and link["conclusion"]
    assert link["conditions"], "每一环都必须带条件追踪"

    trace = link["conditions"][0]
    assert trace["key"] and trace["sources"], "条件追踪必须能回溯到命盘要素"
    assert all(source.startswith("chart.") for source in trace["sources"])


def test_analyze_reports_the_strength_arithmetic():
    body = client.post("/api/analyze", json={**payload(), "question": "事业"}).json()
    evidence = body["analysis"]["evidence"]
    breakdown = evidence["strength_breakdown"]

    assert evidence["strength"] == breakdown["final"]
    assert breakdown["supporting_rules"] == len(evidence["chain"])
    assert breakdown["raw_support"] > 0
    assert 0.0 <= breakdown["final"] < 1.0, "结构层证据不该被读成「几乎确定」"
    assert breakdown["final"] == round(
        max(0.0, breakdown["after_saturation"] - breakdown["conflict_penalty"]), 4
    )


def test_analyze_discloses_that_a_career_question_has_no_career_rules():
    """回归：问「事业」不能拿到一份自称是事业结论的结构层报告。"""
    body = client.post("/api/analyze", json={**payload(), "question": "事业"}).json()
    evidence = body["analysis"]["evidence"]

    assert evidence["topic_id"] == "career"
    assert evidence["status"] == "base_only"
    assert evidence["domain_rules"] == []
    assert evidence["base_rules"], "基础层证据照常要给"
    assert "不构成" in evidence["coverage_note"]
    assert evidence["coverage_note"] in body["analysis"]["conclusion"]


def test_analyze_reports_no_broken_links_in_the_evidence_chain():
    body = client.post("/api/analyze", json={**payload(), "question": "事业"}).json()

    assert body["analysis"]["evidence"]["untraced_rules"] == []
    assert body["critique"]["passed"] is True, body["critique"]["issues"]


def test_topics_endpoint_marks_topics_that_have_no_rules():
    response = client.get("/api/topics")

    assert response.status_code == 200
    topics = {item["id"]: item for item in response.json()["topics"]}

    assert "structure" in topics
    assert topics["career"]["aliases"], "中文别名必须暴露出来，否则用户不知道传什么"
    assert "事业" in topics["career"]["aliases"]
    assert topics["career"]["blocked_by"], "没有规则的主题必须说明原因"


def test_openapi_documents_the_evidence_chain_and_topics():
    schema = client.get("/openapi.json").json()

    assert "RuleChainResponse" in schema["components"]["schemas"]
    assert "StrengthBreakdownResponse" in schema["components"]["schemas"]
    chain = schema["components"]["schemas"]["RuleChainResponse"]["properties"]
    assert "conditions" in chain
    assert "证据链" in chain["conditions"]["description"]
    assert "/api/topics" in schema["paths"]


def test_analyze_reports_how_the_conclusion_was_drafted():
    """结论的来路必须写在响应里。

    ``draft.cited_rules`` 是「结论能追溯到具体规则」这条验收标准的机器可读形式：
    它是 ``evidence.chain`` 里规则 ID 的子集，可以断言，不用人去读文本比对。
    """
    body = client.post("/api/analyze", json={**payload(), "question": "事业"}).json()
    draft = body["analysis"]["draft"]
    chain_ids = {item["rule_id"] for item in body["analysis"]["evidence"]["chain"]}

    assert draft["source"] == "template", "默认服务不注入 provider，必须走确定性模板"
    assert draft["provider"] == ""
    assert draft["model"] == ""
    assert draft["revisions"] == 0
    assert draft["contract_violations"] == []
    assert draft["certainty_risk"] is False
    assert draft["cited_rules"], "模板路径也要报出引用了哪几条规则"
    assert set(draft["cited_rules"]) <= chain_ids


def test_llm_contract_endpoint_exposes_the_boundary():
    response = client.get("/api/llm/contract")

    assert response.status_code == 200
    body = response.json()

    assert body["version"]
    assert body["draft_schema"]["required"] == ["rule_ids", "text"]
    assert body["draft_schema"]["additionalProperties"] is False
    assert len(body["boundary"]) >= 5
    assert body["forbidden_certainty_words"], "禁用词表必须公开，否则无从审计"
    assert body["strength_marker"] in body["system_prompt"]
    assert 0.0 < body["low_strength_ceiling"] < 1.0
    for word in body["forbidden_certainty_words"]:
        assert word in body["system_prompt"]


def test_llm_contract_says_the_model_never_sees_the_chart():
    body = client.get("/api/llm/contract").json()

    assert any("证据链" in rule and "命盘" in rule for rule in body["boundary"])
    assert "没有原始命盘" in body["system_prompt"]


def test_openapi_documents_the_llm_contract():
    schema = client.get("/openapi.json").json()

    assert "/api/llm/contract" in schema["paths"]
    assert "LLMContractResponse" in schema["components"]["schemas"]
    assert "DraftResponse" in schema["components"]["schemas"]
    draft = schema["components"]["schemas"]["DraftResponse"]["properties"]
    assert "cited_rules" in draft
    assert "证据链的子集" in draft["cited_rules"]["description"]


# ── 流年时间轴 ─────────────────────────────────────────────────────────


def timeline_payload(**overrides):
    body = {**payload(), "start_year": 2024, "end_year": 2028, "topic": "财运"}
    body.update(overrides)
    return body


def test_timeline_endpoint_returns_a_window_per_year():
    response = client.post("/api/timeline", json=timeline_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert [w["year"] for w in body["windows"]] == [2024, 2025, 2026, 2027, 2028]


def test_timeline_reports_structure_not_prediction():
    """报告里不得出现必然性措辞 —— 这是产出物的性质，不是文风。"""
    body = client.post("/api/timeline", json=timeline_payload()).json()

    for window in body["windows"]:
        for phrase in ("一定会", "必将", "必定", "肯定会", "必然会"):
            assert phrase not in window["report"], f"{window['year']} 年：{window['report']}"


def test_timeline_without_gender_omits_dayun():
    """缺性别只算流年 —— 顺逆规则需流派选择，不猜默认方向。"""
    body = client.post("/api/timeline", json=timeline_payload()).json()

    for window in body["windows"]:
        assert window["dayun"] is None
        assert all(s["axis"] == "liunian" for s in window["signals"])


def test_timeline_with_gender_includes_dayun():
    body = client.post(
        "/api/timeline", json=timeline_payload(gender="男", start_year=2024, end_year=2026)
    ).json()

    assert all(window["dayun"] is not None for window in body["windows"])
    assert any(
        signal["axis"] == "dayun"
        for window in body["windows"]
        for signal in window["signals"]
    ), "带大运的区间里应有至少一条大运信号"


def test_timeline_matches_a_direct_call_field_by_field():
    """API 不得另算一遍 —— 它必须是服务层的直通，否则两层会悄悄漂移。

    这是本条测试存在的唯一理由：接线错误不会报错，只会让 API 与服务层
    给出不同答案，而没有任何别的测试会发现。
    """
    from runtime.mingli_service import MingLiService

    payload_body = timeline_payload(gender="男", start_year=2024, end_year=2027)
    service = MingLiService()
    direct = [
        window.to_dict()
        for window in service.analyze_timeline(
            {key: value for key, value in payload_body.items()
             if key not in ("start_year", "end_year", "topic")},
            2024, 2027, "财运",
        )
    ]

    body = client.post("/api/timeline", json=payload_body).json()
    assert body["windows"] == direct


def test_timeline_keeps_relation_signals_under_every_topic():
    """冲太岁与问什么无关 —— 按主题筛掉会让同一结构事实在某些主题下消失。"""
    for topic in ("财运", "事业", "婚姻", "健康"):
        body = client.post("/api/timeline", json=timeline_payload(topic=topic)).json()
        relation = [
            signal
            for window in body["windows"]
            for signal in window["signals"]
            if signal["kind"].endswith("relation_pairs")
        ]
        assert relation, f"{topic} 主题丢了地支关系信号"


def test_timeline_rejects_a_reverse_range():
    response = client.post(
        "/api/timeline", json=timeline_payload(start_year=2030, end_year=2020)
    )

    assert response.status_code == 422
    assert "start_year" in response.json()["detail"]


def test_openapi_documents_the_timeline_endpoint():
    schema = client.get("/openapi.json").json()

    assert "/api/timeline" in schema["paths"]
    assert "TimelineResponse" in schema["components"]["schemas"]
    signals = schema["components"]["schemas"]["SignalResponse"]["properties"]
    assert "source" in signals
    assert "最后一跳" in signals["source"]["description"]
