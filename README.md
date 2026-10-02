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
