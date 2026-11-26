"""Malaysia clause library, engineering glossary and tiered retrieval."""
from types import SimpleNamespace

from app.country_knowledge import CLAUSE_DOCUMENT_TYPE, load_clause_library, load_glossary
from app.retrieval import KnowledgeIndex

OFFICIAL_HOSTS = (
    "https://dosh.gov.my/", "https://www.cidb.gov.my/", "https://admin.aiac.world/", "https://www.pdp.gov.my/",
    "https://jtksm.mohr.gov.my/", "https://www.importlicensing.wto.org/", "https://lom.agc.gov.my/", "https://peraturan.bpk.go.id/",
)
READ_QUALITIES = {"OFFICIAL_PDF", "OFFICIAL_REPRINT_VIA_MIRROR", "MIRROR_TRANSCRIPTION", "OFFICIAL_EXPLANATORY_NOTE"}


def test_clause_library_rows_keep_provenance_and_review_flags():
    rows = load_clause_library()
    assert sum(row["country"] == "MY" for row in rows) >= 150
    assert sum(row["country"] == "ID" for row in rows) >= 30
    assert len({row["id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["country"] in {"MY", "ID"} and row["id"].startswith(row["country"] + "-")
        assert row["source_url"].startswith(OFFICIAL_HOSTS), row["id"]
        assert row["read_quality"] in READ_QUALITIES and row["read_from"]
        assert row["source_language"] in {"en", "ms", "id"}
        assert row["version"] and row["provision"] and row["authority"]
        # Postgres enforces the KnowledgeDocument column sizes that SQLite ignores.
        assert len(row["version"]) <= 64 and len(row["authority"]) <= 160 and len(row["id"]) <= 160, row["id"]
        assert len(row["source_url"]) <= 500, row["id"]
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
    # Every row read from a third-party transcription says so in its currency note.
    assert all(row["currency_note"] for row in rows if row["read_quality"] == "MIRROR_TRANSCRIPTION")
    railway = [row for row in rows if row["id"].startswith("MY-ACT463-")]
    assert railway and all("Act 715" in row["currency_note"] for row in railway)
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
    body = client.get("/knowledge/search", params={"q": "level crossing grade separated", "country_code": "ID", "document_type": CLAUSE_DOCUMENT_TYPE, "limit": 3}).json()
    assert body["results"][0]["source_ref"] == "ID-UU23-2007-PASAL-91"


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


def test_glossaries_are_trilingual_and_mark_attestation():
    for code, lang, minimum in (("MY", "ms", 200), ("ID", "id", 120)):
        rows = load_glossary(code)
        assert len(rows) >= minimum
        assert len({(row["domain"], row["en"].lower()) for row in rows}) == len(rows)
        for row in rows:
            assert row["en"] and row["zh"] and row["local"] and row["local_lang"] == lang
            assert row["review_status"] == "NATIVE_REVIEW_REQUIRED"
            assert row["local_basis"] == "TEAM_COMPILED" or row["local_basis"].startswith("ATTESTED_IN:")
    assert load_glossary("ZZ") == []


def test_glossary_endpoint_filters_and_rejects_unknown_pack(client):
    body = client.get("/country-packs/MY/glossary", params={"q": "perancah"}).json()
    assert body["total"] >= 1 and body["terms"][0]["en"] == "scaffolding"
    assert client.get("/country-packs/MY/glossary", params={"domain": "data"}).json()["total"] >= 10
    indonesian = client.get("/country-packs/ID/glossary", params={"q": "dewan sengketa"}).json()
    assert indonesian["local_language"] == "id" and indonesian["terms"][0]["en"] == "dispute board"
    assert client.get("/country-packs/ZZ/glossary").status_code == 404


def test_library_manifest_reports_counts_and_limits(client):
    body = client.get("/knowledge/library").json()
    library = body["clause_library"]
    assert library["clauses"] == len(load_clause_library())
    assert sum(item["clauses"] for item in library["instruments"]) == library["clauses"]
    assert set(library["by_country"]) == {"ID", "MY"}
    assert {g["country"]: g["terms"] for g in body["glossaries"]} == {"ID": len(load_glossary("ID")), "MY": len(load_glossary("MY"))}
    assert any("not authentic statutory text" in limit for limit in body["limits"])


def test_clause_tier_uses_cjk_pairs_so_single_characters_do_not_match():
    from app.retrieval import tokenize_bigrams

    assert tokenize_bigrams("露天焚烧 open burning") == ["open", "burning", "露天", "天焚", "焚烧"]
    assert tokenize_bigrams("天") == ["天"]
    clause = SimpleNamespace(title={"zh": "禁止露天焚烧"}, category=None, jurisdiction=None, content={"zh": "禁止在露天焚烧废物"},
                             summary=None, source_ref="C-1", document_type=CLAUSE_DOCUMENT_TYPE)
    assert KnowledgeIndex([clause]).search("明天吉隆坡天气怎么样？") == []
    assert KnowledgeIndex([clause]).search("露天焚烧")[0][1] is clause
