"""
paperless-pay – Konfiguration (ENV-only via pydantic-settings)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Alle Einstellungen kommen ausschließlich aus ENV-Variablen."""

    # --- Paperless upstream ---------------------------------------------------
    paperless_base_url: str = "http://paperless:8000"
    # Öffentliche URL für den PDF-iframe (falls anders als interne URL)
    paperless_public_url: str = ""

    # --- App ------------------------------------------------------------------
    app_base_path: str = "/pay"
    debug_upstream: bool = False

    # --- Custom Field IDs (aus Paperless Admin → Custom Fields) ---------------
    cf_iban: int
    cf_bic: int | None = None  # optional – BIC ist bei SEPA nicht immer nötig
    cf_betrag: int
    cf_verwendungszweck: int
    cf_bezahlt: int

    # --- Feature Switches ------------------------------------------------------
    enable_edit: bool = False  # Experimentell: Felder editierbar machen

    # --- Templating -----------------------------------------------------------
    # Verfügbare Variablen: {verwendungszweck}, {title}, {correspondent}, {doc_id}
    verwendungszweck_template: str = "{verwendungszweck}"

    @property
    def public_url(self) -> str:
        """URL die der Browser für Paperless-Requests nutzt (PDF-iframe)."""
        return self.paperless_public_url or self.paperless_base_url

    model_config = {"env_file": None}


settings = Settings()  # type: ignore[call-arg]
