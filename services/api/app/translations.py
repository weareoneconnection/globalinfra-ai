"""Deterministic offline fallback for the translation-model integration.

When no real OpenAI-compatible model is configured (``llm_mode=mock``, the
default for local dev / CI / the eval harness) ``llm.translate()`` resolves
English runtime text through this curated phrase table instead of calling
out to the network.

Most runtime text in this platform is now generated directly in both
languages from structured, already-bilingual data (see ``workflow.py`` and
``i18n.bi``), precisely so it does not depend on a fixed phrase table for
text that was never known in advance. This table only needs to cover the
handful of genuinely fixed, case-independent governance strings that are
still routed through ``translate()`` -- today that is the approval-gate
findings produced by ``main.py``'s ``approve`` endpoint, plus the
deterministic-mode notice from ``llm.generate`` itself.

When ``OPENAI_COMPAT_API_KEY`` is set and ``llm_mode`` is not "mock", the
same call sites go through the real model instead (see ``llm.translate``),
and arbitrary text outside this table is translated by that model too.
"""

DEMO_TRANSLATIONS: dict[str, dict[str, str]] = {
    "Evidence-backed candidate action generated": {
        "zh": "已生成有证据支撑的候选行动"
    },
    "Required human approval recorded": {
        "zh": "已记录所需的人工审批"
    },
    "Trusted execution may proceed": {
        "zh": "可信执行流程可以继续"
    },
    "Deterministic demo mode active. No external model call was required.": {
        "zh": "确定性演示模式已启用，本次未调用外部模型。"
    },
}
