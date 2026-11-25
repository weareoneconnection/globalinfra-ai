import base64
import json

import pytest

from app.drawing_model_engine import ModelGenerationError, generate_draft_model


SOURCE_SHA = "a" * 64


def sample_elements():
    return [
        {
            "id": "W-01",
            "type": "WALL",
            "name": "North wall",
            "page": 1,
            "bbox": [0, 0, 0.8, 0.02],
            "geometry_bbox": [0, 0, 8, 0.2],
            "confidence": 0.98,
            "confirmed": True,
            "source_text": "200 mm wall",
        },
        {
            "id": "D-01",
            "type": "DOOR",
            "name": "Equipment room door",
            "page": 1,
            "bbox": [0.1, 0, 0.22, 0.02],
            "geometry_bbox": [1, 0, 2.2, 0.2],
            "confidence": 0.94,
            "confirmation_status": "USER_CONFIRMED",
        },
        {
            "id": "S-01",
            "type": "SPACE",
            "name": "Equipment room",
            "evidence": {
                "page": 1,
                "bbox": [0.02, 0.02, 0.78, 0.58],
                "source_text": "EQUIPMENT ROOM",
            },
            "geometry_bbox": [0.2, 0.2, 7.8, 5.8],
            "confidence": 0.91,
            "status": "CONFIRMED",
        },
        {
            "id": "EQ-01",
            "type": "EQUIPMENT",
            "name": "Switchboard",
            "page": 2,
            "bbox": [0.25, 0.1, 0.45, 0.18],
            "geometry_bbox": [2.5, 1.0, 4.5, 1.8],
            "confidence": 0.89,
            "status": "EXTRACTED_CONFIRMED",
        },
    ]


def sample_parameters():
    return {
        "unit": "m",
        "scale": 100,
        "meters_per_unit": 1,
        "storey_height_m": 3.6,
        "wall_thickness_m": 0.2,
        "door_height_m": 2.1,
        "equipment_height_m": 1.8,
    }


def generate():
    return generate_draft_model(
        drawing_id="METRO-EQ-REV-B",
        source_sha256=SOURCE_SHA,
        elements=sample_elements(),
        parameters=sample_parameters(),
    )


def test_generation_is_deterministic_and_evidence_bound():
    first = generate()
    second = generate()

    assert first.gltf == second.gltf
    assert first.ifc == second.ifc
    assert first.manifest == second.manifest
    assert first.manifest["construction_status"] == "NOT_FOR_CONSTRUCTION"
    assert first.manifest["element_count"] == 4
    assert len({row["twin_id"] for row in first.manifest["elements"]}) == 4
    assert all(row["evidence"]["page"] >= 1 for row in first.manifest["elements"])
    assert all(len(row["evidence"]["bbox"]) == 4 for row in first.manifest["elements"])
    assert first.validation["status"] == "PASSED"
    assert first.validation["checks"]["all_input_elements_user_confirmed"] is True
    assert first.validation["checks"]["derived_elements_traceable"] is True
    assert "all_elements_user_confirmed" not in first.validation["checks"]


def test_gltf_contains_real_mesh_accessors_and_embedded_buffer():
    payload = json.loads(generate().gltf)

    assert payload["asset"]["version"] == "2.0"
    assert payload["asset"]["extras"]["construction_status"] == "NOT_FOR_CONSTRUCTION"
    assert payload["meshes"]
    assert payload["accessors"][0]["type"] == "VEC3"
    assert payload["accessors"][1]["count"] == 36
    assert all("mesh" in node for node in payload["nodes"])
    encoded = payload["buffers"][0]["uri"].split(",", 1)[1]
    binary = base64.b64decode(encoded)
    assert len(binary) == payload["buffers"][0]["byteLength"]
    assert all(node["extras"]["evidence"]["bbox"] for node in payload["nodes"])


def test_ifc_has_draft_hierarchy_semantics_and_source_evidence():
    text = generate().ifc.decode()

    assert "FILE_SCHEMA(('IFC4X3_ADD2'))" in text
    assert "IFCPROJECT(" in text
    assert "IFCSITE(" in text
    assert "IFCBUILDING(" in text
    assert "IFCBUILDINGSTOREY(" in text
    assert "IFCWALL(" in text
    assert "IFCDOOR(" in text
    assert "IFCSPACE(" in text
    assert "IFCBUILDINGELEMENTPROXY(" in text
    assert "Pset_GlobalInfraEvidence" in text
    assert SOURCE_SHA in text
    assert "NOT_FOR_CONSTRUCTION" in text


def test_confirmed_rectangle_derives_traceable_perimeter_walls():
    element = {
        "id": "S-RECT",
        "type": "SPACE",
        "name": "Reviewed footprint",
        "page": 1,
        "bbox": [0.1, 0.1, 0.9, 0.9],
        "geometry_bbox": [0, 0, 8, 6],
        "confidence": 0.9,
        "status": "USER_CONFIRMED",
        "properties": {"geometry_type": "RECTANGLE_FOOTPRINT"},
    }
    result = generate_draft_model(
        drawing_id="RECTANGLE",
        source_sha256=SOURCE_SHA,
        elements=[element],
        parameters=sample_parameters(),
    )
    assert result.manifest["element_count"] == 5
    assert result.manifest["input_element_count"] == 1
    assert result.manifest["derived_element_count"] == 4
    walls = [row for row in result.manifest["elements"] if row["element_type"] == "WALL"]
    assert len(walls) == 4
    assert all(row["derived_from"] == "S-RECT" for row in walls)
    assert all(row["derivation_rule"] == "RECTANGLE_PERIMETER_WALLS_V1" for row in walls)
    assert all(
        row["evidence"]["status"] == "DERIVED_FROM_CONFIRMED_FOOTPRINT"
        for row in walls
    )
    assert "Drawing draft spatial decomposition" in result.ifc.decode()
    assert "DerivationRule" in result.ifc.decode()


def test_diagonal_vector_wall_preserves_rotation_and_exact_line_length():
    wall = {
        "id": "W-DIAGONAL",
        "type": "WALL",
        "name": "Diagonal wall",
        "page": 1,
        "bbox": [0.1, 0.1, 0.8, 0.8],
        "geometry_bbox": [0, 0, 7.1, 7.1],
        "confidence": 0.9,
        "status": "USER_CONFIRMED",
        "properties": {"rotation_deg": 45, "line_length_points": 10},
    }
    result = generate_draft_model(
        drawing_id="DIAGONAL",
        source_sha256=SOURCE_SHA,
        elements=[wall],
        parameters=sample_parameters(),
    )
    row = result.manifest["elements"][0]
    assert row["dimensions_m"]["width"] == 10
    assert row["rotation_degrees"] == 45
    assert json.loads(result.gltf)["nodes"][0]["rotation"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda parameters, elements: parameters.pop("scale"), "scale"),
        (lambda parameters, elements: parameters.pop("storey_height_m"), "storey_height_m"),
        (lambda parameters, elements: elements[0].update(confirmed=False, status="EXTRACTED"), "not user-confirmed"),
        (lambda parameters, elements: elements[1].pop("page"), "source page"),
    ],
)
def test_generation_fails_closed_when_required_evidence_is_missing(mutation, message):
    parameters = sample_parameters()
    elements = sample_elements()
    mutation(parameters, elements)

    with pytest.raises(ModelGenerationError, match=message):
        generate_draft_model(
            drawing_id="METRO-EQ-REV-B",
            source_sha256=SOURCE_SHA,
            elements=elements,
            parameters=parameters,
        )
