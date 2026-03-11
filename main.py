"""
paperless-pay – FastAPI Hauptmodul

Zeigt Zahlungsinformationen und EPC-QR-Code für Paperless-Dokumente.
Authentifizierung ausschließlich via Cookie-Passthrough.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import settings
from iban import validate_iban
from paperless_client import build_payment_info, mark_as_paid, update_custom_fields
from qr import generate_dummy_svg, generate_qr_svg
from verwendungszweck import render_verwendungszweck

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

def _iban_hint(iban: str) -> str:
    """Gibt ein HTML-Snippet für die IBAN-Validierung zurück."""
    if not iban:
        return ""
    result = validate_iban(iban)
    if result.valid:
        return f'<div class="hint hint--ok">&#10003; {result.iban_pretty} ({result.country_code})</div>'
    return f'<div class="hint hint--err">&#10007; {result.error}</div>'


def _render_field_readonly(label: str, value: str, extra_html: str = "", css: str = "") -> str:
    """Einzelnes Feld im Readonly-Modus."""
    return f"""<div class="field {css}">
        <label>{label}</label>
        <div class="value">{value or '–'}</div>
        {extra_html}
    </div>"""


def _render_field_editable(label: str, name: str, value: str, extra_html: str = "",
                           input_type: str = "text", step: str = "") -> str:
    """Einzelnes Feld im Edit-Modus."""
    step_attr = f' step="{step}"' if step else ""
    return f"""<div class="field">
        <label>{label}</label>
        <input type="{input_type}" name="{name}" value="{value}"{step_attr} class="input">
        {extra_html}
    </div>"""


def _render_page(
    info,
    qr_svg: str,
    pdf_url: str,
    error: str = "",
    success: str = "",
) -> str:
    """Rendert die Dokument-Zahlungsseite als HTML."""

    editable = settings.enable_edit and not info.bezahlt

    # Verwendungszweck mit Template rendern
    verwendungszweck_display = render_verwendungszweck(info)

    # IBAN-Validierung
    iban_hint = _iban_hint(info.iban)

    # Zahlungsfelder
    if info.bezahlt:
        status_badge = '<span class="badge badge--paid">BEZAHLT</span>'
        field_class = "field--disabled"
        pay_button = ""
    else:
        status_badge = '<span class="badge badge--open">OFFEN</span>'
        field_class = ""
        pay_button = f"""
        <form method="post" action="{base}/doc/{info.doc_id}/paid" class="mt">
            <button type="submit" class="btn btn--pay">Als bezahlt markieren</button>
        </form>"""

    missing_html = ""
    if not info.bezahlt and not info.is_payable:
        missing = ", ".join(info.missing_fields)
        missing_html = f'<div class="alert alert--warn">Fehlende Felder für QR-Code: {missing}</div>'

    error_html = f'<div class="alert alert--error">{error}</div>' if error else ""
    success_html = f'<div class="alert alert--ok">{success}</div>' if success else ""

    betrag_raw = f"{info.betrag:.2f}" if info.betrag else ""
    betrag_display = f"{betrag_raw} EUR" if betrag_raw else "–"

    # Felder rendern (readonly vs. editable)
    if editable:
        fields_html = "".join([
            _render_field_readonly("Zahlungsempfänger", info.correspondent_name or "–"),
            _render_field_editable("IBAN", "iban", info.iban, extra_html=iban_hint),
            _render_field_editable("BIC", "bic", info.bic),
            _render_field_editable("Betrag (EUR)", "betrag", betrag_raw, input_type="number", step="0.01"),
            _render_field_editable("Verwendungszweck", "verwendungszweck", info.verwendungszweck),
        ])
        edit_form_open = f'<form method="post" action="{base}/doc/{info.doc_id}/save">'
        save_button = '<button type="submit" class="btn btn--save">Speichern</button>'
        edit_form_close = "</form>"
        edit_badge = '<span class="badge badge--edit">EDIT</span> '
    else:
        fields_html = "".join([
            _render_field_readonly("Zahlungsempfänger", info.correspondent_name or "–", css=field_class),
            _render_field_readonly("IBAN", info.iban or "–", extra_html=iban_hint, css=field_class),
            _render_field_readonly("BIC", info.bic or "–", css=field_class),
            _render_field_readonly("Betrag", betrag_display, css=field_class),
            _render_field_readonly("Verwendungszweck", verwendungszweck_display or "–", css=field_class),
        ])
        edit_form_open = ""
        save_button = ""
        edit_form_close = ""
        edit_badge = ""

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

        .card {{ background: #fff; border-radius: 8px; padding: 1.5rem;
                 box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
        .qr-wrap {{ text-align: center; margin-bottom: 1rem; }}
        .qr-wrap svg {{ max-width: 240px; height: auto; }}
        .badge {{ display: inline-block; padding: .25rem .75rem; border-radius: 4px;
                  font-size: .85rem; font-weight: 600; margin-bottom: .5rem; }}
        .badge--paid {{ background: #d4edda; color: #155724; }}
        .badge--open {{ background: #fff3cd; color: #856404; }}
        .badge--edit {{ background: #cce5ff; color: #004085; }}

        .fields {{ margin-bottom: 1rem; }}
        .field {{ margin-bottom: .75rem; }}
        .field label {{ display: block; font-size: .75rem; text-transform: uppercase;
                        color: #666; margin-bottom: .15rem; letter-spacing: .03em; }}
        .field .value {{ font-size: 1rem; font-weight: 500; }}
        .field--disabled .value {{ color: #aaa; text-decoration: line-through; }}

        .input {{ width: 100%; padding: .45rem .6rem; font-size: 1rem; font-weight: 500;
                  border: 1px solid #cbd5e0; border-radius: 4px; font-family: inherit; }}
        .input:focus {{ outline: none; border-color: #17a2b8; box-shadow: 0 0 0 2px rgba(23,162,184,.2); }}

        .hint {{ font-size: .8rem; margin-top: .2rem; }}
        .hint--ok {{ color: #155724; }}
        .hint--err {{ color: #c0392b; }}

        .btn {{ display: inline-block; padding: .6rem 1.2rem; border: none; border-radius: 6px;
                font-size: 1rem; cursor: pointer; font-weight: 600; }}
        .btn--pay {{ background: #17a2b8; color: #fff; width: 100%; }}
        .btn--pay:hover {{ background: #138496; }}
        .btn--save {{ background: #28a745; color: #fff; width: 100%; margin-bottom: .5rem; }}
        .btn--save:hover {{ background: #218838; }}
        .mt {{ margin-top: .5rem; }}

        .alert {{ padding: .75rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: .9rem; }}
        .alert--warn {{ background: #fff3cd; color: #856404; }}
        .alert--error {{ background: #f8d7da; color: #721c24; }}
        .alert--ok {{ background: #d4edda; color: #155724; }}

        .pdf-frame {{ background: #fff; border-radius: 8px; overflow: hidden;
                      box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
        .pdf-frame iframe {{ width: 100%; height: 80vh; border: none; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{info.title}</h1>
        {error_html}{success_html}
        <div class="layout">
            <div class="card">
                {edit_badge}{status_badge}
                <div class="qr-wrap">
                    {qr_svg}
                </div>
                {missing_html}
                {edit_form_open}
                <div class="fields">
                    {fields_html}
                </div>
                {save_button}
                {edit_form_close}
                {pay_button}
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
    return {"ok": True, "enable_edit": settings.enable_edit}


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


@app.post(f"{base}/doc/{{doc_id}}/save")
async def save_document_fields(
    doc_id: int,
    request: Request,
    iban: str = Form(""),
    bic: str = Form(""),
    betrag: str = Form(""),
    verwendungszweck: str = Form(""),
):
    """Speichert geänderte Custom Fields (experimentell, nur wenn ENABLE_EDIT=true)."""
    if not settings.enable_edit:
        return HTMLResponse("<h1>Nicht erlaubt</h1><p>Feldbearbeitung ist deaktiviert.</p>", status_code=403)

    client = _get_client(request)
    cookie = _get_cookie(request)
    ua = _get_ua(request)

    if not cookie:
        return JSONResponse({"error": "Nicht eingeloggt"}, status_code=401)

    # IBAN validieren (wenn angegeben)
    iban_clean = iban.replace(" ", "").replace("-", "").upper()
    if iban_clean:
        iban_result = validate_iban(iban_clean)
        if not iban_result.valid:
            # Seite mit Fehler neu rendern
            try:
                info = await build_payment_info(client, doc_id, cookie, ua)
            except Exception:
                return HTMLResponse(f"<h1>Fehler</h1><p>IBAN ungültig: {iban_result.error}</p>", status_code=400)

            qr_svg = ""
            if info.is_payable:
                try:
                    qr_svg = generate_qr_svg(info)
                except ValueError:
                    pass
            pdf_url = _pdf_url(doc_id)
            html = _render_page(info, qr_svg, pdf_url, error=f"IBAN ungültig: {iban_result.error}")
            return HTMLResponse(content=html, status_code=400)

    # Updates zusammenbauen
    try:
        info = await build_payment_info(client, doc_id, cookie, ua)
    except httpx.HTTPStatusError as exc:
        return HTMLResponse(f"<h1>Fehler</h1><p>Status {exc.response.status_code}</p>", status_code=502)

    updates: dict[int, object] = {}
    if iban_clean != (info.iban or "").replace(" ", "").upper():
        updates[settings.cf_iban] = iban_clean
    if bic.strip() != (info.bic or ""):
        if settings.cf_bic:
            updates[settings.cf_bic] = bic.strip()
    if betrag.strip():
        try:
            from decimal import Decimal
            new_betrag = Decimal(betrag.strip())
            if new_betrag != info.betrag:
                # Paperless erwartet den Betrag als String im Currency-Format
                updates[settings.cf_betrag] = f"EUR{new_betrag:.2f}"
        except Exception:
            pass
    if verwendungszweck.strip() != (info.verwendungszweck or ""):
        updates[settings.cf_verwendungszweck] = verwendungszweck.strip()

    if not updates:
        return RedirectResponse(url=f"{base}/doc/{doc_id}", status_code=303)

    try:
        await update_custom_fields(client, doc_id, info.raw_custom_fields, updates, cookie, ua)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return HTMLResponse("<h1>Nicht authentifiziert</h1>", status_code=401)
        logger.error("Fehler beim Speichern: %s", exc)
        return HTMLResponse(f"<h1>Fehler</h1><p>Paperless meldet Status {status}.</p>", status_code=502)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Verbindungsfehler: %s", exc)
        return HTMLResponse("<h1>Verbindungsfehler</h1>", status_code=502)

    logger.info("✓ Dokument #%d – %d Feld(er) gespeichert", doc_id, len(updates))
    return RedirectResponse(url=f"{base}/doc/{doc_id}", status_code=303)


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
