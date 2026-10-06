from dataclasses import dataclass
from contextvars import ContextVar

import httpx
from .config import settings
from .translations import DEMO_TRANSLATIONS

LANGUAGE_NAMES = {"en": "English", "zh": "Simplified Chinese"}
_ROUTING_TRACE: ContextVar[list[dict] | None] = ContextVar("llm_routing_trace", default=None)


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


@dataclass(frozen=True)
class ModelProvider:
    name: str
    base_url: str
    model: str
    api_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and (self.name == "local" or self.api_key))


def _normalize_route(route: str | None) -> str:
    value = (route or settings.llm_mode).strip().lower()
    aliases = {"live": "openai", "cloud": "openai"}
    value = aliases.get(value, value)
    if value not in {"mock", "local", "openai", "auto"}:
        raise LLMError(f"Unsupported model route {value!r}; expected mock, local, openai, or auto.")
    return value


def _provider(name: str) -> ModelProvider:
    if name == "local":
        return ModelProvider(
            name="local",
            base_url=settings.local_llm_base_url,
            model=settings.local_llm_model,
            api_key=settings.local_llm_api_key,
        )
    return ModelProvider(
        name="openai",
        base_url=settings.openai_compat_base_url,
        model=settings.openai_compat_model,
        api_key=settings.openai_compat_api_key,
    )


def _route_order(route: str | None, sensitivity: str = "internal") -> list[ModelProvider]:
    selected = _normalize_route(route)
    if settings.llm_mode.strip().lower() == "mock" or selected == "mock":
        return []
    if sensitivity not in {"public", "internal", "restricted"}:
        raise LLMError(f"Unsupported data classification {sensitivity!r}.")
    if sensitivity == "restricted":
        # Restricted project data is never sent to a cloud provider, even when
        # a caller explicitly requests one. Classification outranks preference.
        if selected == "openai":
            raise LLMError("Restricted data cannot be routed to the OpenAI provider.")
        providers = [_provider("local")]
    elif selected in {"local", "openai"}:
        providers = [_provider(selected)]
    else:
        preferred = settings.llm_preferred_provider.strip().lower()
        if preferred not in {"local", "openai"}:
            preferred = "local"
        alternate = "openai" if preferred == "local" else "local"
        providers = [_provider(preferred)]
        if alternate == "local" or settings.llm_cloud_fallback_enabled:
            providers.append(_provider(alternate))
    return [provider for provider in providers if provider.configured]


def is_llm_configured(route: str | None = None, sensitivity: str = "internal") -> bool:
    """Return whether the selected route has at least one usable provider."""
    return bool(_route_order(route, sensitivity))


def routing_status() -> dict:
    """Return safe routing metadata without exposing endpoint credentials."""
    mode = _normalize_route(None)
    local = _provider("local")
    cloud = _provider("openai")
    return {
        "mode": mode,
        "preferred_provider": settings.llm_preferred_provider,
        "cloud_fallback_enabled": settings.llm_cloud_fallback_enabled,
        "providers": {
            "local": {"configured": local.configured, "model": local.model},
            "openai": {"configured": cloud.configured, "model": cloud.model},
        },
        "data_policy": {"restricted": "local_only", "public": "routable", "internal": "routable"},
    }


def reset_routing_trace() -> None:
    _ROUTING_TRACE.set([])


def routing_trace() -> list[dict]:
    return list(_ROUTING_TRACE.get() or [])


def _record_route(provider: ModelProvider, status: str) -> None:
    trace = list(_ROUTING_TRACE.get() or [])
    trace.append({"provider": provider.name, "model": provider.model, "status": status})
    _ROUTING_TRACE.set(trace)

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

async def _generate_with_provider(
    provider: ModelProvider, system: str, user: str, response_format: dict | None = None
) -> str:
    url = provider.base_url.rstrip('/') + '/chat/completions'
    messages = [{"role":"system","content":system},{"role":"user","content":user}]
    payload = {"model": provider.model, "messages": messages, "temperature":0.1}
    if response_format is not None:
        payload["response_format"] = response_format
    headers = {}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(url, json=payload, headers=headers)
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
            f"Upstream {provider.name} model {provider.model!r} failed with "
            f"HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Upstream {provider.name} model {provider.model!r} failed: {exc}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(
            f"Upstream {provider.name} model {provider.model!r} returned an unexpected response shape: {exc}"
        ) from exc


async def generate(
    system: str,
    user: str,
    response_format: dict | None = None,
    route: str | None = None,
    sensitivity: str = "internal",
) -> str:
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
    providers = _route_order(route, sensitivity)
    if not providers:
        return "Deterministic demo mode active. No external model call was required."
    errors = []
    for provider in providers:
        try:
            result = await _generate_with_provider(provider, system, user, response_format)
            _record_route(provider, "success")
            return result
        except LLMError as exc:
            _record_route(provider, "failed")
            errors.append(str(exc))
    raise LLMError("All eligible model routes failed: " + " | ".join(errors))

async def translate(
    text: str,
    target_lang: str,
    source_lang: str = "en",
    route: str | None = None,
    sensitivity: str = "internal",
) -> str:
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
    if is_llm_configured(route, sensitivity):
        system = (
            f"You are a professional technical translator for overseas transportation "
            f"infrastructure projects. Translate the user's text from {LANGUAGE_NAMES.get(source_lang, source_lang)} "
            f"to {LANGUAGE_NAMES.get(target_lang, target_lang)}. Preserve contract clause numbers, "
            f"standard references and defined terms exactly. Return only the translated text."
        )
        return (await generate(system, text, route=route, sensitivity=sensitivity)).strip()
    known = DEMO_TRANSLATIONS.get(text)
    if known and target_lang in known:
        return known[target_lang]
    return text
