import httpx
from .config import settings
from .translations import DEMO_TRANSLATIONS

LANGUAGE_NAMES = {"en": "English", "zh": "Simplified Chinese"}


class LLMError(RuntimeError):
    """Raised when a configured real OpenAI-compatible model call fails.

    ``generate``/``translate`` normalize every upstream transport/HTTP
    failure (bad API key, invalid/unreachable model, network timeout,
    malformed response body) into this one exception type instead of
    letting httpx's own exception propagate. Call sites (see
    ``app.main``'s ``/cases/{id}/analyze`` and ``/i18n/translate`` routes)
    catch it and return a clean ``502`` with an actionable message, rather
    than the caller falling through to FastAPI's default handler and
    surfacing an opaque ``Internal Server Error`` with a leaked stack trace.
    """

def _rejects_temperature(response: httpx.Response) -> bool:
    """True if a 400 is OpenAI's "this model only supports the default
    temperature" error (seen on the newer ``gpt-5.x`` reasoning-style model
    family), as opposed to any other bad-request cause (bad model id, bad
    auth, a different unsupported param, ...) that should still raise."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return False
    return error.get("param") == "temperature" and error.get("code") == "unsupported_value"

async def generate(system: str, user: str) -> str:
    if settings.llm_mode.lower() == "mock" or not settings.openai_compat_api_key:
        return "Deterministic demo mode active. No external model call was required."
    url = settings.openai_compat_base_url.rstrip('/') + '/chat/completions'
    messages = [{"role":"system","content":system},{"role":"user","content":user}]
    payload = {"model": settings.openai_compat_model, "messages": messages, "temperature":0.1}
    headers = {"Authorization": f"Bearer {settings.openai_compat_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 400 and _rejects_temperature(r):
                # Some real models (e.g. gpt-5.5) only support the default
                # temperature and 400 on any explicit value; retry once
                # without it rather than failing the whole request.
                retry_payload = {"model": settings.openai_compat_model, "messages": messages}
                r = await client.post(url, json=retry_payload, headers=headers)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip()[:300]
        raise LLMError(
            f"Upstream model call to {settings.openai_compat_model!r} failed with "
            f"HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Upstream model call to {settings.openai_compat_model!r} failed: {exc}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(
            f"Upstream model call to {settings.openai_compat_model!r} returned an unexpected response shape: {exc}"
        ) from exc

async def translate(text: str, target_lang: str, source_lang: str = "en") -> str:
    """Translation-model integration point.

    - If a real OpenAI-compatible model is configured (``llm_mode`` != mock
      and an API key is present), the text is routed through the chat
      completion model with a terminology-preserving system prompt.
    - Otherwise (the default, network-free demo/CI mode) this falls back to
      the curated bilingual phrase table in ``translations.py`` so the
      platform still behaves deterministically end-to-end without calling
      out to the network. Unknown strings are returned unchanged rather
      than silently corrupted.
    """
    if not text or target_lang == source_lang:
        return text
    if settings.llm_mode.lower() != "mock" and settings.openai_compat_api_key:
        system = (
            f"You are a professional technical translator for overseas transportation "
            f"infrastructure projects. Translate the user's text from {LANGUAGE_NAMES.get(source_lang, source_lang)} "
            f"to {LANGUAGE_NAMES.get(target_lang, target_lang)}. Preserve contract clause numbers, "
            f"standard references and defined terms exactly. Return only the translated text."
        )
        return (await generate(system, text)).strip()
    known = DEMO_TRANSLATIONS.get(text)
    if known and target_lang in known:
        return known[target_lang]
    return text
