import httpx
from .config import settings

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
