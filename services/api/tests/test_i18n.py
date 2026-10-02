from app.i18n import bi, localize, parse_accept_language


def test_localize_picks_requested_language():
    value = bi("Hello", "你好")
    assert localize(value, "zh") == "你好"
    assert localize(value, "en") == "Hello"


def test_localize_falls_back_to_default_language_when_missing():
    # No "zh" key at all -> falls back to the default language (en).
    value = {"en": "Hello"}
    assert localize(value, "zh") == "Hello"


def test_localize_recurses_into_nested_structures():
    payload = {"title": bi("Hello", "你好"), "items": [bi("A", "甲"), bi("B", "乙")]}
    assert localize(payload, "zh") == {"title": "你好", "items": ["甲", "乙"]}


def test_localize_leaves_plain_values_untouched():
    assert localize(42, "zh") == 42
    assert localize("plain string", "zh") == "plain string"
    assert localize(None, "zh") is None


def test_parse_accept_language_respects_quality_weights():
    # zh has the highest q value even though it is not listed first.
    assert parse_accept_language("fr;q=0.2, zh;q=0.9, en;q=0.5") == "zh"


def test_parse_accept_language_falls_back_to_default_for_unsupported_languages():
    assert parse_accept_language("fr-FR,fr;q=0.9") == "en"


def test_parse_accept_language_handles_missing_header():
    assert parse_accept_language(None) == "en"


def test_parse_accept_language_matches_regional_subtag():
    assert parse_accept_language("zh-CN,zh;q=0.9") == "zh"
