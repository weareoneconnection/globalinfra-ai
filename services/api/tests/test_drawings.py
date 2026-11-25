"""P0 drawing intelligence: exact evidence, fail-closed gates and isolation."""
from __future__ import annotations

import io
import json

import fitz
import pytest
from fastapi import HTTPException
from PIL import Image

from app.drawings import MAX_PREVIEW_DIMENSION, MAX_PREVIEW_PIXELS, ParsedLine, _element_specs
from app.main import app
from app.security import Principal, get_principal


def _drawing_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=842, height=595)
    lines = [
        "DRAWING TITLE: EQUIPMENT ROOM PLAN",
        "DRAWING NO: STA-A-101",
        "REVISION: B",
        "SCALE: 1:100",
        "UNIT: mm",
        "GRID A",
        "EQUIPMENT ROOM",
        "DIMENSION 5000 mm",
        "MATERIAL: REINFORCED CONCRETE",
    ]
    for index, line in enumerate(lines):
        page.insert_text((60, 55 + index * 28), line, fontsize=12)
    # Real vector content proves this is not just a text letter renamed .pdf.
    page.draw_rect(fitz.Rect(50, 300, 600, 520), width=1)
    page.draw_line(fitz.Point(325, 300), fitz.Point(325, 520), width=1)
    payload = document.tobytes(garbage=4, deflate=True)
    document.close()
    return payload


def _drawing_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _large_page_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=10_000, height=10_000)
    page.insert_text((100, 100), "SCALE: 1:100 UNIT: mm", fontsize=12)
    payload = document.tobytes(garbage=4, deflate=True)
    document.close()
    return payload


def _upload_pdf(client):
    return client.post(
        "/drawings/analyze",
        data={
            "project_id": "1",
            "discipline": "architecture",
            "data_classification": "internal",
        },
        files={"file": ("station-equipment-room.pdf", _drawing_pdf(), "application/pdf")},
    )


def test_pdf_analysis_returns_exact_evidence_and_grounded_answer(client):
    response = _upload_pdf(client)
    assert response.status_code == 201, response.text
    body = response.json()
    drawing = body["document"]
    assert drawing["status"] == "ANALYZED"
    assert drawing["drawing_number"] == "STA-A-101"
    assert drawing["revision"] == "B"
    assert drawing["scale"] == "1:100"
    assert drawing["unit"] == "mm"
    assert drawing["data_classification"] == "internal"
    assert drawing["sha256"] == body["analysis"]["source_sha256"]
    assert body["ingestion_receipt"]["target_type"] == "DrawingDocument"
    assert body["ingestion_receipt"]["checksum"] == drawing["sha256"]

    elements = body["elements"]
    assert any(row["type"] == "DIMENSION" for row in elements)
    assert any(row["type"] == "SPACE" for row in elements)
    assert all(row["page"] == 1 and len(row["bbox"]) == 4 for row in elements)
    assert all(0 <= coordinate <= 1 for row in elements for coordinate in row["bbox"])
    assert all(row["evidence"]["source_sha256"] == drawing["sha256"] for row in elements)

    answer = client.post(
        f"/drawings/{drawing['id']}/ask", json={"question": "What is the drawing number?"}
    )
    assert answer.status_code == 200
    result = answer.json()
    assert result["grounded"] is True
    assert any(item["source_text"] and item["page"] == 1 for item in result["citations"])
    assert "STA-A-101" in result["answer"]

    chinese = client.post(
        f"/drawings/{drawing['id']}/ask", json={"question": "图纸比例是多少？"}
    ).json()
    assert chinese["grounded"] is True
    assert "1:100" in chinese["answer"]

    review = client.post(
        f"/drawings/{drawing['id']}/ask",
        json={"question": "哪些设备、净空或缺失尺寸需要复核？"},
    ).json()
    assert review["grounded"] is True
    assert review["citations"]

    unsupported = client.post(
        f"/drawings/{drawing['id']}/ask", json={"question": "Who approved the construction release?"}
    ).json()
    assert unsupported["grounded"] is False
    assert unsupported["citations"] == []

    materials = client.post(
        f"/drawings/{drawing['id']}/ask", json={"question": "这张图有哪些材料要求？"}
    ).json()
    assert materials["grounded"] is True
    assert "MATERIAL: REINFORCED CONCRETE" in materials["answer"]
    assert len(materials["citations"]) == 1

    area = client.post(
        f"/drawings/{drawing['id']}/ask", json={"question": "建筑面积多少？"}
    ).json()
    assert area["grounded"] is False
    assert "没有检出明确标注" in area["answer"]
    assert "闭合建筑外轮廓" in area["answer"]


def test_title_block_code_outranks_cad_path_noise_and_keeps_revision():
    path = ParsedLine(
        1,
        r"O:\\ECRL\\PD_ECRL_C_DS_AR_RFD_ARD001_00506.dwg REV FILES\\PD SHEET",
        [0.1, 0.1, 0.9, 0.12],
    )
    title_block = ParsedLine(
        1,
        "PD/ECRL/C/DS/AR/RFD/ARD001/00506",
        [0.6, 0.8, 0.9, 0.84],
    )
    revision = ParsedLine(1, "02", [0.92, 0.8, 0.96, 0.84])
    revised_note = ParsedLine(1, "23/12/2022 REVISED AS PER CLOUDED NIC", [0.1, 0.4, 0.5, 0.42])
    metadata, elements = _element_specs([path, revised_note, title_block, revision])
    assert metadata["drawing_number"][0] == "PD/ECRL/C/DS/AR/RFD/ARD001/00506"
    assert metadata["revision"][0] == "02"
    assert not any(row["value"] in {"REV", "FILES"} for row in elements)


def test_materials_and_explicit_area_are_extracted_without_collapsing_requirements():
    lines = [
        ParsedLine(1, "150mm Ø HDPE PIPE COVERED WITH CONCRETE AND EXTENDED", [0.1, 0.1, 0.8, 0.12]),
        ParsedLine(1, "75mm Ø STAINLESS STEEL RAILING AT 900mm HEIGHT", [0.1, 0.2, 0.8, 0.22]),
        ParsedLine(1, "BUILDING AREA: 128.5 m2", [0.1, 0.3, 0.5, 0.32]),
    ]
    _, elements = _element_specs(lines)
    material_values = [row["value"].upper() for row in elements if row["type"] == "MATERIAL"]
    assert "HDPE" in material_values
    assert "CONCRETE" in material_values
    assert "STAINLESS STEEL" in material_values
    area = next(row for row in elements if row["label"] == "building_area")
    assert area["value"] == "128.5"
    assert area["unit"] == "m²"


def test_source_preview_and_human_model_gate_are_private_and_fail_closed(client):
    body = _upload_pdf(client).json()
    drawing_id = body["document"]["id"]
    assert body["model_gate"]["ready"] is False
    assert "SCALE_REQUIRES_CONFIRMATION" in body["model_gate"]["blockers"]
    assert "UNIT_REQUIRES_CONFIRMATION" in body["model_gate"]["blockers"]
    assert "STOREY_HEIGHT_REQUIRES_CONFIRMATION" in body["model_gate"]["blockers"]
    assert "WALL_THICKNESS_REQUIRES_CONFIRMATION" in body["model_gate"]["blockers"]
    assert "NO_CONFIRMED_GEOMETRY" in body["model_gate"]["blockers"]

    source = client.get(f"/drawings/{drawing_id}/source")
    assert source.status_code == 200 and source.content.startswith(b"%PDF-")
    assert "no-store" in source.headers["cache-control"]
    preview = client.get(f"/drawings/{drawing_id}/pages/1/preview")
    assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")
    assert "no-store" in preview.headers["cache-control"]

    confirmed = client.post(f"/drawings/{drawing_id}/confirm", json={
        "unit": "mm", "scale": "1:100",
        "storey_height_m": 3.8, "wall_thickness_m": 0.2,
    })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["model_gate"]["ready"] is False

    space = next(
        row for row in confirmed.json()["elements"]
        if row["properties"].get("geometry_type") == "RECTANGLE_FOOTPRINT"
    )
    final = client.post(f"/drawings/{drawing_id}/confirm", json={
        "field": space["id"], "value": space["value"],
    })
    assert final.status_code == 200, final.text
    assert final.json()["model_gate"]["status"] == "READY"
    assert final.json()["model_gate"]["ready"] is True
    assert final.json()["model_gate"]["blockers"] == []
    # Other extracted vector candidates remain explicitly unconfirmed and are
    # excluded from generation rather than silently promoted.
    assert final.json()["model_gate"]["requires_human_confirmation"] >= 1


def test_pdf_preview_is_bounded_for_very_large_allowed_page(client):
    uploaded = client.post(
        "/drawings/analyze",
        data={"project_id": "1", "data_classification": "internal"},
        files={"file": ("large-sheet.pdf", _large_page_pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    drawing_id = uploaded.json()["document"]["id"]
    preview = client.get(f"/drawings/{drawing_id}/pages/1/preview")
    assert preview.status_code == 200, preview.text
    with Image.open(io.BytesIO(preview.content)) as image:
        assert max(image.size) <= MAX_PREVIEW_DIMENSION
        assert image.width * image.height <= MAX_PREVIEW_PIXELS


@pytest.mark.parametrize("payload", [
    {"field": "unit", "value": "banana"},
    {"field": "height", "value": "NaN"},
    {"field": "height", "value": "21"},
    {"field": "wall_thickness", "value": "0.01"},
    {"field": "source_calibration", "value": "11"},
    {"field": "scale", "value": "1:1000001"},
])
def test_compatibility_confirmations_cannot_bypass_typed_validation(client, payload):
    drawing_id = _upload_pdf(client).json()["document"]["id"]
    response = client.post(f"/drawings/{drawing_id}/confirm", json=payload)
    assert response.status_code == 422, response.text


def test_element_id_confirmation_uses_canonical_validation_and_rolls_back_atomically(client):
    body = _upload_pdf(client).json()
    drawing_id = body["document"]["id"]
    scale = next(row for row in body["elements"] if row["label"] == "scale")
    invalid_scale = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={"field": scale["id"], "value": "not-a-scale"},
    )
    assert invalid_scale.status_code == 422

    footprint = next(
        row for row in body["elements"]
        if row["properties"].get("geometry_type") == "RECTANGLE_FOOTPRINT"
    )
    partly_valid = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={
            "field": footprint["id"], "value": footprint["value"],
            "scale": "1:1000001",
        },
    )
    assert partly_valid.status_code == 422
    current = client.get(f"/drawings/{drawing_id}").json()
    unchanged = next(row for row in current["elements"] if row["id"] == footprint["id"])
    assert unchanged["state"] == "INFERRED"


def test_duplicate_canonical_confirmations_are_rejected_before_audit_writes(client):
    drawing_id = _upload_pdf(client).json()["document"]["id"]
    duplicate = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={"field": "height", "value": "4", "storey_height_m": 3.8},
    )
    assert duplicate.status_code == 422
    assert "Duplicate confirmation" in duplicate.text
    current = client.get(f"/drawings/{drawing_id}").json()
    assert not any(row["label"] == "height" for row in current["elements"])


def test_confirmation_text_lengths_match_database_columns(client):
    drawing_id = _upload_pdf(client).json()["document"]["id"]
    response = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={"field": "revision", "value": "R" * 33},
    )
    assert response.status_code == 422


def test_raster_pixel_budget_is_enforced_before_vision(client, monkeypatch):
    monkeypatch.setattr("app.drawings.MAX_RASTER_PIXELS", 100)
    response = client.post(
        "/drawings/analyze",
        data={"project_id": "1", "data_classification": "internal"},
        files={"file": ("oversized.png", _drawing_png(), "image/png")},
    )
    assert response.status_code == 422
    assert "40 megapixel" in response.text


def test_text_element_budget_aborts_during_spec_construction():
    lines = [
        ParsedLine(1, "DIMENSION 100 mm", [0.1, 0.1, 0.2, 0.2]),
        ParsedLine(1, "DIMENSION 200 mm", [0.2, 0.2, 0.3, 0.3]),
    ]
    with pytest.raises(HTTPException) as error:
        _element_specs(lines, max_elements=1)
    assert error.value.status_code == 422


def test_document_word_budget_is_enforced_before_persistence(client, monkeypatch):
    monkeypatch.setattr("app.drawings.MAX_DOCUMENT_WORDS", 1)
    response = _upload_pdf(client)
    assert response.status_code == 422
    assert "cumulative extracted-word" in response.text


def test_extracted_text_character_budgets_are_enforced(client, monkeypatch):
    monkeypatch.setattr("app.drawings.MAX_EXTRACTED_LINE_CHARS", 5)
    response = _upload_pdf(client)
    assert response.status_code == 422
    assert "overlong extracted text line" in response.text


def test_element_evidence_uses_bounded_excerpt_around_match():
    text = "PREFIX " + ("A" * 1_500) + " DIMENSION 100 mm " + ("Z" * 1_500)
    _, elements = _element_specs([ParsedLine(1, text, [0.1, 0.1, 0.9, 0.2])])
    dimension = next(row for row in elements if row["type"] == "DIMENSION")
    assert len(dimension["properties"]["source_text"]) == 1000
    assert "100 mm" in dimension["properties"]["source_text"]
    assert len(dimension["value"]) <= 500


def test_raster_drawing_is_retained_but_never_invented_without_ocr(client):
    response = client.post(
        "/drawings/analyze",
        data={"project_id": "1", "data_classification": "internal"},
        files={"file": ("scan.png", _drawing_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["status"] == "OCR_REQUIRED"
    assert body["analysis"]["status"] == "OCR_REQUIRED"
    assert body["elements"] == []
    assert body["model_gate"]["ready"] is False
    assert "OCR_REQUIRED" in body["model_gate"]["blockers"]
    assert "RASTER_CALIBRATION_REQUIRES_CONFIRMATION" in body["model_gate"]["blockers"]
    assert body["sheets"][0]["status"] == "OCR_REQUIRED"


def test_confirmed_geometry_generates_downloadable_draft_gltf_and_ifc(client):
    body = _upload_pdf(client).json()
    drawing_id = body["document"]["id"]
    space = next(
        row for row in body["elements"]
        if row["properties"].get("geometry_type") == "RECTANGLE_FOOTPRINT"
    )
    confirmed = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={
            "field": space["id"],
            "value": space["value"],
            "unit": "mm",
            "scale": "1:100",
            "storey_height_m": 3.8,
            "wall_thickness_m": 0.2,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["model_gate"]["ready"] is True

    generated = client.post(
        f"/drawings/{drawing_id}/model",
        json={"formats": ["GLTF", "IFC"], "publish": False},
    )
    assert generated.status_code == 201, generated.text
    model = generated.json()
    assert model["status"] == "DRAFT_GENERATED"
    assert model["boundary"] == "AI_GENERATED_DRAFT / NOT_FOR_CONSTRUCTION"
    assert model["validation"]["status"] == "PASSED"
    assert len(model["objects"]) == 5
    assert sum(row["object_type"] == "WALL" for row in model["objects"]) == 4
    assert model["manifest"]["input_element_count"] == 1
    assert model["manifest"]["derived_element_count"] == 4
    assert all(
        row["properties"]["derived_from"]
        for row in model["objects"] if row["object_type"] == "WALL"
    )
    assert model["publication_status"] == "NOT_PUBLISHED"
    assert model["objects"][0]["properties"]["evidence"]["page"] == 1
    assert {row["type"] for row in model["artifacts"]} == {"GLTF", "IFC"}

    gltf_url = next(row["url"].removeprefix("/backend") for row in model["artifacts"] if row["type"] == "GLTF")
    ifc_url = next(row["url"].removeprefix("/backend") for row in model["artifacts"] if row["type"] == "IFC")
    gltf = client.get(gltf_url)
    ifc = client.get(ifc_url)
    assert gltf.status_code == 200 and gltf.json()["meshes"]
    assert ifc.status_code == 200 and b"FILE_SCHEMA(('IFC4X3_ADD2'))" in ifc.content
    assert gltf.headers["x-data-provenance"] == "AI_GENERATED_DRAFT_NOT_FOR_CONSTRUCTION"
    assert ifc.headers["x-data-provenance"] == "AI_GENERATED_DRAFT_NOT_FOR_CONSTRUCTION"

    partial = client.post(
        f"/drawings/{drawing_id}/model",
        json={"formats": ["GLTF"], "publish": False},
    )
    assert partial.status_code == 422


def test_element_id_confirmation_updates_canonical_scale_and_unit(client):
    body = _upload_pdf(client).json()
    drawing_id = body["document"]["id"]
    scale = next(row for row in body["elements"] if row["label"] == "scale")
    unit = next(row for row in body["elements"] if row["label"] == "unit")
    footprint = next(
        row for row in body["elements"]
        if row["properties"].get("geometry_type") == "RECTANGLE_FOOTPRINT"
    )

    scale_response = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={"field": scale["id"], "value": "1:50"},
    )
    assert scale_response.status_code == 200
    assert scale_response.json()["document"]["scale"] == "1:50"
    unit_response = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={"field": unit["id"], "value": "m"},
    )
    assert unit_response.status_code == 200
    assert unit_response.json()["document"]["unit"] == "m"

    confirmed = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={
            "field": footprint["id"], "value": footprint["value"],
            "storey_height_m": 3.8, "wall_thickness_m": 0.2,
        },
    )
    assert confirmed.json()["model_gate"]["ready"] is True
    model = client.post(
        f"/drawings/{drawing_id}/model",
        json={"formats": ["GLTF", "IFC"], "publish": False},
    ).json()
    source = next(
        row for row in model["manifest"]["elements"]
        if row["source_id"] == footprint["id"]
    )
    assert source["dimensions_m"]["width"] == pytest.approx(
        550 * (0.0254 / 72) * 50
    )
    assert model["manifest"]["parameter_confirmations"]["scale"]["value"] == "1:50"


def test_text_label_bbox_cannot_be_promoted_to_model_geometry(client):
    body = _upload_pdf(client).json()
    drawing_id = body["document"]["id"]
    text_space = next(
        row for row in body["elements"]
        if row["type"] == "SPACE" and row["extraction_method"] == "PDF_VECTOR_TEXT"
    )
    result = client.post(
        f"/drawings/{drawing_id}/confirm",
        json={
            "field": text_space["id"], "value": text_space["value"],
            "unit": "mm", "scale": "1:100",
            "storey_height_m": 3.8, "wall_thickness_m": 0.2,
        },
    )
    assert result.status_code == 200
    assert result.json()["model_gate"]["ready"] is False
    assert "NO_CONFIRMED_GEOMETRY" in result.json()["model_gate"]["blockers"]
    blocked = client.post(
        f"/drawings/{drawing_id}/model",
        json={"formats": ["GLTF", "IFC"], "publish": False},
    )
    assert blocked.status_code == 409


def test_drawing_endpoints_do_not_leak_across_organizations(client):
    drawing_id = _upload_pdf(client).json()["document"]["id"]
    other = Principal(
        subject="other:engineer", organization_id="other-tenant",
        roles=frozenset({"organization_admin", "engineer"}),
        project_ids=frozenset(), issuer="test",
    )
    app.dependency_overrides[get_principal] = lambda: other
    try:
        assert all(row["id"] != drawing_id for row in client.get("/drawings").json())
        assert client.get(f"/drawings/{drawing_id}").status_code == 404
        assert client.get(f"/drawings/{drawing_id}/source").status_code == 404
        assert client.post(
            f"/drawings/{drawing_id}/ask", json={"question": "What is the scale?"}
        ).status_code == 404
    finally:
        app.dependency_overrides.pop(get_principal, None)


def test_internal_drawing_requires_project_and_project_scope_is_enforced(client):
    missing_project = client.post(
        "/drawings/analyze",
        data={"data_classification": "internal"},
        files={"file": ("scope.pdf", _drawing_pdf(), "application/pdf")},
    )
    assert missing_project.status_code == 422

    drawing_id = _upload_pdf(client).json()["document"]["id"]
    restricted = Principal(
        subject="same-org:engineer",
        organization_id="globalinfra-demo",
        roles=frozenset({"engineer"}),
        project_ids=frozenset({999}),
        issuer="test",
    )
    app.dependency_overrides[get_principal] = lambda: restricted
    try:
        assert all(row["id"] != drawing_id for row in client.get("/drawings").json())
        assert client.get(f"/drawings/{drawing_id}").status_code == 404
        assert client.get(f"/drawings/{drawing_id}/source").status_code == 404
    finally:
        app.dependency_overrides.pop(get_principal, None)


def test_configured_vision_extracts_reviewable_raster_evidence(client, monkeypatch):
    monkeypatch.setattr("app.drawings.is_llm_configured", lambda *args, **kwargs: True)

    async def fake_vision(*args, **kwargs):
        return json.dumps({"elements": [
            {
                "type": "METADATA", "label": "scale", "value": "1:50",
                "unit": None, "page": 1, "bbox": [0.7, 0.05, 0.9, 0.1],
                "confidence": 0.9, "source_text": "SCALE 1:50",
                "geometry_type": None,
            },
            {
                "type": "METADATA", "label": "unit", "value": "mm",
                "unit": None, "page": 1, "bbox": [0.7, 0.1, 0.9, 0.15],
                "confidence": 0.88, "source_text": "UNIT mm",
                "geometry_type": None,
            },
            {
                "type": "SPACE", "label": "room", "value": "Pump room",
                "unit": None, "page": 1, "bbox": [0.1, 0.2, 0.8, 0.85],
                "confidence": 0.82, "source_text": "PUMP ROOM",
                "geometry_type": "RECTANGLE_FOOTPRINT",
            },
            {
                "type": "DIMENSION", "label": "dimension", "value": "5000 mm",
                "unit": "mm", "page": 1, "bbox": [0.2, 0.8, 0.5, 0.84],
                "confidence": 0.86, "source_text": "5000 mm",
                "geometry_type": None,
            },
        ]})

    monkeypatch.setattr("app.drawings.generate_vision", fake_vision)
    response = client.post(
        "/drawings/analyze",
        data={"project_id": "1", "data_classification": "internal"},
        files={"file": ("scan.png", _drawing_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["status"] == "ANALYZED"
    assert body["document"]["scale"] == "1:50"
    assert body["analysis"]["summary"]["vision_status"] == "SUCCEEDED"
    assert body["sheets"][0]["status"] == "VISION_PARSED"
    assert all(row["state"] == "INFERRED" for row in body["elements"])
    assert all(row["evidence"]["bbox"] for row in body["elements"])
    assert "RASTER_CALIBRATION_REQUIRES_CONFIRMATION" in body["model_gate"]["blockers"]
