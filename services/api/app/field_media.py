"""Upload and serve validated field evidence.

Files are accepted only when their bytes carry the signature of an allowed
image, video or audio format (the declared content type is not trusted),
stay within the upload limit, and are stored once per SHA-256. Attachments
on field observations may reference only media the same organization has
uploaded, with a matching hash.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import FieldMedia, FieldMediaGrant
from .security import Principal, require_project, require_roles

router = APIRouter(tags=["field"])
MEDIA_PREFIX = "media://sha256/"


def sniff(content: bytes) -> str | None:
    """Media type from file signature, or None when the format is not allowed."""
    head = content[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return "image/heic"
        if brand in (b"M4A ", b"M4B "):
            return "audio/mp4"
        return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    return None


def storage_ref(sha256: str) -> str:
    return f"{MEDIA_PREFIX}{sha256}"


def media_url(ref: str | None) -> str | None:
    return f"/backend/field/media/{ref[len(MEDIA_PREFIX):]}" if ref and ref.startswith(MEDIA_PREFIX) else None


def verify_attachment(
    db: Session,
    organization_id: str,
    project_id: int,
    sha256: str,
    ref: str,
) -> None:
    """Bind an uploaded object to one authorized project, fail closed otherwise."""
    if ref.startswith("s3://"):
        raise HTTPException(
            422,
            "External object references require a configured object-store integrity verifier.",
        )
    if ref != storage_ref(sha256.lower()):
        raise HTTPException(422, "Attachment storage reference does not match its hash")
    media = db.get(FieldMedia, sha256.lower())
    grant = db.scalar(
        select(FieldMediaGrant).where(
            FieldMediaGrant.sha256 == sha256.lower(),
            FieldMediaGrant.organization_id == organization_id,
            FieldMediaGrant.project_id == project_id,
        )
    )
    if media is None or grant is None:
        raise HTTPException(422, "Attachment has not been uploaded")


@router.post("/field/media", status_code=201)
async def upload_field_media(
    project_id: int = Form(..., gt=0),
    file: UploadFile = File(...),
    principal: Principal = Depends(require_roles("field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    require_project(principal, project_id, db)
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"Media exceeds the {settings.max_upload_bytes}-byte limit.")
    if not content:
        raise HTTPException(422, "Uploaded media is empty.")
    media_type = sniff(content)
    if media_type is None:
        raise HTTPException(415, "Only photos (JPEG, PNG, WebP, HEIC), video (MP4, WebM) and audio (M4A, MP3, OGG, WAV) are accepted.")
    sha256 = hashlib.sha256(content).hexdigest()
    existing = db.get(FieldMedia, sha256)
    if existing is None:
        db.add(FieldMedia(sha256=sha256, organization_id=principal.organization_id, project_id=project_id, media_type=media_type,
                          size=len(content), content=content, uploaded_by=principal.subject))
        db.flush()
    grant = db.scalar(
        select(FieldMediaGrant).where(
            FieldMediaGrant.sha256 == sha256,
            FieldMediaGrant.organization_id == principal.organization_id,
            FieldMediaGrant.project_id == project_id,
        )
    )
    grant_created = grant is None
    if grant is None:
        db.add(
            FieldMediaGrant(
                sha256=sha256,
                organization_id=principal.organization_id,
                project_id=project_id,
                uploaded_by=principal.subject,
            )
        )
    db.commit()
    return {"sha256": sha256, "storage_ref": storage_ref(sha256), "media_type": media_type, "size": len(content),
            "created": grant_created}


@router.get("/field/media/{sha256}")
def get_field_media(
    sha256: str,
    principal: Principal = Depends(require_roles("viewer", "field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    normalized = sha256.lower()
    grant_query = select(FieldMediaGrant).where(
        FieldMediaGrant.sha256 == normalized,
        FieldMediaGrant.organization_id == principal.organization_id,
    )
    if not principal.has_org_wide_project_access():
        grant_query = grant_query.where(
            FieldMediaGrant.project_id.in_(principal.project_ids)
        )
    grant = db.scalar(grant_query.limit(1))
    if grant is None:
        raise HTTPException(404, "Media not found")
    require_project(principal, grant.project_id, db)
    media = db.get(FieldMedia, normalized)
    if media is None:
        raise HTTPException(404, "Media not found")
    return Response(media.content, media_type=media.media_type, headers={
        "Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline", "ETag": f'"{media.sha256}"',
    })
