from fastapi.testclient import TestClient

from app.api.errors import BusinessException, ErrorCode
from app.api.responses import Result
from app.main import app

client = TestClient(app)


def test_business_exception_returns_result_with_http_200() -> None:
    @app.get("/_test/raise-business-error")
    async def _raise() -> Result[None]:
        raise BusinessException(ErrorCode.INTERNAL_ERROR, "test error")

    response = client.get("/_test/raise-business-error")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 500
    assert body["message"] == "test error"
    assert body["data"] is None


def test_404_returns_result_with_http_200() -> None:
    response = client.get("/_test/nonexistent-endpoint")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 404
    assert body["data"] is None
