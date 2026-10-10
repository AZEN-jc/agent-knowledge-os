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
