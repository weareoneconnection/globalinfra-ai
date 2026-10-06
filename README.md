> **Language / 语言**: English · [简体中文](README.zh-CN.md)

# GlobalInfra AI V1.1

**Global Transportation Infrastructure Intelligence & Trusted Execution Platform**

GlobalInfra AI V1.1 is an independent, competition-ready platform for overseas transportation infrastructure projects. It is built on a two-axis model: the complete project lifecycle and eight connected intelligence domains. Every event is resolved through an evidence-backed, governed action loop.

> Scope note: this repository is a new standalone codebase. It does not depend on, import, call, or expose TheOne or any TheOne-branded runtime.

## What is runnable in V1.1

- Global Command Center dashboard
- Lifecycle-aware project portfolio and project workspace
- Eight intelligence domains covering 24 engineering disciplines
- Infrastructure digital thread across technical, delivery, commercial and asset records
- Case intelligence workflow
- Dynamic specialist-team assembly and multi-agent analysis trace
- Evidence-backed decisions
- Approval center
- Knowledge search
- Workforce competency and localized training capability
- Country Packs and Domain Packs
- Owner-letter workflow definition
- Independent verification record
- Synthetic demo dataset
- Docker Compose for web + API + PostgreSQL + Redis
- Evaluation harness and CI skeleton
- **Full-chain English/Chinese switching**: the web app auto-detects the browser language (with manual override), the API returns bilingual data per request, and a translation-model integration point powers dynamically generated content

The default AI mode is **deterministic demo mode**, so the system works without buying model tokens. An OpenAI-compatible model gateway is included and can be enabled later with environment variables.

## Quick start: Docker (recommended)

Requirements: Docker Desktop.

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Web: http://localhost:3000
- API docs: http://localhost:8001/docs
- API health: http://localhost:8001/health

(`docker-compose.yml` maps the API container's internal port 8000 to host port 8001, since 8000 is commonly already in use. The web container talks to the API over the internal Docker network on port 8000, so `API_INTERNAL_URL` is unaffected.)

### Run with a local Ollama model

Install Ollama, pull a model such as `qwen3:8b`, then start the same stack with
the local-model override. Ollama does not require a placeholder API key.

```bash
ollama pull qwen3:8b
docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up --build
```

Override `LOCAL_LLM_MODEL` or `LOCAL_LLM_BASE_URL` in `.env` for another
OpenAI-compatible local gateway. The API container reaches the host gateway via
`host.docker.internal`; hosted modes still require `OPENAI_COMPAT_API_KEY`.

Demo login is intentionally skipped in V1.0 competition mode. Add enterprise SSO before production deployment.

## Quick start: local development

### API

Requires Python 3.12 (matches the `python:3.12-slim` image used in Docker). Some pinned dependencies (e.g. `pydantic-core`, `psycopg[binary]`) do not ship prebuilt wheels for every newer Python release yet, so `python3 -m venv` with a 3.13/3.14 interpreter can fail to install. If `python3 --version` on your machine is newer than 3.12, use `python3.12` explicitly (e.g. `brew install python@3.12`).

```bash
cd services/api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./globalinfra.db
uvicorn app.main:app --reload --port 8000
```

### Web

In another terminal:

```bash
cd apps/web
npm install
API_INTERNAL_URL=http://localhost:8000 npm run dev
```

Open http://localhost:3000.

The web app follows the browser's `Accept-Language` automatically (English or Chinese, remembered in a cookie, no URL path change required), or you can override it manually with the language switch button in the top bar.

## Competition demo path

1. Open **Cases**.
2. Select `CASE-2026-0182`.
3. Click **Run AI Analysis**.
4. Review specialist agent runs.
5. Open the evidence chain and verification status.
6. Go to **Approvals** and approve the governed external response.
7. Open **Agent Organization** to show dynamic specialist-team assembly.
8. Open **Architecture** to trace one engineering event across the digital thread.

The seed case is fully synthetic and sanitized.

## Universal Intake (V1.3 M1 + M2 + M3 + M4 + M5)

The "Universal Intake Foundation" turns an arbitrary real-world field input into a structured, routed, analyzed Case in one call — deterministic and offline by default (no API key required), with optional LLM layers for classification (M2) and structured extraction (M3 + M4) when a model is configured, both hardened with schema-constrained structured output (M5).

```text
text / PDF / DOCX / TXT  →  IntakeResult  →  Case  →  analyze_case  →  specialist team + evidence + approval gate
```

Two endpoints:

- `POST /intake/text` — body `{"text": "...", "language": "en|zh (optional)"}`.
- `POST /intake/document` — multipart `file=@...` upload. **Text extraction only** for PDF / DOCX / TXT, with signature/content validation and a configurable 10 MiB default limit (`MAX_UPLOAD_BYTES`). Image OCR and voice ASR are explicitly out of M1 scope (a `.png`/audio upload returns `400`).

For a networked pilot, enable `REQUIRE_API_KEY=true`, set a strong `API_KEY` on the API service, and set the same value as the Web service's server-only `API_SERVICE_KEY`. Configure browser origins with the comma-separated `CORS_ORIGINS`; never expose either key through a `NEXT_PUBLIC_*` variable.

Both return `{ submission_id, case_id, intake: <IntakeResult>, specialist_team: [...], analysis: {...} }`, localized to the requested language (`?lang=`/`Accept-Language`, same negotiation as every other route). The created Case is **new** (id `CASE-INTAKE-<hash>`, never a hardcoded demo id) and is run through the existing retrieval-grounded analysis workflow, so the response shows the Case id and the specialist team that was assembled.

**`IntakeResult`** (see `services/api/app/intake.py`): `primary_domain`, `professional_domain`, `case_type`, `case_type_label`, `classification_method`, `extraction_method`, `lifecycle_stage`, `risk`, `risk_label`, `country`, `country_label`, `language`, `issues[]`, `entities[]`, `deadline`, `recommended_agents[]`, `required_approvals[]`, `confidence`.

- **Layer 1 (deterministic, authoritative by default):** `case_type` + `risk` are produced by wrapping the existing deterministic rules in `classify.py` — its `{"type","risk"}` contract is unchanged, so `/cases/classify`, the eval harness and intake always agree.
- **Layer 2 (LLM classification, M2):** when an OpenAI-compatible model is configured (`llm_mode` ≠ `mock`; hosted modes require an API key, while `local` mode does not), `app/llm_classify.py` refines `case_type`/`risk` with the model, **constrained to exactly the same vocabulary** (the `workflow.SPECIALISTS_BY_CASE_TYPE` keys + risk levels) so the result always routes. It **falls back to the Layer-1 rules** whenever no model is configured (the default) or the call fails / returns malformed / out-of-vocabulary output — so with no key the default hosted path behaves byte-for-byte as in M1, and every unit test and eval stays green offline. `classification_method` in the `IntakeResult` reports which layer decided (`"rules"` / `"llm"`); `classify.py` is never modified.
- **Layer 3 (LLM structured extraction, M3 + M4):** when a model is configured, `app/llm_extract.py` also extracts `country`, `issues` and `entities` (M3) plus the project `lifecycle` stage and the response `deadline` (M4) with the model — all in **one** call. Every field is **constrained to the same vocabularies** the deterministic heuristics use (the `COUNTRY_SIGNALS` / `ISSUE_SIGNALS` / `LIFECYCLE_SIGNALS` tables in `intake.py`, read as a single source of truth so anything returned still routes / still resolves to a real, bilingual stage) and **grounded** against the source text (an extracted entity — and the numeric `deadline` amount — must appear verbatim, so the model can pick the *right* reference or number among several but can never invent one). It **falls back to the deterministic keyword/regex extraction** whenever no model is configured (the default) or the call fails / returns malformed output; `lifecycle` and `deadline` fall back **per-field** when the model leaves them empty, so the LLM path never loses a value the regex would have found. Offline the intake path stays byte-for-byte identical to M1/M2. `extraction_method` in the `IntakeResult` reports which path produced these fields (`"rules"` / `"llm"`); the `intake.py` heuristics are never modified.
- **Structured output (M5):** both LLM layers ask the endpoint for schema-valid JSON via a `response_format` JSON-schema whose enums are built from the **same** constrained vocabularies the parsers validate against (so schema and parser can never drift), instead of hoping the model returns a bare `{...}` to regex out. It is **best-effort hardening**: `llm.generate` drops the `response_format` field and retries once on the specific `400` that names it (exactly as it already does for `temperature` on reasoning-style models), and the reply is **always re-validated** by the layer's own vocabulary/grounding guards — which are stricter than any schema can express — so a gateway without structured-output support, or a model that ignores the hint, still degrades cleanly. Offline (no key) the whole path is inert and byte-for-byte identical to M1–M4.
- **Enrichment:** every other field is derived by auditable rules/heuristics. `case_type_label`/`risk_label`/`issues` are bilingual EN/ZH (same `{"en","zh"}` pattern as `Case.type`); the canonical `case_type` English string is what routes the Case via `workflow.SPECIALISTS_BY_CASE_TYPE`.

Two new tables back this (see **Database migrations** below): `intake_submissions` (raw input reference, input hash, parsed text, detected language, created-at, linked `case_id`) and `source_documents` (filename, file type, storage reference, parse status, linked `intake_submission_id`).

## V2.0 Phase 6 Digital Twin

`/twin` is a complete, data-backed reference implementation of the full-lifecycle twin operating model — not a disconnected 3D mock-up. A stable `Twin ID` connects spatial identity, asset hierarchy, state history, engineering events, WBS, schedule, cost, commissioning, telemetry, maintenance and governed AI simulation.

The six delivered phases are:

1. **Twin foundation:** stable IDs, hierarchy, IFC/GIS references, relations and evidence-bearing state history.
2. **Spatial workspace:** interactive infrastructure scene, component inspection, risk state and linked engineering events.
3. **4D/5D controls:** WBS/activity mapping, planned-vs-actual progress, schedule variance and forecast cost exposure.
4. **Commissioning & handover:** system/test-pack readiness, punch items and document completeness.
5. **Operational twin:** live sensor boundary, health thresholds, anomaly state and predictive maintenance work orders.
6. **AI scenario lab:** schedule-recovery, predictive-maintenance and energy scenarios using verified twin inputs; every operational result remains `AWAITING_APPROVAL` and changes no asset state directly.

Primary APIs: `GET /twin/summary`, `/twin/scene`, `/twin/objects/{twin_id}`, `/twin/controls`, `/twin/commissioning`, `/twin/operations`, `/twin/scenarios`, `/twin/agents`; `POST /twin/scenarios/{scenario_id}/run`.

The bundled IFC/glTF/3D Tiles references, BMS/SCADA readings and scenarios are synthetic integration fixtures. Production deployments replace them through model-conversion, project-controls, object-storage and telemetry adapters while preserving the same Twin ID and API contracts.

## Database migrations (Alembic)

V1.3 introduced Alembic and V2.0 extends it for the full-lifecycle twin. The offline/test path is unchanged: `app.main.lifespan` still calls `Base.metadata.create_all` + `seed()`, so local dev, CI and the eval harness need no migration step. Alembic is the managed path for real (Postgres) deployments.

```bash
cd services/api
# Fresh / bare database → create everything (baseline + intake tables):
DATABASE_URL=postgresql+psycopg://... alembic upgrade head

# Database already provisioned by the historic create_all path → adopt the
# baseline without re-creating existing tables, then apply new migrations:
DATABASE_URL=postgresql+psycopg://... alembic stamp 0001
DATABASE_URL=postgresql+psycopg://... alembic upgrade head
```

- `0001_baseline_schema` captures the pre-existing V1.2 tables as the migration baseline.
- `0002_intake_tables` adds `intake_submissions` and `source_documents`.
- `0003_digital_twin` adds the Twin object graph, state history, engineering events, 4D/5D links, sensors, commissioning, maintenance and governed scenarios.

The database URL is read from app settings (`DATABASE_URL`/`.env`) by `migrations/env.py`, not committed in `alembic.ini`.

## Repository layout

```text
apps/web                 Next.js command center
services/api             FastAPI domain + AI runtime
packages/country-packs   Country-specific policies and terminology
packages/domain-packs    Rail/highway/bridge/etc. domain packs
workflows                Governed workflow definitions
data/demo                 Synthetic competition data
evals                     AI evaluation harness
infra                     Docker/Kubernetes/Terraform scaffolding
docs                      Architecture, security, governance and demo docs
```

## Architecture principles

- Full lifecycle: tender → planning → design → procurement → construction → commissioning → handover → O&M
- Eight intelligence domains with 24 connected professional disciplines
- Digital-thread relationships instead of departmental data silos
- Case-driven, not chat-first
- Evidence before conclusions
- Deterministic workflow + agentic reasoning steps
- Human approval for high-risk external actions
- Independent verification before trusted completion
- Country Packs for jurisdiction/localization
- Domain Packs for transport verticals
- Model-provider abstraction
- Regional data-residency ready
- Offline/edge-ready by design

See `docs/ARCHITECTURE.md` (Chinese: `docs/ARCHITECTURE.zh-CN.md`) for the complete design.

## Production hardening still required

This V1.1 is a strong competition/product foundation, not a claim of production certification. Before enterprise rollout, complete SSO, secrets management, encrypted object storage, full document parsing, regional deployment, privacy impact assessment, threat modeling, vulnerability management, backup/restore drills, and jurisdiction-specific legal review.
