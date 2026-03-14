"""
paperless-pay – FastAPI main module

Displays payment information and EPC QR codes for Paperless documents.
Authentication exclusively via cookie passthrough.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import settings
from translations import get_locale, t
from iban import validate_iban
from models import PaymentInfo
from paperless_client import build_payment_info, mark_as_paid, update_custom_fields
from qr import generate_dummy_svg, generate_qr_svg
from remittance import render_remittance

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
        "Started – PAPERLESS_BASE_URL=%s  APP_BASE_PATH=%s  LANGUAGE=%s",
        settings.paperless_base_url,
        settings.app_base_path,
        settings.language,
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
    """URL for the PDF download/preview (served by Paperless via the browser)."""
    return f"{settings.public_url.rstrip('/')}/api/documents/{doc_id}/preview/"


# ---------------------------------------------------------------------------
# HTML template (inline)
# ---------------------------------------------------------------------------

def _iban_hint(iban: str) -> str:
    """Return an HTML snippet for IBAN validation feedback."""
    if not iban:
        return ""
    result = validate_iban(iban)
    if result.valid:
        return f'<div class="hint hint--ok">&#10003; {result.iban_pretty} ({result.country_code})</div>'
    return f'<div class="hint hint--err">&#10007; {result.error}</div>'


def _render_field_readonly(label: str, value: str, extra_html: str = "", css: str = "") -> str:
    """Single field in read-only mode."""
    return f"""<div class="field {css}">
        <label>{label}</label>
        <div class="value">{value or '–'}</div>
        {extra_html}
    </div>"""


def _render_field_editable(label: str, name: str, value: str, extra_html: str = "",
                           input_type: str = "text", step: str = "") -> str:
    """Single field in edit mode."""
    step_attr = f' step="{step}"' if step else ""
    return f"""<div class="field">
        <label>{label}</label>
        <input type="{input_type}" name="{name}" value="{value}"{step_attr} class="input">
        {extra_html}
    </div>"""


def _render_page(info: PaymentInfo, doc_id: int, error: str = "", save_ok: bool = False) -> str:
    """Render the payment page as HTML."""
    is_paid = info.paid is True
    editable = settings.enable_edit and not is_paid
    iban_result = validate_iban(info.iban) if info.iban else None
    remittance_display = render_remittance(info)
    public_base = settings.paperless_public_url or settings.paperless_base_url
    locale = get_locale()

    # --- Optional fields: only show when CF is configured ---
    show_bic = settings.cf_bic is not None

    status_badge = (
        '<span style="display:inline-block;padding:6px 18px;border-radius:12px;'
        'font-size:.95em;font-weight:600;'
        f'{"background:#e8f5e9;color:#2e7d32" if is_paid else "background:#fff3e0;color:#e65100"}'
        f'">{t("status.paid") if is_paid else t("status.open")}</span>'
    )

    edit_badge = (
        ' <span style="display:inline-block;padding:3px 10px;border-radius:8px;'
        'font-size:.75em;font-weight:600;background:#e3f2fd;color:#1565c0'
        f'">{t("status.edit")}</span>' if editable else ""
    )

    iban_display = info.iban or "–"
    iban_hint = ""
    if info.iban and iban_result:
        if iban_result.valid:
            iban_display = iban_result.iban_pretty
            iban_hint = f' <span style="color:#2e7d32" title="{t("msg.iban_valid")}">✓</span>'
        else:
            iban_hint = f' <span style="color:#c62828" title="{iban_result.error}">✗ {iban_result.error}</span>'

    # --- Field rendering ---
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
        amount_field = (
            f'<input type="text" name="amount" value="{info.amount or ""}" '
            f'style="width:100%;padding:6px;font-size:1.05em">'
        )
        remittance_field = (
            f'<input type="text" name="remittance" value="{info.remittance or ""}" '
            f'style="width:100%;padding:6px;font-size:1.05em">'
        )
    else:
        iban_field = f'<span style="font-family:monospace;font-size:1.05em">{iban_display}</span>{iban_hint}'
        bic_field = f'<span style="font-size:1.05em">{info.bic or "–"}</span>' if show_bic else ""
        amount_field = f'<span style="font-size:1.05em">{info.amount or "–"} EUR</span>'
        remittance_field = f'<span style="font-size:1.05em">{remittance_display or "–"}</span>'

    # --- BIC block (only when configured) ---
    bic_block = ""
    if show_bic:
        bic_block = f"""
            <div style="margin-bottom:14px">
              <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">{t("label.bic")}</div>
              {bic_field}
            </div>
        """

    # --- Error/Success banner ---
    banner = ""
    if error:
        banner = f'<div style="background:#ffebee;color:#c62828;padding:12px;border-radius:8px;margin-bottom:16px">{error}</div>'
    if save_ok:
        banner = f'<div style="background:#e8f5e9;color:#2e7d32;padding:12px;border-radius:8px;margin-bottom:16px">{t("msg.saved")}</div>'

    # --- Form wrapper (only in edit mode) ---
    form_open = f'<form method="post" action="{settings.app_base_path}/doc/{doc_id}/save">' if editable else ""
    form_close = ""
    if editable:
        form_close = f"""
            <button type="submit"
                    style="width:100%;padding:14px;background:#43a047;color:#fff;
                           border:none;border-radius:10px;font-size:1.1em;
                           font-weight:600;cursor:pointer;margin-top:10px">
              {t("btn.save")}
            </button>
          </form>
        """

    # --- PDF embed ---
    pdf_url = f"{public_base}/api/documents/{doc_id}/preview/"
    pdf_frame = (
        f'<iframe src="{pdf_url}" style="width:100%;height:100%;border:none;border-radius:12px">'
        f'</iframe>'
    )

    # --- Paid button ---
    paid_button = ""
    if not is_paid:
        paid_button = f"""
            <form method="post" action="{settings.app_base_path}/doc/{doc_id}/paid" style="margin-top:18px">
              <button type="submit"
                      style="width:100%;padding:14px;background:#ef6c00;color:#fff;
                             border:none;border-radius:10px;font-size:1.1em;
                             font-weight:600;cursor:pointer">
                {t("btn.mark_paid")}
              </button>
            </form>
        """

    # --- QR ---
    qr_svg = generate_qr_svg(info) if info.is_payable and not is_paid else generate_dummy_svg() if is_paid else ""

    html = f"""<!DOCTYPE html>
<html lang="{locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{info.title or t("page.payment")}</title>
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
      <h1 style="font-size:1.3em;margin-bottom:12px">{info.title or t("page.document")}</h1>
      {status_badge}{edit_badge}

      {banner}

      {form_open}

      <div style="margin:20px auto;text-align:center">{qr_svg}</div>

      <div style="{'opacity:.45;pointer-events:none' if is_paid else ''}">

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">{t("label.payee")}</div>
          <span style="font-size:1.05em;font-weight:600">{info.correspondent_name or "–"}</span>
        </div>

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">{t("label.iban")}</div>
          {iban_field}
        </div>

        {bic_block}

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">{t("label.amount")}</div>
          {amount_field}
        </div>

        <div style="margin-bottom:14px">
          <div style="font-size:.8em;color:#78909c;text-transform:uppercase;margin-bottom:2px">{t("label.remittance")}</div>
          {remittance_field}
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
    return {"ok": True, "enable_edit": settings.enable_edit, "language": settings.language}


@app.get(f"{base}/doc/{{doc_id}}", response_class=HTMLResponse)
async def get_document_page(doc_id: int, request: Request):
    """Display the payment page for a document."""
    client = _get_client(request)
    cookie = _get_cookie(request)
    ua = _get_ua(request)

    if not cookie:
        return HTMLResponse(
            content=f"<h1>{t('error.not_logged_in_title')}</h1><p>{t('error.not_logged_in_body')}</p>",
            status_code=401,
        )

    try:
        info = await build_payment_info(client, doc_id, cookie, ua)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return HTMLResponse(
                content=f"<h1>{t('error.not_authenticated_title')}</h1><p>{t('error.not_authenticated_body')}</p>",
                status_code=401,
            )
        if status == 404:
            return HTMLResponse(
                content=f"<h1>{t('error.not_found_title')}</h1><p>{t('error.not_found_body', doc_id=doc_id)}</p>",
                status_code=404,
            )
        logger.error("Upstream error: %s", exc)
        return HTMLResponse(
            content=f"<h1>{t('error.upstream_title')}</h1><p>{t('error.upstream_body', status=status)}</p>",
            status_code=502,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Connection error: %s", exc)
        return HTMLResponse(
            content=f"<h1>{t('error.connection_title')}</h1><p>{t('error.connection_body')}</p>",
            status_code=502,
        )

    html = _render_page(info, doc_id, error="", save_ok=False)
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.post(f"{base}/doc/{{doc_id}}/save")
async def save_document_fields(
    doc_id: int,
    request: Request,
    iban: str = Form(""),
    bic: str = Form(""),
    amount: str = Form(""),
    remittance: str = Form(""),
):
    """Save changed custom fields (experimental, only when ENABLE_EDIT=true)."""
    if not settings.enable_edit:
        return HTMLResponse(
            f"<h1>{t('error.edit_disabled_title')}</h1><p>{t('error.edit_disabled_body')}</p>",
            status_code=403,
        )

    client = _get_client(request)
    cookie = _get_cookie(request)
    ua = _get_ua(request)

    if not cookie:
        return JSONResponse({"error": t("error.not_logged_in_title")}, status_code=401)

    # Validate IBAN (if provided)
    iban_clean = iban.replace(" ", "").replace("-", "").upper()
    if iban_clean:
        iban_result = validate_iban(iban_clean)
        if not iban_result.valid:
            # Re-render page with error
            try:
                info = await build_payment_info(client, doc_id, cookie, ua)
            except Exception:
                return HTMLResponse(
                    f"<h1>{t('error.upstream_title')}</h1><p>{t('msg.iban_invalid')}: {iban_result.error}</p>",
                    status_code=400,
                )

            html = _render_page(info, doc_id, error=f"{t('msg.iban_invalid')}: {iban_result.error}")
            return HTMLResponse(content=html, status_code=400)

    # Build updates
    try:
        info = await build_payment_info(client, doc_id, cookie, ua)
    except httpx.HTTPStatusError as exc:
        return HTMLResponse(
            f"<h1>{t('error.upstream_title')}</h1><p>{t('error.upstream_body', status=exc.response.status_code)}</p>",
            status_code=502,
        )

    updates: dict[int, object] = {}
    if iban_clean != (info.iban or "").replace(" ", "").upper():
        updates[settings.cf_iban] = iban_clean
    if bic.strip() != (info.bic or ""):
        if settings.cf_bic:
            updates[settings.cf_bic] = bic.strip()
    if amount.strip():
        try:
            from decimal import Decimal
            new_amount = Decimal(amount.strip())
            if new_amount != info.amount:
                # Paperless expects the amount as a string in currency format
                updates[settings.cf_amount] = f"EUR{new_amount:.2f}"
        except Exception:
            pass
    if remittance.strip() != (info.remittance or ""):
        updates[settings.cf_remittance] = remittance.strip()

    if not updates:
        return RedirectResponse(url=f"{base}/doc/{doc_id}", status_code=303)

    try:
        await update_custom_fields(client, doc_id, info.raw_custom_fields, updates, cookie, ua)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return HTMLResponse(f"<h1>{t('error.not_authenticated_title')}</h1>", status_code=401)
        logger.error("Error saving fields: %s", exc)
        return HTMLResponse(
            f"<h1>{t('error.upstream_title')}</h1><p>{t('error.upstream_body', status=status)}</p>",
            status_code=502,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Connection error: %s", exc)
        return HTMLResponse(f"<h1>{t('error.connection_title')}</h1>", status_code=502)

    logger.info("✓ Document #%d – %d field(s) saved", doc_id, len(updates))
    return RedirectResponse(url=f"{base}/doc/{doc_id}", status_code=303)


@app.post(f"{base}/doc/{{doc_id}}/paid")
async def mark_document_paid(doc_id: int, request: Request):
    """Mark a document as paid."""
    client = _get_client(request)
    cookie = _get_cookie(request)
    ua = _get_ua(request)

    if not cookie:
        return JSONResponse({"error": t("error.not_logged_in_title")}, status_code=401)

    try:
        # Load current state to get custom_fields
        info = await build_payment_info(client, doc_id, cookie, ua)

        if info.paid:
            # Already paid – just redirect
            return RedirectResponse(
                url=f"{base}/doc/{doc_id}",
                status_code=303,
            )

        await mark_as_paid(client, doc_id, info.raw_custom_fields, cookie, ua)

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return HTMLResponse(
                content=f"<h1>{t('error.not_authenticated_title')}</h1><p>{t('error.not_authenticated_body')}</p>",
                status_code=401,
            )
        logger.error("Error marking as paid: %s", exc)
        return HTMLResponse(
            content=f"<h1>{t('error.upstream_title')}</h1><p>{t('error.upstream_body', status=status)}</p>",
            status_code=502,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Connection error: %s", exc)
        return HTMLResponse(
            content=f"<h1>{t('error.connection_title')}</h1><p>{t('error.connection_body')}</p>",
            status_code=502,
        )

    return RedirectResponse(
        url=f"{base}/doc/{doc_id}",
        status_code=303,  # POST → GET redirect
    )
