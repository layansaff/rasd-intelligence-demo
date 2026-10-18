from fastapi.testclient import TestClient
import json
import sqlite3
import pytest

from backend import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "rasd-test.sqlite3")
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def valid_request():
    return {
        "supplier_name": "Supplier A",
        "critical_process": "Payment Processing",
        "impact_level": "high",
        "recovery_hours": 72,
        "required_recovery_hours": 24,
        "disruption_likelihood": "high",
        "dependency_level": "high",
        "alternative_supplier_available": False,
        "controls_effectiveness": "weak",
    }


def test_health_ui_and_security_headers(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert health.json()["storage"] == "available"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"

    ui = client.get("/ui")
    assert ui.status_code == 200
    assert "RASD Intelligence" in ui.text

    allowed = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5500"
    rejected = client.options(
        "/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in rejected.headers


def test_assessment_returns_explanation_and_persists(client, valid_request):
    response = client.post("/analyze-risk", json=valid_request)
    assert response.status_code == 200
    result = response.json()
    assert result["risk_score"] == 88
    assert result["risk_level"] == "High"
    assert result["model_version"] == main.MODEL_VERSION
    assert result["assessment_id"]
    assert result["risk_dimensions"]
    assert all(isinstance(factor, str) for factor in result["risk_factors"])

    history = client.get("/assessments")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    item = history.json()["items"][0]
    assert item["id"] == result["assessment_id"]
    assert item["input"] == valid_request
    assert item["data"]["risk_score"] == 88


def test_public_demo_never_stores_visitor_assessments(
    tmp_path, monkeypatch, valid_request
):
    database_path = tmp_path / "must-not-be-created.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", database_path)
    monkeypatch.setattr(main, "DEMO_MODE", True)

    with TestClient(main.app) as demo_client:
        health = demo_client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "healthy",
            "version": main.APP_VERSION,
            "storage": "disabled",
            "demo_mode": True,
        }

        result = demo_client.post("/analyze-risk", json=valid_request)
        assert result.status_code == 200
        assert result.json()["risk_score"] == 88
        assert demo_client.get("/assessments").json()["total"] == 0
        assert demo_client.get("/assessments/summary").json() == {
            "total": 0,
            "high_risk": 0,
            "average_score": None,
            "highest_score": None,
        }
        assert demo_client.delete("/assessments").json() == {"deleted": 0}

    assert not database_path.exists()


def test_history_survives_application_restart(tmp_path, monkeypatch, valid_request):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "persistent.sqlite3")
    with TestClient(main.app) as first_client:
        assert first_client.post("/analyze-risk", json=valid_request).status_code == 200

    with TestClient(main.app) as second_client:
        history = second_client.get("/assessments").json()
        assert history["total"] == 1
        assert history["items"][0]["input"]["supplier_name"] == "Supplier A"


def test_database_schema_upgrade_preserves_existing_assessments(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE assessments (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                supplier_name TEXT NOT NULL,
                critical_process TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?)",
            (
                "legacy-id",
                "2026-10-17T12:00:00Z",
                "Supplier A",
                "Payments",
                json.dumps({"supplier_name": "Supplier A", "critical_process": "Payments"}),
                json.dumps({"risk_score": 73, "risk_level": "High"}),
            ),
        )

    main.initialize_database()
    assert main.get_assessment_summary() == {
        "total": 1,
        "high_risk": 1,
        "average_score": 73.0,
        "highest_score": 73,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("recovery_hours", -1),
        ("recovery_hours", 8761),
        ("recovery_hours", 1.5),
        ("required_recovery_hours", 0),
        ("required_recovery_hours", 8761),
        ("impact_level", "critical"),
        ("unexpected", True),
    ],
)
def test_invalid_input_is_rejected(client, valid_request, field, value):
    payload = {**valid_request, field: value}
    response = client.post("/analyze-risk", json=payload)
    assert response.status_code == 422


def test_fractional_json_numbers_are_not_coerced(client, valid_request):
    valid_request["recovery_hours"] = "72"
    response = client.post("/analyze-risk", json=valid_request)
    assert response.status_code == 422


def test_history_pagination_and_delete(client, valid_request):
    for index in range(3):
        payload = {**valid_request, "supplier_name": f"Supplier {index}"}
        assert client.post("/analyze-risk", json=payload).status_code == 200

    page = client.get("/assessments?limit=2&offset=1").json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["offset"] == 1
    summary = client.get("/assessments/summary").json()
    assert summary["total"] == 3
    assert summary["high_risk"] == 3
    assert summary["average_score"] == 88.0
    assert summary["highest_score"] == 88

    assert client.get("/assessments?limit=501").status_code == 422

    deleted = client.delete("/assessments")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": 3}
    assert client.get("/assessments").json()["total"] == 0


@pytest.mark.parametrize(
    "recovery,required,expected",
    [(24, 24, 15), (36, 24, 35), (48, 24, 55), (96, 24, 80), (120, 24, 100)],
)
def test_recovery_score_bands(recovery, required, expected):
    assert main.calculate_recovery_score(recovery, required) == expected


@pytest.mark.parametrize(
    "score,expected",
    [(0, "Low"), (39, "Low"), (40, "Medium"), (69, "Medium"), (70, "High"), (100, "High")],
)
def test_risk_classification_boundaries(score, expected):
    assert main.classify_risk(score) == expected
