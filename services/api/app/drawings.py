"""Evidence-grounded engineering drawing intake and deterministic analysis.

P0 deliberately separates extraction from inference. Vector/text PDFs are
parsed with exact page coordinates. Raster drawings are validated and retained
but stay ``OCR_REQUIRED`` until a configured vision worker supplies evidence;
the API never fabricates drawing entities from a filename or demo template.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .config import settings
from .database import get_db
from .ingestion import record_ingestion_receipt, receipt_payload
from .llm import LLMError, generate_vision, is_llm_configured
from .models import (
    DrawingAnalysisRun,
    DrawingDocument,
    DrawingElement,
    DrawingSheet,
    utc_now,
)
from .security import Principal, get_principal, require_project, require_roles


router = APIRouter(prefix="/drawings", tags=["drawing-intelligence"])
PARSER_VERSION = "globalinfra.drawing.v1.2"
MAX_PDF_PAGES = 200
MAX_PAGE_WORDS = 250_000
MAX_PAGE_VECTOR_PRIMITIVES = 200_000
MAX_DOCUMENT_WORDS = 1_000_000
MAX_DOCUMENT_VECTOR_PRIMITIVES = 1_000_000
MAX_EXTRACTED_LINE_CHARS = 20_000
MAX_DOCUMENT_TEXT_CHARS = 5_000_000
MAX_ANALYSIS_ELEMENTS = 10_000
MAX_PREVIEW_DIMENSION = 3_000
MAX_PREVIEW_PIXELS = 9_000_000
MAX_RASTER_PIXELS = 40_000_000
MAX_BOUNDARY_CANDIDATES_PER_PAGE = 80
SUPPORTED_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
}
VISION_ELEMENT_TYPES = frozenset({
    "METADATA", "DIMENSION", "GRID", "SPACE", "WALL", "DOOR",
    "EQUIPMENT", "MATERIAL", "NOTE",
})
VISION_METADATA_FIELDS = frozenset({
    "drawing_number", "revision", "scale", "unit", "title",
})
VISION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "drawing_evidence",
        "strict": False,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["elements"],
            "properties": {
                "elements": {
                    "type": "array",
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "type", "label", "value", "page", "bbox",
                            "confidence", "source_text",
                        ],
                        "properties": {
                            "type": {"type": "string", "enum": sorted(VISION_ELEMENT_TYPES)},
                            "label": {"type": "string"},
                            "value": {"type": "string"},
                            "unit": {"type": ["string", "null"]},
                            "page": {"type": "integer", "minimum": 1},
                            "bbox": {
                                "type": "array", "minItems": 4, "maxItems": 4,
                                "items": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "source_text": {"type": "string"},
                            "geometry_type": {
                                "type": ["string", "null"],
                                "enum": ["RECTANGLE_FOOTPRINT", "POLYGON_FOOTPRINT", "LINE", None],
                            },
                        },
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class ParsedLine:
    page: int
    text: str
    bbox: list[float]


@dataclass(frozen=True)
class ParsedPage:
    page: int
    width: float
    height: float
    text: str
    word_count: int
    vector_count: int
    lines: list[ParsedLine]
    geometry: list[dict]


class AskDrawingRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class ConfirmDrawingRequest(BaseModel):
    # Single-field contract retained for assistant/tool callers.
    field: str | None = Field(default=None, min_length=1, max_length=96)
    value: str | None = Field(default=None, min_length=1, max_length=500)
    # The drawing workspace confirms all geometry gates in one review action.
    unit: Literal["mm", "cm", "m"] | None = None
    scale: str | None = Field(
        default=None,
        min_length=3,
        max_length=32,
        pattern=r"^1\s*:\s*[1-9]\d*(?:\.\d+)?$",
    )
    storey_height_m: float | None = Field(default=None, ge=0.5, le=20)
    wall_thickness_m: float | None = Field(default=None, ge=0.05, le=3)
    source_calibration_m_per_pixel: float | None = Field(
        default=None, gt=0, le=10
    )


_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "drawing_number": re.compile(
        r"(?:DRAWING\s*(?:NO\.?|NUMBER)|DWG\s*(?:NO\.?)?|图号)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})",
        re.I,
    ),
    "revision": re.compile(r"(?:\bREV(?:ISION)?\b|版本|版次)\s*[:#-]?\s*([A-Z0-9._/-]+)", re.I),
    "scale": re.compile(r"(?:SCALE|比例)\s*[:#-]?\s*(1\s*:\s*\d+)", re.I),
    "unit": re.compile(r"(?:UNITS?|单位)\s*[:#-]?\s*(MM|CM|M|毫米|米)\b", re.I),
    "title": re.compile(r"(?:DRAWING\s*TITLE|TITLE|图名)\s*[:#-]\s*(.{3,160})", re.I),
}
_TITLE_BLOCK_DRAWING_CODE = re.compile(
    r"\b(PD(?:[/_][A-Z0-9-]{1,24}){5,10})\b", re.I
)
_DIMENSION = re.compile(r"(?<![A-Z0-9])((?:Ø|R)?\s*\d+(?:\.\d+)?\s*(?:MM|CM|M))(?![A-Z])", re.I)
_AREA = re.compile(
    r"(?:GROSS\s+FLOOR\s+AREA|BUILDING\s+AREA|总建筑面积|建筑面积|总面积)"
    r"\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(M2|M²|SQ\.?\s*M)\b",
    re.I,
)
_GRID = re.compile(r"\bGRID\s*[-:#]?\s*([A-Z0-9]+)\b", re.I)
_ROOM = re.compile(r"\b(?:EQUIPMENT|CONTROL|PLANT|PUMP|ELECTRICAL|SWITCH|MECHANICAL)?\s*ROOM\b|设备房|控制室|泵房", re.I)
_MATERIAL = re.compile(
    r"\b(?:STAINLESS\s+STEEL|CHANNEL\s+STEEL|STRUCTURAL\s+STEEL|STEEL\s+FRAME\s+METAL|"
    r"REINFORCED\s+CONCRETE|CONCRETE|ALUMINIUM|ALUMINUM|HDPE|TIMBER|PVC|GLASS|"
    r"WIRE\s+(?:NETTING|MESH)|CEM(?:EN)?T\.?\s+PLASTER|MASONRY|STEEL)\b"
    r"|不锈钢|槽钢|钢筋混凝土|混凝土|铝合金|铝材|木材|木门|PVC|玻璃|钢丝网|高密度聚乙烯|水泥砂浆|砌体|结构钢",
    re.I,
)
_MATERIAL_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("STAINLESS_STEEL", re.compile(r"STAINLESS\s+STEEL|不锈钢", re.I)),
    ("CHANNEL_STEEL", re.compile(r"CHANNEL\s+STEEL|槽钢", re.I)),
    ("STEEL", re.compile(r"STRUCTURAL\s+STEEL|STEEL\s+FRAME\s+METAL|\bSTEEL\b|结构钢", re.I)),
    ("CONCRETE", re.compile(r"REINFORCED\s+CONCRETE|\bCONCRETE\b|钢筋混凝土|混凝土", re.I)),
    ("ALUMINIUM", re.compile(r"ALUMINIUM|ALUMINUM|铝合金|铝材", re.I)),
    ("HDPE", re.compile(r"\bHDPE\b|高密度聚乙烯", re.I)),
    ("TIMBER", re.compile(r"\bTIMBER\b|木材|木门", re.I)),
    ("PVC", re.compile(r"\bPVC\b", re.I)),
    ("GLASS", re.compile(r"\bGLASS\b|玻璃", re.I)),
    ("WIRE_MESH", re.compile(r"WIRE\s+(?:NETTING|MESH)|钢丝网", re.I)),
    ("CEMENT_PLASTER", re.compile(r"CEM(?:EN)?T\.?\s+PLASTER|水泥砂浆", re.I)),
    ("MASONRY", re.compile(r"\bMASONRY\b|砌体", re.I)),
)
_QUANTITY = re.compile(r"(?<![A-Z0-9])(\d+)\s*(?:NOS?\.?|PCS?\.?|SETS?\.?)\b", re.I)
_SIZE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:MM|CM|M)?(?:\s*\([WLH]\))?)\s*[X×]\s*"
    r"(\d+(?:\.\d+)?\s*(?:MM|CM|M)?(?:\s*\([WLH]\))?)",
    re.I,
)
_SCHEDULE_KIND = re.compile(r"\b(DOOR|WINDOW|LOUVERS?|SHUTTERS?)\b|门|窗|百叶|快门", re.I)
_SCHEDULE_TITLE = re.compile(r"\b(DOOR|WINDOW|LOUVER|SHUTTER)\s+SCHEDULE\b|门窗表|门表|窗表", re.I)
_SCHEDULE_ROW_CODE = re.compile(r"^[A-Z]{1,4}\d{1,3}$", re.I)
_WORD = re.compile(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]+")
_CONFIRMED_SCALE = re.compile(r"^1\s*:\s*([1-9]\d*(?:\.\d+)?)$")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:20].upper()}"


def _material_categories(text: str) -> list[str]:
    categories = [name for name, pattern in _MATERIAL_CATEGORY_RULES if pattern.search(text)]
    if "STEEL" in categories and any(
        category in categories for category in {"STAINLESS_STEEL", "CHANNEL_STEEL"}
    ):
        categories.remove("STEEL")
    return categories


def _explicit_quantity(text: str) -> int | None:
    match = _QUANTITY.search(text)
    return int(match.group(1)) if match else None


def _schedule_kind(text: str) -> str | None:
    match = _SCHEDULE_KIND.search(text)
    if not match:
        return None
    token = match.group(0).upper()
    if "DOOR" in token or "门" in token:
        return "DOOR"
    if "WINDOW" in token or "窗" in token:
        return "WINDOW"
    if "LOUVER" in token or "百叶" in token:
        return "LOUVER"
    return "SHUTTER"


def _safe_filename(value: str | None, fallback: str) -> str:
    leaf = re.split(r"[/\\]", value or "")[-1]
    leaf = re.sub(r"[\x00-\x1f\x7f]+", "_", leaf).strip()
    return (leaf or fallback)[:255]


def _content_disposition(filename: str, disposition: str = "inline") -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:180] or "drawing"
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def _detect_file_type(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    raise HTTPException(400, "Unsupported or malformed drawing; accepted formats are PDF, PNG, JPEG and TIFF")


def _canonical_confirmation_value(field: str, value: str) -> str:
    """Apply one validation contract to typed, compatibility and element-ID confirmations."""
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(422, "Confirmation value must not be empty")
    if field == "unit":
        normalized = cleaned.lower()
        if normalized not in {"mm", "cm", "m"}:
            raise HTTPException(422, "unit must be mm, cm or m")
        return normalized
    if field == "scale":
        match = _CONFIRMED_SCALE.fullmatch(cleaned)
        if not match:
            raise HTTPException(422, "scale must use the form 1:n")
        denominator = float(match.group(1))
        if not math.isfinite(denominator) or not 1 <= denominator <= 1_000_000:
            raise HTTPException(422, "scale denominator must be between 1 and 1,000,000")
        return f"1:{match.group(1)}"
    ranges = {
        "height": (0.5, 20.0),
        "wall_thickness": (0.05, 3.0),
        "source_calibration": (0.0, 10.0),
    }
    if field in ranges:
        try:
            numeric = float(cleaned)
        except ValueError as exc:
            raise HTTPException(422, f"{field} must be numeric") from exc
        lower, upper = ranges[field]
        lower_valid = numeric > lower if field == "source_calibration" else numeric >= lower
        if not math.isfinite(numeric) or not lower_valid or numeric > upper:
            comparator = "> 0" if field == "source_calibration" else f">= {lower:g}"
            raise HTTPException(422, f"{field} must be finite, {comparator} and <= {upper:g}")
        return f"{numeric:g}"
    max_lengths = {
        "title": 255,
        "drawing_number": 96,
        "revision": 32,
        "discipline": 64,
    }
    if field in max_lengths and len(cleaned) > max_lengths[field]:
        raise HTTPException(422, f"{field} exceeds the {max_lengths[field]}-character limit")
    return cleaned


def _bounded_pdf_render_scale(width: float, height: float) -> float:
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise HTTPException(422, "Drawing page dimensions are invalid")
    return min(
        144 / 72,
        MAX_PREVIEW_DIMENSION / max(width, height),
        math.sqrt(MAX_PREVIEW_PIXELS / (width * height)),
    )


def _normalize_bbox(box: tuple[float, float, float, float], width: float, height: float) -> list[float]:
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [round(max(0.0, min(1.0, box[0] / width)), 6),
            round(max(0.0, min(1.0, box[1] / height)), 6),
            round(max(0.0, min(1.0, box[2] / width)), 6),
            round(max(0.0, min(1.0, box[3] / height)), 6)]


def _parse_pdf(content: bytes) -> list[ParsedPage]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - image is built from pinned requirements
        raise HTTPException(503, "Drawing PDF parser is not installed") from exc
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise HTTPException(400, "PDF drawing could not be parsed safely") from exc
    if document.page_count > MAX_PDF_PAGES:
        document.close()
        raise HTTPException(422, f"Drawing set exceeds the {MAX_PDF_PAGES}-sheet safety limit")
    pages: list[ParsedPage] = []
    total_words = 0
    total_vectors = 0
    total_geometry = 0
    total_text_chars = 0
    try:
        for index, page in enumerate(document):
            width, height = float(page.rect.width), float(page.rect.height)
            if (
                width <= 0 or height <= 0
                or width > 20_000 or height > 20_000
                or width * height > 100_000_000
            ):
                raise HTTPException(422, "Drawing page dimensions exceed the safety limit")
            words = page.get_text("words", sort=True)
            if len(words) > MAX_PAGE_WORDS:
                raise HTTPException(422, "Drawing page exceeds the extracted-word safety limit")
            total_words += len(words)
            if total_words > MAX_DOCUMENT_WORDS:
                raise HTTPException(422, "Drawing set exceeds the cumulative extracted-word safety limit")
            groups: dict[tuple[int, int], list[tuple]] = {}
            for word in words:
                groups.setdefault((int(word[5]), int(word[6])), []).append(word)
            lines: list[ParsedLine] = []
            for grouped in groups.values():
                grouped.sort(key=lambda item: item[0])
                parts = [str(item[4]) for item in grouped]
                line_chars = sum(len(part) for part in parts) + max(0, len(parts) - 1)
                if line_chars > MAX_EXTRACTED_LINE_CHARS:
                    raise HTTPException(422, "Drawing contains an overlong extracted text line")
                line_text = " ".join(parts).strip()
                if not line_text:
                    continue
                total_text_chars += len(line_text)
                if total_text_chars > MAX_DOCUMENT_TEXT_CHARS:
                    raise HTTPException(422, "Drawing set exceeds the cumulative extracted-text safety limit")
                box = (
                    min(float(item[0]) for item in grouped),
                    min(float(item[1]) for item in grouped),
                    max(float(item[2]) for item in grouped),
                    max(float(item[3]) for item in grouped),
                )
                lines.append(ParsedLine(index + 1, line_text, _normalize_bbox(box, width, height)))
            geometry: list[dict] = []
            boundary_candidates: list[dict] = []
            try:
                drawings = page.get_drawings()
                vector_count = sum(len(path.get("items", [])) for path in drawings)
                if vector_count > MAX_PAGE_VECTOR_PRIMITIVES:
                    raise HTTPException(
                        422, "Drawing page exceeds the vector primitive safety limit"
                    )
                total_vectors += vector_count
                if total_vectors > MAX_DOCUMENT_VECTOR_PRIMITIVES:
                    raise HTTPException(
                        422, "Drawing set exceeds the cumulative vector primitive safety limit"
                    )
                for path_index, path in enumerate(drawings, start=1):
                    stroke = max(float(path.get("width") or 0.0), 1.0)
                    path_items = path.get("items", [])
                    points: list[tuple[float, float]] | None = None
                    if len(path_items) >= 3 and all(item[0] == "l" for item in path_items):
                        line_points = [
                            (float(path_items[0][1].x), float(path_items[0][1].y))
                        ] + [
                            (float(item[2].x), float(item[2].y)) for item in path_items
                        ]
                        continuous = all(
                            math.dist(
                                (float(current[2].x), float(current[2].y)),
                                (float(following[1].x), float(following[1].y)),
                            ) <= 1.5
                            for current, following in zip(path_items, path_items[1:])
                        )
                        if continuous and math.dist(line_points[0], line_points[-1]) <= 1.5:
                            points = line_points
                    elif len(path_items) == 1 and path_items[0][0] == "qu":
                        quad = path_items[0][1]
                        points = [
                            (float(quad.ul.x), float(quad.ul.y)),
                            (float(quad.ur.x), float(quad.ur.y)),
                            (float(quad.lr.x), float(quad.lr.y)),
                            (float(quad.ll.x), float(quad.ll.y)),
                            (float(quad.ul.x), float(quad.ul.y)),
                        ]
                    if points:
                        source_area = abs(sum(
                            start[0] * end[1] - end[0] * start[1]
                            for start, end in zip(points, points[1:])
                        )) / 2
                        x0, y0 = min(point[0] for point in points), min(point[1] for point in points)
                        x1, y1 = max(point[0] for point in points), max(point[1] for point in points)
                        bbox_area = max((x1 - x0) * (y1 - y0), 1.0)
                        area_ratio = source_area / max(width * height, 1.0)
                        if (
                            min(x1 - x0, y1 - y0) >= 20
                            and 0.00001 <= area_ratio <= 0.8
                            and source_area / bbox_area >= 0.15
                        ):
                            bbox = _normalize_bbox((x0, y0, x1, y1), width, height)
                            boundary_candidates.append({
                                "type": "SPACE",
                                "label": "closed footprint candidate",
                                "value": f"Closed footprint P{index + 1}-{path_index}",
                                "unit": None,
                                "page": index + 1,
                                "bbox": bbox,
                                "confidence": 0.76,
                                "method": "PDF_VECTOR_GEOMETRY",
                                "state": "INFERRED",
                                "properties": {
                                    "source_text": "Closed PDF vector path; exterior/space semantics require human confirmation",
                                    "geometry_type": "POLYGON_FOOTPRINT",
                                    "outline": [[round(x / width, 6), round(y / height, 6)] for x, y in points[:-1]],
                                    "outline_points": [[round(x, 6), round(y, 6)] for x, y in points[:-1]],
                                    "source_area_points2": round(source_area, 6),
                                    "semantic_boundary": "CANDIDATE_NOT_CONFIRMED",
                                },
                            })
                    for item_index, item in enumerate(path_items, start=1):
                        kind = item[0]
                        if kind == "re":
                            rect = item[1]
                            rect_width, rect_height = float(rect.width), float(rect.height)
                            # Tiny symbols and full-page frames are not useful
                            # footprint candidates.  Remaining rectangles are
                            # still only candidates until an engineer confirms
                            # their semantic meaning.
                            area_ratio = (rect_width * rect_height) / max(width * height, 1.0)
                            if min(rect_width, rect_height) < 20 or area_ratio > 0.85:
                                continue
                            bbox = _normalize_bbox(
                                (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                                width,
                                height,
                            )
                            total_geometry += 1
                            if total_geometry > MAX_ANALYSIS_ELEMENTS:
                                raise HTTPException(422, "Drawing exceeds the 10,000-element analysis safety limit")
                            geometry.append({
                                "type": "SPACE",
                                "label": "vector enclosure candidate",
                                "value": f"Enclosure P{index + 1}-{path_index}-{item_index}",
                                "unit": None,
                                "page": index + 1,
                                "bbox": bbox,
                                "confidence": 0.72,
                                "method": "PDF_VECTOR_GEOMETRY",
                                "state": "INFERRED",
                                "properties": {
                                    "source_text": "PDF vector rectangle; semantic type requires human confirmation",
                                    "geometry_type": "RECTANGLE_FOOTPRINT",
                                    "outline": [
                                        [bbox[0], bbox[1]], [bbox[2], bbox[1]],
                                        [bbox[2], bbox[3]], [bbox[0], bbox[3]],
                                    ],
                                    "outline_points": [
                                        [round(float(rect.x0), 6), round(float(rect.y0), 6)],
                                        [round(float(rect.x1), 6), round(float(rect.y0), 6)],
                                        [round(float(rect.x1), 6), round(float(rect.y1), 6)],
                                        [round(float(rect.x0), 6), round(float(rect.y1), 6)],
                                    ],
                                    "source_area_points2": round(rect_width * rect_height, 6),
                                    "semantic_boundary": "CANDIDATE_NOT_CONFIRMED",
                                },
                            })
                        elif kind == "l":
                            start, end = item[1], item[2]
                            dx = float(end.x - start.x)
                            dy = float(end.y - start.y)
                            length = (dx * dx + dy * dy) ** 0.5
                            if length < 20:
                                continue
                            pad = stroke / 2
                            bbox = _normalize_bbox(
                                (
                                    min(float(start.x), float(end.x)) - pad,
                                    min(float(start.y), float(end.y)) - pad,
                                    max(float(start.x), float(end.x)) + pad,
                                    max(float(start.y), float(end.y)) + pad,
                                ),
                                width,
                                height,
                            )
                            total_geometry += 1
                            if total_geometry > MAX_ANALYSIS_ELEMENTS:
                                raise HTTPException(422, "Drawing exceeds the 10,000-element analysis safety limit")
                            geometry.append({
                                "type": "WALL",
                                "label": "vector wall-line candidate",
                                "value": f"Line P{index + 1}-{path_index}-{item_index}",
                                "unit": None,
                                "page": index + 1,
                                "bbox": bbox,
                                "confidence": 0.68,
                                "method": "PDF_VECTOR_GEOMETRY",
                                "state": "INFERRED",
                                "properties": {
                                    "source_text": "PDF vector line; wall semantics require human confirmation",
                                    "geometry_type": "LINE",
                                    "rotation_deg": round(math.degrees(math.atan2(dy, dx)), 6),
                                    "line_length_points": round(length, 6),
                                    "line_start_points": [round(float(start.x), 6), round(float(start.y), 6)],
                                    "line_end_points": [round(float(end.x), 6), round(float(end.y), 6)],
                                    "semantic_boundary": "CANDIDATE_NOT_CONFIRMED",
                                },
                            })
                for boundary in sorted(
                    boundary_candidates,
                    key=lambda item: float(item["properties"]["source_area_points2"]),
                    reverse=True,
                )[:MAX_BOUNDARY_CANDIDATES_PER_PAGE]:
                    total_geometry += 1
                    if total_geometry > MAX_ANALYSIS_ELEMENTS:
                        raise HTTPException(422, "Drawing exceeds the 10,000-element analysis safety limit")
                    geometry.append(boundary)
            except HTTPException:
                raise
            except Exception:
                vector_count = 0
                geometry = []
            pages.append(ParsedPage(
                page=index + 1,
                width=width,
                height=height,
                text="\n".join(line.text for line in lines),
                word_count=len(words),
                vector_count=vector_count,
                lines=lines,
                geometry=geometry,
            ))
    finally:
        document.close()
    return pages


def _validate_raster(content: bytes, file_type: str) -> tuple[float, float]:
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:  # pragma: no cover - image is built from pinned requirements
        raise HTTPException(503, "Drawing image validator is not installed") from exc
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            image_format = (image.format or "").lower()
    except Exception as exc:
        raise HTTPException(400, "Image drawing could not be decoded safely") from exc
    expected = {"png": "png", "jpeg": "jpeg", "tiff": "tiff"}[file_type]
    if image_format not in {expected, "jpg" if expected == "jpeg" else expected}:
        raise HTTPException(400, "Drawing image signature does not match its decoded format")
    if width * height > MAX_RASTER_PIXELS:
        raise HTTPException(422, "Drawing image exceeds the 40 megapixel safety limit")
    return float(width), float(height)


def _vision_images(content: bytes, file_type: str) -> list[tuple[str, bytes]]:
    """Render a bounded visual packet without changing the retained source."""
    rendered: list[tuple[str, bytes]] = []
    if file_type == "pdf":
        import fitz  # type: ignore

        document = fitz.open(stream=content, filetype="pdf")
        try:
            for page_number in range(min(document.page_count, 4)):
                page = document[page_number]
                max_dimension = max(float(page.rect.width), float(page.rect.height), 1.0)
                scale = min(120 / 72, 3000 / max_dimension)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                rendered.append(("image/png", pixmap.tobytes("png")))
        finally:
            document.close()
        return rendered

    from PIL import Image  # type: ignore

    with Image.open(io.BytesIO(content)) as source:
        source.draft("RGB", (4096, 4096))
        source.thumbnail((4096, 4096))
        image = source.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
    return [("image/png", output.getvalue())]


def _parse_vision_elements(raw: str, page_count: int) -> list[dict]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("Vision response did not contain a JSON object")
    payload = json.loads(match.group(0))
    rows = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("Vision response elements must be a bounded array")
    result: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        element_type = str(row.get("type") or "").strip().upper()
        label = str(row.get("label") or "").strip().lower()
        value = str(row.get("value") or "").strip()
        source_text = str(row.get("source_text") or "").strip()
        if element_type not in VISION_ELEMENT_TYPES or not label or not value or not source_text:
            continue
        if element_type == "METADATA" and label not in VISION_METADATA_FIELDS:
            continue
        try:
            page = int(row.get("page"))
            bbox = [float(item) for item in row.get("bbox", [])]
            confidence = min(float(row.get("confidence")), 0.95)
        except (TypeError, ValueError):
            continue
        if (
            page < 1 or page > page_count or len(bbox) != 4
            or not all(math.isfinite(item) and 0 <= item <= 1 for item in bbox)
            or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]
            or not 0 <= confidence <= 1
        ):
            continue
        if label == "scale":
            value = re.sub(r"\s+", "", value)
            if not re.fullmatch(r"1:[1-9]\d*(?:\.\d+)?", value):
                continue
        if label == "unit":
            value = {"毫米": "mm", "厘米": "cm", "米": "m"}.get(value, value.lower())
            if value not in {"mm", "cm", "m"}:
                continue
        geometry_type = row.get("geometry_type")
        if geometry_type not in {None, "RECTANGLE_FOOTPRINT", "POLYGON_FOOTPRINT", "LINE"}:
            geometry_type = None
        result.append({
            "type": element_type,
            "label": label,
            "value": value[:500],
            "unit": str(row.get("unit") or "").strip().lower() or None,
            "page": page,
            "bbox": [round(item, 6) for item in bbox],
            "confidence": confidence,
            "method": "MULTIMODAL_VISION",
            "state": "INFERRED",
            "properties": {
                "source_text": source_text[:1000],
                "geometry_type": geometry_type,
                "semantic_boundary": "MODEL_EXTRACTED_REQUIRES_REVIEW",
            },
        })
    return result


async def _vision_specs(
    content: bytes,
    file_type: str,
    page_count: int,
    data_classification: str,
) -> tuple[list[dict], str]:
    try:
        if not is_llm_configured(sensitivity=data_classification):
            return [], "NOT_CONFIGURED"
        images = await run_in_threadpool(_vision_images, content, file_type)
        response = await generate_vision(
            "You extract engineering drawing evidence. Never guess or complete missing facts. "
            "Every result must quote visible source text and use a tight normalized bbox. "
            "Geometry is only a review candidate, never construction truth.",
            "Read the supplied drawing pages in order. Return only visible metadata, dimensions, "
            "grids, spaces, wall/door/equipment candidates, materials and notes. Pages are 1-indexed. "
            "For METADATA, label must be title, drawing_number, revision, scale, or unit.",
            images,
            response_format=VISION_RESPONSE_FORMAT,
            sensitivity=data_classification,
        )
        rows = _parse_vision_elements(response, min(page_count, 4))
        return rows, "SUCCEEDED" if rows else "EMPTY"
    except (LLMError, ValueError, json.JSONDecodeError, OSError):
        return [], "FAILED_CLOSED"


def _element_specs(
    lines: list[ParsedLine], max_elements: int = MAX_ANALYSIS_ELEMENTS
) -> tuple[dict[str, tuple[str, ParsedLine]], list[dict]]:
    metadata: dict[str, tuple[str, ParsedLine]] = {}
    elements: list[dict] = []
    seen: set[tuple] = set()

    def source_excerpt(line: ParsedLine, span: tuple[int, int] | None) -> str:
        if len(line.text) <= 1000:
            return line.text
        if span is None:
            return line.text[:1000]
        center = max(0, min(len(line.text), (span[0] + span[1]) // 2))
        start = max(0, min(center - 500, len(line.text) - 1000))
        return line.text[start:start + 1000]

    def add(
        kind: str,
        label: str,
        value: str,
        line: ParsedLine,
        confidence: float,
        unit: str | None = None,
        source_span: tuple[int, int] | None = None,
        extra_properties: dict | None = None,
    ):
        key = (kind, value.upper(), line.page, tuple(line.bbox))
        if key in seen:
            return
        if len(elements) >= max_elements:
            raise HTTPException(422, "Drawing exceeds the 10,000-element analysis safety limit")
        seen.add(key)
        elements.append({
            "type": kind, "label": label, "value": value.strip()[:500], "unit": unit,
            "page": line.page, "bbox": line.bbox, "confidence": confidence,
            "method": "PDF_VECTOR_TEXT", "state": "EXTRACTED",
            "properties": {
                "source_text": source_excerpt(line, source_span),
                **(extra_properties or {}),
            },
        })

    # Title-block codes are authoritative and must outrank CAD file paths such
    # as ``...00506.dwg REV FILES``.  Score all candidates before applying the
    # generic key/value patterns so extraction order cannot promote path noise.
    title_block_candidates: list[tuple[int, str, str | None, ParsedLine, tuple[int, int]]] = []
    for line in lines:
        for match in _TITLE_BLOCK_DRAWING_CODE.finditer(line.text):
            path_noise = "\\" in line.text or ".dwg" in line.text.lower()
            context = line.text.upper()
            score = (4 if "ISSUED FOR" in context or "DRAWING NO" in context else 0)
            score += 2 if "/" in match.group(1) else 0
            score -= 8 if path_noise else 0
            tail = line.text[match.end():]
            revision_match = re.match(r"\s+([A-Z0-9]{1,4})\b", tail, re.I)
            revision = revision_match.group(1) if revision_match and not path_noise else None
            if revision is None and not path_noise:
                # Title blocks frequently extract the revision as its own tiny
                # text box immediately to the right of the drawing number.
                nearby = [
                    candidate for candidate in lines
                    if candidate.page == line.page
                    and re.fullmatch(r"[A-Z0-9]{1,4}", candidate.text.strip(), re.I)
                    and candidate.text.strip().upper() not in {"REV", "NO", "DWG"}
                    and candidate.bbox[0] >= line.bbox[2]
                    and abs(
                        (candidate.bbox[1] + candidate.bbox[3]) / 2
                        - (line.bbox[1] + line.bbox[3]) / 2
                    ) <= 0.02
                ]
                if nearby:
                    revision = min(
                        nearby,
                        key=lambda candidate: (
                            candidate.bbox[0] - line.bbox[2],
                            abs(candidate.bbox[1] - line.bbox[1]),
                        ),
                    ).text.strip()
            title_block_candidates.append((score, match.group(1).replace("_", "/"), revision, line, match.span(1)))
    if title_block_candidates:
        _, drawing_number, revision, source_line, source_span = max(
            title_block_candidates, key=lambda item: item[0]
        )
        metadata["drawing_number"] = (drawing_number, source_line)
        add("METADATA", "drawing_number", drawing_number, source_line, 0.99, source_span=source_span)
        if revision:
            metadata["revision"] = (revision, source_line)
            add("METADATA", "revision", revision, source_line, 0.99, source_span=source_span)

    for line in lines:
        path_noise = "\\" in line.text or ".dwg" in line.text.lower()
        for field, pattern in _FIELD_PATTERNS.items():
            match = pattern.search(line.text)
            if match and field not in metadata and not (path_noise and field in {"drawing_number", "revision"}):
                value = re.sub(r"\s+", "", match.group(1)) if field == "scale" else match.group(1).strip()
                if field == "unit":
                    value = {"毫米": "mm", "米": "m"}.get(value, value.lower())
                metadata[field] = (value, line)
                add("METADATA", field, value, line, 0.98, source_span=match.span(1))
        for match in _DIMENSION.finditer(line.text):
            raw = re.sub(r"\s+", "", match.group(1)).upper()
            unit_match = re.search(r"(MM|CM|M)$", raw)
            add(
                "DIMENSION", "dimension", raw, line, 0.9,
                unit_match.group(1).lower() if unit_match else None,
                source_span=match.span(1),
            )
        area = _AREA.search(line.text)
        if area:
            add("PARAMETER", "building_area", area.group(1), line, 0.95, "m²", area.span(1))
        grid = _GRID.search(line.text)
        if grid:
            add("GRID", "grid", grid.group(1), line, 0.9, source_span=grid.span(1))
        room = _ROOM.search(line.text)
        if room:
            add("SPACE", "room", room.group(0), line, 0.84, source_span=room.span(0))
        material_categories = _material_categories(line.text)
        quantity = _explicit_quantity(line.text)
        for material in _MATERIAL.finditer(line.text):
            add(
                "MATERIAL", "material_requirement", material.group(0), line, 0.88,
                source_span=material.span(0),
                extra_properties={
                    "material_categories": material_categories,
                    "quantity": quantity,
                    "quantity_basis": "EXPLICIT_TEXT" if quantity is not None else None,
                },
            )
        schedule_kind = _schedule_kind(line.text)
        if schedule_kind:
            sizes = [
                f"{match.group(1).strip()} x {match.group(2).strip()}"
                for match in _SIZE.finditer(line.text)
            ]
            add(
                "SCHEDULE_ITEM", f"{schedule_kind.lower()}_schedule_item",
                line.text, line, 0.86,
                extra_properties={
                    "schedule_kind": schedule_kind,
                    "material_categories": material_categories,
                    "quantity": quantity,
                    "sizes": sizes,
                },
            )
        if re.search(r"\b(?:NOTE|GENERAL NOTES?)\b|说明", line.text, re.I):
            add("NOTE", "note", line.text, line, 0.82)

    # CAD/PDF schedules often place each cell in a separate text object. Rejoin
    # cells by their row baseline so type, size and description remain one
    # evidence unit instead of unrelated OCR fragments.
    for title_line in (line for line in lines if _SCHEDULE_TITLE.search(line.text)):
        title_kind = _schedule_kind(title_line.text) or "DOOR"
        table_x0 = max(0.0, title_line.bbox[0] - 0.01)
        table_x1 = min(1.0, title_line.bbox[0] + 0.11)
        table_y0 = title_line.bbox[3]
        table_y1 = min(1.0, title_line.bbox[3] + 0.22)
        table_lines = [
            line for line in lines
            if line.page == title_line.page
            and table_x0 <= line.bbox[0] <= table_x1
            and table_y0 <= (line.bbox[1] + line.bbox[3]) / 2 <= table_y1
        ]
        for anchor in (line for line in table_lines if _SCHEDULE_ROW_CODE.fullmatch(line.text.strip())):
            anchor_y = (anchor.bbox[1] + anchor.bbox[3]) / 2
            cells = sorted(
                (
                    line for line in table_lines
                    if abs((line.bbox[1] + line.bbox[3]) / 2 - anchor_y) <= 0.006
                ),
                key=lambda line: line.bbox[0],
            )
            combined = " | ".join(
                line.text.strip() for line in cells if line.text.strip()
            )
            if not combined or not _SIZE.search(combined):
                continue
            row = ParsedLine(
                page=anchor.page,
                text=f"{title_kind} SCHEDULE: {combined}",
                bbox=[
                    min(line.bbox[0] for line in cells),
                    min(line.bbox[1] for line in cells),
                    max(line.bbox[2] for line in cells),
                    max(line.bbox[3] for line in cells),
                ],
            )
            sizes = [
                f"{match.group(1).strip()} x {match.group(2).strip()}"
                for match in _SIZE.finditer(combined)
            ]
            add(
                "SCHEDULE_ITEM", f"{title_kind.lower()}_schedule_row", combined,
                row, 0.93,
                extra_properties={
                    "schedule_kind": title_kind,
                    "row_code": anchor.text.strip(),
                    "material_categories": _material_categories(combined),
                    "quantity": _explicit_quantity(combined),
                    "sizes": sizes,
                    "reconstructed_from_cells": len(cells),
                },
            )
    return metadata, elements


def _is_audited_confirmation(row: DrawingElement) -> bool:
    properties = row.properties or {}
    return bool(
        row.review_status == "USER_CONFIRMED"
        and properties.get("evidence_kind") == "USER_CONFIRMATION"
        and properties.get("actor")
        and properties.get("confirmed_at")
    )


def _is_model_geometry(row: DrawingElement) -> bool:
    properties = row.properties or {}
    geometry_type = str(properties.get("geometry_type") or "").upper()
    return bool(
        row.element_type in {"WALL", "DOOR", "SPACE", "EQUIPMENT"}
        and row.extraction_method in {"PDF_VECTOR_GEOMETRY", "MULTIMODAL_VISION"}
        and geometry_type in {"LINE", "RECTANGLE_FOOTPRINT", "POLYGON_FOOTPRINT"}
    )


def _serialized_confirmation(item: dict) -> bool:
    properties = item.get("properties") or {}
    return bool(
        item.get("state") == "USER_CONFIRMED"
        and properties.get("evidence_kind") == "USER_CONFIRMATION"
        and properties.get("actor")
        and properties.get("confirmed_at")
    )


def _footprint_area_m2(document: DrawingDocument, detail: dict, item: dict) -> float | None:
    properties = item.get("properties") or {}
    geometry_type = str(properties.get("geometry_type") or "").upper()
    if geometry_type not in {"RECTANGLE_FOOTPRINT", "POLYGON_FOOTPRINT"}:
        return None
    try:
        source_area = float(properties.get("source_area_points2"))
    except (TypeError, ValueError):
        source_area = 0.0
    if source_area <= 0 and geometry_type == "RECTANGLE_FOOTPRINT":
        sheet = next(
            (row for row in detail["sheets"] if row["page"] == item["page"]),
            None,
        )
        bbox = item.get("bbox") or []
        if sheet and len(bbox) == 4:
            source_area = (
                max(0.0, float(bbox[2]) - float(bbox[0])) * float(sheet["width"])
                * max(0.0, float(bbox[3]) - float(bbox[1])) * float(sheet["height"])
            )
    if source_area <= 0:
        return None
    if document.file_type == "pdf":
        scale_match = _CONFIRMED_SCALE.match(document.scale or "")
        if not scale_match:
            return None
        metres_per_point = (0.0254 / 72.0) * float(scale_match.group(1))
        return source_area * metres_per_point * metres_per_point
    try:
        metres_per_source_unit = float(document.metadata_json.get("meters_per_source_unit"))
    except (TypeError, ValueError):
        return None
    return source_area * metres_per_source_unit * metres_per_source_unit


def _model_gate(document: DrawingDocument, elements: list[DrawingElement]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    confirmed_metadata = {
        row.label
        for row in elements
        if row.element_type == "METADATA" and _is_audited_confirmation(row)
    }
    if not document.scale or "scale" not in confirmed_metadata:
        blockers.append("SCALE_REQUIRES_CONFIRMATION")
    if not document.unit or "unit" not in confirmed_metadata:
        blockers.append("UNIT_REQUIRES_CONFIRMATION")
    if not any(row.element_type in {"DIMENSION", "PARAMETER"} and row.review_status != "REJECTED" for row in elements):
        blockers.append("NO_EVIDENCED_DIMENSIONS")
    confirmed_parameters = {
        row.label for row in elements
        if row.element_type == "PARAMETER" and _is_audited_confirmation(row)
    }
    if "height" not in confirmed_parameters:
        blockers.append("STOREY_HEIGHT_REQUIRES_CONFIRMATION")
    if "wall_thickness" not in confirmed_parameters:
        blockers.append("WALL_THICKNESS_REQUIRES_CONFIRMATION")
    geometry = [
        row for row in elements
        if _is_model_geometry(row)
        and row.review_status != "REJECTED"
    ]
    if not geometry or not any(_is_audited_confirmation(row) for row in geometry):
        blockers.append("NO_CONFIRMED_GEOMETRY")
    if document.status == "OCR_REQUIRED":
        blockers.append("OCR_REQUIRED")
    if document.file_type != "pdf" and not any(
        row.element_type == "PARAMETER"
        and row.label == "source_calibration"
        and _is_audited_confirmation(row)
        for row in elements
    ):
        blockers.append("RASTER_CALIBRATION_REQUIRES_CONFIRMATION")
    return not blockers, blockers


def _scoped_documents(principal: Principal):
    stmt = select(DrawingDocument).where(DrawingDocument.organization_id == principal.organization_id)
    if not principal.has_org_wide_project_access():
        stmt = stmt.where(
            or_(
                DrawingDocument.project_id.in_(principal.project_ids),
                and_(
                    DrawingDocument.project_id.is_(None),
                    DrawingDocument.data_classification == "public",
                ),
            )
        )
    return stmt


def _get_document(db: Session, drawing_id: str, principal: Principal) -> DrawingDocument:
    document = db.scalar(_scoped_documents(principal).where(DrawingDocument.id == drawing_id))
    if not document:
        raise HTTPException(404, "Drawing not found")
    return document


def _latest_analysis(db: Session, drawing_id: str) -> DrawingAnalysisRun | None:
    return db.scalar(
        select(DrawingAnalysisRun)
        .where(DrawingAnalysisRun.drawing_id == drawing_id)
        .order_by(DrawingAnalysisRun.started_at.desc())
        .limit(1)
    )


def _summary(document: DrawingDocument) -> dict:
    return {
        "id": document.id,
        "filename": document.filename,
        "project_id": document.project_id,
        "file_type": document.file_type,
        "status": document.status,
        "data_classification": document.data_classification,
        "sha256": document.sha256,
        "title": document.title,
        "drawing_number": document.drawing_number,
        "revision": document.revision,
        "scale": document.scale,
        "unit": document.unit,
        "page_count": document.page_count,
        "created_at": document.created_at.isoformat(),
        "source_url": f"/backend/drawings/{document.id}/source",
    }


def _detail(db: Session, document: DrawingDocument) -> dict:
    sheets = list(db.scalars(
        select(DrawingSheet).where(DrawingSheet.drawing_id == document.id).order_by(DrawingSheet.page_number)
    ))
    sheet_by_id = {sheet.id: sheet for sheet in sheets}
    elements = list(db.scalars(
        select(DrawingElement).where(DrawingElement.drawing_id == document.id).order_by(DrawingElement.created_at)
    ))
    analysis = _latest_analysis(db, document.id)
    ready, blockers = _model_gate(document, elements)
    return {
        "document": {**_summary(document), "content_type": document.content_type,
                     "byte_size": document.byte_size, "discipline": document.discipline,
                     "metadata": document.metadata_json},
        "sheets": [{
            "id": sheet.id, "page": sheet.page_number, "width": sheet.width,
            "height": sheet.height, "word_count": sheet.word_count,
            "vector_primitive_count": sheet.vector_primitive_count,
            "status": sheet.parse_status,
            "preview_url": f"/backend/drawings/{document.id}/pages/{sheet.page_number}/preview",
        } for sheet in sheets],
        "elements": [{
            "id": row.id, "type": row.element_type, "label": row.label,
            "value": row.value, "unit": row.unit,
            "page": sheet_by_id[row.sheet_id].page_number,
            "bbox": row.bbox, "confidence": row.confidence,
            "state": row.review_status,
            "extraction_method": row.extraction_method,
            "properties": row.properties,
            "evidence": {
                "drawing_id": document.id, "source_sha256": document.sha256,
                "page": sheet_by_id[row.sheet_id].page_number, "bbox": row.bbox,
                "source_text": row.properties.get("source_text", row.value),
            },
        } for row in elements],
        "analysis": None if not analysis else {
            "id": analysis.id, "status": analysis.status,
            "parser_version": analysis.parser_version, "source_sha256": analysis.source_sha256,
            "summary": analysis.summary, "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
        },
        "model_gate": {
            "status": "READY" if ready else "NOT_READY", "ready": ready,
            "blockers": blockers,
            "requires_human_confirmation": sum(row.review_status == "INFERRED" or row.confidence < 0.8 for row in elements),
        },
    }


@router.post("/analyze", status_code=201)
async def analyze_drawing(
    file: UploadFile = File(...),
    project_id: int | None = Form(default=None, gt=0),
    discipline: str | None = Form(default=None, max_length=64),
    data_classification: Literal["public", "internal", "restricted"] = Form(default="internal"),
    project_id_query: int | None = Query(default=None, alias="project_id", gt=0),
    discipline_query: str | None = Query(default=None, alias="discipline", max_length=64),
    principal: Principal = Depends(require_roles("engineer", "project_manager", "organization_admin")),
    db: Session = Depends(get_db),
):
    project_id = project_id if project_id is not None else project_id_query
    discipline = discipline or discipline_query
    if data_classification != "public" and project_id is None:
        raise HTTPException(
            422,
            "Internal and restricted drawings must be bound to an authorized project",
        )
    if project_id is not None:
        require_project(principal, project_id, db)
    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(422, "Uploaded drawing is empty")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"Upload exceeds the {settings.max_upload_bytes}-byte limit")
    file_type = _detect_file_type(content)
    checksum = hashlib.sha256(content).hexdigest()
    drawing_id = _id("DRW")
    content_type = SUPPORTED_CONTENT_TYPES[file_type]

    if file_type == "pdf":
        pages = await run_in_threadpool(_parse_pdf, content)
    else:
        width, height = await run_in_threadpool(_validate_raster, content, file_type)
        pages = [ParsedPage(1, width, height, "", 0, 0, [], [])]

    all_lines = [line for page in pages for line in page.lines]
    geometry_count = sum(len(page.geometry) for page in pages)
    metadata, text_specs = _element_specs(
        all_lines, max_elements=max(0, MAX_ANALYSIS_ELEMENTS - geometry_count)
    )
    vision_specs: list[dict] = []
    vision_status = "NOT_NEEDED"
    if not text_specs or sum(page.word_count for page in pages) < 5:
        vision_specs, vision_status = await _vision_specs(
            content, file_type, len(pages), data_classification
        )
    # Geometry candidates appear first in review controls so an engineer
    # confirms a real vector footprint rather than a text-label bounding box.
    specs = [spec for page in pages for spec in page.geometry] + text_specs + vision_specs
    if len(specs) > MAX_ANALYSIS_ELEMENTS:
        raise HTTPException(422, "Drawing exceeds the 10,000-element analysis safety limit")
    metadata_values = {key: value[0] for key, value in metadata.items()}
    for spec in vision_specs:
        if spec["type"] == "METADATA" and spec["label"] in VISION_METADATA_FIELDS:
            metadata_values.setdefault(spec["label"], spec["value"])
    status = "ANALYZED" if specs else "OCR_REQUIRED"
    document = DrawingDocument(
        id=drawing_id, organization_id=principal.organization_id,
        project_id=project_id,
        filename=_safe_filename(file.filename, f"drawing.{file_type}"),
        file_type=file_type, content_type=content_type, byte_size=len(content),
        sha256=checksum, storage_ref=f"sha256:{checksum}", status=status,
        data_classification=data_classification,
        discipline=discipline, title=metadata_values.get("title"),
        drawing_number=metadata_values.get("drawing_number"),
        revision=metadata_values.get("revision"),
        scale=metadata_values.get("scale"),
        unit=metadata_values.get("unit"),
        page_count=len(pages),
        metadata_json=metadata_values,
        original_content=content, uploaded_by=principal.subject,
    )
    db.add(document)
    db.flush()
    sheet_rows: dict[int, DrawingSheet] = {}
    for page in pages:
        sheet = DrawingSheet(
            id=_id("SHEET"), drawing_id=drawing_id, page_number=page.page,
            width=page.width, height=page.height, extracted_text=page.text,
            word_count=page.word_count, vector_primitive_count=page.vector_count,
            parse_status=(
                "PARSED" if page.word_count
                else "VISION_PARSED" if any(
                    spec["page"] == page.page for spec in vision_specs
                )
                else "OCR_REQUIRED"
            ),
        )
        db.add(sheet)
        sheet_rows[page.page] = sheet
    db.flush()
    for spec in specs:
        db.add(DrawingElement(
            id=_id("DE"), drawing_id=drawing_id,
            sheet_id=sheet_rows[spec["page"]].id,
            element_type=spec["type"], label=spec["label"], value=spec["value"],
            unit=spec["unit"], bbox=spec["bbox"], confidence=spec["confidence"],
            extraction_method=spec["method"], review_status=spec["state"],
            properties=spec["properties"],
        ))
    db.flush()
    rows = list(db.scalars(select(DrawingElement).where(DrawingElement.drawing_id == drawing_id)))
    ready, blockers = _model_gate(document, rows)
    run = DrawingAnalysisRun(
        id=_id("DAR"), drawing_id=drawing_id,
        status="COMPLETED" if status == "ANALYZED" else "OCR_REQUIRED",
        parser_version=PARSER_VERSION, source_sha256=checksum,
        summary={
            "pages": len(pages),
            "elements": len(rows),
            "metadata_fields": sorted(metadata_values),
            "vision_status": vision_status,
        },
        model_ready=ready, blockers=blockers, completed_at=utc_now(),
    )
    db.add(run)
    receipt = record_ingestion_receipt(
        db, organization_id=principal.organization_id, project_id=project_id,
        channel="document_correspondence", source_type=f"DRAWING_{file_type.upper()}",
        status=status, target_type="DrawingDocument", target_id=drawing_id,
        checksum=checksum, records_accepted=1,
        validation_summary={"signature_valid": True, "pages": len(pages),
                            "elements": len(rows), "model_ready": ready,
                            "blockers": blockers, "vision_status": vision_status},
        lineage={"filename": document.filename, "uploaded_by": principal.subject,
                 "parser_version": PARSER_VERSION, "storage_ref": document.storage_ref,
                 "data_classification": data_classification},
    )
    db.commit()
    db.refresh(document)
    db.refresh(receipt)
    return {**_detail(db, document), "ingestion_receipt": receipt_payload(receipt)}


@router.get("")
def list_drawings(
    project_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    if project_id is not None:
        require_project(principal, project_id, db)
    stmt = _scoped_documents(principal)
    if project_id is not None:
        stmt = stmt.where(DrawingDocument.project_id == project_id)
    rows = db.scalars(stmt.order_by(DrawingDocument.created_at.desc()).limit(limit)).all()
    return [_summary(row) for row in rows]


@router.get("/{drawing_id}")
def drawing_detail(
    drawing_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    return _detail(db, _get_document(db, drawing_id, principal))


@router.get("/{drawing_id}/source")
def drawing_source(
    drawing_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    return Response(
        content=document.original_content, media_type=document.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                 "Content-Disposition": _content_disposition(document.filename)},
    )


@router.get("/{drawing_id}/pages/{page_number}/preview")
def drawing_preview(
    drawing_id: str, page_number: int,
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    if page_number < 1 or page_number > document.page_count:
        raise HTTPException(404, "Drawing page not found")
    if document.file_type != "pdf":
        if page_number != 1:
            raise HTTPException(404, "Drawing page not found")
        return Response(content=document.original_content, media_type=document.content_type,
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    try:
        import fitz  # type: ignore
        pdf = fitz.open(stream=document.original_content, filetype="pdf")
        try:
            page = pdf[page_number - 1]
            scale = _bounded_pdf_render_scale(
                float(page.rect.width), float(page.rect.height)
            )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            if (
                pixmap.width > MAX_PREVIEW_DIMENSION
                or pixmap.height > MAX_PREVIEW_DIMENSION
                or pixmap.width * pixmap.height > MAX_PREVIEW_PIXELS
            ):
                raise HTTPException(422, "Drawing page preview exceeds the render safety limit")
            preview = pixmap.tobytes("png")
        finally:
            pdf.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "Drawing page preview could not be rendered") from exc
    return Response(content=preview, media_type="image/png",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{drawing_id}/ask")
def ask_drawing(
    drawing_id: str, payload: AskDrawingRequest,
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    detail = _detail(db, document)
    question_lower = payload.question.lower()
    chinese = bool(re.search(r"[\u4e00-\u9fff]", payload.question))

    if re.search(
        r"建筑面积|总面积|占地面积|轮廓面积|面积(?:是|有|为|多少|计算)"
        r"|building\s+area|gross\s+floor\s+area|footprint\s+area",
        question_lower, re.I,
    ):
        area = next(
            (
                item for item in detail["elements"]
                if item["type"] == "PARAMETER" and item["label"] == "building_area"
            ),
            None,
        )
        if area:
            citation = {
                "element_id": area["id"], **area["evidence"],
                "confidence": area["confidence"], "state": area["state"],
            }
            answer = (
                f'图纸明确标注的建筑面积为 {area["value"]} {area["unit"] or "m²"}。'
                if chinese else
                f'The drawing explicitly states a building area of {area["value"]} {area["unit"] or "m²"}.'
            )
            return {
                "answer": answer, "grounded": True,
                "facts": [{"id": area["id"], "type": area["type"], "label": area["label"],
                           "value": area["value"], "confidence": area["confidence"]}],
                "citations": [citation],
                "boundary": "The value is returned only because it is explicitly labelled in the source drawing.",
            }
        geometry = [
            item for item in detail["elements"]
            if item["type"] in {"WALL", "DOOR", "SPACE", "EQUIPMENT"}
            and str(item["properties"].get("geometry_type", "")).upper()
            in {"LINE", "RECTANGLE_FOOTPRINT", "POLYGON_FOOTPRINT"}
        ]
        confirmed = [item for item in geometry if _serialized_confirmation(item)]
        footprints = [
            item for item in geometry
            if str(item["properties"].get("geometry_type", "")).upper()
            in {"RECTANGLE_FOOTPRINT", "POLYGON_FOOTPRINT"}
        ]
        confirmed_footprints = [item for item in footprints if _serialized_confirmation(item)]
        calibration_label = "scale" if document.file_type == "pdf" else "source_calibration"
        calibration = next(
            (
                item for item in detail["elements"]
                if item["label"] == calibration_label and _serialized_confirmation(item)
            ),
            None,
        )
        computed = [
            (item, _footprint_area_m2(document, detail, item))
            for item in confirmed_footprints
        ] if calibration else []
        computed = [(item, value) for item, value in computed if value is not None]
        if computed:
            total_area = sum(value for _, value in computed)
            answer = (
                f"已根据 {len(computed)} 个经工程师确认的闭合轮廓和已确认比例计算，"
                f"闭合轮廓面积合计为 {total_area:.2f} m²。"
                "该数值是已确认轮廓的几何面积；如果轮廓相互重叠或不代表建筑外边界，不应直接当作总建筑面积。"
                if chinese else
                f"Using {len(computed)} engineer-confirmed closed footprint(s) and the confirmed scale, "
                f"the confirmed footprint area totals {total_area:.2f} m². This is a geometric footprint total; "
                "overlapping or non-exterior footprints must not be treated as gross building area."
            )
            evidence_items = [item for item, _ in computed]
            if calibration:
                evidence_items.append(calibration)
            return {
                "answer": answer, "grounded": True,
                "facts": [{
                    "id": item["id"], "type": item["type"], "label": item["label"],
                    "value": f"{value:.2f} m²", "confidence": item["confidence"],
                } for item, value in computed],
                "citations": [{
                    "element_id": item["id"], **item["evidence"],
                    "confidence": item["confidence"], "state": item["state"],
                } for item in evidence_items],
                "calculation": {
                    "method": "CONFIRMED_VECTOR_FOOTPRINT_X_CONFIRMED_SCALE",
                    "footprint_count": len(computed), "area_m2": round(total_area, 2),
                },
                "boundary": "Only audited closed footprints and an audited scale/calibration enter the calculation.",
            }
        if confirmed_footprints and not calibration:
            answer = (
                f"已确认 {len(confirmed_footprints)} 个闭合轮廓，但比例尺尚未经工程师确认，因此暂不计算面积。"
                if chinese else
                f"{len(confirmed_footprints)} closed footprint(s) are confirmed, but the scale is not audited, so area is not calculated."
            )
            return {
                "answer": answer, "grounded": False, "facts": [], "citations": [],
                "boundary": "Area calculation requires audited geometry and scale/calibration.",
            }
        answer = (
            f"这张图没有检出明确标注的建筑面积。当前识别到 {len(footprints)} 个闭合轮廓候选，"
            f"已确认 {len(confirmed_footprints)} 个；全部几何候选已确认 {len(confirmed)}/{len(geometry)}。"
            "请先在图纸工作台选中并确认建筑外轮廓和比例，系统将自动计算面积。"
            if chinese else
            f"No explicit building-area label was found. {len(footprints)} closed footprint candidates were detected; "
            f"{len(confirmed_footprints)} are confirmed, and {len(confirmed)}/{len(geometry)} total geometry candidates are confirmed. "
            "Confirm the exterior footprint and scale in the Drawing Workbench to calculate area automatically."
        )
        return {
            "answer": answer, "grounded": False, "facts": [], "citations": [],
            "boundary": "No area is inferred from unconfirmed or open geometry.",
        }

    if re.search(r"门窗|门表|窗表|门.*(?:规格|数量|材料)|窗.*(?:规格|数量|材料)|(?:door|window)\s+schedule", question_lower, re.I):
        schedule_items: list[dict] = []
        seen_schedule: set[str] = set()
        for item in detail["elements"]:
            if item["type"] != "SCHEDULE_ITEM":
                continue
            source = re.sub(r"\s+", " ", str(item["properties"].get("source_text") or item["value"])).strip()
            normalized = source.casefold()
            if not normalized or normalized in seen_schedule:
                continue
            seen_schedule.add(normalized)
            schedule_items.append(item)
        schedule_items.sort(
            key=lambda item: (
                not str(item["label"]).endswith("_schedule_row"),
                item["page"], item["bbox"][1], item["bbox"][0],
            )
        )
        schedule_items = schedule_items[:16]
        if schedule_items:
            kind_labels = {
                "DOOR": "门", "WINDOW": "窗", "LOUVER": "百叶", "SHUTTER": "快门/遮挡",
            } if chinese else {
                "DOOR": "door", "WINDOW": "window", "LOUVER": "louver", "SHUTTER": "shutter",
            }
            counts: dict[str, int] = {}
            explicit_quantities: dict[str, int] = {}
            for item in schedule_items:
                properties = item["properties"]
                kind = str(properties.get("schedule_kind") or "OTHER")
                counts[kind] = counts.get(kind, 0) + 1
                quantity = properties.get("quantity")
                if isinstance(quantity, int):
                    explicit_quantities[kind] = explicit_quantities.get(kind, 0) + quantity
            summary = ", ".join(
                f"{kind_labels.get(kind, kind)} {count} {'条' if chinese else 'rows'}"
                + (f"/明确数量 {explicit_quantities[kind]}" if chinese and kind in explicit_quantities else "")
                for kind, count in sorted(counts.items())
            )
            details = [
                re.sub(r"\s+", " ", str(item["properties"].get("source_text") or item["value"])).strip()
                for item in schedule_items[:12]
            ]
            prefix = f"门窗/构件表识别结果（{summary}）：" if chinese else f"Door/window schedule results ({summary}): "
            answer = prefix + ("；" if chinese else "; ").join(
                f"{index}. {source}" for index, source in enumerate(details, start=1)
            )
            return {
                "answer": answer, "grounded": True,
                "facts": [{"id": item["id"], "type": item["type"], "label": item["label"],
                           "value": item["value"], "confidence": item["confidence"]} for item in schedule_items[:12]],
                "citations": [{"element_id": item["id"], **item["evidence"],
                               "confidence": item["confidence"], "state": item["state"]} for item in schedule_items[:12]],
                "schedule_summary": {"counts": counts, "explicit_quantities": explicit_quantities},
                "boundary": "Counts distinguish schedule rows from explicit quantities; missing quantities are not inferred.",
            }

    if re.search(r"材料|材质|materials?", question_lower, re.I):
        unique: list[dict] = []
        seen_requirements: set[str] = set()
        grouped_sources: dict[str, set[str]] = {}
        explicit_quantities: dict[str, int] = {}
        for item in detail["elements"]:
            if item["type"] != "MATERIAL":
                continue
            requirement = str(item["properties"].get("source_text") or item["value"]).strip()
            normalized = re.sub(r"\s+", " ", requirement).casefold()
            categories = item["properties"].get("material_categories") or _material_categories(requirement)
            for category in categories:
                grouped_sources.setdefault(str(category), set()).add(normalized)
            if not normalized or normalized in seen_requirements:
                continue
            seen_requirements.add(normalized)
            quantity = item["properties"].get("quantity")
            if isinstance(quantity, int):
                for category in categories:
                    explicit_quantities[str(category)] = explicit_quantities.get(str(category), 0) + quantity
            unique.append(item)
        unique = unique[:12]
        if unique:
            requirements = [
                re.sub(r"\s+", " ", str(item["properties"].get("source_text") or item["value"])).strip()
                for item in unique
            ]
            category_labels = {
                "STAINLESS_STEEL": "不锈钢", "CHANNEL_STEEL": "槽钢", "STEEL": "钢制品",
                "CONCRETE": "混凝土", "ALUMINIUM": "铝材", "HDPE": "HDPE",
                "CEMENT_PLASTER": "水泥抹灰", "MASONRY": "砌体",
                "TIMBER": "木材", "PVC": "PVC", "GLASS": "玻璃", "WIRE_MESH": "金属网",
            } if chinese else {
                "STAINLESS_STEEL": "stainless steel", "CHANNEL_STEEL": "channel steel", "STEEL": "steel",
                "CONCRETE": "concrete", "ALUMINIUM": "aluminium", "HDPE": "HDPE",
                "CEMENT_PLASTER": "cement plaster", "MASONRY": "masonry",
                "TIMBER": "timber", "PVC": "PVC", "GLASS": "glass", "WIRE_MESH": "wire mesh",
            }
            category_summary = ", ".join(
                f"{category_labels.get(category, category)} {len(sources)} {'条' if chinese else 'requirements'}"
                + (f"/{'明确数量' if chinese else 'explicit quantity'} {explicit_quantities[category]}" if category in explicit_quantities else "")
                for category, sources in sorted(grouped_sources.items())
            )
            prefix = (
                f"材料分类汇总（{category_summary}）。原图要求："
                if chinese else
                f"Material category summary ({category_summary}). Source requirements: "
            )
            separator = "；" if chinese else "; "
            answer = prefix + separator.join(
                f"{index}. {requirement}" for index, requirement in enumerate(requirements, start=1)
            )
            return {
                "answer": answer, "grounded": True,
                "facts": [{"id": item["id"], "type": item["type"], "label": item["label"],
                           "value": item["value"], "confidence": item["confidence"]} for item in unique],
                "citations": [{"element_id": item["id"], **item["evidence"],
                               "confidence": item["confidence"], "state": item["state"]} for item in unique],
                "material_summary": {
                    "requirement_counts": {category: len(sources) for category, sources in grouped_sources.items()},
                    "explicit_quantities": explicit_quantities,
                },
                "boundary": "Requirements are deduplicated from source text; no missing specification is inferred.",
            }

    synonyms = {
        "比例": "scale", "单位": "unit", "图号": "drawing_number", "版本": "revision",
        "尺寸": "dimension", "房间": "room", "材料": "material", "轴网": "grid",
        "设备": "equipment", "净空": "clearance", "墙": "wall", "门": "door",
    }
    tokens = {
        token.lower() for token in _WORD.findall(payload.question)
        if len(token) > 1 and not re.fullmatch(r"[\u4e00-\u9fff]+", token)
    }
    # Chinese text is not whitespace-delimited.  Match the governed domain
    # lexicon by containment instead of treating an entire sentence as one
    # token, so questions such as “图纸比例是多少？” remain evidence-grounded.
    tokens.update(value for key, value in synonyms.items() if key in question_lower)
    scored: list[tuple[int, dict]] = []
    for element in detail["elements"]:
        haystack = " ".join((element["type"], element["label"], element["value"],
                             str(element["properties"].get("source_text", "")))).lower()
        score = sum(token in haystack for token in tokens)
        if score:
            scored.append((score, element))
    scored.sort(key=lambda item: (item[0], item[1]["confidence"]), reverse=True)
    facts = [item[1] for item in scored[:8]]
    citations = [{"element_id": item["id"], **item["evidence"],
                  "confidence": item["confidence"], "state": item["state"]} for item in facts]
    if not facts:
        answer = (
            "当前提取的图纸证据不足以回答这个问题。我不会推断图纸中未标注或尚未确认的信息。"
            if chinese else
            "The extracted drawing evidence is insufficient to answer this question. "
            "I will not infer facts that are not labelled or confirmed in the drawing."
        )
        return {"answer": answer,
                "grounded": False, "facts": [], "citations": [],
                "boundary": "The assistant does not infer missing drawing facts."}
    answer = "; ".join(f'{item["label"]}: {item["value"]}' for item in facts)
    return {"answer": answer, "grounded": True,
            "facts": [{"id": item["id"], "type": item["type"], "label": item["label"],
                       "value": item["value"], "confidence": item["confidence"]} for item in facts],
            "citations": citations,
            "boundary": "Every returned fact is anchored to the immutable source drawing."}


@router.post("/{drawing_id}/confirm")
def confirm_drawing_field(
    drawing_id: str, payload: ConfirmDrawingRequest,
    principal: Principal = Depends(require_roles("engineer", "project_manager", "organization_admin")),
    db: Session = Depends(get_db),
):
    document = _get_document(db, drawing_id, principal)
    confirmations: list[tuple[str, str, str | None]] = []
    if payload.field is not None or payload.value is not None:
        if payload.field is None or payload.value is None:
            raise HTTPException(422, "field and value must be supplied together")
        confirmations.append((payload.field.strip(), payload.value.strip(), None))
    if payload.unit is not None:
        confirmations.append(("unit", payload.unit.strip(), None))
    if payload.scale is not None:
        confirmations.append(("scale", payload.scale.strip(), None))
    if payload.storey_height_m is not None:
        confirmations.append(("height", f"{payload.storey_height_m:g}", "m"))
    if payload.wall_thickness_m is not None:
        confirmations.append(("wall_thickness", f"{payload.wall_thickness_m:g}", "m"))
    if payload.source_calibration_m_per_pixel is not None:
        confirmations.append((
            "source_calibration",
            f"{payload.source_calibration_m_per_pixel:g}",
            "m/source_unit",
        ))
    if not confirmations:
        raise HTTPException(422, "At least one confirmation is required")

    supported_document_fields = {"title", "drawing_number", "revision", "scale", "unit", "discipline"}
    supported_parameters = {"height", "wall_thickness", "source_calibration"}
    resolved: list[tuple[str, str, str | None, DrawingElement | None]] = []
    seen_fields: set[str] = set()
    for field, value, confirmed_unit in confirmations:
        element = db.get(DrawingElement, field)
        if element is not None and element.drawing_id != drawing_id:
            raise HTTPException(404, "Drawing field not found")
        effective_field = field
        if element is not None:
            if element.element_type == "METADATA" and element.label in supported_document_fields:
                effective_field = element.label
            elif element.element_type == "PARAMETER" and element.label in supported_parameters:
                effective_field = element.label
        if (
            element is None
            and effective_field not in supported_document_fields
            and effective_field not in supported_parameters
        ):
            raise HTTPException(422, "Unsupported confirmation field")
        if effective_field in seen_fields:
            raise HTTPException(422, f"Duplicate confirmation for {effective_field}")
        seen_fields.add(effective_field)
        resolved.append((
            effective_field,
            _canonical_confirmation_value(effective_field, value),
            confirmed_unit,
            element,
        ))

    last_field = resolved[-1][0]
    confirmed_at = utc_now().isoformat()
    for effective_field, value, confirmed_unit, element in resolved:
        if effective_field in supported_document_fields:
            setattr(document, effective_field, value)
            document.metadata_json = {**document.metadata_json, effective_field: value}
            if element is None:
                element = db.scalar(select(DrawingElement).where(
                    DrawingElement.drawing_id == drawing_id,
                    DrawingElement.label == effective_field,
                ).limit(1))
        if element is None:
            sheet = db.scalar(select(DrawingSheet).where(DrawingSheet.drawing_id == drawing_id).order_by(DrawingSheet.page_number).limit(1))
            if not sheet:
                raise HTTPException(409, "Drawing has no normalized sheet")
            element = DrawingElement(
                id=_id("DE"), drawing_id=drawing_id, sheet_id=sheet.id,
                element_type="PARAMETER" if effective_field in {
                    "height", "wall_thickness", "source_calibration"
                } else "METADATA",
                label=effective_field, value=value, unit=confirmed_unit or document.unit,
                bbox=[0.0, 0.0, 0.0, 0.0], confidence=1.0,
                extraction_method="HUMAN_CONFIRMATION", review_status="USER_CONFIRMED",
                properties={"source_text": value, "actor": principal.subject,
                            "evidence_kind": "USER_CONFIRMATION",
                            "confirmed_at": confirmed_at},
            )
            db.add(element)
        else:
            element.value = value
            element.unit = confirmed_unit or element.unit
            element.confidence = 1.0
            element.review_status = "USER_CONFIRMED"
            element.properties = {**element.properties, "actor": principal.subject,
                                  "evidence_kind": "USER_CONFIRMATION",
                                  "confirmed_at": confirmed_at,
                                  "confirmed_from_method": element.extraction_method}
        if effective_field == "height":
            document.metadata_json = {
                **document.metadata_json, "storey_height_m": float(value)
            }
        elif effective_field == "wall_thickness":
            document.metadata_json = {
                **document.metadata_json, "wall_thickness_m": float(value)
            }
        elif effective_field == "source_calibration":
            document.metadata_json = {
                **document.metadata_json, "meters_per_source_unit": float(value)
            }
        last_field = effective_field
    db.flush()
    elements = list(db.scalars(select(DrawingElement).where(DrawingElement.drawing_id == drawing_id)))
    ready, blockers = _model_gate(document, elements)
    analysis = _latest_analysis(db, drawing_id)
    if analysis:
        analysis.model_ready = ready
        analysis.blockers = blockers
        analysis.summary = {**analysis.summary, "last_confirmation": last_field,
                            "confirmed_by": principal.subject}
    db.commit()
    db.refresh(document)
    return _detail(db, document)
