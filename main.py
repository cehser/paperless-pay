"""
cookie-passthrough-check – Super-minimaler PoC
Testet, ob Cookie-Passthrough zur paperless-ngx API funktioniert.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Config (ENV-only)
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    paperless_base_url: str  # z.B. http://paperless:8000
    app_base_path: str = "/qr-poc"
    debug_upstream: bool = False  # DEBUG_UPSTREAM=1

    model_config = {"env_file": None}  # rein ENV, kein .env file


settings = Settings()  # type: ignore[call-arg]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if settings.debug_upstream else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("cookie-passthrough")

# ---------------------------------------------------------------------------
# Shared httpx client (async, connection-pooled)
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    logger.info(
        "Started – PAPERLESS_BASE_URL=%s  APP_BASE_PATH=%s  DEBUG_UPSTREAM=%s",
        settings.paperless_base_url,
        settings.app_base_path,
        settings.debug_upstream,
    )
    yield
    await app.state.client.aclose()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

base = settings.app_base_path.rstrip("/")

app = FastAPI(
    title="cookie-passthrough-check",
    docs_url=f"{base}/docs",
    openapi_url=f"{base}/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Headers die wir 1:1 forwarden (lowercase)
_FORWARD_HEADERS = {"cookie", "user-agent", "accept"}


def _build_upstream_headers(request: Request) -> dict[str, str]:
    """Nimmt relevante Header aus dem eingehenden Request."""
    out: dict[str, str] = {}
    for key in _FORWARD_HEADERS:
        val = request.headers.get(key)
        if val is not None:
            out[key] = val
    return out


def _preview(body: str, max_len: int = 500) -> str:
    return body[:max_len] + ("…" if len(body) > max_len else "")


def _safe_log_headers(headers: httpx.Headers) -> dict[str, str]:
    """Header-Subset fürs Logging / Response (ohne sensitive Werte)."""
    keep = {"content-type", "content-length", "server", "x-request-id",
            "x-content-type-options", "vary"}
    return {k: v for k, v in headers.items() if k in keep}


async def _upstream_get(
    request: Request, path: str
) -> dict[str, Any]:
    """GET gegen Paperless, gibt ein einheitliches Result-dict zurück."""
    client: httpx.AsyncClient = request.app.state.client
    url = settings.paperless_base_url.rstrip("/") + path
    fwd_headers = _build_upstream_headers(request)

    # Cookie-Wert NICHT loggen
    logger.info("→ Upstream GET %s", url)

    try:
        resp = await client.get(url, headers=fwd_headers)
    except httpx.ConnectError as exc:
        logger.error("Connection error to %s: %s", url, exc)
        return {
            "upstream_url": url,
            "upstream_status": 0,
            "error": f"Connection error: {exc}",
            "authenticated_guess": False,
            "upstream_headers_subset": {},
            "upstream_body_preview": "",
        }
    except httpx.TimeoutException as exc:
        logger.error("Timeout reaching %s: %s", url, exc)
        return {
            "upstream_url": url,
            "upstream_status": 0,
            "error": f"Timeout: {exc}",
            "authenticated_guess": False,
            "upstream_headers_subset": {},
            "upstream_body_preview": "",
        }

    body_text = resp.text
    headers_subset = _safe_log_headers(resp.headers)

    logger.info("← Upstream %s  status=%d", url, resp.status_code)
    if settings.debug_upstream:
        logger.debug("← Upstream headers: %s", dict(resp.headers))

    result: dict[str, Any] = {
        "upstream_url": url,
        "upstream_status": resp.status_code,
        "authenticated_guess": resp.status_code == 200,
        "upstream_headers_subset": headers_subset,
        "upstream_body_preview": _preview(body_text),
    }

    if settings.debug_upstream:
        result["upstream_all_headers"] = dict(resp.headers)

    return result

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get(f"{base}/healthz")
async def healthz():
    return {"ok": True}


@app.get(f"{base}/probe")
async def probe(request: Request):
    """
    Probe: GET /api/ bei Paperless mit Cookie-Passthrough.
    Zeigt ob die Session-Cookies akzeptiert werden.
    """
    result = await _upstream_get(request, "/api/")

    status = result["upstream_status"]
    if status == 200:
        result["verdict"] = "OK (authenticated)"
    elif status in (401, 403):
        result["verdict"] = "NOT AUTHENTICATED"
    elif status == 0:
        result["verdict"] = "UPSTREAM UNREACHABLE"
    else:
        result["verdict"] = f"UNEXPECTED STATUS {status}"

    return JSONResponse(
        content=result,
        status_code=200,
        headers={"Cache-Control": "no-store"},
    )


@app.get(f"{base}/doc/{{doc_id}}")
async def get_document(doc_id: int, request: Request):
    """
    Ruft /api/documents/{id}/ bei Paperless auf.
    Gibt upstream_status als HTTP-Status weiter (soweit sinnvoll).
    """
    result = await _upstream_get(request, f"/api/documents/{doc_id}/")

    upstream_status = result["upstream_status"]

    # Sinnvolle Status-Codes weiterreichen
    if upstream_status in (200, 401, 403, 404):
        http_status = upstream_status
    elif upstream_status == 0:
        http_status = 502
    else:
        http_status = upstream_status if 400 <= upstream_status < 600 else 502

    if upstream_status == 200:
        result["verdict"] = "OK (authenticated)"
    elif upstream_status in (401, 403):
        result["verdict"] = "NOT AUTHENTICATED"
    else:
        result["verdict"] = f"UPSTREAM STATUS {upstream_status}"

    return JSONResponse(
        content=result,
        status_code=http_status,
        headers={"Cache-Control": "no-store"},
    )
