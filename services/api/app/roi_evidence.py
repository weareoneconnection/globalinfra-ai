"""Reproducible, source-limited paired-study ROI evidence.

A digest proves byte-level integrity of a declared dataset, NOT truth of a
record or permission to use it. A separate reviewer must assess source and
authorization out of band. Never send customer text into the evidence payload.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PairedCase(BaseModel):
    case_id: str = Field(min_length=3, max_length=96, pattern=r"^[A-Za-z0-9_.-]+$")
    baseline_value: float = Field(ge=0, allow_inf_nan=False)
    assisted_value: float = Field(ge=0, allow_inf_nan=False)


class PairedStudy(BaseModel):
    schema_version: Literal["globalinfra.pilot-roi-paired.v1"]
    project_id: int = Field(gt=0)
    metric_name: str = Field(min_length=3, max_length=80)
    unit: str = Field(min_length=1, max_length=32)
    source_type: Literal["AUTHORIZED_REAL", "SYNTHETIC"]
    authorization_ref: str = Field(min_length=6, max_length=255)
    study_protocol_ref: str = Field(min_length=6, max_length=255)
    cases: list[PairedCase] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_case_ids(self):
        keys = [row.case_id for row in self.cases]
        if len(set(keys)) != len(keys):
            raise ValueError("Case IDs must be unique; repeated cases bias ROI")
        return self


def canonical_evidence_bytes(study: PairedStudy) -> bytes:
    return json.dumps(
        study.model_dump(mode="json"),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def evidence_sha256(study: PairedStudy) -> str:
    return hashlib.sha256(canonical_evidence_bytes(study)).hexdigest()


def study_means(study: PairedStudy) -> tuple[float, float]:
    size = len(study.cases)
    return (
        math.fsum(row.baseline_value for row in study.cases) / size,
        math.fsum(row.assisted_value for row in study.cases) / size,
    )


def validate_record_against_study(
    study: PairedStudy,
    *,
    project_id: int,
    metric_name: str,
    unit: str,
    sample_size: int,
    baseline_value: float,
    assisted_value: float,
) -> list[str]:
    reasons: list[str] = []
    if study.project_id != project_id:
        reasons.append("PROJECT_MISMATCH")
    if study.metric_name != metric_name:
        reasons.append("METRIC_MISMATCH")
    if study.unit != unit:
        reasons.append("UNIT_MISMATCH")
    if len(study.cases) != sample_size:
        reasons.append("SAMPLE_SIZE_MISMATCH")
    mean_baseline, mean_assisted = study_means(study)
    # The stored summary permits 0.01-unit rounding at intake but not an
    # arbitrary claimed percentage. Use strict absolute tolerance, not relative.
    if abs(mean_baseline - baseline_value) > 0.01:
        reasons.append("BASELINE_NOT_REPRODUCED")
    if abs(mean_assisted - assisted_value) > 0.01:
        reasons.append("ASSISTED_NOT_REPRODUCED")
    return reasons
