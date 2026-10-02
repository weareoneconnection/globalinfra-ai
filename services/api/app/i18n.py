"""Language negotiation and bilingual-value resolution for the API layer.

Any field that needs to be shown to a user can be stored as a plain string
(legacy / untranslated) or as a "localized value": a dict keyed by language
code, e.g. ``{"en": "Working at height", "zh": "高处作业"}``. ``localize()``
walks a response payload (dict / list / scalar, arbitrarily nested) and
resolves every localized value down to a single string for the requested
language, falling back to the default language and finally to whatever
value is available. This lets every route return raw bilingual data and
localize it in one place right before the response is sent.
"""
from fastapi import Header, Query

SUPPORTED_LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"


def parse_accept_language(header_value: str | None) -> str:
    """Pick the best supported language out of a browser Accept-Language header."""
    if not header_value:
        return DEFAULT_LANGUAGE
    weighted = []
    for part in header_value.split(','):
        part = part.strip()
        if not part:
            continue
        tag, _, qpart = part.partition(';')
        tag = tag.strip().lower()
        q = 1.0
        if qpart:
            try:
                q = float(qpart.strip().removeprefix('q='))
            except ValueError:
                q = 1.0
        weighted.append((q, tag))
    weighted.sort(key=lambda x: x[0], reverse=True)
    for _, tag in weighted:
        primary = tag.split('-')[0]
        if primary in SUPPORTED_LANGUAGES:
            return primary
    return DEFAULT_LANGUAGE


def get_lang(lang: str | None = Query(default=None, description="Explicit language override, e.g. 'en' or 'zh'"),
             accept_language: str | None = Header(default=None)) -> str:
    """FastAPI dependency: resolve the active language for a request.

    Priority: explicit ?lang= query param (what the web app sends, based on
    its own next-intl locale) -> Accept-Language header (what a browser or
    direct API client sends) -> default language.
    """
    if lang and lang.lower() in SUPPORTED_LANGUAGES:
        return lang.lower()
    return parse_accept_language(accept_language)


def bi(en: str, zh: str | None = None) -> dict:
    """Build a localized value. Falls back to the English text when no
    translation is supplied yet (keeps the data model incremental)."""
    return {"en": en, "zh": zh or en}


def _is_localized_value(value) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and set(value.keys()) <= set(SUPPORTED_LANGUAGES)
        and all(isinstance(v, str) for v in value.values())
    )


def localize(value, lang: str = DEFAULT_LANGUAGE):
    """Recursively resolve localized values inside dicts/lists to plain strings."""
    if _is_localized_value(value):
        return value.get(lang) or value.get(DEFAULT_LANGUAGE) or next(iter(value.values()))
    if isinstance(value, dict):
        return {k: localize(v, lang) for k, v in value.items()}
    if isinstance(value, list):
        return [localize(v, lang) for v in value]
    return value
