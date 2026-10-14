def test_country_pack_registry_has_operational_coverage(client):
    response = client.get("/country-packs?lang=en")
    assert response.status_code == 200
    packs = response.json()
    assert {pack["code"] for pack in packs} == {"MY", "ID", "SA", "AE"}
    assert all(pack["coverage_percent"] == 100 for pack in packs)
    assert all(pack["permit_count"] >= 4 for pack in packs)
    assert all(pack["authority_count"] >= 3 for pack in packs)
    assert all("not legal advice" in pack["disclaimer"].lower() for pack in packs)


def test_country_pack_detail_connects_projects_permits_and_sources(client):
    response = client.get("/country-packs/MY?lang=en")
    assert response.status_code == 200
    pack = response.json()
    assert pack["project_count"] == 1
    assert pack["projects"][0]["code"] == "MY-RAIL-A"
    assert any(item["code"] == "MY-CONTRACTOR" for item in pack["permit_catalog"])
    assert all(source["verification"] == "OFFICIAL_SOURCE" for source in pack["source_registry"])
    assert pack["approval_policy"]["legal_interpretation"] == "qualified_local_review"


def test_country_pack_applicability_filters_lifecycle_stage(client):
    response = client.get("/country-packs/ID/applicability?stage=commissioning&domain=building&lang=en")
    assert response.status_code == 200
    body = response.json()
    assert body["authority_review_required"] is True
    assert any(item["code"] == "ID-SLF" for item in body["applicable_items"])
    assert all("commissioning" in item["stages"] for item in body["applicable_items"])


def test_knowledge_search_is_jurisdiction_and_version_aware(client):
    response = client.get("/knowledge/search?q=contractor+registration&country_code=MY&lang=en")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["retrieval"] == {
        "method": "deterministic-tfidf", "jurisdiction_aware": True,
        "version_aware": True, "authority_review_required": True,
    }
    first = body["results"][0]
    assert first["country_code"] == "MY"
    assert first["content_hash"]
    assert first["citation"]["version"] == first["version"]
    assert first["source_url"].startswith("https://")


def test_knowledge_stats_and_document_detail(client):
    stats = client.get("/knowledge/stats?lang=zh").json()
    assert stats["documents"] >= 14
    assert stats["countries"] == 4
    assert stats["traceability_percent"] == 100
    results = client.get("/knowledge/search?country_code=SA&lang=zh").json()["results"]
    detail = client.get(f"/knowledge/{results[0]['id']}?lang=zh")
    assert detail.status_code == 200
    assert detail.json()["content"]
    assert detail.json()["country_code"] == "SA"
