import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

TEST_TOKEN = "test-service-token-0123456789"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SERVICE_TOKEN", TEST_TOKEN)
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())
