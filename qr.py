"""
paperless-pay – EPC-QR-Code-Generierung (SEPA Credit Transfer)

Nutzt segno für die QR-Code-Erzeugung im EPC-Format.
Referenz: European Payments Council – Quick Response Code (EPC QR)
"""

from __future__ import annotations

import io
import logging

import segno

from config import settings
from models import PaymentInfo

logger = logging.getLogger("paperless-pay.qr")

# EPC-QR Maximallängen laut Spezifikation
_MAX_NAME = 70
_MAX_REMITTANCE = 140
_MAX_IBAN = 34
_MAX_BIC = 11


def _truncate(value: str, max_len: int) -> str:
    """Kürzt einen String auf die maximale Länge."""
    return value[:max_len]


def _render_verwendungszweck(info: PaymentInfo) -> str:
    """Wendet das Verwendungszweck-Template an."""
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

    return _truncate(result, _MAX_REMITTANCE)


def build_epc_payload(info: PaymentInfo) -> str:
    """
    Baut den EPC-QR-Code-Payload (Text) gemäß EPC069-12.

    Format:
        BCD\n002\n1\nSCT\n{BIC}\n{Name}\n{IBAN}\nEUR{Betrag}\n\n{Remittance}\n\n
    """
    if not info.is_payable:
        raise ValueError(f"Dokument {info.doc_id} ist nicht zahlbar: fehlende Felder {info.missing_fields}")

    name = _truncate(info.correspondent_name, _MAX_NAME)
    iban = _truncate(info.iban.replace(" ", ""), _MAX_IBAN)
    bic = _truncate(info.bic.replace(" ", ""), _MAX_BIC)
    amount = f"EUR{info.betrag:.2f}"
    remittance = _render_verwendungszweck(info)

    lines = [
        "BCD",           # Service Tag
        "002",           # Version
        "1",             # Encoding (1 = UTF-8)
        "SCT",           # Identification (SEPA Credit Transfer)
        bic,             # BIC
        name,            # Beneficiary Name
        iban,            # IBAN
        amount,          # Amount
        "",              # Purpose (AT-44, optional)
        remittance,      # Remittance Information (Unstructured)
        "",              # Beneficiary to originator info (optional)
    ]

    payload = "\n".join(lines)
    logger.debug("EPC-QR payload (%d chars): %s", len(payload), payload)
    return payload


def generate_qr_svg(info: PaymentInfo) -> str:
    """
    Generiert einen EPC-QR-Code als SVG-String.
    Gibt inline-fähiges SVG zurück.
    """
    payload = build_epc_payload(info)

    # EPC-QR muss Error Correction Level M sein
    qr = segno.make(payload, error="m")

    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="svg",
        scale=4,
        border=2,
        svgclass="epc-qr",
        xmldecl=False,     # kein <?xml ...?> – für inline-Embed
    )
    return buffer.getvalue().decode("utf-8")


def generate_dummy_svg() -> str:
    """
    Generiert einen 'Dummy'-QR-Code für bereits bezahlte Dokumente.
    Enthält nur den Text 'BEZAHLT'.
    """
    qr = segno.make("BEZAHLT", error="m")

    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="svg",
        scale=4,
        border=2,
        svgclass="epc-qr epc-qr--paid",
        xmldecl=False,
    )
    return buffer.getvalue().decode("utf-8")
