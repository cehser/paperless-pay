"""
paperless-pay – Link Worker

Polls the Paperless API and sets a pay-link in a URL custom field
for all matching documents (e.g. invoices).

Auth via API token (headless, no cookie).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class WorkerSettings(BaseSettings):
    """Settings for the link worker (read exclusively from ENV)."""

    # --- Paperless upstream --------------------------------------------------
    paperless_base_url: str = "http://paperless:8000"
    paperless_token: str  # API token (required)

    # --- Custom field for the pay-link ---------------------------------------
    cf_link: int  # Custom field ID (type: URL)

    # --- Public URL of paperless-pay -----------------------------------------
    pay_public_url: str  # e.g. https://docs.example.com/pay

    # --- Filter (Paperless API query params) ---------------------------------
    # Freely configurable API filter, e.g.:
    #   document_type__id=3           → invoices only
    #   tags__id__all=5               → specific tag only
    #   tags__id__all=5&correspondent__id=2  → tag + correspondent
    worker_filter: str = ""

    # --- Timing --------------------------------------------------------------
    worker_interval: int = 60  # seconds between polling cycles

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
# HTTP helpers
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
# Core logic
# ---------------------------------------------------------------------------

async def _fetch_documents(client: httpx.AsyncClient) -> list[dict]:
    """
    Fetch *all* documents matching the configured filter.
    Paginates automatically.
    """
    url = f"{settings.paperless_base_url}/api/documents/"
    params = {"page_size": "100"}

    # Insert worker filter as additional query parameters
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
    """Check whether the document already has a pay-link in the CF_LINK field."""
    for cf in doc.get("custom_fields", []):
        if cf.get("field") == settings.cf_link:
            val = cf.get("value")
            return val is not None and val != ""
    return False


def _build_patch_payload(doc: dict, link: str) -> dict:
    """
    Build the PATCH payload for custom_fields.
    Keep existing custom fields, set/overwrite CF_LINK.
    """
    existing: list[dict] = doc.get("custom_fields", [])

    # Keep existing fields, replace CF_LINK if present
    new_fields = [cf for cf in existing if cf.get("field") != settings.cf_link]
    new_fields.append({"field": settings.cf_link, "value": link})

    return {"custom_fields": new_fields}


async def _patch_document(client: httpx.AsyncClient, doc_id: int, payload: dict) -> None:
    url = f"{settings.paperless_base_url}/api/documents/{doc_id}/"
    resp = await client.patch(url, json=payload, headers=_auth_headers(),
                              follow_redirects=True)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_once(client: httpx.AsyncClient) -> int:
    """Single pass: check documents and set links. Returns number of patched documents."""
    docs = await _fetch_documents(client)
    logger.info("Documents found (filter): %d", len(docs))

    patched = 0
    for doc in docs:
        doc_id = doc["id"]

        if _has_link(doc):
            continue

        link = _build_pay_url(doc_id)
        payload = _build_patch_payload(doc, link)

        try:
            await _patch_document(client, doc_id, payload)
            logger.info("✓ Document #%d → %s", doc_id, link)
            patched += 1
        except httpx.HTTPStatusError as exc:
            logger.error("✗ Document #%d – HTTP %d: %s",
                         doc_id, exc.response.status_code, exc.response.text[:200])
        except httpx.HTTPError as exc:
            logger.error("✗ Document #%d – Error: %s", doc_id, exc)

    return patched


async def main() -> None:
    logger.info("paperless-pay link worker started")
    logger.info("  Paperless:  %s", settings.paperless_base_url)
    logger.info("  Pay-URL:    %s", settings.pay_public_url)
    logger.info("  CF_LINK:    %d", settings.cf_link)
    logger.info("  Filter:     %s", settings.worker_filter or "(no filter – ALL documents)")
    logger.info("  Interval:   %ds", settings.worker_interval)

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                patched = await run_once(client)
                if patched:
                    logger.info("Pass complete – %d document(s) patched", patched)
            except httpx.ConnectError as exc:
                logger.error("Connection error: %s", exc)
            except Exception:
                logger.exception("Unexpected error in worker pass")

            await asyncio.sleep(settings.worker_interval)


if __name__ == "__main__":
    asyncio.run(main())
