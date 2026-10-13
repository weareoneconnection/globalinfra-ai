# Phase 7 Production Pilot

GlobalInfra AI V3.0 advances the Phase 6 digital-twin product into a production-pilot operating plane. It does not claim that vendor credentials, customer identity tenants or customer model files are bundled in the repository. Instead, it provides the enforceable contracts those systems plug into.

## 7.1 Trusted execution

Claims and evidence create governed action intents. Approval unlocks execution but does not imply success. Content-addressed artifacts, execution receipts and independent verification receipts are required before closure.

## 7.2 Identity and authorization

`AUTH_MODE` supports `disabled`, `api_key` and `oidc`. OIDC validates signed JWTs through the issuer JWKS and normalizes organization, roles and project scope into a `Principal`. Mutating production routes use RBAC. Request IDs and tenant-scoped audit events record every mutation. The server-rendered Web tier can use a separately configured service credential; browser/API clients use OIDC bearer tokens. The public demo intentionally defaults to `disabled`; production must use `oidc`.

## 7.3 Field operations

`/field` is an offline-first PWA workspace. Observations are stored in IndexedDB, retried with idempotent client IDs and synchronized in batches. Camera/media evidence is hashed on-device; original binaries require configured object storage. Each synchronized observation creates a governed Case and can reference a stable Twin ID.

## 7.4 Real twin sources

The source registry accepts IFC, glTF, 3D Tiles, GeoJSON, WMS and IoT references with versions, CRS, checksums and metadata. Registration does not pretend to convert a customer model. A deployment connects a conversion/streaming worker while preserving the Twin ID contract.

## 7.5 Enterprise connectors

The catalog covers Primavera P6, Autodesk Construction Cloud, SharePoint, SAP/Oracle, ArcGIS/GeoServer and MQTT/BMS/SCADA. All adapters normalize into `external_id`, `object_type`, `updated_at` and `payload`. Credentials are rejected from persisted connector configuration and must come from the deployment secret manager. Webhooks require HMAC signatures.

## 7.6 AI release gates

Model evaluation runs store dataset version, metrics, thresholds and a pass/block result. A score below its declared minimum closes the release gate. This complements the existing deterministic fallback, restricted-data local routing and evidence-grounded workflow.

## 7.7 Operations and security

The API exposes `/livez`, `/readyz` and Prometheus-compatible `/metrics`, issues a request ID on every response, rate limits abusive clients and writes mutation audit events. Kubernetes uses separate liveness/readiness probes. CI checks API tests, evaluations, migrations, dependency consistency, the Web production build and full-stack smoke routes.

## Production activation checklist

1. Set `AUTH_MODE=oidc`, issuer, audience and claims mapping.
2. Configure object storage and malware scanning for field media.
3. Provision connector credentials in the secret manager, never connector JSON.
4. Replace sample twin source references with customer-controlled URIs.
5. Run the AI evaluation suites and require open release gates.
6. Export `/metrics` and application logs to the selected observability backend.
7. Run database backup/restore and incident-response exercises before go-live.
