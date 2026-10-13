"""Deterministic synthetic twin packs for projects without customer data.

The pack is intentionally standards-shaped and downloadable.  Every format is
derived from the same project objects and stable Twin IDs so a demonstration
exercises the integration contract instead of showing six unrelated mock rows.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Project, TwinObject, TwinSensor, TwinSource

router = APIRouter(prefix="/twin/demo-pack", tags=["synthetic-digital-twin"])

PACK_CONFIG = {
    1: {"slug": "my-rail-a", "center": [101.6870, 3.1390], "kind": "rail", "version": "2026.10-A"},
    2: {"slug": "id-highway-b", "center": [106.8456, -6.2088], "kind": "highway", "version": "2026.10-B"},
    3: {"slug": "sa-metro-c", "center": [46.6753, 24.7136], "kind": "metro", "version": "2026.10-C"},
}

FORMAT_PATHS = {
    "IFC": "model.ifc",
    "GLTF": "model.gltf",
    "3D_TILES": "tileset.json",
    "GEOJSON": "features.geojson",
    "WMS": "wms?service=WMS&request=GetCapabilities",
    "IOT": "iot/telemetry",
}

LEGACY_SOURCE_IDS = {
    (1, "IFC"): "TS-MYRAIL-IFC",
    (1, "3D_TILES"): "TS-MYRAIL-TILES",
    (1, "IOT"): "TS-MYRAIL-IOT",
}


def _context(project_id: int, db: Session) -> tuple[Project, list[TwinObject], dict]:
    project = db.get(Project, project_id)
    config = PACK_CONFIG.get(project_id)
    if not project or not config:
        raise HTTPException(404, "Synthetic twin pack is not configured for this project")
    objects = list(db.scalars(select(TwinObject).where(TwinObject.project_id == project_id).order_by(TwinObject.id)))
    if not objects:
        raise HTTPException(404, "Project has no Twin ID objects")
    return project, objects, config


def _name(value: dict | str) -> str:
    return value.get("en") or value.get("zh") or next(iter(value.values()), "Twin object") if isinstance(value, dict) else value


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_ifc(project: Project, objects: list[TwinObject], config: dict) -> bytes:
    timestamp = "2026-10-13T00:00:00"
    lines = [
        "ISO-10303-21;", "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');",
        f"FILE_NAME('{config['slug']}.ifc','{timestamp}',('GlobalInfra AI'),('ONEAI LABS'),'GlobalInfra AI','Synthetic Twin Pack','');",
        "FILE_SCHEMA(('IFC4X3_ADD2'));", "ENDSEC;", "DATA;",
        "#1=IFCPERSON($,$,'GlobalInfra AI',$,$,$,$,$);",
        "#2=IFCORGANIZATION($,'ONEAI LABS',$,$,$);",
        "#3=IFCPERSONANDORGANIZATION(#1,#2,$);",
        "#4=IFCAPPLICATION(#2,'3.0','GlobalInfra AI','GLOBALINFRA');",
        "#5=IFCOWNERHISTORY(#3,#4,$,.ADDED.,$,$,$,1791849600);",
        f"#10=IFCPROJECT('{hashlib.sha1(project.code.encode()).hexdigest()[:22]}',#5,'{project.code} - Synthetic Digital Twin',$,$,$,$,$,$);",
        f"#11=IFCSITE('{hashlib.sha1((project.code+'site').encode()).hexdigest()[:22]}',#5,'{escape(_name(project.name))}',$,$,$,$,$,$,$,$,$,$,$);",
    ]
    entity_ids = []
    for index, obj in enumerate(objects, start=20):
        guid = (obj.ifc_guid or hashlib.sha1(obj.id.encode()).hexdigest())[:22]
        lines.append(
            f"#{index}=IFCBUILDINGELEMENTPROXY('{guid}',#5,'{escape(_name(obj.name))}','Twin ID: {obj.id}',$,$,$,$,.NOTDEFINED.);"
        )
        entity_ids.append(f"#{index}")
    lines.extend([
        f"#12=IFCRELAGGREGATES('{hashlib.sha1((project.code+'agg').encode()).hexdigest()[:22]}',#5,'Twin hierarchy',$,#11,({','.join(entity_ids)}));",
        "ENDSEC;", "END-ISO-10303-21;", "",
    ])
    return "\n".join(lines).encode()


def build_gltf(project: Project, objects: list[TwinObject], config: dict) -> bytes:
    positions = [-.5,-.5,-.5, .5,-.5,-.5, .5,.5,-.5, -.5,.5,-.5, -.5,-.5,.5, .5,-.5,.5, .5,.5,.5, -.5,.5,.5]
    indices = [0,1,2,0,2,3, 4,6,5,4,7,6, 0,4,5,0,5,1, 1,5,6,1,6,2, 2,6,7,2,7,3, 3,7,4,3,4,0]
    pos_bytes = struct.pack("<24f", *positions)
    idx_bytes = struct.pack("<36H", *indices)
    buffer = pos_bytes + idx_bytes
    nodes = []
    for index, obj in enumerate(objects):
        nodes.append({
            "name": _name(obj.name), "mesh": 0,
            "translation": [index * 2.2 - (len(objects) - 1) * 1.1, (index % 2) * .45, 0],
            "scale": [1.7 if obj.object_type in {"PROJECT", "FACILITY"} else .75, .55 + (index % 3) * .25, .7],
            "extras": {"twin_id": obj.id, "status": obj.status, "health": obj.health_score, "synthetic": True},
        })
    payload = {
        "asset": {"version": "2.0", "generator": "GlobalInfra AI Synthetic Twin Generator", "extras": {"provenance": "SYNTHETIC_DEMO"}},
        "scene": 0, "scenes": [{"name": project.code, "nodes": list(range(len(nodes)))}], "nodes": nodes,
        "meshes": [{"name": f"{config['kind']}-asset", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"name": "GlobalInfra cyan", "pbrMetallicRoughness": {"baseColorFactor": [.08,.72,.82,1], "metallicFactor": .35, "roughnessFactor": .48}}],
        "buffers": [{"byteLength": len(buffer), "uri": "data:application/octet-stream;base64," + base64.b64encode(buffer).decode()}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962}, {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(idx_bytes), "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3", "min": [-.5,-.5,-.5], "max": [.5,.5,.5]}, {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"}],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def build_geojson(project: Project, objects: list[TwinObject], config: dict) -> bytes:
    lng, lat = config["center"]
    line = [[lng + index * .003, lat + math.sin(index / 2) * .0015] for index in range(max(4, len(objects) + 1))]
    features = [{"type": "Feature", "id": f"{project.code}-alignment", "properties": {"project": project.code, "kind": config["kind"], "synthetic": True}, "geometry": {"type": "LineString", "coordinates": line}}]
    for index, obj in enumerate(objects):
        point = line[min(index, len(line) - 1)]
        features.append({"type": "Feature", "id": obj.id, "properties": {"twin_id": obj.id, "name": _name(obj.name), "object_type": obj.object_type, "status": obj.status, "health": obj.health_score}, "geometry": {"type": "Point", "coordinates": point}})
    return json.dumps({"type": "FeatureCollection", "name": project.code, "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": features}, ensure_ascii=False, separators=(",", ":")).encode()


def build_tileset(project: Project, objects: list[TwinObject], config: dict) -> bytes:
    lng, lat = [math.radians(value) for value in config["center"]]
    payload = {
        "asset": {"version": "1.1", "tilesetVersion": config["version"], "extras": {"provenance": "SYNTHETIC_DEMO"}},
        "geometricError": 500,
        "root": {"boundingVolume": {"region": [lng-.01, lat-.01, lng+.01, lat+.01, 0, 180]}, "geometricError": 80, "refine": "ADD", "content": {"uri": "model.gltf"}, "extras": {"project": project.code, "twin_ids": [obj.id for obj in objects]}},
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def build_wms_capabilities(project: Project, config: dict) -> bytes:
    lng, lat = config["center"]
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<WMS_Capabilities version="1.3.0" xmlns="http://www.opengis.net/wms" xmlns:xlink="http://www.w3.org/1999/xlink">
  <Service><Name>WMS</Name><Title>GlobalInfra AI Synthetic Twin WMS</Title><Abstract>SYNTHETIC_DEMO for {escape(project.code)}</Abstract></Service>
  <Capability><Request><GetCapabilities><Format>text/xml</Format></GetCapabilities><GetMap><Format>image/svg+xml</Format></GetMap></Request>
  <Layer><Title>{escape(_name(project.name))}</Title><CRS>EPSG:4326</CRS><EX_GeographicBoundingBox><westBoundLongitude>{lng-.02}</westBoundLongitude><eastBoundLongitude>{lng+.02}</eastBoundLongitude><southBoundLatitude>{lat-.02}</southBoundLatitude><northBoundLatitude>{lat+.02}</northBoundLatitude></EX_GeographicBoundingBox>
  <Layer queryable="1"><Name>{escape(config['slug'])}:twin</Name><Title>{escape(project.code)} Twin Assets</Title><CRS>EPSG:4326</CRS></Layer></Layer></Capability>
</WMS_Capabilities>'''
    return xml.encode()


def build_wms_map(project: Project, objects: list[TwinObject], config: dict) -> bytes:
    marks = "".join(f'<circle cx="{70+i*70}" cy="{130+(i%2)*35}" r="9" fill="#65e5f5"/><text x="{70+i*70}" y="{165+(i%2)*35}" text-anchor="middle">{escape(obj.id[-10:])}</text>' for i, obj in enumerate(objects[:8]))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320" viewBox="0 0 640 320"><rect width="640" height="320" fill="#071016"/><path d="M40 180 C170 60 350 250 600 105" fill="none" stroke="#2a7180" stroke-width="12"/><path d="M40 180 C170 60 350 250 600 105" fill="none" stroke="#76e9f5" stroke-width="2" stroke-dasharray="9 8"/>{marks}<text x="30" y="35" fill="#fff" font-family="sans-serif" font-size="18">{escape(project.code)} · Synthetic WMS</text><text x="30" y="58" fill="#6ba6ae" font-family="monospace" font-size="11">EPSG:4326 · {escape(config['version'])}</text></svg>'''.encode()


def artifact_payloads(project: Project, objects: list[TwinObject], config: dict) -> dict[str, bytes]:
    return {
        "IFC": build_ifc(project, objects, config), "GLTF": build_gltf(project, objects, config),
        "3D_TILES": build_tileset(project, objects, config), "GEOJSON": build_geojson(project, objects, config),
        "WMS": build_wms_capabilities(project, config),
    }


def seed_synthetic_twin_sources(db: Session) -> None:
    """Ensure that every seeded project advertises the complete 6-format pack."""
    for project_id, config in PACK_CONFIG.items():
        project = db.get(Project, project_id)
        if not project:
            continue
        objects = list(db.scalars(select(TwinObject).where(TwinObject.project_id == project_id).order_by(TwinObject.id)))
        if not objects:
            continue
        payloads = artifact_payloads(project, objects, config)
        for source_type, path in FORMAT_PATHS.items():
            source_id = LEGACY_SOURCE_IDS.get((project_id, source_type), f"TS-{project.code}-{source_type.replace('_', '')}")
            row = db.get(TwinSource, source_id)
            if row is None:
                row = TwinSource(id=source_id, organization_id="globalinfra-demo", project_id=project_id, source_type=source_type, name=f"{project.code} · {source_type.replace('_', ' ')} synthetic instance", uri="", version=config["version"], coordinate_reference_system=None, status="SYNTHETIC_DEMO", checksum=None, metadata_json={})
                db.add(row)
            row.name = f"{project.code} · {source_type.replace('_', ' ')} synthetic instance"
            row.uri = f"/backend/twin/demo-pack/{project_id}/{path}"
            row.version = config["version"]
            row.coordinate_reference_system = None if source_type in {"IOT", "GLTF", "IFC"} else "EPSG:4326"
            row.status = "SYNTHETIC_DEMO"
            row.checksum = _sha(payloads[source_type]) if source_type in payloads else None
            row.metadata_json = {"provenance": "SYNTHETIC_DEMO", "generator": "GlobalInfra AI", "project_code": project.code, "downloadable": True, "twin_ids": len(objects)}
    db.commit()


@router.get("/{project_id}/manifest")
def manifest(project_id: int, db: Session = Depends(get_db)):
    project, objects, config = _context(project_id, db)
    payloads = artifact_payloads(project, objects, config)
    base = f"/backend/twin/demo-pack/{project_id}"
    artifacts = [{"type": kind, "url": f"{base}/{FORMAT_PATHS[kind]}", "sha256": _sha(data), "bytes": len(data)} for kind, data in payloads.items()]
    artifacts.append({"type": "IOT", "url": f"{base}/{FORMAT_PATHS['IOT']}", "sha256": None, "bytes": None})
    return {"project_id": project.id, "project_code": project.code, "version": config["version"], "provenance": "SYNTHETIC_DEMO", "disclaimer": "Generated demonstration data; not an as-built or customer model.", "twin_ids": [obj.id for obj in objects], "coverage": "6/6", "artifacts": artifacts}


@router.get("/{project_id}/model.ifc")
def ifc(project_id: int, db: Session = Depends(get_db)):
    project, objects, config = _context(project_id, db)
    return Response(build_ifc(project, objects, config), media_type="application/x-step", headers={"Content-Disposition": f'inline; filename="{config["slug"]}.ifc"', "X-Data-Provenance": "SYNTHETIC_DEMO"})


@router.get("/{project_id}/model.gltf")
def gltf(project_id: int, db: Session = Depends(get_db)):
    project, objects, config = _context(project_id, db)
    return Response(build_gltf(project, objects, config), media_type="model/gltf+json", headers={"X-Data-Provenance": "SYNTHETIC_DEMO"})


@router.get("/{project_id}/tileset.json")
def tileset(project_id: int, db: Session = Depends(get_db)):
    project, objects, config = _context(project_id, db)
    return Response(build_tileset(project, objects, config), media_type="application/json", headers={"X-Data-Provenance": "SYNTHETIC_DEMO"})


@router.get("/{project_id}/features.geojson")
def geojson(project_id: int, db: Session = Depends(get_db)):
    project, objects, config = _context(project_id, db)
    return Response(build_geojson(project, objects, config), media_type="application/geo+json", headers={"X-Data-Provenance": "SYNTHETIC_DEMO"})


@router.get("/{project_id}/wms")
def wms(project_id: int, request: str = Query(default="GetCapabilities"), db: Session = Depends(get_db)):
    project, objects, config = _context(project_id, db)
    if request.lower() == "getmap":
        return Response(build_wms_map(project, objects, config), media_type="image/svg+xml", headers={"X-Data-Provenance": "SYNTHETIC_DEMO"})
    return Response(build_wms_capabilities(project, config), media_type="application/xml", headers={"X-Data-Provenance": "SYNTHETIC_DEMO"})


@router.get("/{project_id}/iot/telemetry")
def iot(project_id: int, db: Session = Depends(get_db)):
    project, objects, config = _context(project_id, db)
    ids = [obj.id for obj in objects]
    sensors = list(db.scalars(select(TwinSensor).where(TwinSensor.twin_id.in_(ids))))
    now = datetime.now(UTC)
    readings = [{"sensor_id": sensor.id, "twin_id": sensor.twin_id, "type": sensor.sensor_type, "value": sensor.latest_value, "unit": sensor.unit, "status": sensor.status, "sampled_at": now.isoformat()} for sensor in sensors]
    if not readings:
        readings = [{"sensor_id": f"SNS-{project.code}-ENV", "twin_id": objects[-1].id, "type": "ENVIRONMENT", "value": round(22 + project_id * 1.7 + math.sin(now.minute / 10), 2), "unit": "°C", "status": "ONLINE", "sampled_at": now.isoformat()}]
    return JSONResponse({"project_id": project.id, "project_code": project.code, "topic": f"globalinfra/{config['slug']}/telemetry", "provenance": "SYNTHETIC_DEMO", "readings": readings}, headers={"Cache-Control": "no-store", "X-Data-Provenance": "SYNTHETIC_DEMO"})
