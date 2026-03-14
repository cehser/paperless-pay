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


def _render_page(info: PaymentInfo, doc_id: int, error: str = "", save_ok: bool = False) -> str:
    """Render the payment page as HTML."""
    is_paid = info.bezahlt is True
    editable = settings.enable_edit and not is_paid
    iban_result = validate_iban(info.iban) if info.iban else None
    verwendungszweck_display = render_verwendungszweck(info)
    public_base = settings.paperless_public_url or settings.paperless_base_url

    # --- Optionale Felder: nur anzeigen wenn CF konfiguriert ---
    show_bic = settings.cf_bic is not None

    status_badge = (
        '<span style="display:inline-block;padding:6px 18px;border-radius:12px;'
        'font-size:.95em;font-weight:600;'
        f'{"background:#e8f5e9;color:#2e7d32" if is_paid else "background:#fff3e0;color:#e65100"}'
        f'">{"BEZAHLT" if is_paid else "OFFEN"}</span>'
    )

    edit_badge = (
        ' <span style="display:inline-block;padding:3px 10px;border-radius:8px;'
        'font-size:.75em;font-weight:600;background:#e3f2fd;color:#1565c0'
        '">EDIT</span>' if editable else ""
    )

    iban_display = info.iban or "–"
    iban_hint = ""
    if info.iban and iban_result:
        if iban_result.valid:
            iban_display = iban_result.formatted
            iban_hint = ' <span style="color:#2e7d32" title="IBAN gültig">✓</span>'
        else:
            iban_hint = f' <span style="color:#c62828" title="{iban_result.error}">✗ {iban_result.error}</span>'

    # --- Felder-Rendering ---
    if editable:
        iban_field = (
            f'<input type="text" name="iban" value="{info.iban or ""}" '
            f'style="width:100%;padding:6px;font-size:1.05em;font-family:monospace">'
            f'{iban_hint}'
        )
        bic_field = (
            f'<input type="text" name="bic" value="{info.bic or ""}" '
            f'style="width:100%;padding:6px;font-size:1.05em">'
        ) if show_bic else ""
        betrag_field = (
            f'<input type="text" name="betrag" value="{info.betrag or ""}" '
            f'style="width:100%;padding:6px;font-size:1.05em">'
        )
        verwendungszweck_field = (
            f'<input type="text" name="verwendungszweck" value="{info.verwendungszweck or ""}" '
            f'style="width:100%;padding:6px;font-size:1.05em">'
        )
    else:
        iban_field = f'<span style="font-family:monospace;font-size:1.05em">{iban_display}</span>{iban_hint}'
        bic_field = f'<span style="font-size:1.05em">{info.bic or "–"}</span>' if show_bic else ""
        betrag_field = f'<span style="font-size:1.05em">{info.betrag or "–"} EUR</span>'
        verwendungszweck_field = f'<span style="font-size:1.05em">{verwendungszweck_display or "–"}</span>'

    # --- BIC-Block (nur wenn konfiguriert) ---
    bic_block = ""
    if show_bic:
        bic_block = f"""
            <div style="margin-bottom:14px">
              <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">BIC</div>
              {bic_field}
            </div>
        """

    # --- Error/Success Banner ---
    banner = ""
    if error:
        banner = f'<div style="background:#ffebee;color:#c62828;padding:12px;border-radius:8px;margin-bottom:16px">{error}</div>'
    if save_ok:
        banner = '<div style="background:#e8f5e9;color:#2e7d32;padding:12px;border-radius:8px;margin-bottom:16px">Gespeichert ✓</div>'

    # --- Form wrapper (nur im Edit-Modus) ---
    form_open = f'<form method="post" action="{settings.app_base_path}/doc/{doc_id}/save">' if editable else ""
    form_close = ""
    if editable:
        form_close = """
            <button type="submit"
                    style="width:100%;padding:14px;background:#43a047;color:#fff;
                           border:none;border-radius:10px;font-size:1.1em;
                           font-weight:600;cursor:pointer;margin-top:10px">
              Speichern
            </button>
          </form>
        """

    # --- PDF embed ---
    pdf_url = f"{public_base}/api/documents/{doc_id}/preview/"
    pdf_frame = (
        f'<iframe src="{pdf_url}" style="width:100%;height:100%;border:none;border-radius:12px">'
        f'</iframe>'
    )

    # --- Paid-Button ---
    paid_button = ""
    if not is_paid:
        paid_button = f"""
            <form method="post" action="{settings.app_base_path}/doc/{doc_id}/paid" style="margin-top:18px">
              <button type="submit"
                      style="width:100%;padding:14px;background:#ef6c00;color:#fff;
                             border:none;border-radius:10px;font-size:1.1em;
                             font-weight:600;cursor:pointer">
                Als bezahlt markieren
              </button>
            </form>
        """

    # --- QR ---
    qr_svg = generate_epc_qr_svg(info) if not is_paid else generate_dummy_qr_svg()

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{info.title or "Zahlung"}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
           background:#f5f5f5; color:#263238; }}
    .container {{ display:flex; height:100vh; }}
    .left {{ width:420px; min-width:380px; padding:28px; overflow-y:auto;
             background:#fff; box-shadow:2px 0 12px rgba(0,0,0,.06); }}
    .right {{ flex:1; padding:16px; }}
    @media (max-width:900px) {{
      .container {{ flex-direction:column; height:auto; }}
      .left {{ width:100%; min-width:auto; }}
      .right {{ height:70vh; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="left">
      <h1 style="font-size:1.3em;margin-bottom:12px">{info.title or "Dokument"}</h1>
      {status_badge}{edit_badge}

      {banner}

      {form_open}

      <div style="margin:20px auto;text-align:center">{qr_svg}</div>

      <div style="{'opacity:.45;pointer-events:none' if is_paid else ''}">

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">Zahlungsempfänger</div>
          <span style="font-size:1.05em;font-weight:600">{info.correspondent or "–"}</span>
        </div>

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">IBAN</div>
          {iban_field}
        </div>

        {bic_block}

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">Betrag</div>
          {betrag_field}
        </div>

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">Verwendungszweck</div>
          {verwendungszweck_field}
        </div>

      </div>

      {form_close}
      {paid_button}
    </div>
    <div class="right">
      {pdf_frame}
    </div>
  </div>
</body>
</html>"""
    return html


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
    html = _render_page(info, doc_id, error="", save_ok=False)

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
            html = _render_page(info, doc_id, error=f"IBAN ungültig: {iban_result.error}")
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
