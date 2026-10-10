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
