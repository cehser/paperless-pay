"""paperless-pay – IBAN validation

Thin wrapper around ``schwifty`` (ISO 13616, full country / BBAN checks).
"""

from __future__ import annotations

from schwifty import IBAN
from schwifty.exceptions import SchwiftyException

from translations import t


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class IbanValidationResult:
    """Result of an IBAN validation."""

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
    Validate an IBAN via schwifty (ISO 13616).

    Checks country code, length, BBAN structure and check digits.

    Returns:
        IbanValidationResult with .valid, .error, .iban_pretty
    """
    if not raw or not raw.strip():
        return IbanValidationResult(valid=False, error=t("msg.iban_empty"))

    try:
        iban = IBAN(raw)
    except SchwiftyException as exc:
        return IbanValidationResult(valid=False, error=str(exc))

    return IbanValidationResult(
        valid=True,
        iban_pretty=iban.formatted,
        country_code=iban.country_code,
    )
