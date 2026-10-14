# Phase 9.1: Competition Golden Thread and Evaluation Evidence

Phase 9.1 turns existing product capabilities into one jury-verifiable AI-outbound story instead of adding a separate scripted demo.

## Positioning

**GlobalInfra AI — trusted AI execution and operational digital twins for overseas transport infrastructure.**

The `/competition` surface demonstrates all three AI-outbound directions:

- **Tool export:** bilingual intake, country/lifecycle routing, country packs and contract/compliance evidence.
- **Local integration:** localized HSE, authority and permit gates, training and explicit human accountability.
- **Capability export:** project operational twins with IFC, GLTF, 3D Tiles, GeoJSON, WMS and IoT interfaces.

## Seven-step golden thread

The synthetic `MY-RAIL-A` scenario runs through bilingual intake, Malaysia routing, a versioned country pack, live evidence retrieval, Twin-ID/4D/5D context, multi-agent planning with two human gates for critical HSE, and finally the existing governed document tool plus independent verification.

The operator must explicitly click the approval action. The resulting artifact remains `DRAFT_ONLY_NOT_SENT`; `external_delivery_performed` is always false.

## Reproducible benchmark

`services/api/evals/competition_outbound.jsonl` contains 30 synthetic cases: eight multilingual field events, eight regulation/permit queries, six contract/claim cases, four localized HSE-training cases and four twin-operation cases.

The suite executes the production intake and retrieval code and measures country, lifecycle, risk and case-type accuracy; Top-3 evidence recall; citation completeness; no-evidence abstention; schema validity; offline fallback success; and wall-clock latency.

```bash
python evals/run_competition_eval.py
curl 'http://localhost:8001/competition/evaluation?include_cases=true'
```

The same suite is a CI gate. Metrics shown in the UI are computed from that function; they are not authored presentation values.

All project, case, twin and evaluation records in this route are synthetic. Country packs are operational source indexes rather than legal advice, and the six twin formats are integration-shaped examples rather than as-built models.
