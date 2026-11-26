"""Authorized, de-identified field records (real project correspondence, NCRs,
daily reports) for the knowledge base.

Nothing in this module invents data. It only:

1. checks that an authorization record exists, is complete, unexpired and
   covers the document type being imported;
2. removes personal identifiers and replaces names of people, companies and
   projects with stable aliases supplied by the data owner;
3. loads the redacted records as project-scoped, non-public knowledge
   documents, so they can never leak into public search or the hermetic
   competition benchmark.

The redaction report keeps counts per category, never the removed values.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .i18n import bi
from .models import KnowledgeDocument, Project

FIELD_DOCUMENT_TYPE = "FIELD_RECORD"
FIELD_RECORDS_FILE = "field_records.jsonl"
AUTHORIZATION_FIELDS = (
    "authorization_id", "grantor_organisation", "grantor_role", "granted_on", "expires_on",
    "purpose", "permitted_uses", "document_types", "countries", "evidence_ref",
)
PERMITTED_USES = {"competition_demo", "pilot_evaluation", "internal_rnd"}

# Order matters: longer, more specific identifiers first.
PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("ID_NIK", re.compile(r"(?<!\d)\d{16}(?!\d)")),
    ("MY_NRIC", re.compile(r"(?<!\d)\d{6}-\d{2}-\d{4}(?!\d)")),
    ("BANK_ACCOUNT", re.compile(r"(?i)(?:a/c|acct|account|rekening|akaun|账号|账户)[\s:#.no]*([\d][\d -]{7,22}\d)")),
    ("PHONE", re.compile(r"(?<![\w])(?:\+?6[02]|\+?86|0)[\s-]?\d{1,4}(?:[\s-]?\d{3,4}){2}(?![\w])")),
    ("PASSPORT", re.compile(r"(?i)(?:passport|pasport|paspor|护照)[\s:#.no]*([A-Z]{1,2}\d{6,9})")),
]
HONORIFIC_NAME = re.compile(
    r"\b(?:Mr|Mrs|Ms|Mdm|Dr|Ir|Encik|En|Puan|Pn|Tuan|Cik|Bapak|Pak|Ibu|Bu|Saudara|Sdr)\.?\s+"
    r"(?:[A-Z][a-zA-Z'’-]+)(?:\s+(?:bin|binti|a/l|a/p|[A-Z][a-zA-Z'’-]+)){0,4}"
)


class AuthorizationError(ValueError):
    """The authorization record is missing, incomplete, expired or out of scope."""


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


def validate_authorization(record: dict, *, document_type: str | None = None, today: date | None = None) -> dict:
    missing = [key for key in AUTHORIZATION_FIELDS if not record.get(key)]
    if missing:
        raise AuthorizationError(f"authorization record is missing: {', '.join(missing)}")
    today = today or date.today()
    try:
        expires = date.fromisoformat(str(record["expires_on"]))
        granted = date.fromisoformat(str(record["granted_on"]))
    except ValueError as exc:
        raise AuthorizationError("granted_on / expires_on must be ISO dates (YYYY-MM-DD)") from exc
    if granted > today:
        raise AuthorizationError("authorization is not yet in effect")
    if expires < today:
        raise AuthorizationError(f"authorization expired on {expires.isoformat()}")
    unknown = set(record["permitted_uses"]) - PERMITTED_USES
    if unknown:
        raise AuthorizationError(f"unknown permitted_uses: {', '.join(sorted(unknown))}")
    if document_type and document_type not in record["document_types"]:
        raise AuthorizationError(f"document type {document_type!r} is outside the authorized scope")
    return record


def redact(text: str, *, names: list[str] | None = None, aliases: dict[str, str] | None = None) -> RedactionResult:
    """Remove personal identifiers and apply owner-supplied aliases."""
    counts: dict[str, int] = {}

    def bump(kind: str, n: int = 1) -> None:
        if n:
            counts[kind] = counts.get(kind, 0) + n

    for original, alias in sorted((aliases or {}).items(), key=lambda item: -len(item[0])):
        if not original:
            continue
        text, n = re.subn(re.escape(original), alias, text, flags=re.IGNORECASE)
        bump("ALIAS", n)
    for name in sorted({n for n in (names or []) if n and len(n) >= 2}, key=len, reverse=True):
        text, n = re.subn(re.escape(name), "[PERSON]", text, flags=re.IGNORECASE)
        bump("PERSON", n)
    text, n = HONORIFIC_NAME.subn("[PERSON]", text)
    bump("PERSON", n)
    for kind, pattern in PII_PATTERNS:
        text, n = pattern.subn(f"[{kind}]", text)
        bump(kind, n)
    return RedactionResult(text=text, counts=counts)


def fingerprint(text: str) -> str:
    """Digest of the original text, kept for audit; the text itself is not stored."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_field_records(directory: str | os.PathLike) -> list[dict]:
    path = Path(directory) / FIELD_RECORDS_FILE
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def seed_field_records(db: Session, directory: str | os.PathLike | None = None) -> int:
    """Upsert redacted field records from ``FIELD_DATA_DIR`` (if configured).

    Each record must still carry a valid authorization; expired or
    unauthorized records are skipped and removed from the knowledge base.
    """
    directory = directory or os.environ.get("FIELD_DATA_DIR")
    if not directory:
        return 0
    loaded = 0
    for row in load_field_records(directory):
        ref = row["record_id"]
        document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == ref))
        try:
            validate_authorization(row["authorization"], document_type=row["document_type"])
        except AuthorizationError:
            if document is not None:
                db.delete(document)
            continue
        project = db.scalar(select(Project).where(Project.code == row["project_code"]))
        if project is None:
            continue
        content = bi(row["text"], row.get("text_zh") or row["text"])
        values = dict(
            title=bi(row["title"], row.get("title_zh") or row["title"]),
            category=bi("Field record", "现场记录"), jurisdiction=bi(row["country"], row["country"]),
            language=bi(row.get("language", "mixed"), row.get("language", "mixed")), source_ref=ref, content=content,
            summary=bi(row["title"], row.get("title_zh") or row["title"]), country_code=row["country"], project_id=project.id,
            document_type=FIELD_DOCUMENT_TYPE, authority=None, version="1", status="CURRENT", effective_date=row.get("record_date"),
            review_due=None, source_url=None, content_hash=row["redacted_sha256"],
            tags=[row["document_type"], "AUTHORIZED_DEIDENTIFIED", row["authorization"]["authorization_id"]],
            lifecycle_stages=row.get("lifecycle_stages") or ["construction"], confidentiality="CONFIDENTIAL",
            updated_at=datetime.fromisoformat(row["imported_at"]),
        )
        if document is None:
            db.add(KnowledgeDocument(**values))
        else:
            for key, value in values.items():
                setattr(document, key, value)
        loaded += 1
    return loaded
