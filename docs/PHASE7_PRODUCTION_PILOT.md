# Phase 7 Production Pilot

GlobalInfra AI V3.0 advances the Phase 6 digital-twin product into a production-pilot operating plane. It does not claim that vendor credentials, customer identity tenants or customer model files are bundled in the repository. Instead, it provides the enforceable contracts those systems plug into.

## 7.1 Trusted execution

Claims and evidence create governed action intents. Approval unlocks execution but does not imply success. Content-addressed artifacts, execution receipts and independent verification receipts are required before closure.

## 7.2 Identity and authorization

`AUTH_MODE` supports `disabled`, `api_key` and `oidc`. OIDC validates signed JWTs through the issuer JWKS and normalizes organization, roles and project scope into a `Principal`. Mutating production routes use RBAC. Request IDs and tenant-scoped audit events record every mutation. In OIDC mode, the Web tier completes the authorization-code + PKCE flow at `/auth/login` and `/auth/callback`, verifies the ID-token signature and binding claims through issuer JWKS, keeps the access token in an encrypted HTTP-only session, and forwards the current user's bearer token to tenant routes. Its separate service credential is limited to explicitly public competition routes and cannot stand in for a human identity. The public demo intentionally defaults to `disabled`; production must use `oidc`.

## 7.3 Field operations

`/field` is an offline-first PWA workspace. Observations are stored in IndexedDB, retried with idempotent client IDs and synchronized in batches. Camera/media evidence is hashed on-device; original binaries require configured object storage. Each synchronized observation creates a governed Case and can reference a stable Twin ID.

## 7.4 Real twin sources

The source registry accepts IFC, glTF, 3D Tiles, GeoJSON, WMS and IoT references with versions, CRS, checksums and metadata. Registration does not pretend to convert a customer model. A deployment connects a conversion/streaming worker while preserving the Twin ID contract.

## 7.5 Enterprise connectors

The catalog covers Primavera P6, Autodesk Construction Cloud, SharePoint, SAP/Oracle, ArcGIS/GeoServer and MQTT/BMS/SCADA. All adapters normalize into `external_id`, `object_type`, `updated_at` and `payload`. Credentials are rejected from persisted connector configuration and must come from the deployment secret manager. Webhooks require HMAC signatures with a connector-scoped key derived as `HMAC-SHA256(CONNECTOR_WEBHOOK_SECRET, "globalinfra.webhook.v1:<connector_id>")`; provision only that derived key to each vendor, never the deployment root.

## 7.6 AI release gates

Model evaluation runs store dataset version, metrics, thresholds and a pass/block result. A score below its declared minimum closes the release gate. This complements the existing deterministic fallback, restricted-data local routing and evidence-grounded workflow.

## 7.7 Operations and security

The API exposes `/livez`, `/readyz` and Prometheus-compatible `/metrics`, issues a request ID on every response, rate limits abusive clients and writes mutation audit events. The Web exposes unauthenticated `/healthz` for process liveness and `/readyz` for fail-closed auth/session configuration readiness; protected pages are not valid health endpoints. Kubernetes uses those separate liveness/readiness probes. CI checks API tests, evaluations, migrations, dependency consistency, the Web production build and full-stack smoke routes.

## Production activation checklist

1. Set API `AUTH_MODE=oidc`; configure issuer, audience and claims mapping. Set Web `API_AUTH_MODE=oidc`, its OAuth client/endpoints/callback, and a high-entropy `WEB_SESSION_SECRET` as documented in `RAILWAY_DEPLOYMENT.md`.
2. Configure object storage and malware scanning for field media.
3. Provision connector credentials in the secret manager, never connector JSON.
4. Replace sample twin source references with customer-controlled URIs.
5. Run the AI evaluation suites and require open release gates.
6. Export `/metrics` and application logs to the selected observability backend.
7. Run database backup/restore and incident-response exercises before go-live.
