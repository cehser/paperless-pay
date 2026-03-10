"""
paperless-pay – Link-Worker

Pollt die Paperless-API und setzt für alle passenden Dokumente
(z.B. Rechnungen) einen Pay-Link in ein URL-Custom-Field.

Auth via API-Token (headless, kein Cookie).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

class WorkerSettings(BaseSettings):
    """Einstellungen für den Link-Worker (ausschließlich aus ENV)."""

    # --- Paperless upstream --------------------------------------------------
    paperless_base_url: str = "http://paperless:8000"
    paperless_token: str  # API-Token (Pflicht)

    # --- custom field für den Pay-Link ---------------------------------------
    cf_link: int  # Custom-Field-ID (Typ: URL)

    # --- öffentliche URL von paperless-pay -----------------------------------
    pay_public_url: str  # z.B. https://docs.cehser.de/pay

    # --- Filter (Paperless API query params) ---------------------------------
    # Frei konfigurierbarer API-Filter, z.B.:
    #   document_type__id=3           → nur Rechnungen
    #   tags__id__all=5               → nur bestimmter Tag
    #   tags__id__all=5&correspondent__id=2  → Tag + Korrespondent
    worker_filter: str = ""

    # --- Timing --------------------------------------------------------------
    worker_interval: int = 60  # Sekunden zwischen Durchläufen

    model_config = {"env_file": None}


settings = WorkerSettings()  # type: ignore[call-arg]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("paperless-pay.worker")

# ---------------------------------------------------------------------------
# HTTP-Helpers
# ---------------------------------------------------------------------------

def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Token {settings.paperless_token}",
        "Accept": "application/json",
    }


def _build_pay_url(doc_id: int) -> str:
    base = settings.pay_public_url.rstrip("/")
    return f"{base}/doc/{doc_id}"


# ---------------------------------------------------------------------------
# Core-Logik
# ---------------------------------------------------------------------------

async def _fetch_documents(client: httpx.AsyncClient) -> list[dict]:
    """
    Holt *alle* Dokumente, die dem konfigurierten Filter entsprechen.
    Paginiert automatisch.
    """
    url = f"{settings.paperless_base_url}/api/documents/"
    params = {"page_size": "100"}

    # Worker-Filter als zusätzliche Query-Parameter einfügen
    if settings.worker_filter:
        for pair in settings.worker_filter.split("&"):
            if "=" in pair:
                key, val = pair.split("=", 1)
                params[key.strip()] = val.strip()

    all_docs: list[dict] = []
    page = 1

    while True:
        params["page"] = str(page)
        resp = await client.get(url, params=params, headers=_auth_headers(),
                                follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        all_docs.extend(results)

        if data.get("next") is None:
            break
        page += 1

    return all_docs


def _has_link(doc: dict) -> bool:
    """Prüft ob das Dokument bereits einen Pay-Link im CF_LINK-Feld hat."""
    for cf in doc.get("custom_fields", []):
        if cf.get("field") == settings.cf_link:
            val = cf.get("value")
            return val is not None and val != ""
    return False


def _build_patch_payload(doc: dict, link: str) -> dict:
    """
    Baut das PATCH-Payload für custom_fields.
    Bestehende Custom Fields beibehalten, CF_LINK setzen/überschreiben.
    """
    existing: list[dict] = doc.get("custom_fields", [])

    # Bestehende Felder übernehmen, CF_LINK ersetzen falls vorhanden
    new_fields = [cf for cf in existing if cf.get("field") != settings.cf_link]
    new_fields.append({"field": settings.cf_link, "value": link})

    return {"custom_fields": new_fields}


async def _patch_document(client: httpx.AsyncClient, doc_id: int, payload: dict) -> None:
    url = f"{settings.paperless_base_url}/api/documents/{doc_id}/"
    resp = await client.patch(url, json=payload, headers=_auth_headers(),
                              follow_redirects=True)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------

async def run_once(client: httpx.AsyncClient) -> int:
    """Ein Durchlauf: Dokumente prüfen und Links setzen. Gibt Anzahl gepatcht zurück."""
    docs = await _fetch_documents(client)
    logger.info("Gefundene Dokumente (Filter): %d", len(docs))

    patched = 0
    for doc in docs:
        doc_id = doc["id"]

        if _has_link(doc):
            continue

        link = _build_pay_url(doc_id)
        payload = _build_patch_payload(doc, link)

        try:
            await _patch_document(client, doc_id, payload)
            logger.info("✓ Dokument #%d → %s", doc_id, link)
            patched += 1
        except httpx.HTTPStatusError as exc:
            logger.error("✗ Dokument #%d – HTTP %d: %s",
                         doc_id, exc.response.status_code, exc.response.text[:200])
        except httpx.HTTPError as exc:
            logger.error("✗ Dokument #%d – Fehler: %s", doc_id, exc)

    return patched


async def main() -> None:
    logger.info("paperless-pay Link-Worker gestartet")
    logger.info("  Paperless:  %s", settings.paperless_base_url)
    logger.info("  Pay-URL:    %s", settings.pay_public_url)
    logger.info("  CF_LINK:    %d", settings.cf_link)
    logger.info("  Filter:     %s", settings.worker_filter or "(kein Filter – ALLE Dokumente)")
    logger.info("  Intervall:  %ds", settings.worker_interval)

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                patched = await run_once(client)
                if patched:
                    logger.info("Durchlauf fertig – %d Dokument(e) gepatcht", patched)
            except httpx.ConnectError as exc:
                logger.error("Verbindungsfehler: %s", exc)
            except Exception:
                logger.exception("Unerwarteter Fehler im Worker-Durchlauf")

            await asyncio.sleep(settings.worker_interval)


if __name__ == "__main__":
    asyncio.run(main())
