> **Language / 语言**: English · [简体中文](ARCHITECTURE.zh-CN.md)

# GlobalInfra AI V2.0 Domain + Digital Twin Architecture

## V2.0 full-lifecycle digital twin

The Digital Twin plane is anchored on `TwinObject.id`, a stable source-neutral identity. Geometry references (IFC/glTF/3D Tiles/GeoJSON), object relationships, evidence-bearing state transitions, WBS/activity/cost links, commissioning records, telemetry, maintenance and simulations all reference that identity. This avoids coupling the platform to one BIM authoring tool, IoT vendor or scheduling system.

```text
BIM / GIS / Project Controls / QMS / CxMS / BMS / SCADA
                         │ adapters
                         ▼
Twin Object Graph → Temporal State → 4D/5D → Handover → Operations
                         │
                         ▼
         Twin Agents → Evidence Verification → Human Approval
```

The bundled dataset is synthetic. Geometry and telemetry fields are integration contracts, not claims of a connected production source. Scenario execution produces recommendations only and cannot mutate operational asset state.

## 1. Product model

GlobalInfra AI is a **lifecycle-aware infrastructure intelligence and trusted-execution platform**. Chat is optional; the system of record is the project case and its evidence, decision, action, approval and verification history.

The model has two axes:

```text
Lifecycle: Tender → Planning → Design → Procurement → Construction → Commissioning → Handover → O&M
Domains:   Project → Engineering → Delivery → Commercial → Assurance → Resources → Knowledge → Assets
```

The eight intelligence domains contain 24 professional disciplines. They are views of one connected project model, not separate applications.

Core domain chain:

```text
Organization → Project → Lifecycle Stage → Domain → Event → Case → Evidence → Decision → Action → Verification
```

## 2. Global topology

```text
Global Control Plane
  Identity / Tenant / Agent Catalog / Skill Registry / Model Registry / Country Pack Registry / Policies
          │
          ├── APAC Data Plane
          ├── MEA Data Plane
          └── EU Data Plane
                   │
               Project Edge
        Offline cache / secure sync / local tools
```

V1.0 runs as one deployable regional stack. The boundaries are already modeled so the services can later split by region.

## 3. Infrastructure digital thread

```text
Asset → Drawing → Specification → Work Package → Method Statement → Inspection → NCR
      → Technical Decision → Contract Impact → Schedule / Cost Impact
      → Corrective Action → Verification → Lesson Learned
```

Relationships preserve cause, responsibility, time, cost, risk and verification context across domains.

## 4. Trusted execution model

```text
Field Event
  ↓
Case Intelligence
  ↓
Knowledge Retrieval + Specialist Agents
  ↓
Action Plan
  ↓
Human Governance
  ↓
Execution
  ↓
Independent Verification
  ↓
Evidence Record
```

Important external actions must fail closed when approval/evidence is missing.

## 5. Agent model

An agent is not an unrestricted autonomous process. Each agent must have:

- explicit role;
- input/output schema;
- approved tools;
- evidence policy;
- risk level;
- execution budget;
- approval policy.

The Case Router classifies each event and assembles the smallest suitable specialist team. A complex NCR may activate Quality, Engineering, Contract and Planning agents without running every registered agent.

## 6. Knowledge Fabric

V1.0 uses relational synthetic knowledge records. Production evolution:

- Object storage: source documents
- PostgreSQL: authoritative metadata and domain state
- pgvector / OpenSearch: semantic + lexical retrieval projections
- graph store: claim/evidence/entity relationships

Indexes are rebuildable projections; source documents and authoritative metadata remain the system of record.

## 7. Country Packs

Country Packs isolate:

- language/locales/RTL;
- terminology;
- local workflow policies;
- data residency metadata;
- approved regulatory sources;
- country-specific templates.

A Country Pack is configuration + curated knowledge, not permission for the AI to invent legal conclusions.

This release ships a full-chain language switch (browser-language auto-detection + cookie memory + bilingual API data + a translation-model integration point) as the concrete implementation of the "language/locales" capability above; the term-pair structure in `packages/country-packs/*/glossary.json` can be reused directly for terminology-locking the translation model.

## 8. Domain Packs

Domain Packs isolate transport vertical semantics: rail, highway, bridge, tunnel, port and airport.

## 9. Model Gateway

`LLM_MODE=mock` is default. Production must route by sensitivity, latency, cost, capability, jurisdiction and data policy, and must support a local/regional model route when cross-border processing is not permitted. The translation-model integration point (`translate()` in `services/api/app/llm.py`) shares the same gateway abstraction: it calls the real model when one is configured, otherwise it falls back to a deterministic offline phrase table so the demo environment produces bilingual content without network access.

## 10. Deployment evolution

- V1 competition: Docker Compose, one region.
- Pilot: managed PostgreSQL, Redis, object storage, private networking, SSO.
- Enterprise: Kubernetes, regional data planes, centralized control plane, policy-as-code, KMS/HSM, SIEM.
- Edge: offline-first PWA, encrypted local cache, store-and-forward synchronization.

This release adds the first concrete, reviewable artifacts for the Pilot/Enterprise rows above, without claiming either stage is complete:

- `infra/terraform/` is now a worked (AWS) starter for the Pilot stage's managed PostgreSQL/Redis/object storage/private networking — not a certified production baseline (see its README for exactly what is and is not covered).
- `infra/kubernetes/` manifests gained liveness/readiness probes, resource requests/limits, a `HorizontalPodAutoscaler`, an example `Secret` and an example `Ingress`, closing part of the gap toward the Enterprise stage's Kubernetes row. The regional data-plane split, centralized control plane and KMS/HSM/SIEM items are still open.
- `services/api/app/security.py` adds an opt-in, off-by-default shared-secret API key gate as an interim network-boundary control. It is explicitly not SSO/OIDC — that remains the Pilot stage's identity item.
- `evals/run_eval.py` now runs a real (if intentionally simple, rule-based) classifier against the dataset and fails the build on a regression, and `services/api/tests/` adds a pytest suite (i18n, translation fallback, the classifier, the auth gate, and an end-to-end check that `analyze_case` is idempotent) exercised by CI alongside a `docker compose up --wait` smoke test — see RELEASE_NOTES.md for the full list.
