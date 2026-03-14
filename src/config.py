"""
paperless-pay – Configuration (ENV-only via pydantic-settings)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings are read exclusively from environment variables."""

    # --- Paperless upstream ---------------------------------------------------
    paperless_base_url: str = "http://paperless:8000"
    # Public URL used for the PDF iframe (if different from internal URL)
    paperless_public_url: str = ""

    # --- App ------------------------------------------------------------------
    app_base_path: str = "/pay"
    debug_upstream: bool = False

    # --- Locale ---------------------------------------------------------------
    language: str = "en"  # Supported: "en", "de"

    # --- Custom Field IDs (from Paperless Admin → Custom Fields) --------------
    cf_iban: int
    cf_bic: int | None = None  # optional – BIC is not always required for SEPA
    cf_amount: int
    cf_remittance: int
    cf_paid: int

    # --- Feature Switches -----------------------------------------------------
    enable_edit: bool = False  # Experimental: make fields editable

    # --- Templating -----------------------------------------------------------
    # Available variables: {remittance}, {title}, {correspondent}, {doc_id}
    remittance_template: str = "{remittance}"

    @property
    def public_url(self) -> str:
        """URL the browser uses for Paperless requests (PDF iframe)."""
        return self.paperless_public_url or self.paperless_base_url

    model_config = {"env_file": None}


settings = Settings()  # type: ignore[call-arg]

# Initialize i18n with the configured locale
from translations import init as _init_i18n  # noqa: E402

_init_i18n(settings.language)
