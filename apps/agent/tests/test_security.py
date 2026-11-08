from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN


def test_rejects_missing_token(client: TestClient) -> None:
    assert client.get("/whoami").status_code == 401


def test_rejects_wrong_token(client: TestClient) -> None:
    res = client.get("/whoami", headers={"X-Service-Token": "nope"})
    assert res.status_code == 401


def test_accepts_correct_token(client: TestClient) -> None:
    res = client.get("/whoami", headers={"X-Service-Token": TEST_TOKEN})
    assert res.status_code == 200
