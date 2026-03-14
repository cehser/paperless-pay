"""
paperless-pay – Data models
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class PaymentInfo:
    """Payment information extracted from Paperless custom fields."""

    doc_id: int
    title: str
    correspondent_id: int | None = None
    correspondent_name: str = ""

    iban: str = ""
    bic: str = ""
    amount: Decimal | None = None
    remittance: str = ""
    paid: bool = False

    # Raw data for debugging
    raw_custom_fields: list[dict] = field(default_factory=list)

    @property
    def is_payable(self) -> bool:
        """True when all required fields for EPC-QR are present and not yet paid."""
        return bool(
            self.iban
            and self.amount
            and self.amount > 0
            and self.correspondent_name
            and not self.paid
        )

    @property
    def missing_fields(self) -> list[str]:
        """List of missing required fields."""
        missing = []
        if not self.iban:
            missing.append("IBAN")
        if not self.amount or self.amount <= 0:
            missing.append("Amount")
        if not self.correspondent_name:
            missing.append("Correspondent")
        return missing
