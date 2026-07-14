from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_result_format() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["message"] == "success"
    assert body["data"]["status"] == "healthy"
