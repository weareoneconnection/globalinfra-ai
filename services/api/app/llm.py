import httpx
from .config import settings
from .translations import DEMO_TRANSLATIONS

LANGUAGE_NAMES = {"en": "English", "zh": "Simplified Chinese"}

async def generate(system: str, user: str) -> str:
    if settings.llm_mode.lower() == "mock" or not settings.openai_compat_api_key:
        return "Deterministic demo mode active. No external model call was required."
    url = settings.openai_compat_base_url.rstrip('/') + '/chat/completions'
    payload = {"model": settings.openai_compat_model, "messages": [{"role":"system","content":system},{"role":"user","content":user}], "temperature":0.1}
    headers = {"Authorization": f"Bearer {settings.openai_compat_api_key}"}
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

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
