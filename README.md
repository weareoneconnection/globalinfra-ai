> **Language / 语言**: English · [简体中文](README.zh-CN.md)

# GlobalInfra AI V4.3

**Global Transportation Infrastructure Intelligence & Trusted Execution Platform**

GlobalInfra AI V4.3 is an operational digital-twin and trusted-execution platform for overseas infrastructure projects. It connects the complete project lifecycle and eight intelligence domains to live geometry, schedule, cost, telemetry and evidence-grounded decisions, with a reproducible competition golden thread, measured evaluation evidence and a six-channel unified data-ingestion control plane.

> Scope note: this repository is a new standalone codebase. It does not depend on, import, call, or expose TheOne or any TheOne-branded runtime.

## What is runnable in V1.1

- Conversational Assistant entry point (default home)
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

### Runtime model routing

The same running API supports `local`, `openai`, and `auto` on each model-backed
request. No process-wide setting is mutated. `auto` starts with
`LLM_PREFERRED_PROVIDER` and can fail over to the other configured provider;
set `LLM_CLOUD_FALLBACK_ENABLED=false` to prohibit local-to-cloud fallback.
Data marked `restricted` is always local-only, and an explicit OpenAI request is
rejected before any network call.

```bash
# Safe status: provider/model availability, never credentials
curl http://localhost:8001/llm/status

# Explicit OpenAI route
curl http://localhost:8001/i18n/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Engineering review required.","target_lang":"zh","model_route":"openai","data_classification":"internal"}'

# Automatic route with a local-only data boundary
curl http://localhost:8001/i18n/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Confidential claim evidence.","target_lang":"zh","model_route":"auto","data_classification":"restricted"}'
```

Responses include a credential-free `model_routing.trace` showing every
provider/model attempt and whether it succeeded. The same fields are accepted by
`POST /intake/text`; document intake and case re-analysis accept them as query
parameters.

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
- `POST /intake/document` — multipart `file=@...` upload for PDF / DOCX / TXT, with signature/content validation and a configurable 10 MiB default limit (`MAX_UPLOAD_BYTES`). Text-bearing files enter classification and analysis immediately. Valid scanned/image-only PDFs are retained with their checksum and return an `OCR_REQUIRED` document receipt without creating an ungrounded Case. Image-file OCR and voice ASR remain outside this endpoint (a `.png`/audio upload returns `400`).

For a networked pilot, enable `REQUIRE_API_KEY=true`, set a strong `API_KEY` on the API service, and set the same value as the Web service's server-only `API_SERVICE_KEY`. Configure browser origins with the comma-separated `CORS_ORIGINS`; never expose either key through a `NEXT_PUBLIC_*` variable.

Text intake and text-bearing documents return `{ submission_id, case_id, intake: <IntakeResult>, specialist_team: [...], analysis: {...} }`, localized to the requested language (`?lang=`/`Accept-Language`, same negotiation as every other route). The created Case is **new** (id `CASE-INTAKE-<hash>`, never a hardcoded demo id) and is run through the existing retrieval-grounded analysis workflow. A scanned document instead returns the same standard ingestion envelope with `case_id: null`, `analysis: null` and an `OCR_REQUIRED` `SourceDocument` receipt until text evidence exists.

**`IntakeResult`** (see `services/api/app/intake.py`): `primary_domain`, `professional_domain`, `case_type`, `case_type_label`, `classification_method`, `extraction_method`, `lifecycle_stage`, `risk`, `risk_label`, `country`, `country_label`, `language`, `issues[]`, `entities[]`, `deadline`, `recommended_agents[]`, `required_approvals[]`, `confidence`.

- **Layer 1 (deterministic, authoritative by default):** `case_type` + `risk` are produced by wrapping the existing deterministic rules in `classify.py` — its `{"type","risk"}` contract is unchanged, so `/cases/classify`, the eval harness and intake always agree.
- **Layer 2 (LLM classification, M2):** when an OpenAI-compatible model is configured (`llm_mode` ≠ `mock`; hosted modes require an API key, while `local` mode does not), `app/llm_classify.py` refines `case_type`/`risk` with the model, **constrained to exactly the same vocabulary** (the `workflow.SPECIALISTS_BY_CASE_TYPE` keys + risk levels) so the result always routes. It **falls back to the Layer-1 rules** whenever no model is configured (the default) or the call fails / returns malformed / out-of-vocabulary output — so with no key the default hosted path behaves byte-for-byte as in M1, and every unit test and eval stays green offline. `classification_method` in the `IntakeResult` reports which layer decided (`"rules"` / `"llm"`); `classify.py` is never modified.
- **Layer 3 (LLM structured extraction, M3 + M4):** when a model is configured, `app/llm_extract.py` also extracts `country`, `issues` and `entities` (M3) plus the project `lifecycle` stage and the response `deadline` (M4) with the model — all in **one** call. Every field is **constrained to the same vocabularies** the deterministic heuristics use (the `COUNTRY_SIGNALS` / `ISSUE_SIGNALS` / `LIFECYCLE_SIGNALS` tables in `intake.py`, read as a single source of truth so anything returned still routes / still resolves to a real, bilingual stage) and **grounded** against the source text (an extracted entity — and the numeric `deadline` amount — must appear verbatim, so the model can pick the *right* reference or number among several but can never invent one). It **falls back to the deterministic keyword/regex extraction** whenever no model is configured (the default) or the call fails / returns malformed output; `lifecycle` and `deadline` fall back **per-field** when the model leaves them empty, so the LLM path never loses a value the regex would have found. Offline the intake path stays byte-for-byte identical to M1/M2. `extraction_method` in the `IntakeResult` reports which path produced these fields (`"rules"` / `"llm"`); the `intake.py` heuristics are never modified.
- **Structured output (M5):** both LLM layers ask the endpoint for schema-valid JSON via a `response_format` JSON-schema whose enums are built from the **same** constrained vocabularies the parsers validate against (so schema and parser can never drift), instead of hoping the model returns a bare `{...}` to regex out. It is **best-effort hardening**: `llm.generate` drops the `response_format` field and retries once on the specific `400` that names it (exactly as it already does for `temperature` on reasoning-style models), and the reply is **always re-validated** by the layer's own vocabulary/grounding guards — which are stricter than any schema can express — so a gateway without structured-output support, or a model that ignores the hint, still degrades cleanly. Offline (no key) the whole path is inert and byte-for-byte identical to M1–M4.
- **Enrichment:** every other field is derived by auditable rules/heuristics. `case_type_label`/`risk_label`/`issues` are bilingual EN/ZH (same `{"en","zh"}` pattern as `Case.type`); the canonical `case_type` English string is what routes the Case via `workflow.SPECIALISTS_BY_CASE_TYPE`.

Two tables back this (see **Database migrations** below): `intake_submissions` (raw input reference, input hash, parsed text, detected language, created-at, linked `case_id`) and `source_documents` (filename, file type, content-addressed reference, parse status, validated original bytes, content type/size, linked `intake_submission_id`).

## V2.1 Trusted Execution Closure

V2.1 turns the candidate-decision demo into a governed execution lifecycle. Analysis creates a claim/evidence graph and an action intent, but it never creates a verification PASS. Human approval only moves the action to `APPROVED`; it does not execute the tool or alter any verification record.

The first executable tool is `document.generate`. It produces a content-addressed owner-response draft with `DRAFT_ONLY_NOT_SENT` and `external_delivery_performed: false`—no email or external letter is sent. The lifecycle is:

```text
analysis → claim/evidence → action intent → human approval → execution receipt → independent verification receipt → close
```

Key APIs: `POST /actions/{id}/execute`, `POST /actions/{id}/verify`, `POST /actions/{id}/close`, plus the case-scoped equivalents. Execution is evidence-bound and idempotent; verification checks approval linkage, receipt integrity, artifact digest, evidence references and the output contract. A failed check remains `VERIFICATION_FAILED` and cannot be closed.

The legacy `verification` object on a Case is analysis-quality scoring (`WARN`), not proof that an action succeeded. Trusted proof is exposed separately as `execution_receipt` and `verification_receipt`.

## V3.0 Phase 7 Production Pilot

Phase 7 adds OIDC/RBAC identity boundaries, organization and project scope, mutation audit trails, an offline-first field PWA, real twin-source registration, six enterprise connector contracts, AI quality release gates, Prometheus-compatible metrics, rate limits and dedicated liveness/readiness probes. See [Phase 7 Production Pilot](docs/PHASE7_PRODUCTION_PILOT.md) for activation boundaries and the production checklist.

## V4.0 Phase 8 Operational Twin

Phase 8 adds a native WebGL GLTF workspace with Twin-ID picking, traceable model versions and conversion jobs, one-click six-format project twin generation, time-series ingestion and SSE streaming, interactive 4D progress and 5D health/cost coloring, an evidence-grounded Twin Copilot, and a timed competition showcase. See [Phase 8 Operational Twin](docs/PHASE8_OPERATIONAL_TWIN.md) for the capability matrix and honest integration boundaries.

For competition and pre-integration demonstrations, every seeded project also exposes one coherent six-format synthetic twin pack: IFC 4.3, glTF 2.0, 3D Tiles 1.1, GeoJSON, WMS 1.3.0 and IoT telemetry. All artifacts are generated from the same stable Twin IDs, downloadable from `/twin`, checksummed where static, and explicitly labelled `SYNTHETIC_DEMO`. See [项目级合成数字孪生数据包](docs/SYNTHETIC_TWIN_PACK.zh-CN.md).

## V4.2 Phase 9.1 Competition Golden Thread

`/competition` now composes bilingual intake, country/lifecycle routing, country packs, knowledge evidence, multi-agent analysis, digital-twin context, explicit human approval, governed execution and independent verification into one seven-step AI-outbound golden thread. A versioned 30-case suite supplies live metrics and a CI release gate; none of the displayed evaluation figures are hard-coded. See [Phase 9.1 Competition Golden Thread](docs/PHASE9_COMPETITION_GOLDEN_THREAD.md).

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

The generated IFC/glTF/3D Tiles/GeoJSON/WMS artifacts, BMS/SCADA readings and scenarios are synthetic integration fixtures. Production deployments replace them through model-conversion, project-controls, object-storage and telemetry adapters while preserving the same Twin ID and API contracts.

## Field operations 2.0

- **One-line reporting**: by default a single box with Voice / Photo / Send buttons; project, type, severity, component and location are under "More (optional)". Severity defaults to "Let the AI assess".
- **Into the agent organization**: synced reports are classified with the intake rules (the reporter's category is a hint), the risk is the higher of the reporter's and the AI's (never lowered), and the agent organization runs in the background. "My reports" shows analysis status, risk review, plan and answerable questions (`GET /field/reports`).
- **Field evidence**: photos, video and voice notes are validated by file signature (declared types are not trusted), size-limited and stored once per SHA-256 (`POST /field/media`, `GET /field/media/{sha256}`); observations may only reference media the organization uploaded. The offline queue keeps original files and uploads them before syncing.
- **Component and location**: the Twin ID is picked from the project's components or scanned where the browser supports it; with location already permitted, the nearest project within 150 km is selected.
- **Voice**: speech to text where the browser supports it; otherwise the recording is kept as an evidence attachment and is not transcribed.

## Agent organization 2.0

Every case is handled by a governed agent organization (`services/api/app/agent_org/`); every agent is advisory only:

- **Agent cards**: each agent's scope, tools, evidence policy, escalation question and country-specific search terms are defined once and versioned (`GET /agents/cards`).
- **Dynamic teams**: the core team for the case type plus specialists triggered by the letter (cost, claims, procurement, plant, commissioning, asset; at most 6), each with the reason it was selected; with a model configured, up to 2 more may be proposed from the registry.
- **Real tools**: jurisdiction-filtered knowledge search, resolved similar cases, project status, twin element lookup, permit gates, schedule impact and cost estimate. Tools only read existing data and say so when data is missing.
- **Structured findings**: claim, evidence, confidence, gaps, actions with an owner role and questions for people; a model citing a source its agent did not retrieve is downgraded to a gap.
- **Coordination and escalation**: the coordinator detects dependency conflicts (e.g. a contractual position that depends on an unknown technical cause) and gaps; with a model it sends one targeted follow-up, otherwise it escalates to a human. Agent questions can be answered in the chat, which re-runs the analysis (`POST /cases/{id}/inputs`).
- **Plan and verification**: every plan step traces to a finding, a question or a governance gate and has an owner and due time; the verifier checks each finding against its evidence.
- **Observability**: full trace `GET /cases/{id}/agent-run`, recent runs `GET /agents/runs`, scorecards `GET /agents/scorecards`; the agent organization page shows live runs.
- **Evaluation**: `python evals/run_agent_org_eval.py` checks team composition, escalation, plan traceability and grounded findings on 12 synthetic cases, and runs in CI.

Each case uses at most 9 model calls, with 5 concurrent calls to a cloud model and 2 to a local one; a failing model degrades step by step to rules without aborting the analysis.

## Dispatching assistant

Every message on the assistant home page goes to the dispatcher (`POST /assistant/dispatch`, `services/api/app/dispatcher.py`):

- **Several tasks per message**: up to 4 steps, each served by a sub-agent -- intake (convenes the agent organization), regulation, case follow-up, clarification, progress, approval queue, field reports (`GET /assistant/agents`). Independent steps run concurrently; a step that refers to the work order created in the same plan (`case_id = NEW`) waits for it; writes never run concurrently.
- **Verifiable plans**: with a model, the plan follows a JSON schema and every agent, case id, project code and question id is checked against the database and the conversation; anything invalid falls back to the rules, which route each clause and plan single-intent messages exactly like `/assistant/chat`. A reported incident always reaches intake.
- **Live timeline**: server-sent events `plan -> step_start/step_done -> summary -> done` show each agent's state and result as it happens.
- **Grounded summary**: with two or more steps a model summarises, citing only steps (`[S1]`) and the sources they returned; otherwise one line per step.
- **Memory**: recent turns and the current case and project are kept server-side (`AssistantSession`, migration 0014), so "this case" resolves after a reload; agent questions can be answered in the chat and trigger re-analysis.
- **Governance unchanged**: approving, executing, verifying and closing are not sub-agents; at most 4 steps per message, with 1 planning call, up to 2 knowledge answers and 1 summary (the organization inside intake has its own budget).
- **Evaluation**: `python evals/run_dispatch_eval.py` checks plans, step completion and summaries on 15 synthetic messages, in CI.

## V4.3 Assistant (conversational entry point)

The web app now opens on the **Assistant** (`/`); the former Command Center moved to `/overview` and every other page is unchanged. The assistant is a conversational entry point to the same governed capabilities, not a new reasoning engine:

- **Report an incident / handle an owner letter**: text or PDF/DOCX/TXT goes through `/intake/text` or `/intake/document`, creates a work order and runs the specialist analysis, shown in the chat as a verdict card, response plan, evidence and process trace.
- **Project confirmation**: a work order whose project cannot be identified stays `NEEDS_PROJECT_CONFIRMATION`. The user picks the project in the chat, and the new `POST /cases/{id}/confirm-project` re-runs the analysis before any governed action or approval is created; the system never guesses. A project code typed explicitly in the message (e.g. `MY-RAIL-A`) counts as confirmation.
- **Approval and trusted execution**: approve, generate the draft (`DRAFT_ONLY_NOT_SENT`), verify independently and close from the chat cards, using the existing endpoints and role checks.
- **Reply draft**: after every approval, "Generate reply draft" has the model (when configured) write a bilingual reply from the incoming letter, the specialist findings and the cited evidence. It may not commit to cost, time or liability, uses [●] for unknown details, and may cite only this work order's evidence; otherwise the template is used. The full draft is shown in the chat with a copy button, still `DRAFT_ONLY_NOT_SENT` and subject to the same independent verification. A question typed alongside an uploaded file (e.g. "how should we reply?") is recorded as `user_note` lineage and used only as a drafting instruction, never merged into the document text.
- **Regulation questions**: deterministic TF-IDF retrieval via `/knowledge/search` with the workflow's relevance thresholds. Below the threshold the assistant declines; weakly related material is folded away and never presented as evidence.
- **Project progress / my approvals**: progress, schedule variance, next gate and pending approvals.
- **Sensitive data**: the "Sensitive" toggle submits with the `restricted` classification and forces the local model.

**Chat agent (`POST /assistant/chat`)**: with a model configured, the model reads the message plus the last 8 turns and picks exactly one tool (report incident, search regulations, existing work order, project progress, pending approvals, answer directly). The tool name is a JSON-schema enum, and work-order ids and project codes must exist in the database; anything else falls back to the deterministic keyword planner, which is also the only planner when no model is configured, so offline and CI behaviour stays deterministic. Regulation answers are composed **only from the retrieved sources** and must cite them as `[source ref]`; an answer that cites nothing, or cites a source that was not retrieved, is discarded in favour of the plain source list. Retrieval runs on both the user's own words and the model's rewritten query, so a rewrite can add hits but never lose them. Approval, execution, verification and closure are not tools, so the model cannot perform them, and a message with incident signals is never brushed off with a chat reply. Every reply is labelled LLM / rules / your choice. Conversations are kept only in the current browser tab (`sessionStorage`).

## V4.3 Phase 10.1 Unified Data Ingestion

The `/data-ingestion` workspace replaces the assumption that every input is an event with six explicit channels: events/work orders, documents/correspondence, project master data, enterprise connectors, BIM/GIS/digital-twin models, and IoT/telemetry. Each channel writes its native domain object and a tenant-scoped `IngestionReceipt` containing validation results, accepted/rejected counts, the canonical mapping version, target identity, checksum and source lineage. Events are emitted only when a domain change is actionable.

Primary APIs: `GET /ingestion/catalog`, `/ingestion/summary`, `/ingestion/receipts`; `POST /ingestion/project-master`. Existing field, intake, connector, twin-source, model-conversion, project-factory and telemetry endpoints now return the same standard ingestion receipt.

## Database migrations (Alembic)

V1.3 introduced Alembic, V2.0 extended it for the full-lifecycle twin, and V2.1 adds the trusted execution closure. The offline/test path is unchanged: `app.main.lifespan` still calls `Base.metadata.create_all` + `seed()`, so local dev, CI and the eval harness need no migration step. Alembic is the managed path for real (Postgres) deployments.

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
- `0010_preserve_source_document_content` retains validated original document bytes plus content type/size for governed OCR handoff.
- `0003_digital_twin` adds the Twin object graph, state history, engineering events, 4D/5D links, sensors, commissioning, maintenance and governed scenarios.
- `0004_trusted_execution_closure` adds claims, governed action intents, execution/verification receipts, content-addressed artifacts, and unassigned-intake routing fields.
- `0005_phase7_production_pilot` adds organizations, identities, audit events, field observations, real twin sources, connector sync runs and AI quality release gates.
- `0006_phase8_operational_twin` adds operational twin models, conversions and telemetry history.
- `0007_country_knowledge` adds governed country packs and knowledge lifecycle fields.
- `0008_approval_decision_audit` adds explicit approval decision attribution and timestamps.
- `0009_unified_ingestion_control_plane` adds tenant-scoped validation and lineage receipts across all six ingestion channels.

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
- Domain-native data, with events emitted only for actionable change
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
