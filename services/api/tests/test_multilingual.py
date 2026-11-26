"""Malay, Indonesian and Arabic input through the deterministic rule layer."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.classify import classify_text
from app.intake import build_intake_result, detect_language
from app.main import app
from app.multilingual import contains, expand_query, normalize

EVALS = Path(__file__).resolve().parent.parent / "evals"


def test_language_detection_covers_five_languages():
    assert detect_language("Worker observed at an unprotected edge.") == "en"
    assert detect_language("工人在无防护临边作业") == "zh"
    assert detect_language("إشعار من صاحب العمل في دبي") == "ar"
    assert detect_language("Notis pemilik projek: kerja hendaklah dibaiki dalam tempoh 24 jam.") == "ms"
    assert detect_language("Pemberitahuan pemilik proyek: harus diperbaiki dalam waktu 3 hari.") == "id"
    # English that happens to contain a Malay-looking token stays English.
    assert detect_language("Dan from the Bali office sent the drawing.") == "en"


def test_arabic_normalization_folds_spelling_variants():
    assert normalize("إشعار") == normalize("اشعار")
    assert normalize("خلال ٧٢ ساعة") == "خلال 72 ساعه"
    assert contains(normalize("والسقوط من حافة"), "السقوط")
    assert not contains(normalize("الإسقاط"), "سقوط")


def test_local_language_notices_route_like_english_ones():
    ar = build_intake_result("إشعار من صاحب العمل في دبي: عامل يعمل على ارتفاع دون معدات الوقاية الشخصية. يجب إيقاف العمل فوراً.")
    assert (ar["language"], ar["country"], ar["case_type"], ar["risk"]) == ("ar", "AE", "HSE", "CRITICAL")
    assert ar["deadline"]["en"] == "Immediate"
    ms = build_intake_result("Notis pemilik: jalan masuk di tapak Malaysia rosak dan perlu dibaiki dalam tempoh 2 hari.")
    assert (ms["language"], ms["country"], ms["case_type"], ms["deadline"]["en"]) == ("ms", "MY", "Contract / Technical Interface", "2 days")
    idn = build_intake_result("Beton keropos ditemukan pada pilar jembatan proyek di Surabaya setelah bekisting dibongkar.")
    assert (idn["language"], idn["country"], idn["case_type"]) == ("id", "ID", "Quality")
    assert classify_text("تشققات في الخرسانة") == {"type": "Quality", "risk": "MEDIUM"}


def test_english_rules_unchanged():
    out = build_intake_result("Malaysia owner notice alleges access road responsibility and requests rectification within 48 hours.")
    assert (out["language"], out["country"], out["case_type"], out["risk"], out["deadline"]["en"]) == (
        "en", "MY", "Contract / Technical Interface", "HIGH", "48 hours")


def test_query_expansion_uses_longest_glossary_match():
    rows = [
        {"id": "T-1", "en": "employer", "local": "صاحب العمل", "local_lang": "ar"},
        {"id": "T-2", "en": "work", "local": "العمل", "local_lang": "ar"},
        {"id": "T-3", "en": "decennial liability", "local": "الضمان العشري", "local_lang": "ar"},
    ]
    query, matches = expand_query("الضمان العشري على صاحب العمل", rows)
    assert [m["term_id"] for m in matches] == ["T-3", "T-1"]
    assert query.endswith("decennial liability employer")
    assert expand_query("工人 加班", rows) == ("工人 加班", [])


def test_search_reports_glossary_expansion():
    with TestClient(app) as client:
        body = client.get("/knowledge/search", params={
            "q": "مكافأة نهاية الخدمة", "country_code": "AE", "document_type": "CLAUSE_SUMMARY", "limit": 3}).json()
    assert body["results"][0]["source_ref"] == "AE-FDL33-2021-ART-51"
    assert body["retrieval"]["query_language"] == "ar"
    assert body["retrieval"]["glossary_expansion"][0]["en"] == "end-of-service gratuity"


def test_multilingual_datasets_cover_three_languages():
    intake = [json.loads(line) for line in (EVALS / "multilingual_intake.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {lang: sum(r["language"] == lang for r in intake) for lang in ("ms", "id", "ar")} == {"ms": 8, "id": 8, "ar": 8}
    clauses = [json.loads(line) for line in (EVALS / "clause_retrieval.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    langs = {r["lang"] for r in clauses}
    assert {"en", "zh", "ms", "id", "ar"} <= langs
    assert sum(r["lang"] == "ar" for r in clauses) >= 16
