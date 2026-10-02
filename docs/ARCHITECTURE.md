> **Language / 语言**: English · [简体中文](ARCHITECTURE.zh-CN.md)

# GlobalInfra AI V1.1 Domain Architecture

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
