"""
paperless-pay – FastAPI Hauptmodul

Zeigt Zahlungsinformationen und EPC-QR-Code für Paperless-Dokumente.
Authentifizierung ausschließlich via Cookie-Passthrough.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import settings
from paperless_client import build_payment_info, mark_as_paid
from qr import generate_dummy_svg, generate_qr_svg

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if settings.debug_upstream else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("paperless-pay")

# ---------------------------------------------------------------------------
# httpx client (lifespan-managed)
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    logger.info(
        "Started – PAPERLESS_BASE_URL=%s  APP_BASE_PATH=%s",
        settings.paperless_base_url,
        settings.app_base_path,
    )
    yield
    await app.state.client.aclose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

base = settings.app_base_path.rstrip("/")

app = FastAPI(
    title="paperless-pay",
    docs_url=f"{base}/docs",
    openapi_url=f"{base}/openapi.json",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.client


def _get_cookie(request: Request) -> str | None:
    return request.headers.get("cookie")


def _get_ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _pdf_url(doc_id: int) -> str:
    """URL für den PDF-Download/-Preview (geht an Paperless direkt via Browser)."""
    return f"{settings.public_url.rstrip('/')}/api/documents/{doc_id}/preview/"


# ---------------------------------------------------------------------------
# HTML-Template (inline – Phase 3 wird auf Jinja2 umgestellt wenn nötig)
# ---------------------------------------------------------------------------

def _render_page(
    info,
    qr_svg: str,
    pdf_url: str,
    error: str = "",
) -> str:
    """Rendert die Dokument-Zahlungsseite als HTML."""

    # Zahlungsfelder
    if info.bezahlt:
        status_badge = '<span class="badge badge--paid">BEZAHLT</span>'
        field_class = "field--disabled"
        button_html = ""
    else:
        status_badge = '<span class="badge badge--open">OFFEN</span>'
        field_class = ""
        button_html = f"""
        <form method="post" action="{base}/doc/{info.doc_id}/paid">
            <button type="submit" class="btn btn--pay">Als bezahlt markieren</button>
        </form>
        """

    missing_html = ""
    if not info.bezahlt and not info.is_payable:
        missing = ", ".join(info.missing_fields)
        missing_html = f'<div class="alert alert--warn">Fehlende Felder für QR-Code: {missing}</div>'

    error_html = f'<div class="alert alert--error">{error}</div>' if error else ""

    betrag_display = f"{info.betrag:.2f} EUR" if info.betrag else "–"

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{info.title} – paperless-pay</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
               background: #f4f5f7; color: #1a1a1a; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 1.5rem; }}
        h1 {{ font-size: 1.4rem; margin-bottom: 1rem; color: #333; }}
        .layout {{ display: grid; grid-template-columns: 380px 1fr; gap: 1.5rem; align-items: start; }}
        @media (max-width: 800px) {{ .layout {{ grid-template-columns: 1fr; }} }}

        /* Karte links */
        .card {{ background: #fff; border-radius: 8px; padding: 1.5rem;
                 box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
        .qr-wrap {{ text-align: center; margin-bottom: 1rem; }}
        .qr-wrap svg {{ max-width: 240px; height: auto; }}
        .badge {{ display: inline-block; padding: .25rem .75rem; border-radius: 4px;
                  font-size: .85rem; font-weight: 600; margin-bottom: 1rem; }}
        .badge--paid {{ background: #d4edda; color: #155724; }}
        .badge--open {{ background: #fff3cd; color: #856404; }}

        /* Felder */
        .fields {{ margin-bottom: 1rem; }}
        .field {{ margin-bottom: .75rem; }}
        .field label {{ display: block; font-size: .75rem; text-transform: uppercase;
                        color: #666; margin-bottom: .15rem; letter-spacing: .03em; }}
        .field .value {{ font-size: 1rem; font-weight: 500; }}
        .field--disabled .value {{ color: #aaa; text-decoration: line-through; }}

        /* Button */
        .btn {{ display: inline-block; padding: .6rem 1.2rem; border: none; border-radius: 6px;
                font-size: 1rem; cursor: pointer; font-weight: 600; }}
        .btn--pay {{ background: #17a2b8; color: #fff; width: 100%; }}
        .btn--pay:hover {{ background: #138496; }}

        /* Alerts */
        .alert {{ padding: .75rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: .9rem; }}
        .alert--warn {{ background: #fff3cd; color: #856404; }}
        .alert--error {{ background: #f8d7da; color: #721c24; }}

        /* PDF rechts */
        .pdf-frame {{ background: #fff; border-radius: 8px; overflow: hidden;
                      box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
        .pdf-frame iframe {{ width: 100%; height: 80vh; border: none; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{info.title}</h1>
        {error_html}
        <div class="layout">
            <div class="card">
                {status_badge}
                <div class="qr-wrap">
                    {qr_svg}
                </div>
                {missing_html}
                <div class="fields">
                    <div class="field {field_class}">
                        <label>Zahlungsempfänger</label>
                        <div class="value">{info.correspondent_name or '–'}</div>
                    </div>
                    <div class="field {field_class}">
                        <label>IBAN</label>
                        <div class="value">{info.iban or '–'}</div>
                    </div>
                    <div class="field {field_class}">
                        <label>BIC</label>
                        <div class="value">{info.bic or '–'}</div>
                    </div>
                    <div class="field {field_class}">
                        <label>Betrag</label>
                        <div class="value">{betrag_display}</div>
                    </div>
                    <div class="field {field_class}">
                        <label>Verwendungszweck</label>
                        <div class="value">{info.verwendungszweck or '–'}</div>
                    </div>
                </div>
                {button_html}
            </div>
            <div class="pdf-frame">
                <iframe src="{pdf_url}" title="Dokument-Vorschau"></iframe>
            </div>
        </div>
    </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get(f"{base}/healthz")
async def healthz():
    return {"ok": True}


@app.get(f"{base}/doc/{{doc_id}}", response_class=HTMLResponse)
async def get_document_page(doc_id: int, request: Request):
    """Zeigt die Zahlungsseite für ein Dokument."""
    client = _get_client(request)
    cookie = _get_cookie(request)
    ua = _get_ua(request)

    if not cookie:
        return HTMLResponse(
            content="<h1>Nicht eingeloggt</h1><p>Bitte zuerst bei Paperless einloggen.</p>",
            status_code=401,
        )

    try:
        info = await build_payment_info(client, doc_id, cookie, ua)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return HTMLResponse(
                content="<h1>Nicht authentifiziert</h1><p>Session abgelaufen? Bitte neu einloggen.</p>",
                status_code=401,
            )
        if status == 404:
            return HTMLResponse(
                content=f"<h1>Nicht gefunden</h1><p>Dokument {doc_id} existiert nicht.</p>",
                status_code=404,
            )
        logger.error("Upstream-Fehler: %s", exc)
        return HTMLResponse(
            content=f"<h1>Fehler</h1><p>Paperless meldet Status {status}.</p>",
            status_code=502,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Verbindungsfehler: %s", exc)
        return HTMLResponse(
            content="<h1>Verbindungsfehler</h1><p>Paperless nicht erreichbar.</p>",
            status_code=502,
        )

    # QR-Code generieren
    if info.bezahlt:
        qr_svg = generate_dummy_svg()
    elif info.is_payable:
        try:
            qr_svg = generate_qr_svg(info)
        except ValueError as exc:
            logger.warning("QR-Generierung fehlgeschlagen: %s", exc)
            qr_svg = ""
    else:
        qr_svg = ""

    pdf_url = _pdf_url(doc_id)
    html = _render_page(info, qr_svg, pdf_url)

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.post(f"{base}/doc/{{doc_id}}/paid")
async def mark_document_paid(doc_id: int, request: Request):
    """Markiert ein Dokument als bezahlt."""
    client = _get_client(request)
    cookie = _get_cookie(request)
    ua = _get_ua(request)

    if not cookie:
        return JSONResponse({"error": "Nicht eingeloggt"}, status_code=401)

    try:
        # Zuerst Current State laden um custom_fields zu haben
        info = await build_payment_info(client, doc_id, cookie, ua)

        if info.bezahlt:
            # Bereits bezahlt – einfach redirect
            return RedirectResponse(
                url=f"{base}/doc/{doc_id}",
                status_code=303,
            )

        await mark_as_paid(client, doc_id, info.raw_custom_fields, cookie, ua)

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return HTMLResponse(
                content="<h1>Nicht authentifiziert</h1><p>Session abgelaufen?</p>",
                status_code=401,
            )
        logger.error("Fehler beim Markieren: %s", exc)
        return HTMLResponse(
            content=f"<h1>Fehler</h1><p>Paperless meldet Status {status}.</p>",
            status_code=502,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Verbindungsfehler: %s", exc)
        return HTMLResponse(
            content="<h1>Verbindungsfehler</h1><p>Paperless nicht erreichbar.</p>",
            status_code=502,
        )

    return RedirectResponse(
        url=f"{base}/doc/{doc_id}",
        status_code=303,  # POST → GET redirect
    )
