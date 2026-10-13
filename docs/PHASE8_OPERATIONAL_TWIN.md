# Phase 8 — Operational Digital Twin

GlobalInfra AI V4.0 turns the synthetic six-format packs into a runnable operational-twin vertical slice. Every seeded project shares stable Twin IDs across geometry, geospatial services, telemetry, schedule/cost links and AI citations.

| Stage | Runnable capability | Primary surface |
| --- | --- | --- |
| 8.1 | Native WebGL renderer, GLTF node loading, object picking and inspection | `/twin` |
| 8.2 | Model versions, checksums, change summaries and conversion jobs | `GET /twin/model-versions`, `POST /twin/conversions` |
| 8.3 | Atomic project + twin graph + six-format data-plane generator | `/twin/generate`, `POST /twin/projects/generate` |
| 8.4 | Time-series ingestion, history and server-sent live events | `/twin/telemetry/*` |
| 8.5 | 4D progress timeline and 5D health/progress/cost coloring | WebGL workspace |
| 8.6 | Grounded project answer with Twin ID, event, model version and timestamp citations | `POST /twin/copilot/query` |
| 8.7 | Seven-step, 180-second competition story driven by live project data | `/showcase` |

## Data contract

The database migration `0006` adds profiles, model versions, conversion jobs, telemetry readings and Copilot runs. Project generation provisions stable Twin IDs and registers IFC, GLTF, 3D Tiles, GeoJSON, WMS and IoT instances. The Next.js proxy streams `text/event-stream` bodies without buffering.

## Honest boundaries

- The built-in conversion adapter generates reference GLTF/3D Tiles/GeoJSON output from the shared synthetic model. Customer IFC conversion requires a separately configured worker and object store.
- Live telemetry is a standards-shaped SSE stream over seeded/ingested values. A production MQTT, BMS or SCADA broker remains an external connector.
- Twin Copilot is deterministic and evidence-grounded in the demo environment. It never performs project or commercial actions; every response exposes a human-approval boundary.
- All bundled project data is clearly marked `SYNTHETIC_DEMO`, not as-built or customer data.

## Verification

Run `pytest -q` in `services/api`, apply `alembic upgrade head` to a fresh database, and run `npm run build` in `apps/web`. The API test suite covers model lineage, conversion, project generation, telemetry history/SSE, grounded citations and the complete 8.1–8.7 showcase sequence.
