"""Field evidence upload: signature validation, dedupe, serving and linking."""
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + uuid4().bytes
PNG = b"\x89PNG\r\n\x1a\n" + uuid4().bytes
M4A = b"\x00\x00\x00\x20ftypM4A " + uuid4().bytes


def _upload(client, name, content, declared="application/octet-stream"):
    return client.post("/field/media", files={"file": (name, content, declared)})


def test_upload_detects_type_from_bytes_and_dedupes(client):
    first = _upload(client, "photo.bin", JPEG)
    assert first.status_code == 201 and first.json()["media_type"] == "image/jpeg"
    assert first.json()["sha256"] == hashlib.sha256(JPEG).hexdigest()
    again = _upload(client, "same.jpg", JPEG, "image/jpeg").json()
    assert again["created"] is False and again["storage_ref"] == first.json()["storage_ref"]
    assert _upload(client, "voice.m4a", M4A).json()["media_type"] == "audio/mp4"


def test_upload_rejects_disguised_and_empty_files(client):
    assert _upload(client, "evil.jpg", b"<script>alert(1)</script>", "image/jpeg").status_code == 415
    assert _upload(client, "empty.jpg", b"", "image/jpeg").status_code == 422


def test_media_is_served_with_safe_headers(client):
    sha = _upload(client, "p.png", PNG).json()["sha256"]
    r = client.get(f"/field/media/{sha}")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/field/media/{'0' * 64}").status_code == 404


def test_observation_may_only_reference_uploaded_media(client):
    def observation(attachment):
        return {"client_id": f"media-test:{uuid4().hex}", "project_id": 1, "twin_id": None, "event_type": "inspection",
                "severity": "LOW", "description": "Photo of the P47 pier cap edge.", "location": {},
                "attachments": [attachment], "captured_at": datetime.now(UTC).isoformat()}
    fake = {"name": "x.jpg", "media_type": "image/jpeg", "size": 10, "sha256": "b" * 64, "storage_ref": f"media://sha256/{'b' * 64}"}
    assert client.post("/field/observations", json=observation(fake)).status_code == 422
    foreign = {**fake, "storage_ref": "s3://somewhere/x.jpg"}
    assert client.post("/field/observations", json=observation(foreign)).status_code == 422
    uploaded = _upload(client, "real.jpg", JPEG).json()
    good = {"name": "real.jpg", "media_type": "image/jpeg", "size": uploaded["size"], "sha256": uploaded["sha256"],
            "storage_ref": uploaded["storage_ref"]}
    created = client.post("/field/observations", json=observation(good))
    assert created.status_code == 201 and created.json()["sync_status"] == "SYNCED"
    report = next(r for r in client.get("/field/reports").json() if r["id"] == created.json()["id"])
    assert report["attachments"][0]["url"] == f"/backend/field/media/{uploaded['sha256']}"
