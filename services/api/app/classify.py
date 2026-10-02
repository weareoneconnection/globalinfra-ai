"""Deterministic case-text classifier.

This backs two things:

1. The ``POST /cases/classify`` endpoint — a real (if intentionally simple)
   capability that takes free-text field/owner-notice input and returns a
   case type + risk level, independent of the seeded demo dataset.
2. ``evals/run_eval.py`` — the evaluation harness asserts its predictions
   against ``evals/datasets/cases.jsonl`` instead of only checking that the
   dataset rows have the right shape.

It is deliberately rule-based rather than a model call, following the same
"deterministic demo mode" philosophy as ``llm.py``/``translations.py``: the
evaluation harness and the endpoint behave identically with or without a
configured LLM, and every mapping below is auditable instead of opaque.
When a real classification model is wired in, keep the same
``{"type": ..., "risk": ...}`` return contract so call sites do not change.
"""

# Ordered (keyword-set, type, risk) rules. First rule with a matching
# keyword wins, mirroring how a human triage reviewer scans a notice for
# safety signals before administrative/contractual ones. Keywords are kept
# lowercase; Chinese keywords are matched as-is since case folding does not
# apply to them.
_RULES: list[tuple[set[str], str, str]] = [
    (
        {"unprotected edge", "fall protection", "elevated workface", "working at height",
         "no ppe", "无防护", "坠落", "高处作业"},
        "HSE", "CRITICAL",
    ),
    (
        {"honeycomb", "surface defect", "concrete crack", "formwork", "defect",
         "蜂窝", "裂缝", "表面缺陷"},
        "Quality", "MEDIUM",
    ),
    (
        {"method statement", "local compliance", "local law", "permit",
         "合规", "施工方案"},
        "Compliance", "HIGH",
    ),
    (
        {"owner notice", "access road", "rectification", "encroachment",
         "通知", "便道", "整改"},
        "Contract / Technical Interface", "HIGH",
    ),
]

DEFAULT_TYPE = "Contract / Technical Interface"
DEFAULT_RISK = "MEDIUM"


def classify_text(text: str) -> dict:
    """Classify a free-text observation/notice into ``{type, risk}``.

    Falls back to ``DEFAULT_TYPE``/``DEFAULT_RISK`` when no rule matches,
    rather than raising, so the endpoint and the eval harness always get a
    usable (if generic) answer for out-of-vocabulary input.
    """
    lowered = (text or "").lower()
    for keywords, case_type, risk in _RULES:
        if any(keyword in lowered for keyword in keywords):
            return {"type": case_type, "risk": risk}
    return {"type": DEFAULT_TYPE, "risk": DEFAULT_RISK}
