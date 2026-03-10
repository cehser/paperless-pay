"""
paperless-pay – Datenmodelle
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class PaymentInfo:
    """Extrahierte Zahlungsinformationen aus Paperless Custom Fields."""

    doc_id: int
    title: str
    correspondent_id: int | None = None
    correspondent_name: str = ""

    iban: str = ""
    bic: str = ""
    betrag: Decimal | None = None
    verwendungszweck: str = ""
    bezahlt: bool = False

    # Rohdaten für Debugging
    raw_custom_fields: list[dict] = field(default_factory=list)

    @property
    def is_payable(self) -> bool:
        """True wenn alle Pflichtfelder für EPC-QR vorhanden und nicht bezahlt."""
        return bool(
            self.iban
            and self.betrag
            and self.betrag > 0
            and self.correspondent_name
            and not self.bezahlt
        )

    @property
    def missing_fields(self) -> list[str]:
        """Liste fehlender Pflichtfelder."""
        missing = []
        if not self.iban:
            missing.append("IBAN")
        if not self.betrag or self.betrag <= 0:
            missing.append("Betrag")
        if not self.correspondent_name:
            missing.append("Korrespondent")
        return missing
