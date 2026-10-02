"""Unit tests for the TF-IDF evidence retrieval engine (app.retrieval).

These exercise the actual ranking math with small fake documents, isolated
from the database and from the rest of the analysis workflow, to pin down
the properties the workflow engine depends on: relevant documents outrank
irrelevant ones, bilingual text is searchable from either language, and an
empty/unrelated query does not fabricate a match.
"""
from types import SimpleNamespace

from app.retrieval import KnowledgeIndex, case_query_text, tokenize


def _doc(source_ref, title_en, title_zh, content_en, content_zh):
    return SimpleNamespace(
        title={"en": title_en, "zh": title_zh},
        category={"en": "Contract", "zh": "合同"},
        jurisdiction={"en": "Project", "zh": "项目"},
        content={"en": content_en, "zh": content_zh},
        summary={"en": content_en, "zh": content_zh},
        source_ref=source_ref,
    )


DOCS = [
    _doc("DOC-1", "Crack assessment note", "裂缝评估说明",
         "Crack responsibility requires location, width and causation evidence.",
         "裂缝责任归属需要位置、宽度及成因证据。"),
    _doc("DOC-2", "Working at height pack", "高处作业手册",
         "Use fall protection and approved access systems for work at height.",
         "高处作业须使用坠落防护及经批准的通道系统。"),
]


def test_tokenize_splits_latin_words_and_individual_cjk_characters():
    assert tokenize("Clause C-14.2") == ["clause", "c-14.2"]
    assert tokenize("裂缝") == ["裂", "缝"]
    assert tokenize("") == []


def test_search_ranks_the_topically_relevant_document_first():
    index = KnowledgeIndex(DOCS)
    results = index.search("structural crack width causation", top_k=2)
    assert results, "expected at least one match"
    top_score, top_doc = results[0]
    assert top_doc.source_ref == "DOC-1"
    assert top_score > 0


def test_search_matches_across_languages_without_translation():
    index = KnowledgeIndex(DOCS)
    # A Chinese-only query should still surface the Chinese-authored match
    # for the HSE document ahead of the unrelated crack document, because
    # both languages of every document are indexed together.
    results = index.search("高处作业 坠落 防护", top_k=2)
    assert results[0][1].source_ref == "DOC-2"


def test_search_returns_nothing_for_a_completely_unrelated_query():
    index = KnowledgeIndex(DOCS)
    assert index.search("unrelated query term zzyzx", top_k=2) == []


def test_case_query_text_flattens_bilingual_case_fields():
    case = SimpleNamespace(
        type={"en": "HSE", "zh": "HSE"},
        title={"en": "Fall protection gap", "zh": "坠落防护缺口"},
        description={"en": "desc", "zh": "描述"},
        detected_issues=[{"en": "Access control", "zh": "通道管控"}],
    )
    text = case_query_text(case)
    assert "Fall protection gap" in text
    assert "坠落防护缺口" in text
    assert "Access control" in text
