import pytest
from fastapi.testclient import TestClient

from stylecut.api import health


def test_health_all_green(client: TestClient) -> None:
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"db", "redis", "s3"}
    for check in body["checks"].values():
        assert check["ok"] is True
        assert check["latency_ms"] >= 0
        assert check["error"] is None


def test_health_unversioned_alias(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_health_degraded_when_a_dependency_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise ConnectionError("redis://user:secret@redis:6379 refused")

    monkeypatch.setitem(health.CHECKS, "redis", boom)
    res = client.get("/api/v1/health")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == {"ok": False, "latency_ms": None, "error": "ConnectionError"}
    assert body["checks"]["db"]["ok"] is True
    assert "secret" not in res.text


def test_errors_use_the_envelope(client: TestClient) -> None:
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "HTTP_404", "message": "Not Found", "hint": None}}

    res = client.get("/api/v1/jobs/not-a-uuid")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
