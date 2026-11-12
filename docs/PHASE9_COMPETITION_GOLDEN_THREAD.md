# Phase 9.1: Competition Golden Thread and Evaluation Evidence

Phase 9.1 turns existing product capabilities into one jury-verifiable AI-outbound story instead of adding a separate scripted demo.

V6.0 retains the seven-step story but replaces the shared one-click demo with a fresh synthetic session per judge and five distinct human identities. Three suites contribute 57 versioned cases; test totals, source commit, dataset digests, web build, migration and full-stack smoke gates are read only from the signed release artifact rather than hard-coded into this document.

## Positioning

**GlobalInfra AI — trusted AI execution and operational digital twins for overseas transport infrastructure.**

The `/competition` surface demonstrates all three AI-outbound directions:

- **Tool export:** bilingual intake, country/lifecycle routing, country packs and contract/compliance evidence.
- **Local integration:** localized HSE, authority and permit gates, training and explicit human accountability.
- **Capability export:** project operational twins with IFC, GLTF, 3D Tiles, GeoJSON, WMS and IoT interfaces.

## Seven-step golden thread

The isolated `COMP-SYNTH-MY-P47` scenario runs through bilingual intake, Malaysia routing, a versioned country pack, allowlisted synthetic evidence, Twin-ID context, multi-agent planning with two human gates for critical HSE, governed document execution, independent verification and separate closure.

Project manager, HSE manager, executor, verifier and closer each act with a different short-lived role ticket. The resulting artifact remains `DRAFT_ONLY_NOT_SENT`; `external_delivery_performed` is always false.

## Reproducible benchmark

`services/api/evals/competition_outbound.jsonl` contains 30 synthetic cases: eight multilingual field events, eight regulation/permit queries, six contract/claim cases, four localized HSE-training cases and four twin-operation cases.

The suite executes the production intake and retrieval code and measures country, lifecycle, risk and case-type accuracy; Top-3 evidence recall; citation completeness; no-evidence abstention; schema validity; offline fallback success; and wall-clock latency.

```bash
python evals/run_competition_eval.py
curl 'http://localhost:8001/competition/evaluation?include_cases=true'
```

The same suite is a CI gate. The live evaluation endpoint is diagnostic only;
release status and published suite metrics in the UI come from the
commit-bound, signature-verified release artifact. They are never authored
presentation values.

The ten judging cards map published criteria to inspectable system evidence. They are not self-awarded scores.

All project, case, twin and evaluation records in this route are synthetic. Country packs are operational source indexes rather than legal advice, and the six twin formats are integration-shaped examples rather than as-built models.
