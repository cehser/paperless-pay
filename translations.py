"""
paperless-pay – Translation support (i18n)

Uses ``python-i18n`` with JSON locale files in ``locales/``.
Supported locales: en, de.
"""

from __future__ import annotations

import os

import i18n as _i18n

# ---------------------------------------------------------------------------
# Configure python-i18n
# ---------------------------------------------------------------------------

_locales_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

_i18n.set("load_path", [_locales_dir])
_i18n.set("file_format", "json")
_i18n.set("fallback", "en")
_i18n.set("enable_memoization", True)

_active_locale: str = "en"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init(locale: str) -> None:
    """Set the active locale. Called once at startup."""
    global _active_locale
    normalized = locale.strip().lower()[:2]
    if normalized not in ("en", "de"):
        normalized = "en"
    _active_locale = normalized
    _i18n.set("locale", normalized)


def t(key: str, **kwargs: object) -> str:
    """
    Translate a key to the active locale.

    Supports interpolation::

        t("error.not_found_body", doc_id=42)
        # → "Document 42 does not exist."

    Falls back to English if the key or locale is missing.
    """
    return _i18n.t(key, locale=_active_locale, **kwargs)


def get_locale() -> str:
    """Return the active locale code (e.g. ``'en'`` or ``'de'``)."""
    return _active_locale
