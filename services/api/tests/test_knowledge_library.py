"""Malaysia clause library, engineering glossary and tiered retrieval."""
from types import SimpleNamespace

from app.country_knowledge import CLAUSE_DOCUMENT_TYPE, load_clause_library, load_glossary
from app.retrieval import KnowledgeIndex

OFFICIAL_HOSTS = ("https://dosh.gov.my/", "https://www.cidb.gov.my/", "https://admin.aiac.world/", "https://www.pdp.gov.my/")


def test_clause_library_rows_keep_provenance_and_review_flags():
    rows = load_clause_library()
    assert len(rows) >= 100
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["instrument"] for row in rows}) == 6
    for row in rows:
        assert row["country"] == "MY"
        assert row["source_url"].startswith(OFFICIAL_HOSTS), row["id"]
        assert row["source_language"] in {"en", "ms"}
        assert row["version"] and row["provision"] and row["authority"]
        assert row["heading"]["en"] and row["heading"]["zh"]
        assert row["summary"]["en"] and row["summary"]["zh"]
        assert row["text_type"] == "PARAPHRASE_NOT_AUTHENTIC_TEXT"
        assert row["review_status"] == "EXPERT_REVIEW_REQUIRED"
        assert row["topics"] and row["lifecycle_stages"]


def test_outdated_or_unconsolidated_sources_are_flagged():
    rows = load_clause_library()
    cipaa = [row for row in rows if row["id"].startswith("MY-ACT746-")]
    cidb = [row for row in rows if row["id"].startswith("MY-ACT520-")]
    assert cipaa and all("A1738" in row["currency_note"] for row in cipaa)
    assert cidb and all("not reflected" in row["currency_note"] for row in cidb)
    # The repealed 1986 construction regulations must never be presented as current.
    assert not any("BOWEC" in row["instrument"] for row in rows)


def test_seeded_clauses_are_searchable_by_type_and_language(client):
    def top(q):
        body = client.get("/knowledge/search", params={"q": q, "country_code": "MY", "document_type": CLAUSE_DOCUMENT_TYPE, "limit": 3}).json()
        return [hit["source_ref"] for hit in body["results"]], body

    refs, body = top("pay when paid conditional payment void")
    assert refs[0] == "MY-ACT746-S35"
    assert body["filters"]["document_type"] == CLAUSE_DOCUMENT_TYPE
    assert all(hit["document_type"] == CLAUSE_DOCUMENT_TYPE for hit in body["results"])
    assert top("开挖 坍塌 支护 每班检查")[0][0] == "MY-CDM2024-REG24"


def test_clause_documents_carry_caveat_and_source(client):
    hit = client.get("/knowledge/search", params={"q": "data breach notify Commissioner", "document_type": CLAUSE_DOCUMENT_TYPE, "limit": 1}).json()["results"][0]
    doc = client.get(f"/knowledge/{hit['id']}").json()
    assert doc["source_url"].startswith("https://www.pdp.gov.my/")
    assert "not the authentic text" in doc["content"]
    assert "EXPERT_REVIEW_REQUIRED" in doc["tags"]


def test_tiered_index_keeps_source_scores_stable_when_clauses_are_added():
    def doc(ref, text, document_type="REGULATION_INDEX"):
        return SimpleNamespace(title={"en": text}, category=None, jurisdiction=None, content={"en": text},
                               summary=None, source_ref=ref, document_type=document_type)

    sources = [doc("S-1", "crane lifting permit and operator registration"), doc("S-2", "concrete curing record")]
    clauses = [doc(f"C-{i}", f"crane lifting registration clause {i}", CLAUSE_DOCUMENT_TYPE) for i in range(30)]
    query = "crane lifting permit"
    before = dict((d.source_ref, s) for s, d in KnowledgeIndex(sources).search(query, top_k=5))
    after = dict((d.source_ref, s) for s, d in KnowledgeIndex(sources + clauses).search(query, top_k=40))
    assert before["S-1"] == after["S-1"]
    assert any(ref.startswith("C-") for ref in after)


def test_glossary_is_trilingual_and_marks_attestation():
    rows = load_glossary("MY")
    assert len(rows) >= 200
    assert len({(row["domain"], row["en"].lower()) for row in rows}) == len(rows)
    for row in rows:
        assert row["en"] and row["zh"] and row["ms"]
        assert row["review_status"] == "NATIVE_REVIEW_REQUIRED"
        assert row["ms_basis"] == "TEAM_COMPILED" or row["ms_basis"].startswith("MS_ATTESTED_IN:")
    assert load_glossary("ZZ") == []


def test_glossary_endpoint_filters_and_rejects_unknown_pack(client):
    body = client.get("/country-packs/MY/glossary", params={"q": "perancah"}).json()
    assert body["total"] >= 1 and body["terms"][0]["en"] == "scaffolding"
    assert client.get("/country-packs/MY/glossary", params={"domain": "data"}).json()["total"] >= 10
    assert client.get("/country-packs/ZZ/glossary").status_code == 404


def test_library_manifest_reports_counts_and_limits(client):
    body = client.get("/knowledge/library").json()
    library = body["clause_library"]
    assert library["clauses"] == len(load_clause_library())
    assert sum(item["clauses"] for item in library["instruments"]) == library["clauses"]
    assert body["glossaries"][0]["terms"] == len(load_glossary("MY"))
    assert any("not authentic statutory text" in limit for limit in body["limits"])
