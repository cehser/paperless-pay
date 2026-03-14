"""
paperless-pay – EPC QR code generation (SEPA Credit Transfer)

Uses segno for QR code generation in the EPC format.
Reference: European Payments Council – Quick Response Code (EPC QR)
"""

from __future__ import annotations

import io
import logging

import segno

from config import settings
from translations import t
from models import PaymentInfo
from remittance import render_remittance

logger = logging.getLogger("paperless-pay.qr")

# EPC-QR maximum lengths per specification
_MAX_NAME = 70
_MAX_REMITTANCE = 140
_MAX_IBAN = 34
_MAX_BIC = 11


def _truncate(value: str, max_len: int) -> str:
    """Truncate a string to the maximum length."""
    return value[:max_len]


def _render_remittance(info: PaymentInfo) -> str:
    """Apply the remittance info template."""
    return render_remittance(info)


def build_epc_payload(info: PaymentInfo) -> str:
    """
    Build the EPC QR code payload (text) according to EPC069-12.

    Format:
        BCD\\n002\\n1\\nSCT\\n{BIC}\\n{Name}\\n{IBAN}\\nEUR{Amount}\\n\\n{Remittance}\\n\\n
    """
    if not info.is_payable:
        raise ValueError(f"Document {info.doc_id} is not payable: missing fields {info.missing_fields}")

    name = _truncate(info.correspondent_name, _MAX_NAME)
    iban = _truncate(info.iban.replace(" ", ""), _MAX_IBAN)
    bic = _truncate(info.bic.replace(" ", ""), _MAX_BIC) if info.bic else ""
    amount = f"EUR{info.amount:.2f}"
    remittance = _render_remittance(info)

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
    Generate an EPC QR code as SVG string.
    Returns inline-embeddable SVG.
    """
    payload = build_epc_payload(info)

    # EPC-QR requires Error Correction Level M
    qr = segno.make(payload, error="m")

    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="svg",
        scale=4,
        border=2,
        svgclass="epc-qr",
        xmldecl=False,     # no <?xml ...?> – for inline embedding
    )
    return buffer.getvalue().decode("utf-8")


def generate_dummy_svg() -> str:
    """
    Generate a 'dummy' QR code for already-paid documents.
    Contains only the localized 'PAID' text.
    """
    qr = segno.make(t("qr.paid_text"), error="m")

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
