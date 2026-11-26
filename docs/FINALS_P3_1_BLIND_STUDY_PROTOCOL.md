# GlobalInfra AI P3.1 — Independently adjudicated blind-study protocol

**Status:** engineering instrumentation only. No authorized live blind cases,
real-model win rate, professional sign-off, business ROI, or production
customer result has been produced by this change.

## Workflow

| Stage | Input | Tool/output | Audit boundary |
| --- | --- | --- | --- |
| 0. Consent & sampling | Public/explicitly authorized case records | Independent source approval and blinded stratified selection | Outside this code |
| 1. Freeze | 50–200 distinct JSONL records, risk labels, reference IDs | `p3_1_study.py freeze` → frozen manifest with dataset SHA256, approved hosts, code commit, declared consent | Recorded declaration, **not** consent verification |
| 2. Live execution | Real model key, authorized provider, actual governed runtime adapter | `run_model_comparison.py --execute --study-manifest ...` → 4 complete raw result files with digests | One run per case; source adapter authenticity requires external verification |
| 3. Blind | Raw outputs and comparison report | `p3_1_study.py blind` → separate blinded packet and **private** identity key | Never give the key to reviewers |
| 4. Expert label review | Packet; 2 independent reviewers + distinct adjudicator | Reviews in JSONL; independent gold assessment and four candidate assessments | No reviewer sees frozen expected labels or system identities |
| 5. Reconcile | Labels, review records, restricted identity key | `p3_1_study.py adjudicate` → hashes, rates, paired intervals and disagreements | Disputed or incomplete cases fail closed |
| 6. External source audit | Project permission, sample inclusion, authentic expert identities, raw records and billings | Qualified human sign-off + signed, authorization-controlled publication | **Not automated**; public publishing remains CLOSED |

The **strictest reachable computed status** is
`EXPERT_ADJUDICATED_SOURCE_AUDIT_PENDING`, with
`publication_gate=CLOSED_PENDING_SOURCE_AUDIT_AND_APPROVAL`.
Never present this as a legally or economically audited result.

## Case dataset (illustrative structure only)

Never commit original owner letters, employee names, photographs, confidential
reference text, credentials or a real case dataset to the repository.

```json
{"id":"BLIND-001","input":"Sanitized, explicitly authorized overseas owner notice","language":"en","expected_risk":"HIGH","expected_action":"HUMAN_REVIEW_REQUIRED","expected_evidence":["SRC-001"],"requires_abstention":false,"data_classification":"public","evidence_context":[{"ref":"SRC-001","text":"Authorized public reference excerpt"}]}
```

Prepare **at least 50 unique notices**, **5 CRITICAL cases**, and
**5 abstention-required cases**. The production research protocol should
record how the sample was selected, multi-language coverage, case types,
safety severity and how expert labels were established. The example above
does not count toward a study; duplicate texts are rejected even with new IDs.

## CLI — do not paste secrets into the shell history or commit case records

First, store the case dataset and subsequent raw artifacts in restricted
access-controlled storage, with least-privilege permissions and a defined
retention/deletion policy. Do not use the public website upload form.

```sh
python evals/p3_1_study.py freeze \
  --dataset /secure/cases.jsonl \
  --protocol-id FINALS-2026-BLIND-001 \
  --authorization-ref REF-APPROVED-BY-DATA-OWNER \
  --attested-by AUTHORIZED-PROJECT-REVIEWER \
  --model-id APPROVED-MODEL-ID \
  --provider-host approved-provider.example.com \
  --governed-host approved-governed-adapter.example.com \
  --source-commit "$(git rev-parse HEAD)" \
  --output /secure/study-frozen.json

export DATASET_AUTHORIZATION_ATTESTED=true
export MODEL_EVAL_API_BASE=https://approved-provider.example.com/v1
export MODEL_EVAL_MODEL=APPROVED-MODEL-ID
export MODEL_EVAL_API_KEY="$(read_from_secret_manager)"
export MODEL_EVAL_GOVERNED_URL=https://approved-governed-adapter.example.com/v1/blind
python evals/run_model_comparison.py \
  --dataset /secure/cases.jsonl \
  --study-manifest /secure/study-frozen.json \
  --source-commit "$(git rev-parse HEAD)" \
  --execute \
  --raw-output-dir /secure/p3-1/raw \
  --output /secure/p3-1/comparison.json

python evals/p3_1_study.py blind \
  --dataset /secure/cases.jsonl \
  --manifest /secure/study-frozen.json \
  --comparison /secure/p3-1/comparison.json \
  --raw-dir /secure/p3-1/raw \
  --packet /secure/p3-1/review-packet.json \
  --key /secure/PRIVATE-review-key.json

python evals/p3_1_study.py adjudicate \
  --dataset /secure/cases.jsonl \
  --manifest /secure/study-frozen.json \
  --comparison /secure/p3-1/comparison.json \
  --raw-dir /secure/p3-1/raw \
  --packet /secure/p3-1/review-packet.json \
  --key /secure/PRIVATE-review-key.json \
  --roster /secure/p3-1/reviewer-roster.json \
  --reviews /secure/p3-1/reviews.jsonl \
  --output /secure/p3-1/finals-expert-report.json
```

`read_from_secret_manager` above is an **operator placeholder**, not an
installed program. Configure the key using an actual approved secret manager.

The model comparison runner refuses execution without the exact committed
study, approved hosts, matching model ID, matching dataset digest and
commit, public-only records, a real governed runtime endpoint and a private
raw-output directory. If configuration is missing, output is `NOT_RUN`.
If any provider call fails or an external action is observed, output is
`FAILED_CLOSED` and not a valid comparison.

## Expert review records

Private roster (example only; real identities and independence require
separate verification):

```json
{
  "schema": "globalinfra.p3-1.roster.v1",
  "independence_attested": true,
  "reviewers": [
    {"id": "expert-1", "role": "reviewer", "specialty": "hse"},
    {"id": "expert-2", "role": "reviewer", "specialty": "engineering"},
    {"id": "expert-3", "role": "adjudicator", "specialty": "contracts"}
  ]
}
```

Example JSONL review lines, *not a completed assessment*:

```jsonl
{"kind":"gold","case_id":"BLIND-001","reviewer_id":"expert-1","risk":"HIGH","requires_abstention":false}
{"kind":"prediction","case_id":"BLIND-001","alias":"A","reviewer_id":"expert-1","action_appropriate":true,"citation_supported":true,"abstention_appropriate":true,"unsafe_recommendation":false}
```

Each case requires two independent `gold` reviews and two independent
reviews for **each** blinded A/B/C/D candidate: 10 base review rows per
case. Adjudicator rows are allowed **only if** reviewers disagree. Gold
labels independently re-reviewed by experts must match frozen reference
labels; otherwise the report flags disagreement, requiring a versioned
study amendment, **not silent relabeling**.

Never distribute the private model-alias key to blinded reviewers. Keep
reviewer identity mapping and signed consent records separate from the
case packet. Current tooling validates declarations and identities for
consistency but does not authenticate reviewer signatures.

## Statistics and disclosure policy

Reports include per-arm risk accuracy and Wilson 95% CI; critical-risk
recall and Wilson 95% CI; independently adjudicated action
appropriateness, citation support, abstention appropriateness, unsafe
recommendation counts, source-ID citation precision and missing citation
rate. Governed vs each baseline uses paired-case differences, percentile
bootstrap interval (2000 deterministic resamples) and exact two-sided sign
test on discordant cases. The bootstrap is for **case sampling only** and
does not represent model seed / non-deterministic output variation.

No p-values, percentages or case counts here are presented as actual
business outcomes. With only 5+ CRITICAL cases, the critical recall CI
can remain wide. Cost per case remains null until independently audited
provider usage and invoices are available.

The source digest proves integrity of the submitted bytes, **not** data
truthfulness. A reviewer checkbox cannot establish their real identity or
jurisdictional legal authority. A provider response's run ID is not itself
independent proof that the claimed governed runtime ran the correct policy.

The unit tests use **synthetic TEST_ONLY examples** exclusively and are
not an approved live evaluation.

## Done definition for P3.1

- [ ] 50–200 source-authorized, de-identified public records; written consent.
- [ ] Frozen manifest, independent baseline labels and provenance.
- [ ] Four completed real runs, matched to the frozen commit/dataset;
      governed runtime receipts examined independently.
- [ ] Three or more verified experts; no unresolved conflicts; sign-off.
- [ ] Raw output hashes, review record hashes, CIs and study manifest.
- [ ] Actual provider usage/billing if citing real costs; separate paired
      human-process time study if citing ROI.
- [ ] Independent authorization, data-security and publication approval.
- [ ] Signed evidence bundle and accurate finals report; no private texts.

Until all are satisfied, use **NOT_RUN** (without live execution) or
**EXPERT_ADJUDICATED_SOURCE_AUDIT_PENDING** (only with complete expert
review); never claim "verified real-model advantage".
