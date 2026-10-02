import asyncio

from app.llm import translate


def _run(coro):
    return asyncio.run(coro)


def test_translate_uses_the_offline_demo_table_for_known_phrases():
    # llm_mode defaults to "mock" (see conftest.py), so this must resolve
    # through translations.DEMO_TRANSLATIONS rather than calling a network model.
    result = _run(translate("Deterministic demo mode active. No external model call was required.", "zh"))
    assert result == "确定性演示模式已启用，本次未调用外部模型。"


def test_translate_is_a_noop_when_source_and_target_languages_match():
    result = _run(translate("Hello", "en", "en"))
    assert result == "Hello"


def test_translate_returns_empty_text_unchanged():
    assert _run(translate("", "zh")) == ""


def test_translate_returns_original_text_for_phrases_outside_the_demo_table():
    text = "Some text that was never added to the demo phrase table."
    assert _run(translate(text, "zh")) == text
