import os
import re
import secrets
import string
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from app.ratelimit import build_rate_limiter
from app.store import build_store

ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 7
CODE_PATTERN = re.compile(r"^[A-Za-z0-9]{4,16}$")
MAX_URL_LENGTH = 2048
STATIC_DIR = Path(__file__).parent / "static"


class ShortenRequest(BaseModel):
    url: str


def validate_url(url):
    """Accept only absolute http(s) URLs. Rejects javascript:, data:, file: etc."""
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise HTTPException(status_code=400, detail="URL is empty or too long")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(status_code=400, detail="Only http:// and https:// URLs are allowed")
    return url


def create_app(store=None, rate_limiter=None):
    app = FastAPI(title="URL Shortener")
    app.state.store = store or build_store(os.getenv("DATABASE_URL"))
    app.state.rate_limiter = rate_limiter or build_rate_limiter(
        os.getenv("REDIS_URL"), int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
    )
    base_url = os.getenv("BASE_URL", "").rstrip("/")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.get("/healthz")
    def healthz():
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        """Readiness: the database answers, so this pod can take traffic."""
        try:
            app.state.store.ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {"status": "ready"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/static/{name}", include_in_schema=False)
    def static(name: str):
        if name not in ("app.js", "style.css"):
            raise HTTPException(status_code=404)
        return FileResponse(STATIC_DIR / name)

    @app.post("/api/shorten", status_code=201)
    def shorten(body: ShortenRequest, request: Request):
        client = request.client.host if request.client else "unknown"
        if not app.state.rate_limiter.allow(client):
            raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")

        url = validate_url(body.url)
        for _ in range(5):
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            if app.state.store.save(code, url):
                root = base_url or str(request.base_url).rstrip("/")
                return {"code": code, "short_url": f"{root}/{code}", "url": url}
        raise HTTPException(status_code=500, detail="Could not generate a unique code")

    @app.get("/api/stats/{code}")
    def stats(code: str):
        result = app.state.store.stats(code) if CODE_PATTERN.match(code) else None
        if result is None:
            raise HTTPException(status_code=404, detail="Unknown code")
        return result

    @app.get("/{code}", include_in_schema=False)
    def follow(code: str):
        url = app.state.store.hit(code) if CODE_PATTERN.match(code) else None
        if url is None:
            raise HTTPException(status_code=404, detail="Unknown code")
        return RedirectResponse(url, status_code=307)

    return app


app = create_app()
