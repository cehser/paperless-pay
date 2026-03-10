"""
paperless-pay – Verwendungszweck-Templating

Wendet das VERWENDUNGSZWECK_TEMPLATE auf die Zahlungsdaten an.
Wird sowohl im QR-Code als auch in der HTML-Anzeige verwendet.
"""

from __future__ import annotations

import logging

from config import settings
from models import PaymentInfo

logger = logging.getLogger("paperless-pay.verwendungszweck")

_MAX_REMITTANCE = 140


def render_verwendungszweck(info: PaymentInfo) -> str:
    """
    Wendet das Verwendungszweck-Template an.

    Verfügbare Variablen:
        {verwendungszweck}  – Rohwert aus dem Custom Field
        {title}             – Dokument-Titel
        {correspondent}     – Korrespondent-Name
        {doc_id}            – Dokument-ID
    """
    try:
        result = settings.verwendungszweck_template.format(
            verwendungszweck=info.verwendungszweck,
            title=info.title,
            correspondent=info.correspondent_name,
            doc_id=info.doc_id,
        )
    except (KeyError, IndexError) as exc:
        logger.warning("Verwendungszweck-Template fehlerhaft: %s – Fallback auf raw", exc)
        result = info.verwendungszweck

    return result[:_MAX_REMITTANCE]
