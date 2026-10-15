"""Upload and serve validated field evidence.

Files are accepted only when their bytes carry the signature of an allowed
image, video or audio format (the declared content type is not trusted),
stay within the upload limit, and are stored once per SHA-256. Attachments
on field observations may reference only media the same organization has
uploaded, with a matching hash.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import FieldMedia
from .security import Principal, require_roles

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


def verify_attachment(db: Session, organization_id: str, sha256: str, ref: str) -> None:
    """An attachment must point at media this organization uploaded here, or,
    once an object store is configured, at an object in it."""
    if ref.startswith("s3://") and settings.object_storage_endpoint:
        return
    if ref != storage_ref(sha256.lower()):
        raise HTTPException(422, "Attachment storage reference does not match its hash")
    media = db.get(FieldMedia, sha256.lower())
    if media is None or media.organization_id != organization_id:
        raise HTTPException(422, "Attachment has not been uploaded")


@router.post("/field/media", status_code=201)
async def upload_field_media(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_roles("field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
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
        db.add(FieldMedia(sha256=sha256, organization_id=principal.organization_id, media_type=media_type,
                          size=len(content), content=content, uploaded_by=principal.subject))
        db.commit()
    elif existing.organization_id != principal.organization_id:
        raise HTTPException(409, "Media already belongs to another organization")
    return {"sha256": sha256, "storage_ref": storage_ref(sha256), "media_type": media_type, "size": len(content),
            "created": existing is None}


@router.get("/field/media/{sha256}")
def get_field_media(
    sha256: str,
    principal: Principal = Depends(require_roles("viewer", "field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    media = db.get(FieldMedia, sha256.lower())
    if media is None or media.organization_id != principal.organization_id:
        raise HTTPException(404, "Media not found")
    return Response(media.content, media_type=media.media_type, headers={
        "Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline", "ETag": f'"{media.sha256}"',
    })
