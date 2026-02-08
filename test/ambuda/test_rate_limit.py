"""Smoke test that rate limiting returns 429 when limits are exceeded."""

import pytest

import config
from ambuda import create_app
from test.ambuda.conftest import initialize_test_db


@pytest.fixture()
def rate_limited_app(s3_mocks, monkeypatch):
    monkeypatch.setattr(config.UnitTestConfig, "RATELIMIT_ENABLED", True)
    monkeypatch.setattr(config.UnitTestConfig, "RATELIMIT_STORAGE_URI", "memory://")

    app = create_app("testing")
    with app.app_context():
        initialize_test_db()
        yield app


@pytest.fixture()
def rate_limited_client(rate_limited_app):
    return rate_limited_app.test_client()


def test_sign_in_rate_limit(rate_limited_client):
    for _ in range(10):
        resp = rate_limited_client.post(
            "/sign-in",
            data={"username": "nobody", "password": "badpassword"},
        )
        assert resp.status_code != 429

    resp = rate_limited_client.post(
        "/sign-in",
        data={"username": "nobody", "password": "badpassword"},
    )
    assert resp.status_code == 429


def test_get_request_not_limited(rate_limited_client):
    for _ in range(15):
        resp = rate_limited_client.get("/sign-in")
        assert resp.status_code == 200
