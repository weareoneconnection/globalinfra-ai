# Finals P0 closure — 2026-11-26

This branch is a minimal-risk **competition finals** hardening change. It does not introduce new AI domains or change any production customer data.

## Delivered

1. **Web release gate:** regenerate `apps/web/app/theme-light.css` from the checked-in `globals.css`. CI still validates byte-for-byte agreement via `scripts/gen_light_theme.py`; the gate is **not** bypassed.
2. **Official finals scorecard:** `GET /competition/submission-evidence` now exposes `scoring_standard=C4AI_2026_FINAL_AI_OUTBOUND_11_ITEMS` and 11 official criteria totaling 100. Score values are criterion maxima, **not predicted or awarded marks**. The outdated preliminary 10-criterion scoreboard is superseded.
3. **Document-vs-site closure scope:** `/competition/sessions/{id}/state` now includes `closure_scope`. The signed action chain closes only the **document-response draft workflow**. It does **not** close or certify physical remediation, site reinspection, external dispatch, or the overarching safety incident.
4. **Judge-facing language:** the Jury Control Room explicitly displays the boundary; removes unqualified use of "case/work-order closed" for the draft.
5. **Regression tests:** enforce exactly 11 official score weights, 100-point total, and the document-only closure evidence boundary.

## Official AI-outbound finals criteria

| Group | Item | Max |
| --- | --- | ---: |
| Innovation | Industry pain point resolution | 10 |
| Innovation | Technology integration innovation | 8 |
| Innovation | Business model innovation | 7 |
| Technical solution | Technical route soundness | 15 |
| Technical solution | Data support effectiveness | 10 |
| Completeness | Design report quality | 8 |
| Completeness | Scenario applicability | 7 |
| Completeness | Scalability | 5 |
| Application value | Quantified economic impact | 8 |
| Application value | Overseas rollout potential | 7 |
| Presentation | On-site presentation | 15 |

## Acceptance gates

- [ ] GitHub PR branch `api`, `web`, and `docker-compose-smoke-test` succeed.
- [ ] Generated light-theme file passes the **existing** CI diff check.
- [ ] `test_competition.py` passes the 11-score/closure assertions.
- [ ] No evidence of a customer-data import or actual physical reinspection is claimed.
- [ ] After review/merge into the protected main branch: obtain a **new main-commit-bound** signed release artifact and immutable image. PR-branch CI does not trigger the protected production release signing.
- [ ] Verify deployed `/competition/submission-evidence` reports the matching commit and `VERIFIED_PASSED`; if not, retain `UNVERIFIED`.
- [ ] Check Jury Control Room in both Chinese and English at 1440x900 and on projector.

## Deferred P1; not silently counted as done

- Real blinded model-vs-RAG comparison with authorized records.
- Raw-record-backed economic impact verification (current ROI verifier only acknowledges a matching digest from a separate actor).
- Qualified country-pack source review and second-country applicability study.
- Full end-to-end site remediation with reinspection, separately from the document draft lifecycle.
- V6.2 finals report, presentation and field-proven ROI evidence.

## Safety boundary

No real correspondence is sent by `document.generate` (`DRAFT_ONLY_NOT_SENT`). Sandbox actors are role-scoped demonstration tickets, **not** enterprise OIDC identities. Validating a draft is not a safety acceptance or physical defect closeout.
