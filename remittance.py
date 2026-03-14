"""
paperless-pay – Remittance info templating

Applies the REMITTANCE_TEMPLATE to payment data.
Used in both the QR code and the HTML display.
"""

from __future__ import annotations

import logging

from config import settings
from models import PaymentInfo

logger = logging.getLogger("paperless-pay.remittance")

_MAX_REMITTANCE = 140


def render_remittance(info: PaymentInfo) -> str:
    """
    Apply the remittance info template.

    Available variables:
        {remittance}    – Raw value from the custom field
        {title}         – Document title
        {correspondent} – Correspondent name
        {doc_id}        – Document ID
    """
    try:
        result = settings.remittance_template.format(
            remittance=info.remittance,
            title=info.title,
            correspondent=info.correspondent_name,
            doc_id=info.doc_id,
        )
    except (KeyError, IndexError) as exc:
        logger.warning("Remittance template error: %s – falling back to raw value", exc)
        result = info.remittance

    return result[:_MAX_REMITTANCE]
