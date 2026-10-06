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

def _rejects_response_format(response: httpx.Response) -> bool:
    """True if a 400 is the endpoint/model rejecting the ``response_format``
    (structured-output / JSON-schema) field -- e.g. an older OpenAI-compatible
    gateway that does not implement structured outputs -- as opposed to any
    other bad-request cause (bad model id, bad auth, ...) that should still
    raise. We match on the ``param`` the API attributes the error to, so an
    unrelated 400 is never swallowed."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return False
    return error.get("param") == "response_format"

async def generate(system: str, user: str, response_format: dict | None = None) -> str:
    """Call the configured OpenAI-compatible chat model, or return the
    deterministic demo string when no real model is configured (mock mode /
    no API key).

    ``response_format`` (V1.3 M5) optionally asks the endpoint for structured
    JSON output (a JSON-schema ``response_format`` object). It is a *best-effort*
    hardening: endpoints/models that do not implement structured outputs answer
    with a 400 naming the ``response_format`` param, in which case the field is
    dropped and the call retried once -- exactly as an explicit ``temperature``
    is dropped for reasoning-style models -- so requesting structured output can
    never break an otherwise-working model. Callers still validate the reply, so
    a model that silently ignores the hint is handled too.
    """
    if settings.llm_mode.lower() == "mock" or not settings.openai_compat_api_key:
        return "Deterministic demo mode active. No external model call was required."
    url = settings.openai_compat_base_url.rstrip('/') + '/chat/completions'
    messages = [{"role":"system","content":system},{"role":"user","content":user}]
    payload = {"model": settings.openai_compat_model, "messages": messages, "temperature":0.1}
    if response_format is not None:
        payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {settings.openai_compat_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(url, json=payload, headers=headers)
            # Some real endpoints 400 on an optional tuning field: newer
            # reasoning models (e.g. gpt-5.5) reject an explicit ``temperature``;
            # gateways without structured-output support reject
            # ``response_format``. Drop the named field and retry rather than
            # failing the whole request. The loop terminates because each branch
            # removes a key, so the same field can never be dropped twice.
            while r.status_code == 400:
                if _rejects_temperature(r) and "temperature" in payload:
                    del payload["temperature"]
                elif _rejects_response_format(r) and "response_format" in payload:
                    del payload["response_format"]
                else:
                    break
                r = await client.post(url, json=payload, headers=headers)
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
