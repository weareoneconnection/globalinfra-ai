# P3.1.1 Hybrid AI Expert Council — operating guide

**Not human expert verification.** This is an AI-assisted screening extension
stacked on P3.1 PR #4. It cannot grant publication approval or replace the
independent two-human-reviewer protocol. Real experiments require approved
public-only data, model credentials, legal data-egress authorization and an
approved protocol.

## Design

The council runs three independent, declared cross-family AI roles:
HSE safety, engineering, and contracts. The three reviewers independently
assess all **four blinded A/B/C/D** answers twice, with reversed presentation
order on the second pass. An **additional fourth model from a different
family** arbitrates conflicting AI opinions; this arbitrator is NOT a human
adjudicator. The existing private blind-key mapping is *validated* and hashed
for provenance, **never included in model prompts**.

Critical-risk cases, citation anomalies, unsafe suggestions, cross-model
disagreement and order-sensitivity all become mandatory human-review cases.
For other cases, the queue selects a deterministic sample (20% by default,
minimum 5 if enough cases). Mandatory cases require two different human
reviewer records, sampled ordinary cases one. Human disagreements require
an additional distinct human adjudicator.

Human reviewers should inspect the blind packet BEFORE receiving AI opinions.
A review's `signed_review_ref` is a record reference; current code does
**not** cryptographically verify that a qualified individual signed it.
The closed publication gate always remains in place.

## Cross-provider configuration

Create `/secure/council-registry.json` with the schema:

```json
{
  "schema": "globalinfra.p3-1-1.hybrid-council.v1",
  "mode": "AI_SCREENING_ONLY",
  "evaluated_model_ids": ["evaluated-raw-model", "evaluated-rag-model", "evaluated-governed-model"],
  "human_gate_required": true,
  "experts": [
    {
      "id": "hse-expert",
      "role": "expert",
      "specialty": "hse",
      "family": "provider-family-a",
      "model": "authorized-hse-model-id",
      "endpoint": "https://approved-a.example.com/v1/chat/completions",
      "api_key_env": "COUNCIL_HSE_API_KEY"
    },
    {
      "id": "engineering-expert",
      "role": "expert",
      "specialty": "engineering",
      "family": "provider-family-b",
      "model": "authorized-engineering-model-id",
      "endpoint": "https://approved-b.example.com/v1/chat/completions",
      "api_key_env": "COUNCIL_ENGINEERING_API_KEY"
    },
    {
      "id": "contracts-expert",
      "role": "expert",
      "specialty": "contracts",
      "family": "provider-family-c",
      "model": "authorized-contracts-model-id",
      "endpoint": "https://approved-c.example.com/v1/chat/completions",
      "api_key_env": "COUNCIL_CONTRACTS_API_KEY"
    }
  ],
  "arbiter": {
    "id": "independent-arbiter",
    "role": "arbiter",
    "specialty": "engineering",
    "family": "provider-family-d",
    "model": "authorized-arbiter-model-id",
    "endpoint": "https://approved-d.example.com/v1/chat/completions",
    "api_key_env": "COUNCIL_ARBITER_API_KEY"
  }
}
```

**These are intentionally non-working example identifiers.** The code
requires four distinct model IDs and four declared model families, with all
model IDs different from the evaluated model IDs and the frozen
`execution.model_id`. Operators must independently confirm that provider
names actually map to separate underlying families. The code validates
declarations, not real provider ownership or model lineage.

Use four separate API keys from an approved secret manager; never commit or
log them. For live execution use only explicitly approved HTTPS
`/chat/completions` endpoints. Local HTTP is opt-in for testing only.
Provider data processing and cross-border transfer permission must be
independently assessed before sending any case excerpts to vendors.

## Execution

The existing P3.1 pipeline must first produce its frozen study, four real
baseline outputs and the blind packet/private alias key. Keep case texts and
model responses in private controlled storage. P3.1.1 does **not** replace
the original independent human assessment stage.

```sh
# Safe mode: always NOT_RUN, no provider call.
python evals/p3_1_hybrid_council.py run \
  --study /secure/study-frozen.json \
  --packet /secure/review-packet.json \
  --blind-key /secure/PRIVATE-review-key.json \
  --registry /secure/council-registry.json \
  --output /secure/council-not-run.json

# Configure these through your approved secret management tool:
# COUNCIL_HSE_API_KEY, COUNCIL_ENGINEERING_API_KEY,
# COUNCIL_CONTRACTS_API_KEY, COUNCIL_ARBITER_API_KEY
export DATASET_AUTHORIZATION_ATTESTED=true
export COUNCIL_EXTERNAL_PROCESSING_APPROVED=true
export COUNCIL_APPROVED_HOSTS=approved-a.example.com,approved-b.example.com,approved-c.example.com,approved-d.example.com

python evals/p3_1_hybrid_council.py run \
  --study /secure/study-frozen.json \
  --packet /secure/review-packet.json \
  --blind-key /secure/PRIVATE-review-key.json \
  --registry /secure/council-registry.json \
  --max-calls 800 --execute \
  --output /secure/private-council-output.json

python evals/p3_1_hybrid_council.py queue \
  --packet /secure/review-packet.json \
  --council /secure/private-council-output.json \
  --output /secure/private-human-review-queue.json

python evals/p3_1_hybrid_council.py human-gate \
  --queue /secure/private-human-review-queue.json \
  --council /secure/private-council-output.json \
  --reviews /secure/human-review-records.jsonl \
  --output /secure/private-human-gate.json
```

Example human review JSONL line:

```json
{"case_id":"BLIND-001","role":"reviewer","reviewer_id":"human-expert-1","decision":"ACCEPT","signed_review_ref":"restricted-human-attestation-001","queue_sha256":"REPLACE_WITH_REAL_QUEUE_HASH"}
```

Never send confidential cases to the public service or unapproved AI
endpoints. The CLI writes restrictive POSIX 0600 outputs, but operators
must enforce storage permissions, secure retention and access control.

## Evidence boundaries and failure handling

- AI three-model agreement is **not** ground truth or professional approval.
- A matching source *reference ID* is not semantic verification of source
  authority; humans must inspect actual text and applicability.
- Failure, malformed provider JSON, missing key, unapproved endpoint, missing
  consent, insufficient call budget or altered packet **fail closed**.
- AI arbitration never resolves a human dispute or authorizes publication.
- The sample-based review lane **does not satisfy** P3.1's full two-human-
  reviewer assessment of every case; report it as hybrid AI screening.
- The public Finals dashboard remains `NOT_RUN` for real model claims unless
  separate authorization, independent source audit, human sign-off and
  protected release are completed.
- Actual model results and expert approval are **NOT included** in this PR.
