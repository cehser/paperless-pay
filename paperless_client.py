"""
paperless-pay – Paperless-ngx API Client (Cookie-Passthrough)
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from config import settings
from models import PaymentInfo

logger = logging.getLogger("paperless-pay.client")

# ---------------------------------------------------------------------------
# Header-Handling
# ---------------------------------------------------------------------------

def _extract_csrf_token(cookie: str | None) -> str | None:
    """Extrahiert das CSRF-Token aus dem Cookie-Header."""
    if not cookie:
        return None
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("csrftoken="):
            return part.split("=", 1)[1]
    return None


def build_upstream_headers(cookie: str | None, user_agent: str | None = None) -> dict[str, str]:
    """Baut Header für den Upstream-Request. Cookie 1:1, Accept immer JSON."""
    headers: dict[str, str] = {"accept": "application/json"}
    if cookie:
        headers["cookie"] = cookie
    if user_agent:
        headers["user-agent"] = user_agent
    return headers


def build_upstream_headers_write(cookie: str | None, user_agent: str | None = None) -> dict[str, str]:
    """Baut Header für schreibende Upstream-Requests (PATCH/POST). Inkl. CSRF-Token."""
    headers = build_upstream_headers(cookie, user_agent)
    csrf = _extract_csrf_token(cookie)
    if csrf:
        headers["X-CSRFToken"] = csrf
    return headers


# ---------------------------------------------------------------------------
# Custom-Field-Extraktion
# ---------------------------------------------------------------------------

def _extract_cf_value(custom_fields: list[dict], field_id: int) -> Any:
    """Extrahiert den Wert eines Custom Fields anhand seiner ID."""
    for cf in custom_fields:
        # Paperless gibt custom_fields als [{field: <id>, value: <val>}, ...]
        if cf.get("field") == field_id:
            return cf.get("value")
    return None


def _parse_decimal(value: Any) -> Decimal | None:
    """Parst einen Wert sicher in Decimal. Entfernt Währungspräfixe wie 'EUR'."""
    if value is None:
        return None
    try:
        raw = str(value).strip()
        # Währungspräfix entfernen (z.B. "EUR693.12" → "693.12")
        for prefix in ("EUR", "USD", "GBP", "CHF", "€", "$", "£"):
            if raw.upper().startswith(prefix):
                raw = raw[len(prefix):].strip()
                break
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        logger.warning("Konnte Betrag nicht parsen: %r", value)
        return None


def _parse_bool(value: Any) -> bool:
    """Parst einen Wert sicher in bool."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


# ---------------------------------------------------------------------------
# API Calls
# ---------------------------------------------------------------------------

async def fetch_document(
    client: httpx.AsyncClient,
    doc_id: int,
    cookie: str | None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """
    Lädt ein Dokument von Paperless.
    Gibt das rohe JSON-dict zurück.
    Raises httpx.HTTPStatusError bei Fehlern.
    """
    url = f"{settings.paperless_base_url.rstrip('/')}/api/documents/{doc_id}/"
    headers = build_upstream_headers(cookie, user_agent)

    logger.info("→ GET %s", url)
    resp = await client.get(url, headers=headers, follow_redirects=True)

    logger.info("← %s status=%d", url, resp.status_code)
    if settings.debug_upstream:
        logger.debug("← headers: %s", dict(resp.headers))

    resp.raise_for_status()
    return resp.json()


async def fetch_correspondent(
    client: httpx.AsyncClient,
    correspondent_id: int,
    cookie: str | None,
    user_agent: str | None = None,
) -> str:
    """Lädt den Namen eines Korrespondenten. Gibt '' bei Fehler zurück."""
    url = f"{settings.paperless_base_url.rstrip('/')}/api/correspondents/{correspondent_id}/"
    headers = build_upstream_headers(cookie, user_agent)

    logger.info("→ GET %s", url)
    try:
        resp = await client.get(url, headers=headers, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        return data.get("name", "")
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("Korrespondent %d nicht ladbar: %s", correspondent_id, exc)
        return ""


async def build_payment_info(
    client: httpx.AsyncClient,
    doc_id: int,
    cookie: str | None,
    user_agent: str | None = None,
) -> PaymentInfo:
    """
    Lädt Dokument + Korrespondent und baut PaymentInfo zusammen.
    Raises httpx.HTTPStatusError wenn das Dokument nicht geladen werden kann.
    """
    doc = await fetch_document(client, doc_id, cookie, user_agent)

    custom_fields = doc.get("custom_fields", [])
    correspondent_id = doc.get("correspondent")

    # Korrespondent-Name auflösen
    correspondent_name = ""
    if correspondent_id:
        correspondent_name = await fetch_correspondent(
            client, correspondent_id, cookie, user_agent
        )

    return PaymentInfo(
        doc_id=doc_id,
        title=doc.get("title", ""),
        correspondent_id=correspondent_id,
        correspondent_name=correspondent_name,
        iban=_extract_cf_value(custom_fields, settings.cf_iban) or "",
        bic=(_extract_cf_value(custom_fields, settings.cf_bic) or "") if settings.cf_bic else "",
        betrag=_parse_decimal(_extract_cf_value(custom_fields, settings.cf_betrag)),
        verwendungszweck=_extract_cf_value(custom_fields, settings.cf_verwendungszweck) or "",
        bezahlt=_parse_bool(_extract_cf_value(custom_fields, settings.cf_bezahlt)),
        raw_custom_fields=custom_fields,
    )


async def mark_as_paid(
    client: httpx.AsyncClient,
    doc_id: int,
    current_custom_fields: list[dict],
    cookie: str | None,
    user_agent: str | None = None,
) -> int:
    """
    Setzt das Custom Field 'Bezahlt' auf true via PATCH.
    Gibt den HTTP-Statuscode zurück.
    """
    url = f"{settings.paperless_base_url.rstrip('/')}/api/documents/{doc_id}/"
    headers = build_upstream_headers_write(cookie, user_agent)
    # alle anderen Felder beibehalten
    updated_fields = []
    bezahlt_found = False
    for cf in current_custom_fields:
        if cf.get("field") == settings.cf_bezahlt:
            updated_fields.append({"field": settings.cf_bezahlt, "value": True})
            bezahlt_found = True
        else:
            updated_fields.append(cf)

    # Falls das Feld noch gar nicht existiert, hinzufügen
    if not bezahlt_found:
        updated_fields.append({"field": settings.cf_bezahlt, "value": True})

    payload = {"custom_fields": updated_fields}

    logger.info("→ PATCH %s (mark as paid)", url)
    resp = await client.patch(
        url, headers=headers, json=payload, follow_redirects=True
    )

    logger.info("← %s status=%d", url, resp.status_code)
    if settings.debug_upstream:
        logger.debug("← body: %s", resp.text[:500])

    resp.raise_for_status()
    return resp.status_code


async def update_custom_fields(
    client: httpx.AsyncClient,
    doc_id: int,
    current_custom_fields: list[dict],
    updates: dict[int, Any],
    cookie: str | None,
    user_agent: str | None = None,
) -> int:
    """
    Aktualisiert beliebige Custom Fields via PATCH.

    Args:
        updates: Dict von {field_id: new_value}

    Gibt den HTTP-Statuscode zurück.
    """
    url = f"{settings.paperless_base_url.rstrip('/')}/api/documents/{doc_id}/"
    headers = build_upstream_headers_write(cookie, user_agent)

    updated_fields = []
    updated_ids: set[int] = set()

    for cf in current_custom_fields:
        fid = cf.get("field")
        if fid in updates:
            updated_fields.append({"field": fid, "value": updates[fid]})
            updated_ids.add(fid)
        else:
            updated_fields.append(cf)

    # Felder hinzufügen, die noch nicht existierten
    for fid, val in updates.items():
        if fid not in updated_ids:
            updated_fields.append({"field": fid, "value": val})

    payload = {"custom_fields": updated_fields}

    logger.info("→ PATCH %s (update fields: %s)", url, list(updates.keys()))
    resp = await client.patch(
        url, headers=headers, json=payload, follow_redirects=True
    )

    logger.info("← %s status=%d", url, resp.status_code)
    if settings.debug_upstream:
        logger.debug("← body: %s", resp.text[:500])

    resp.raise_for_status()
    return resp.status_code
