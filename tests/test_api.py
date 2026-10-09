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
