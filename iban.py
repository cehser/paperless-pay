"""paperless-pay – IBAN-Validierung

Dünner Wrapper um ``schwifty`` (ISO 13616, vollständige Länder- / BBAN-Prüfung).
"""

from __future__ import annotations

from schwifty import IBAN
from schwifty.exceptions import SchwiftyException


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class IbanValidationResult:
    """Ergebnis einer IBAN-Validierung."""

    __slots__ = ("valid", "error", "iban_pretty", "country_code")

    def __init__(
        self,
        valid: bool,
        error: str = "",
        iban_pretty: str = "",
        country_code: str = "",
    ):
        self.valid = valid
        self.error = error
        self.iban_pretty = iban_pretty
        self.country_code = country_code

    def __bool__(self) -> bool:
        return self.valid

    def __repr__(self) -> str:
        return f"IbanValidationResult(valid={self.valid}, error={self.error!r})"


def validate_iban(raw: str) -> IbanValidationResult:
    """
    Validiert eine IBAN via schwifty (ISO 13616).

    Prüft Ländercode, Länge, BBAN-Struktur und Check-Digits.

    Returns:
        IbanValidationResult mit .valid, .error, .iban_pretty
    """
    if not raw or not raw.strip():
        return IbanValidationResult(valid=False, error="IBAN ist leer")

    try:
        iban = IBAN(raw)
    except SchwiftyException as exc:
        return IbanValidationResult(valid=False, error=str(exc))

    return IbanValidationResult(
        valid=True,
        iban_pretty=iban.formatted,
        country_code=iban.country_code,
    )
