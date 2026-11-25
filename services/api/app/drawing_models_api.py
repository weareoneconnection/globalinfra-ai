"""Governed P1/P2 API for drawing-derived 3D and Draft BIM artifacts.

Generation is deliberately separate from drawing analysis.  It accepts only
human-confirmed, evidence-bound elements and stores immutable content-addressed
artifacts as a draft model version.  Publishing into the operational twin is a
different governed action and is never implied by this endpoint.
"""

from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .drawing_model_engine import ModelGenerationError, generate_draft_model
from .drawings import (
    _get_document,
    _is_audited_confirmation,
    _is_model_geometry,
    _latest_analysis,
    _model_gate,
)
from .ingestion import record_ingestion_receipt, receipt_payload
from .models import (
    DrawingElement,
    DrawingModelRun,
    DrawingSheet,
)
from .security import Principal, get_principal, require_roles


router = APIRouter(prefix="/drawings", tags=["drawing-to-twin"])


class GenerateDrawingModelRequest(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["GLTF", "IFC"], min_length=1)
    publish: bool = False


def _run_id() -> str:
    return f"DMR-{uuid4().hex[:20].upper()}"


def _scale_denominator(value: str | None) -> float:
    text = (value or "").strip()
    match = re.fullmatch(r"1\s*:\s*(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    try:
        result = float(text)
    except (TypeError, ValueError) as exc:
        raise ModelGenerationError("Confirmed drawing scale must be 1:N") from exc
    if result <= 0:
        raise ModelGenerationError("Confirmed drawing scale must be positive")
    return result


def _model_parameters(document) -> dict:
    metadata = dict(document.metadata_json or {})
    scale = _scale_denominator(document.scale or metadata.get("scale"))
    # PDF coordinates are typographic points.  Elements are converted back from
    # normalized sheet coordinates below, so this converts one point on paper
    # into metres in the represented asset at the confirmed drawing scale.
    if document.file_type == "pdf":
        metres_per_source_unit = (0.0254 / 72.0) * scale
    else:
        try:
            metres_per_source_unit = float(metadata["meters_per_source_unit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelGenerationError(
                "Confirmed raster source calibration is required"
            ) from exc
        if metres_per_source_unit <= 0:
            raise ModelGenerationError(
                "Confirmed raster source calibration must be positive"
            )
    return {
        "unit": document.unit or metadata.get("unit"),
        "scale": scale,
        "meters_per_unit": metres_per_source_unit,
        "storey_height_m": metadata.get("storey_height_m"),
        "wall_thickness_m": metadata.get("wall_thickness_m"),
        "door_height_m": metadata.get("door_height_m"),
        "equipment_height_m": metadata.get("equipment_height_m"),
        "storey_elevation_m": metadata.get("storey_elevation_m", 0.0),
    }


def _engine_elements(db: Session, drawing_id: str) -> tuple[list[dict], dict[str, DrawingElement]]:
    sheets = {
        row.id: row
        for row in db.scalars(
            select(DrawingSheet).where(DrawingSheet.drawing_id == drawing_id)
        )
    }
    rows = list(
        db.scalars(
            select(DrawingElement)
            .where(
                DrawingElement.drawing_id == drawing_id,
                DrawingElement.element_type.in_(["WALL", "DOOR", "SPACE", "EQUIPMENT"]),
            )
            .order_by(DrawingElement.id)
        )
    )
    values: list[dict] = []
    for row in rows:
        # A draft may be generated from a reviewed subset, but unconfirmed
        # geometry never crosses the model boundary.  The receipt below records
        # excluded candidates as rejected so partial scope stays explicit.
        if not _is_audited_confirmation(row) or not _is_model_geometry(row):
            continue
        sheet = sheets.get(row.sheet_id)
        if sheet is None:
            continue
        bbox = list(row.bbox or [])
        if len(bbox) != 4:
            continue
        # Analysis persists normalized source coordinates so the browser can
        # overlay them.  The model engine needs paper-space coordinates.
        paper_bbox = [
            float(bbox[0]) * sheet.width,
            float(bbox[1]) * sheet.height,
            float(bbox[2]) * sheet.width,
            float(bbox[3]) * sheet.height,
        ]
        values.append(
            {
                "id": row.id,
                "type": row.element_type,
                "name": row.value or row.label,
                "page": sheet.page_number,
                "bbox": bbox,
                "geometry_bbox": paper_bbox,
                "confidence": row.confidence,
                "status": row.review_status,
                "properties": dict(row.properties or {}),
                "evidence": {
                    "page": sheet.page_number,
                    "bbox": bbox,
                    "source_text": (row.properties or {}).get("source_text", row.value),
                    "confidence": row.confidence,
                },
            }
        )
    return values, {row.id: row for row in rows}


def _confirmation_record(row: DrawingElement) -> dict:
    properties = dict(row.properties or {})
    return {
        "element_id": row.id,
        "label": row.label,
        "value": row.value,
        "unit": row.unit,
        "confirmed_by": properties.get("actor"),
        "confirmed_at": properties.get("confirmed_at"),
        "evidence_kind": properties.get("evidence_kind"),
    }


def _model_run(db: Session, run_id: str, principal: Principal) -> DrawingModelRun:
    run = db.scalar(
        select(DrawingModelRun).where(
            DrawingModelRun.id == run_id,
            DrawingModelRun.organization_id == principal.organization_id,
        )
    )
    if run is None:
        raise HTTPException(404, "Drawing model run not found")
    if (
        not principal.has_org_wide_project_access()
        and run.project_id is not None
        and run.project_id not in principal.project_ids
    ):
        raise HTTPException(404, "Drawing model run not found")
    return run


@router.post("/{drawing_id}/model", status_code=201)
def generate_drawing_model(
    drawing_id: str,
    payload: GenerateDrawingModelRequest,
    principal: Principal = Depends(
        require_roles("engineer", "project_manager", "organization_admin")
    ),
    db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    formats = {item.strip().upper() for item in payload.formats}
    if formats != {"GLTF", "IFC"}:
        raise HTTPException(
            422,
            "A governed Draft BIM package must contain both GLTF and IFC",
        )
    if payload.publish:
        raise HTTPException(
            409,
            "Draft generation cannot publish an operational twin; independent approval is required",
        )

    analysis = _latest_analysis(db, drawing_id)
    if analysis is None:
        raise HTTPException(409, "Drawing analysis must complete before model generation")
    all_elements = list(
        db.scalars(
            select(DrawingElement).where(DrawingElement.drawing_id == drawing_id)
        )
    )
    ready, blockers = _model_gate(document, all_elements)
    if not ready:
        raise HTTPException(
            409,
            {
                "code": "MODEL_GATE_BLOCKED",
                "blockers": blockers,
                "boundary": "Only reviewed parameters and geometry may enter Draft BIM",
            },
        )
    elements, element_rows = _engine_elements(db, drawing_id)
    try:
        parameters = _model_parameters(document)
        artifacts = generate_draft_model(
            drawing_id=drawing_id,
            source_sha256=document.sha256,
            elements=elements,
            parameters=parameters,
        )
    except ModelGenerationError as exc:
        raise HTTPException(
            409,
            {
                "code": "MODEL_GATE_BLOCKED",
                "message": str(exc),
                "boundary": "Missing or unconfirmed drawing facts are never inferred",
            },
        ) from exc

    parameter_labels = {"scale", "unit", "height", "wall_thickness"}
    if document.file_type != "pdf":
        parameter_labels.add("source_calibration")
    parameter_confirmations = {
        row.label: _confirmation_record(row)
        for row in all_elements
        if row.label in parameter_labels and _is_audited_confirmation(row)
    }
    if parameter_labels - parameter_confirmations.keys():  # invariant guard
        raise HTTPException(409, "Audited parameter confirmations are incomplete")
    artifacts.manifest["parameter_confirmations"] = parameter_confirmations
    for item in artifacts.manifest["elements"]:
        source_id = item.get("derived_from") or item["source_id"]
        source_row = element_rows.get(source_id)
        item["confirmation"] = (
            _confirmation_record(source_row) if source_row is not None else None
        )
    artifacts.validation["checks"]["parameter_confirmations_recorded"] = True
    artifacts.validation["checks"]["geometry_confirmations_recorded"] = all(
        item["confirmation"] is not None
        for item in artifacts.manifest["elements"]
    )

    run_id = _run_id()
    objects = [
        {
            "id": row["twin_id"],
            "twin_id": row["twin_id"],
            "object_type": row["element_type"],
            "name": row["name"],
            "status": "AI_GENERATED_DRAFT",
            "geometry_ref": f"gltf://{run_id}#{row['twin_id']}",
            "properties": {
                "ifc_guid": row["ifc_guid"],
                "source_id": row["source_id"],
                "source_element_id": row.get("derived_from") or row["source_id"],
                "evidence": row["evidence"],
                "derived_from": row.get("derived_from"),
                "derivation_rule": row.get("derivation_rule"),
                "construction_status": "NOT_FOR_CONSTRUCTION",
            },
        }
        for row in artifacts.manifest["elements"]
    ]
    package_digest = hashlib.sha256(artifacts.gltf + artifacts.ifc).hexdigest()
    model_run = DrawingModelRun(
        id=run_id,
        drawing_document_id=drawing_id,
        organization_id=principal.organization_id,
        project_id=document.project_id,
        status="DRAFT_GENERATED",
        assumptions={
            "parameters": parameters,
            "confirmation_evidence": parameter_confirmations,
        },
        manifest=artifacts.manifest,
        validation=artifacts.validation,
        gltf_content=artifacts.gltf,
        ifc_content=artifacts.ifc,
        gltf_digest=hashlib.sha256(artifacts.gltf).hexdigest(),
        ifc_digest=hashlib.sha256(artifacts.ifc).hexdigest(),
        created_by=principal.subject,
    )
    db.add(model_run)

    receipt = record_ingestion_receipt(
        db,
        organization_id=principal.organization_id,
        project_id=document.project_id,
        channel="twin_model",
        source_type="DRAWING_TO_TWIN",
        status="DRAFT_GENERATED",
        target_type="DrawingModelRun",
        target_id=run_id,
        records_received=len(element_rows),
        records_accepted=len(elements),
        records_rejected=max(0, len(element_rows) - len(elements)),
        checksum=package_digest,
        validation_summary=artifacts.validation,
        lineage={
            "drawing_id": drawing_id,
            "source_sha256": document.sha256,
            "publication_status": "NOT_PUBLISHED",
            "data_classification": document.data_classification,
            "created_by": principal.subject,
        },
    )
    db.commit()
    db.refresh(model_run)
    db.refresh(receipt)

    artifact_rows = []
    if model_run.gltf_content is not None:
        artifact_rows.append(
            {
                "type": "GLTF",
                "url": f"/backend/drawings/{drawing_id}/models/{run_id}/gltf",
                **artifacts.manifest["artifacts"]["gltf"],
            }
        )
    if model_run.ifc_content is not None:
        artifact_rows.append(
            {
                "type": "IFC",
                "url": f"/backend/drawings/{drawing_id}/models/{run_id}/ifc",
                **artifacts.manifest["artifacts"]["ifc"],
            }
        )
    return {
        "id": run_id,
        "drawing_id": drawing_id,
        "status": model_run.status,
        "version": f"DRAWING-DRAFT-{run_id[-8:]}",
        "gltf_url": next(
            (row["url"] for row in artifact_rows if row["type"] == "GLTF"), None
        ),
        "artifacts": artifact_rows,
        "manifest": artifacts.manifest,
        "validation": artifacts.validation,
        "objects": objects,
        "ingestion_receipt": receipt_payload(receipt),
        "publication_status": "NOT_PUBLISHED",
        "boundary": "AI_GENERATED_DRAFT / NOT_FOR_CONSTRUCTION",
    }


@router.get("/{drawing_id}/models/{run_id}")
def drawing_model_detail(
    drawing_id: str,
    run_id: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    run = _model_run(db, run_id, principal)
    if run.drawing_document_id != document.id:
        raise HTTPException(404, "Drawing model run not found")
    return {
        "id": run.id,
        "drawing_id": drawing_id,
        "status": run.status,
        "manifest": run.manifest,
        "validation": run.validation,
        "artifacts": [
            row
            for row in (
                {
                    "type": "GLTF",
                    "url": f"/backend/drawings/{drawing_id}/models/{run.id}/gltf",
                    "sha256": run.gltf_digest,
                }
                if run.gltf_content is not None
                else None,
                {
                    "type": "IFC",
                    "url": f"/backend/drawings/{drawing_id}/models/{run.id}/ifc",
                    "sha256": run.ifc_digest,
                }
                if run.ifc_content is not None
                else None,
            )
            if row is not None
        ],
        "boundary": "AI_GENERATED_DRAFT / NOT_FOR_CONSTRUCTION",
    }


def _artifact_response(content: bytes | None, media_type: str, filename: str) -> Response:
    if content is None:
        raise HTTPException(404, "Requested model artifact was not generated")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Data-Provenance": "AI_GENERATED_DRAFT_NOT_FOR_CONSTRUCTION",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/{drawing_id}/models/{run_id}/gltf")
def drawing_model_gltf(
    drawing_id: str,
    run_id: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    run = _model_run(db, run_id, principal)
    if run.drawing_document_id != document.id:
        raise HTTPException(404, "Drawing model run not found")
    return _artifact_response(run.gltf_content, "model/gltf+json", f"{drawing_id}-draft.gltf")


@router.get("/{drawing_id}/models/{run_id}/ifc")
def drawing_model_ifc(
    drawing_id: str,
    run_id: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    run = _model_run(db, run_id, principal)
    if run.drawing_document_id != document.id:
        raise HTTPException(404, "Drawing model run not found")
    return _artifact_response(run.ifc_content, "application/x-step", f"{drawing_id}-draft.ifc")
