"""Deterministic drawing-to-twin draft model generation.

This module deliberately implements a narrow, auditable contract.  It turns
*confirmed* drawing elements into a real glTF mesh and an IFC4X3 draft model,
while retaining a source-page/bounding-box evidence link for every object.

It is not a free-form generative model and it never fills missing engineering
parameters.  Callers must provide confirmed units, scale and vertical
dimensions; otherwise generation fails closed with :class:`ModelGenerationError`.
The resulting artifacts are always labelled ``NOT_FOR_CONSTRUCTION``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SUPPORTED_ELEMENT_TYPES = frozenset({"WALL", "DOOR", "SPACE", "EQUIPMENT"})
CONFIRMED_STATES = frozenset({"CONFIRMED", "USER_CONFIRMED", "EXTRACTED_CONFIRMED"})
IFC_GUID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


class ModelGenerationError(ValueError):
    """Raised when evidence or confirmed engineering parameters are missing."""


@dataclass(frozen=True)
class DraftModelArtifacts:
    """Commit-ready bytes plus their audit manifest and validation report."""

    gltf: bytes
    ifc: bytes
    manifest: dict[str, Any]
    validation: dict[str, Any]


@dataclass(frozen=True)
class _ModelElement:
    source_id: str
    element_type: str
    name: str
    page: int
    bbox: tuple[float, float, float, float]
    confidence: float
    evidence_status: str
    source_text: str
    twin_id: str
    ifc_guid: str
    center_x: float
    center_y: float
    width: float
    depth: float
    height: float
    elevation: float
    rotation_radians: float
    derived_from: str | None
    derivation_rule: str | None


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _ifc_guid(seed: str) -> str:
    """Return a deterministic 22-character IFC compressed-GUID value.

    IFC's alphabet is a base-64 encoding of a 128-bit identifier.  Encoding the
    first 128 bits of a SHA-256 digest gives a stable value whose first digit is
    necessarily in the permitted 0-3 range.
    """

    value = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:16], "big")
    chars = ["0"] * 22
    for index in range(21, -1, -1):
        chars[index] = IFC_GUID_ALPHABET[value & 0x3F]
        value >>= 6
    return "".join(chars)


def _step_text(value: Any) -> str:
    text = str(value).replace("'", "''")
    return "".join(character if ord(character) >= 32 else " " for character in text)


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise ModelGenerationError("Model geometry contains a non-finite number")
    rendered = f"{value:.6f}".rstrip("0").rstrip(".")
    if "." not in rendered:
        rendered += "."
    return rendered


def _required_positive(parameters: Mapping[str, Any], key: str) -> float:
    try:
        value = float(parameters[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelGenerationError(f"Confirmed parameter '{key}' is required") from exc
    if not math.isfinite(value) or value <= 0:
        raise ModelGenerationError(f"Confirmed parameter '{key}' must be positive")
    return value


def _unit_factor(parameters: Mapping[str, Any]) -> tuple[str, float]:
    unit = str(parameters.get("unit", "")).strip().lower()
    if not unit:
        raise ModelGenerationError("Confirmed drawing unit is required")

    explicit = parameters.get("meters_per_unit")
    if explicit is not None:
        try:
            factor = float(explicit)
        except (TypeError, ValueError) as exc:
            raise ModelGenerationError("meters_per_unit must be numeric") from exc
        if not math.isfinite(factor) or factor <= 0:
            raise ModelGenerationError("meters_per_unit must be positive")
        return unit, factor

    factors = {"m": 1.0, "metre": 1.0, "meter": 1.0, "cm": 0.01, "mm": 0.001}
    if unit not in factors:
        raise ModelGenerationError(
            "Pixel/point drawing coordinates require confirmed meters_per_unit"
        )
    return unit, factors[unit]


def _raw_evidence(element: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence = element.get("evidence")
    return evidence if isinstance(evidence, Mapping) else element


def _bbox(element: Mapping[str, Any]) -> tuple[float, float, float, float]:
    evidence = _raw_evidence(element)
    raw = evidence.get("bbox", element.get("bbox"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 4:
        raise ModelGenerationError("Every model element requires a four-number source bbox")
    try:
        x0, y0, x1, y1 = (float(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise ModelGenerationError("Source bbox values must be numeric") from exc
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise ModelGenerationError("Source bbox values must be finite")
    if x1 <= x0 or y1 <= y0:
        raise ModelGenerationError("Source bbox must have positive width and height")
    return x0, y0, x1, y1


def _geometry_bbox(element: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """Return model-space coordinates while source evidence stays normalized."""
    raw = element.get("geometry_bbox")
    if raw is None:
        return _bbox(element)
    return _bbox({"bbox": raw})


def _is_confirmed(element: Mapping[str, Any]) -> tuple[bool, str]:
    state = str(
        element.get("confirmation_status")
        or element.get("evidence_status")
        or element.get("status")
        or ""
    ).strip().upper()
    return element.get("confirmed") is True or state in CONFIRMED_STATES, state


def _element_property(element: Mapping[str, Any], key: str) -> Any:
    properties = element.get("properties")
    if isinstance(properties, Mapping) and key in properties:
        return properties[key]
    return element.get(key)


def _normalise_elements(
    drawing_id: str,
    source_sha256: str,
    elements: Sequence[Mapping[str, Any]],
    parameters: Mapping[str, Any],
) -> list[_ModelElement]:
    if not elements:
        raise ModelGenerationError("At least one confirmed drawing element is required")
    if len(elements) > 2_000:
        raise ModelGenerationError("Draft BIM accepts at most 2,000 confirmed elements per run")

    _, metres_per_unit = _unit_factor(parameters)
    _required_positive(parameters, "scale")
    storey_height = _required_positive(parameters, "storey_height_m")
    wall_thickness = _required_positive(parameters, "wall_thickness_m")
    elevation = float(parameters.get("storey_elevation_m", 0.0))
    if not math.isfinite(elevation):
        raise ModelGenerationError("storey_elevation_m must be finite")

    provisional: list[tuple[str, Mapping[str, Any]]] = []
    for raw in elements:
        if not isinstance(raw, Mapping):
            raise ModelGenerationError("Drawing elements must be objects")
        element_type = str(
            raw.get("element_type") or raw.get("type") or raw.get("kind") or ""
        ).strip().upper()
        if element_type not in SUPPORTED_ELEMENT_TYPES:
            raise ModelGenerationError(f"Unsupported drawing element type: {element_type or 'EMPTY'}")
        source_id = str(raw.get("id") or raw.get("element_id") or "").strip()
        if not source_id:
            source_id = "E-" + _sha(_canonical(raw))[:16].upper()
        provisional.append((f"{element_type}:{source_id}", raw))

    output: list[_ModelElement] = []
    for _, raw in sorted(provisional, key=lambda item: item[0]):
        element_type = str(
            raw.get("element_type") or raw.get("type") or raw.get("kind")
        ).strip().upper()
        source_id = str(raw.get("id") or raw.get("element_id") or "").strip()
        if not source_id:
            source_id = "E-" + _sha(_canonical(raw))[:16].upper()
        confirmed, state = _is_confirmed(raw)
        if not confirmed:
            raise ModelGenerationError(
                f"Element '{source_id}' is not user-confirmed and cannot enter Draft BIM"
            )

        evidence = _raw_evidence(raw)
        try:
            page = int(evidence.get("page", raw.get("page")))
        except (TypeError, ValueError) as exc:
            raise ModelGenerationError(f"Element '{source_id}' requires a source page") from exc
        if page < 1:
            raise ModelGenerationError(f"Element '{source_id}' source page must be >= 1")
        source_bbox = _bbox(raw)
        geometry_bbox = _geometry_bbox(raw)
        if not all(0 <= coordinate <= 1 for coordinate in source_bbox):
            raise ModelGenerationError(
                f"Element '{source_id}' source bbox must use normalized page coordinates"
            )
        try:
            confidence = float(raw.get("confidence", evidence.get("confidence", 1.0)))
        except (TypeError, ValueError) as exc:
            raise ModelGenerationError(f"Element '{source_id}' confidence must be numeric") from exc
        if not 0 <= confidence <= 1:
            raise ModelGenerationError(f"Element '{source_id}' confidence must be between 0 and 1")

        x0, y0, x1, y1 = geometry_bbox
        bbox_width = (x1 - x0) * metres_per_unit
        bbox_depth = (y1 - y0) * metres_per_unit
        center_x = ((x0 + x1) / 2) * metres_per_unit
        center_y = ((y0 + y1) / 2) * metres_per_unit

        rotation_value = _element_property(raw, "rotation_deg")
        if rotation_value is None:
            rotation_value = _element_property(raw, "rotation_degrees")
        if rotation_value is None and element_type in {"WALL", "DOOR"}:
            rotation_radians = math.pi / 2 if bbox_depth > bbox_width else 0.0
        else:
            try:
                rotation_radians = math.radians(float(rotation_value or 0.0))
            except (TypeError, ValueError) as exc:
                raise ModelGenerationError(
                    f"Element '{source_id}' rotation must be numeric"
                ) from exc
        if not math.isfinite(rotation_radians):
            raise ModelGenerationError(f"Element '{source_id}' rotation must be finite")

        if element_type == "WALL":
            line_length = _element_property(raw, "line_length_points")
            width = (
                float(line_length) * metres_per_unit
                if line_length is not None
                else max(bbox_width, bbox_depth)
            )
            depth = float(_element_property(raw, "thickness_m") or wall_thickness)
            height = float(_element_property(raw, "height_m") or storey_height)
        elif element_type == "DOOR":
            width = float(_element_property(raw, "width_m") or max(bbox_width, bbox_depth))
            depth = float(_element_property(raw, "thickness_m") or wall_thickness / 2)
            height_value = _element_property(raw, "height_m") or parameters.get("door_height_m")
            if height_value is None:
                raise ModelGenerationError(
                    f"Element '{source_id}' requires confirmed door_height_m"
                )
            height = float(height_value)
        elif element_type == "SPACE":
            width = bbox_width
            depth = bbox_depth
            # A thin plate makes the reviewed footprint visible without
            # pretending that a slab thickness was present in the drawing.
            height = 0.02
        else:  # EQUIPMENT
            width = bbox_width
            depth = bbox_depth
            height_value = _element_property(raw, "height_m") or parameters.get(
                "equipment_height_m"
            )
            if height_value is None:
                raise ModelGenerationError(
                    f"Element '{source_id}' requires confirmed equipment_height_m"
                )
            height = float(height_value)

        if not all(
            math.isfinite(value) and value > 0 for value in (width, depth, height)
        ):
            raise ModelGenerationError(f"Element '{source_id}' has invalid confirmed dimensions")

        identity_seed = (
            f"{source_sha256}:{drawing_id}:{element_type}:{source_id}:"
            f"{source_bbox}:{geometry_bbox}"
        )
        twin_id = "TWIN-DRW-" + hashlib.sha256(identity_seed.encode()).hexdigest()[:20].upper()
        base_element = _ModelElement(
                source_id=source_id,
                element_type=element_type,
                name=str(raw.get("name") or raw.get("label") or f"{element_type} {source_id}"),
                page=page,
                bbox=source_bbox,
                confidence=confidence,
                evidence_status=state or "USER_CONFIRMED",
                source_text=str(evidence.get("source_text", raw.get("source_text", ""))),
                twin_id=twin_id,
                ifc_guid=_ifc_guid(identity_seed),
                center_x=center_x,
                center_y=center_y,
                width=width,
                depth=depth,
                height=height,
                elevation=elevation,
                rotation_radians=rotation_radians,
                derived_from=None,
                derivation_rule=None,
            )
        output.append(base_element)

        # One confirmed vector enclosure represents a reviewed footprint.  Four
        # perimeter walls are derived deterministically from it and keep the
        # exact same source evidence.  They are draft geometry, never inferred
        # semantic construction objects.
        if (
            element_type == "SPACE"
            and str(_element_property(raw, "geometry_type") or "").upper()
            == "RECTANGLE_FOOTPRINT"
        ):
            x0m, y0m, x1m, y1m = (
                x0 * metres_per_unit,
                y0 * metres_per_unit,
                x1 * metres_per_unit,
                y1 * metres_per_unit,
            )
            segments = (
                ("N", (x0m + x1m) / 2, y0m, bbox_width, 0.0),
                ("S", (x0m + x1m) / 2, y1m, bbox_width, 0.0),
                ("W", x0m, (y0m + y1m) / 2, bbox_depth, math.pi / 2),
                ("E", x1m, (y0m + y1m) / 2, bbox_depth, math.pi / 2),
            )
            for side, wall_x, wall_y, wall_length, wall_rotation in segments:
                derived_id = f"{source_id}:WALL:{side}"
                derived_seed = f"{identity_seed}:derived-wall:{side}"
                output.append(
                    _ModelElement(
                        source_id=derived_id,
                        element_type="WALL",
                        name=f"{base_element.name} perimeter {side}",
                        page=page,
                        bbox=source_bbox,
                        confidence=confidence,
                        evidence_status="DERIVED_FROM_CONFIRMED_FOOTPRINT",
                        source_text=base_element.source_text,
                        twin_id="TWIN-DRW-"
                        + hashlib.sha256(derived_seed.encode()).hexdigest()[:20].upper(),
                        ifc_guid=_ifc_guid(derived_seed),
                        center_x=wall_x,
                        center_y=wall_y,
                        width=wall_length,
                        depth=wall_thickness,
                        height=storey_height,
                        elevation=elevation,
                        rotation_radians=wall_rotation,
                        derived_from=source_id,
                        derivation_rule="RECTANGLE_PERIMETER_WALLS_V1",
                    )
                )
    return output


def _build_gltf(drawing_id: str, elements: Sequence[_ModelElement]) -> bytes:
    positions = [
        -0.5, -0.5, -0.5,
        0.5, -0.5, -0.5,
        0.5, 0.5, -0.5,
        -0.5, 0.5, -0.5,
        -0.5, -0.5, 0.5,
        0.5, -0.5, 0.5,
        0.5, 0.5, 0.5,
        -0.5, 0.5, 0.5,
    ]
    indices = [
        0, 1, 2, 0, 2, 3,
        4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1,
        1, 5, 6, 1, 6, 2,
        2, 6, 7, 2, 7, 3,
        3, 7, 4, 3, 4, 0,
    ]
    position_bytes = struct.pack("<24f", *positions)
    index_bytes = struct.pack("<36H", *indices)
    binary = position_bytes + index_bytes

    palette = {
        "WALL": [0.24, 0.62, 0.72, 1.0],
        "DOOR": [0.86, 0.58, 0.20, 1.0],
        "SPACE": [0.25, 0.70, 0.52, 0.35],
        "EQUIPMENT": [0.58, 0.42, 0.82, 1.0],
    }
    types = sorted({element.element_type for element in elements})
    materials = [
        {
            "name": f"{element_type} draft",
            "doubleSided": True,
            "alphaMode": "BLEND" if element_type == "SPACE" else "OPAQUE",
            "pbrMetallicRoughness": {
                "baseColorFactor": palette[element_type],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.85,
            },
            "extensions": {"KHR_materials_unlit": {}},
        }
        for element_type in types
    ]
    material_by_type = {element_type: index for index, element_type in enumerate(types)}
    meshes = [
        {
            "name": f"{element_type} evidence box",
            "primitives": [
                {
                    "attributes": {"POSITION": 0},
                    "indices": 1,
                    "material": material_by_type[element_type],
                    "mode": 4,
                }
            ],
        }
        for element_type in types
    ]
    mesh_by_type = {element_type: index for index, element_type in enumerate(types)}

    nodes = []
    for element in elements:
        node = {
                "name": element.name,
                "mesh": mesh_by_type[element.element_type],
                # glTF is Y-up. Drawing Y maps to negative world Z.
                "translation": [
                    round(element.center_x, 6),
                    round(element.elevation + element.height / 2, 6),
                    round(-element.center_y, 6),
                ],
                "scale": [
                    round(element.width, 6),
                    round(element.height, 6),
                    round(element.depth, 6),
                ],
                "extras": {
                    "twin_id": element.twin_id,
                    "ifc_guid": element.ifc_guid,
                    "element_type": element.element_type,
                    "source_id": element.source_id,
                    "derived_from": element.derived_from,
                    "derivation_rule": element.derivation_rule,
                    "construction_status": "NOT_FOR_CONSTRUCTION",
                    "evidence": {
                        "page": element.page,
                        "bbox": list(element.bbox),
                        "coordinate_space": "NORMALIZED_SOURCE_PAGE",
                        "confidence": element.confidence,
                        "status": element.evidence_status,
                    },
                },
            }
        if element.rotation_radians:
            # Drawing XY maps to glTF X/-Z, so plan rotation is around -Y.
            half_angle = -element.rotation_radians / 2
            node["rotation"] = [0.0, round(math.sin(half_angle), 9), 0.0, round(math.cos(half_angle), 9)]
        nodes.append(node)

    payload = {
        "asset": {
            "version": "2.0",
            "generator": "GlobalInfra AI Drawing-to-Twin Draft Engine",
            "extras": {
                "provenance": "AI_GENERATED_DRAFT",
                "construction_status": "NOT_FOR_CONSTRUCTION",
                "drawing_id": drawing_id,
            },
        },
        "extensionsUsed": ["KHR_materials_unlit"],
        "scene": 0,
        "scenes": [{"name": drawing_id, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "buffers": [
            {
                "byteLength": len(binary),
                "uri": "data:application/octet-stream;base64,"
                + base64.b64encode(binary).decode("ascii"),
            }
        ],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(position_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(position_bytes),
                "byteLength": len(index_bytes),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": [-0.5, -0.5, -0.5],
                "max": [0.5, 0.5, 0.5],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": 36,
                "type": "SCALAR",
                "min": [0],
                "max": [7],
            },
        ],
    }
    return _canonical(payload)


class _IfcBuilder:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, expression: str) -> str:
        reference = f"#{len(self.lines) + 1}"
        self.lines.append(f"{reference}={expression};")
        return reference


def _build_ifc(
    drawing_id: str,
    source_sha256: str,
    elements: Sequence[_ModelElement],
) -> bytes:
    builder = _IfcBuilder()
    person = builder.add("IFCPERSON($,$,'GlobalInfra AI',$,$,$,$,$)")
    organisation = builder.add("IFCORGANIZATION($,'GlobalInfra AI',$,$,$)")
    person_org = builder.add(f"IFCPERSONANDORGANIZATION({person},{organisation},$)")
    application = builder.add(
        f"IFCAPPLICATION({organisation},'6.1-P0P2','Drawing-to-Twin Copilot','GLOBALINFRA_DRAWING')"
    )
    owner = builder.add(
        f"IFCOWNERHISTORY({person_org},{application},$,.ADDED.,$,$,$,0)"
    )

    origin = builder.add("IFCCARTESIANPOINT((0.,0.,0.))")
    z_axis = builder.add("IFCDIRECTION((0.,0.,1.))")
    x_axis = builder.add("IFCDIRECTION((1.,0.,0.))")
    world_axis = builder.add(f"IFCAXIS2PLACEMENT3D({origin},{z_axis},{x_axis})")
    context = builder.add(
        f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,{world_axis},$)"
    )
    metre = builder.add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    units = builder.add(f"IFCUNITASSIGNMENT(({metre}))")
    project = builder.add(
        "IFCPROJECT("
        f"'{_ifc_guid(drawing_id + ':project')}',{owner},"
        f"'{_step_text(drawing_id)} - Drawing Draft','AI_GENERATED_DRAFT / NOT_FOR_CONSTRUCTION',"
        f"$,$,$,({context}),{units})"
    )

    site_placement = builder.add(f"IFCLOCALPLACEMENT($,{world_axis})")
    site = builder.add(
        "IFCSITE("
        f"'{_ifc_guid(drawing_id + ':site')}',{owner},'Drawing Site',"
        f"'NOT_FOR_CONSTRUCTION',$,{site_placement},$,$,.ELEMENT.,$,$,$,$,$)"
    )
    building_placement = builder.add(f"IFCLOCALPLACEMENT({site_placement},{world_axis})")
    building = builder.add(
        "IFCBUILDING("
        f"'{_ifc_guid(drawing_id + ':building')}',{owner},'Drawing Building',"
        f"'NOT_FOR_CONSTRUCTION',$,{building_placement},$,$,.ELEMENT.,$,$,$)"
    )
    storey_placement = builder.add(f"IFCLOCALPLACEMENT({building_placement},{world_axis})")
    storey = builder.add(
        "IFCBUILDINGSTOREY("
        f"'{_ifc_guid(drawing_id + ':storey')}',{owner},'Drawing Storey',"
        f"'NOT_FOR_CONSTRUCTION',$,{storey_placement},$,$,.ELEMENT.,0.)"
    )
    builder.add(
        f"IFCRELAGGREGATES('{_ifc_guid(drawing_id + ':project-site')}',{owner},$,$,{project},({site}))"
    )
    builder.add(
        f"IFCRELAGGREGATES('{_ifc_guid(drawing_id + ':site-building')}',{owner},$,$,{site},({building}))"
    )
    builder.add(
        f"IFCRELAGGREGATES('{_ifc_guid(drawing_id + ':building-storey')}',{owner},$,$,{building},({storey}))"
    )

    contained_product_refs: list[str] = []
    spatial_refs: list[str] = []
    for element in elements:
        placement_point = builder.add(
            "IFCCARTESIANPOINT(("
            f"{_number(element.center_x)},{_number(element.center_y)},{_number(element.elevation)}))"
        )
        element_x_axis = builder.add(
            "IFCDIRECTION(("
            f"{_number(math.cos(element.rotation_radians))},"
            f"{_number(math.sin(element.rotation_radians))},0.))"
        )
        placement_axis = builder.add(
            f"IFCAXIS2PLACEMENT3D({placement_point},{z_axis},{element_x_axis})"
        )
        placement = builder.add(f"IFCLOCALPLACEMENT({storey_placement},{placement_axis})")
        profile_origin = builder.add("IFCCARTESIANPOINT((0.,0.))")
        profile_axis = builder.add(f"IFCAXIS2PLACEMENT2D({profile_origin},$)")
        profile = builder.add(
            "IFCRECTANGLEPROFILEDEF("
            f".AREA.,'{_step_text(element.element_type)}',"
            f"{profile_axis},{_number(element.width)},{_number(element.depth)})"
        )
        solid_origin = builder.add("IFCCARTESIANPOINT((0.,0.,0.))")
        solid_axis = builder.add(f"IFCAXIS2PLACEMENT3D({solid_origin},{z_axis},{x_axis})")
        solid = builder.add(
            f"IFCEXTRUDEDAREASOLID({profile},{solid_axis},{z_axis},{_number(element.height)})"
        )
        representation = builder.add(
            f"IFCSHAPEREPRESENTATION({context},'Body','SweptSolid',({solid}))"
        )
        product_shape = builder.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({representation}))")
        description = "AI_GENERATED_DRAFT / NOT_FOR_CONSTRUCTION"
        name = _step_text(element.name)
        tag = _step_text(element.twin_id)
        if element.element_type == "WALL":
            product = builder.add(
                f"IFCWALL('{element.ifc_guid}',{owner},'{name}','{description}',$,"
                f"{placement},{product_shape},'{tag}',.NOTDEFINED.)"
            )
        elif element.element_type == "DOOR":
            product = builder.add(
                f"IFCDOOR('{element.ifc_guid}',{owner},'{name}','{description}',$,"
                f"{placement},{product_shape},'{tag}',{_number(element.height)},"
                f"{_number(element.width)},.DOOR.,.NOTDEFINED.,$)"
            )
        elif element.element_type == "SPACE":
            product = builder.add(
                f"IFCSPACE('{element.ifc_guid}',{owner},'{name}','{description}',$,"
                f"{placement},{product_shape},'{tag}',.ELEMENT.,$,$)"
            )
        else:
            product = builder.add(
                f"IFCBUILDINGELEMENTPROXY('{element.ifc_guid}',{owner},'{name}',"
                f"'{description}','EQUIPMENT',{placement},{product_shape},'{tag}',.NOTDEFINED.)"
            )
        if element.element_type == "SPACE":
            spatial_refs.append(product)
        else:
            contained_product_refs.append(product)

        evidence_values = {
            "TwinId": element.twin_id,
            "SourceDocumentSha256": source_sha256,
            "SourcePage": str(element.page),
            "SourceBBoxNormalized": json.dumps(list(element.bbox), separators=(",", ":")),
            "SourceText": element.source_text,
            "Confidence": f"{element.confidence:.6f}",
            "EvidenceStatus": element.evidence_status,
            "GenerationStatus": "AI_GENERATED_DRAFT",
            "ConstructionStatus": "NOT_FOR_CONSTRUCTION",
        }
        if element.derived_from is not None:
            evidence_values["DerivedFrom"] = element.derived_from
            evidence_values["DerivationRule"] = element.derivation_rule or "DETERMINISTIC_DERIVATION"
        properties = [
            builder.add(
                f"IFCPROPERTYSINGLEVALUE('{_step_text(key)}',$,"
                f"IFCTEXT('{_step_text(value)}'),$)"
            )
            for key, value in evidence_values.items()
        ]
        property_set = builder.add(
            "IFCPROPERTYSET("
            f"'{_ifc_guid(element.twin_id + ':evidence')}',{owner},"
            f"'Pset_GlobalInfraEvidence','Source drawing evidence',({','.join(properties)}))"
        )
        builder.add(
            "IFCRELDEFINESBYPROPERTIES("
            f"'{_ifc_guid(element.twin_id + ':evidence-rel')}',{owner},$,$,"
            f"({product}),{property_set})"
        )

    if spatial_refs:
        builder.add(
            "IFCRELAGGREGATES("
            f"'{_ifc_guid(drawing_id + ':storey-spaces')}',{owner},"
            f"'Drawing draft spatial decomposition',$,{storey},({','.join(spatial_refs)}))"
        )
    if contained_product_refs:
        builder.add(
            "IFCRELCONTAINEDINSPATIALSTRUCTURE("
            f"'{_ifc_guid(drawing_id + ':containment')}',{owner},'Drawing draft containment',$,"
            f"({','.join(contained_product_refs)}),{storey})"
        )

    safe_name = _step_text(drawing_id).replace("/", "-")
    header = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]','AI_GENERATED_DRAFT','NOT_FOR_CONSTRUCTION'),'2;1');",
        f"FILE_NAME('{safe_name}.ifc','1970-01-01T00:00:00',('GlobalInfra AI'),('GlobalInfra AI'),'Drawing-to-Twin Copilot','Draft BIM','');",
        "FILE_SCHEMA(('IFC4X3_ADD2'));",
        "ENDSEC;",
        "DATA;",
    ]
    return ("\n".join(header + builder.lines + ["ENDSEC;", "END-ISO-10303-21;", ""])).encode(
        "utf-8"
    )


def generate_draft_model(
    *,
    drawing_id: str,
    source_sha256: str,
    elements: Sequence[Mapping[str, Any]],
    parameters: Mapping[str, Any],
) -> DraftModelArtifacts:
    """Generate deterministic glTF and IFC4X3 draft artifacts.

    ``elements`` must contain one of ``WALL``, ``DOOR``, ``SPACE`` or
    ``EQUIPMENT`` together with a confirmed state and source evidence
    ``page``/``bbox``.  ``parameters`` must provide confirmed ``unit``,
    ``scale``, ``storey_height_m`` and ``wall_thickness_m`` values, plus
    element-specific heights when applicable.
    """

    drawing_id = drawing_id.strip()
    source_sha256 = source_sha256.strip().lower()
    if not drawing_id:
        raise ModelGenerationError("drawing_id is required")
    if len(source_sha256) != 64 or any(character not in "0123456789abcdef" for character in source_sha256):
        raise ModelGenerationError("source_sha256 must be a 64-character hexadecimal digest")

    normalised = _normalise_elements(
        drawing_id, source_sha256, elements, parameters
    )
    gltf = _build_gltf(drawing_id, normalised)
    ifc = _build_ifc(drawing_id, source_sha256, normalised)

    manifest_elements = [
        {
            "source_id": element.source_id,
            "name": element.name,
            "element_type": element.element_type,
            "twin_id": element.twin_id,
            "ifc_guid": element.ifc_guid,
            "derived_from": element.derived_from,
            "derivation_rule": element.derivation_rule,
            "dimensions_m": {
                "width": element.width,
                "depth": element.depth,
                "height": element.height,
            },
            "rotation_degrees": round(math.degrees(element.rotation_radians), 6),
            "evidence": {
                "page": element.page,
                "bbox": list(element.bbox),
                "coordinate_space": "NORMALIZED_SOURCE_PAGE",
                "confidence": element.confidence,
                "status": element.evidence_status,
            },
        }
        for element in normalised
    ]
    validation = {
        "status": "PASSED",
        "profile": "GLOBALINFRA_DRAFT_BIM_V1",
        "schema": "IFC4X3_ADD2",
        "checks": {
            "all_input_elements_user_confirmed": all(
                element.derived_from is not None
                or element.evidence_status in CONFIRMED_STATES
                for element in normalised
            ),
            "derived_elements_traceable": all(
                element.derived_from is None
                or (
                    element.evidence_status == "DERIVED_FROM_CONFIRMED_FOOTPRINT"
                    and bool(element.derivation_rule)
                )
                for element in normalised
            ),
            "all_elements_evidence_bound": all(
                element.page >= 1 and len(element.bbox) == 4 for element in normalised
            ),
            "stable_twin_ids": len({element.twin_id for element in normalised})
            == len(normalised),
            "gltf_has_mesh": b'"meshes"' in gltf and b'"accessors"' in gltf,
            "ifc_spatial_hierarchy": all(
                token in ifc
                for token in (
                    b"IFCPROJECT",
                    b"IFCSITE",
                    b"IFCBUILDING(",
                    b"IFCBUILDINGSTOREY",
                )
            ),
            "draft_boundary_embedded": b"NOT_FOR_CONSTRUCTION" in ifc
            and b"NOT_FOR_CONSTRUCTION" in gltf,
        },
        "warnings": [
            "AI-generated Draft BIM requires qualified engineering review before any project use.",
            "No construction authorization is implied by successful schema-shaped generation.",
        ],
    }
    if not all(validation["checks"].values()):  # pragma: no cover - invariant guard
        raise ModelGenerationError("Generated artifacts failed internal validation")

    manifest = {
        "contract": "globalinfra.drawing-to-twin.v1",
        "drawing_id": drawing_id,
        "source_sha256": source_sha256,
        "provenance": "AI_GENERATED_DRAFT",
        "construction_status": "NOT_FOR_CONSTRUCTION",
        "schema": "IFC4X3_ADD2",
        "element_count": len(normalised),
        "input_element_count": sum(element.derived_from is None for element in normalised),
        "derived_element_count": sum(element.derived_from is not None for element in normalised),
        "elements": manifest_elements,
        "artifacts": {
            "gltf": {
                "media_type": "model/gltf+json",
                "bytes": len(gltf),
                "sha256": _sha(gltf),
            },
            "ifc": {
                "media_type": "application/x-step",
                "bytes": len(ifc),
                "sha256": _sha(ifc),
            },
        },
        "validation": validation,
    }
    return DraftModelArtifacts(
        gltf=gltf, ifc=ifc, manifest=manifest, validation=validation
    )
