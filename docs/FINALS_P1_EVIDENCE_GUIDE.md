# GlobalInfra AI — Finals P1 Evidence and Impact Edition

This is a **code-ready evidence workflow**, not a claim that any live model, real
project or overseas authority has independently validated the product.
Expected result on CI: deterministic tests PASS; real-model experiment
remains **NOT_RUN** until authorized inputs and a real governed adapter exist.

## 1. Model comparison — executable, fail-closed

`python evals/run_model_comparison.py --output /tmp/model-comparison.json`
returns `NOT_RUN` when blind data, approved credentials or real governed
adapter are unavailable. It never substitutes the 57 synthetic CI cases as
real-model evidence.

Four arms:

1. `rules`: calls the application's `app.classify.classify_text` code.
2. `raw_llm`: calls a live OpenAI-compatible Chat Completions endpoint
   without reference passages.
3. `rag`: same live model with explicitly provided permitted reference
   snippets (`evidence_context`); a prompt-level retrieval baseline.
4. `governed`: POSTs to a separate adapter that **must execute the real
   governed business runtime** and return a non-empty run ID and standardized
   `prediction`. A prompt-only stand-in is not eligible.

The last adapter contract is:

```json
{
  "schema": "globalinfra.blinded-governed-response.v1",
  "run_id": "a-real-stored-governed-run-id",
  "prediction": {
    "risk": "CRITICAL",
    "action": "STOP_WORK_AND_NOTIFY_PM",
    "evidence_refs": ["AUTHORIZED-DOC-REF"],
    "abstained": false,
    "external_action_executed": false
  }
}
```

**No such real governed adapter is included in this P1 package.** Wiring it
requires an authorized pilot. The runner therefore refuses to claim a complete
four-way model comparison until it exists.

Blind JSONL records require:
`id,input,expected_risk,expected_action,expected_evidence,requires_abstention,data_classification`.
Optional `evidence_context` is a list of `{"ref":"...","text":"..."}`.
At least 50 **distinct** IDs; only authorized `public` data are accepted.
Expert labels must be independently sourced; the runner cannot verify that
an attestation environment variable represents a genuine authorization.

Required environment variables:

```sh
export DATASET_AUTHORIZATION_ATTESTED=true
export MODEL_EVAL_API_BASE=https://approved-provider.example/v1
export MODEL_EVAL_MODEL=approved-model-id
export MODEL_EVAL_API_KEY=...  # secret manager only, never commit
export MODEL_EVAL_GOVERNED_URL=https://approved-internal-adapter.example/v1/blind
python evals/run_model_comparison.py \
  --dataset /secure/authorized-public-blind.jsonl \
  --execute \
  --raw-output-dir /secure/evidence-outputs \
  --output /secure/comparison.json
```

All four arms must finish to return `EXECUTED_UNREVIEWED`. Partial runs return
`FAILED_CLOSED`; a live run is not a verified competition result until model
settings, raw outputs, labels and citations have independent expert sign-off.
Cost/financial impact is intentionally `null` when no verified billing exists.
The current runner executes each case **once**; repeat experiments separately
to study stochastic variance and aggregate only with a documented protocol.

## 2. Paired ROI with reproducible case means

The API retains the original `POST /pilot/roi-measurements` record endpoint,
but `/verify` now requires the **canonical full paired-study payload**, not
only the previously stored digest.

The canonical JSON is encoded as
`json.dumps(study.model_dump(mode="json"), ensure_ascii=False,
sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")`
and hashed with SHA-256.

Minimal schema:

```json
{
  "schema_version": "globalinfra.pilot-roi-paired.v1",
  "project_id": 1,
  "metric_name": "human_minutes_per_case",
  "unit": "minutes",
  "source_type": "SYNTHETIC",
  "authorization_ref": "synthetic://demonstration-only",
  "study_protocol_ref": "protocol://pairing-method-001",
  "cases": [
    {"case_id": "EXAMPLE-001", "baseline_value": 120, "assisted_value": 42}
  ]
}
```

The sample above is **not real ROI** and is explicitly rejected for a real
`VERIFIED` claim. For actual authorized data, the reviewer must be a distinct
authenticated principal, the declared source type must be `AUTHORIZED_REAL`,
the canonical SHA-256 must match the stored one, case IDs must be unique, and
means, units, metric and sample size must recompute. Changing any measurement
after recording invalidates the digest.

**Remaining source audit requirement:** The reviewer must check authorizations,
time logs, independent observers, sample selection and source records outside
the endpoint. Recomputing JSON does not establish that the numbers are true.

## 3. Country adaptation (MY vs AE)

```sh
python evals/run_country_adaptation.py \
  --country-a MY --country-b AE --stage construction \
  --output /tmp/country-adaptation.json
```

Compares language, jurisdiction authority codes, permit gates, source URL
indexes, privacy routing and canonical config SHA-256; returns
`CONFIGURATION_COMPARISON_ONLY`. Both seeded Country Packs still require local
expert validation and do **not** demonstrate lawful applicability or actual
multi-country deployment. Do not imply a second-country pilot is operational.

## 4. Claims gate for the finals

- **Confirmed by CI:** API/Web/Compose tests, selected source-code behaviors,
  deterministic country configuration differences and paired ROI hash checks.
- **Only after approved experiment:** multi-arm real model performance,
  cross-language task reliability and blind expert labels.
- **Only after validated shadow pilot:** labor-time improvement, financial ROI,
  real source data quality and cross-national customer rollout.
- **Never inferred from fixture tests:** accident prevention savings,
  project productivity percentages, live foreign-law compliance or externally
  dispatched work orders.

The signed release-evidence chain remains tied to the exact merged main commit.
A successful P1 PR CI is NOT a signed main release or Railway promotion.
