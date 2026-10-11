from fastapi.testclient import TestClient
import pytest
from app.main import app
from app import store
from tests.test_engine import example, student


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    with TestClient(app) as c:
        yield c


def test_upload_duplicate_citation_activate_and_profile_persistence(client):
    text = "五项指标按各自权重计算".encode()
    r = client.post("/api/documents", files={"file": ("rules.txt", text, "text/plain")})
    assert r.status_code == 200
    d = r.json()
    assert d["units"][0]["text"] == "五项指标按各自权重计算"
    assert client.post("/api/documents", files={"file": ("rules.txt", text)}).json()["id"] == d["id"]
    p = example()
    p["document_ids"] = [d["id"]]
    for obj in p["item_rules"] + p["formulas"]:
        obj["citations"] = [dict(document_id=d["id"], unit=1, quote="五项指标按各自权重计算")]
    p = client.post("/api/policies/import", json=p).json()
    assert not p["validation_errors"]
    assert client.post("/api/policies/" + p["id"] + "/activate").status_code == 200
    u = client.post("/api/profiles", json={"policy_id": p["id"], "name": "test"}).json()
    u.update(student())
    assert client.put("/api/profiles/" + u["id"], json=u).status_code == 200
    r = client.post("/api/profiles/" + u["id"] + "/calculate", json={})
    assert r.status_code == 200
    assert r.json()["total"] == 80
    assert client.get("/api/profiles/" + u["id"] + "/report").json()["result"]["total"] == 80
    p["formulas"][-1]["expression"] = "undefined_variable"
    assert client.put("/api/policies/" + p["id"], json=p).status_code == 200
    assert client.post("/api/policies/" + p["id"] + "/activate").status_code == 400


def test_calendar_end_date_and_cross_origin(client):
    assert (
        client.post(
            "/api/plans", json={"title": "报名,准备", "date": "2026-10-11", "notes": "检查材料"}
        ).status_code
        == 200
    )
    response = client.get("/api/plans/calendar")
    assert "DTSTART;VALUE=DATE:20261011" in response.text
    assert "DTEND;VALUE=DATE:20261012" in response.text
    assert "报名\\,准备" in response.text
    assert client.post("/api/plans", json={}, headers={"Origin": "https://other.example"}).status_code == 403
