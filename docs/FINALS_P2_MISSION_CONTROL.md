# P2 Finals Mission Control — implementation and acceptance

Base: P1 merged main `fbf83b56c24c65765fccf164039b66e53e00a9b0`.

## Objective

Replace a feature inventory as the default finals narrative with an explicit
**one overseas engineering issue -> six accountable stages -> evidence / impact
proof -> reusable country configuration** story.

P2 is a presentation and safe read-model layer over the existing system, not
another Case, Approval, receipt, or ROI state authority.

## Delivered

- `GET /competition/finals/overview`: read-only public projection; derives
  the mission status from the **existing synthetic golden case and stored
  action evidence**, and release trust from `/competition/submission-evidence`.
- `/competition/finals`: responsive English/Chinese presentation page with
  an overseas mission hero, six evidence-linked stages, document-vs-physical
  remediation disclosure, model/ROI/release status cards, MY vs AE Country Pack
  differences and exact 11-item finals scoring map.
- Auth route allowlist change for **this GET endpoint and page only**. All
  `/pilot/*`, tenant-specific records and administration routes remain under
  existing authentication and project checks.
- API tests: official rubric, six stages, synthetic-only demo, tenant ROI
  secrecy, missing release artifact fail-closed.
- Original `/competition` evidence center and `/competition/jury` five-role
  governance demo are retained and linked from the new page.

## Evidence boundary

`model_comparison.status = NOT_RUN` until externally authorized, independently
reviewed live model comparisons are available through an **approved,
non-public publication mechanism**.

`paired_roi.status = NO_AUDITED_PUBLIC_RESULT` and no fabricated baseline,
AI-assisted time, savings ratio, or financial return is shown.

MY/AE comparisons expose **configuration differences**, not legal
certification, expert source validation or multi-country production rollout.

The synthetic P47 document workflow can be `DRAFT_VERIFIED` while the physical
hazard remains `REINSPECTION_NOT_PERFORMED`. Drafts are not sent externally.

Release `VERIFIED_PASSED` must come from the running deployment's
commit-bound signed evidence, not from a successful PR CI.

## Decision on real business evidence

P2 intentionally avoids adding tenant ROI into the public page. A future
version may publish separately approved, aggregate and redacted studies
through an explicit approval gate, not through direct `/pilot/roi-summary`
lookups or by exposing original cases.

## Acceptance

- [ ] API tests pass including `test_finals_p2.py`.
- [ ] Web lint/build and TypeScript checks pass.
- [ ] Compose full-stack smoke passes.
- [ ] `GET /competition/finals/overview` returns no tenant ROI detail;
      scorecard 11 items total 100 points.
- [ ] `/competition/finals` is accessible through the public allowlist.
- [ ] Inspect page in Chinese and English, 1440x900 and mobile widths.
- [ ] Verify release evidence against production commit after PR merge and
      protected main signing.
- [ ] Rehearse the new script; no invented metrics, no physical site closure.

## Suggested finals narrative

0:00-0:35 problem and cross-border context; 0:35-1:20 multilingual
understanding and country limits; 1:20-2:15 specialist coordination;
2:15-3:05 governed document execution and independent verification;
3:05-4:05 quality/ROI real evidence if actually available, otherwise
accurate `NOT_RUN` / `NO_AUDITED_PUBLIC_RESULT`; 4:05-5:00 country
configuration extensibility and repeatability.

The five-minute outline is a rehearsal proposal; event organizer instructions
supersede this duration.
