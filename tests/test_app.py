import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ratelimit import MemoryRateLimiter
from app.store import MemoryStore


@pytest.fixture
def client():
    app = create_app(store=MemoryStore(), rate_limiter=MemoryRateLimiter(limit=5, window_seconds=60))
    return TestClient(app, follow_redirects=False)


def shorten(client, url):
    return client.post("/api/shorten", json={"url": url})


def test_shorten_and_follow(client):
    response = shorten(client, "https://example.com/some/long/path?x=1")
    assert response.status_code == 201
    code = response.json()["code"]

    redirect = client.get(f"/{code}")
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com/some/long/path?x=1"


def test_clicks_are_counted(client):
    code = shorten(client, "https://example.com").json()["code"]
    client.get(f"/{code}")
    client.get(f"/{code}")

    stats = client.get(f"/api/stats/{code}").json()
    assert stats["clicks"] == 2


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com",
        "example.com",
        "",
        "https://example.com/" + "a" * 3000,
    ],
)
def test_rejects_unsafe_or_invalid_urls(client, url):
    assert shorten(client, url).status_code == 400


def test_unknown_code_is_404(client):
    assert client.get("/doesnotexist").status_code == 404
    assert client.get("/api/stats/doesnotexist").status_code == 404


def test_weird_codes_are_404(client):
    assert client.get("/api/stats/bad%20code").status_code == 404
    assert client.get("/ab").status_code == 404


def test_rate_limit(client):
    statuses = [shorten(client, "https://example.com").status_code for _ in range(6)]
    assert statuses[:5] == [201] * 5
    assert statuses[5] == 429


def test_security_headers(client):
    headers = client.get("/").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in headers["Content-Security-Policy"]


def test_health_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_static_files_only_whitelisted(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/..%2Fmain.py").status_code == 404
