"""Universal Intake Foundation (V1.3 Mission M1) -- deterministic intake layer.

This module turns an arbitrary free-text field observation / owner notice /
letter (already extracted from PDF/DOCX/TXT by ``documents.py``) into a
structured, bilingual ``IntakeResult``. It is fully deterministic and runs
with no external API key, matching the platform's offline posture.

Layering:

* **Classification (Layers 1 & 2).** ``case_type`` and ``risk`` are *never*
  decided inside this module. By default (``classification=None``) they come
  from wrapping the deterministic ``classify.classify_text`` rules (Layer 1).
  The async intake pipeline may instead pass in the result of
  ``llm_classify.classify_text_llm`` (V1.3 Mission M2, Layer 2) via the
  ``classification`` argument -- an LLM-refined ``{type, risk}`` constrained to
  the same vocabulary, with a rule fallback. Either way the ``classify.py``
  return contract (``{"type", "risk"}``) is untouched and the ``/cases/classify``
  endpoint, the eval harness and intake always agree on the *default* path, so
  the deterministic unit tests / evals here keep calling this synchronously.
* **Deterministic enrichment.** Every other field (domains, lifecycle stage,
  country, language, issues, entities, deadline, recommended agents, required
  approvals, confidence) is derived by auditable rules/heuristics below. The
  async intake pipeline may refine ``country``/``issues``/``entities`` (M3) and
  ``lifecycle``/``deadline`` (M4) with the LLM extraction layer (``llm_extract``)
  via the ``extraction`` argument -- constrained to the same vocabularies and
  grounded against the text, with a deterministic fallback -- and
  ``extraction_method`` reports which path produced them. All other fields stay
  deterministic.

``case_type``/``risk`` are returned as their canonical machine values (the
English ``classify`` labels and the risk-level code) *plus* bilingual display
companions ``case_type_label``/``risk_label``; ``issues`` are bilingual. The
canonical ``case_type`` English string is what routes the Case to a specialist
team via ``workflow.SPECIALISTS_BY_CASE_TYPE`` -- intake and analysis therefore
select the same agents for the same input.
"""
from __future__ import annotations

import re

from .classify import DEFAULT_RISK, DEFAULT_TYPE, classify_text
from .domain import INTELLIGENCE_DOMAINS, LIFECYCLE_STAGES, PROFESSIONAL_DOMAINS
from .i18n import bi
from .workflow import DEFAULT_SPECIALISTS, SPECIALISTS_BY_CASE_TYPE

_CJK_RE = re.compile(r"[一-鿿]")

# Canonical ``classify`` case-type label (English, = SPECIALISTS_BY_CASE_TYPE
# key) -> bilingual display label. English side MUST stay identical to the
# classify label so Case.type["en"] keeps routing correctly in workflow.py.
CASE_TYPE_LABELS: dict[str, dict] = {
    "Contract / Technical Interface": bi("Contract / Technical Interface", "合同 / 技术接口"),
    "HSE": bi("HSE", "健康安全环保（HSE）"),
    "Quality": bi("Quality", "质量"),
    "Compliance": bi("Compliance", "合规"),
}

RISK_LABELS: dict[str, dict] = {
    "CRITICAL": bi("Critical", "紧急"),
    "HIGH": bi("High", "高"),
    "MEDIUM": bi("Medium", "中"),
    "LOW": bi("Low", "低"),
}

# case_type -> (intelligence-domain id, professional-domain English name)
CASE_TYPE_DOMAIN: dict[str, tuple[str, str]] = {
    "Contract / Technical Interface": ("commercial", "Contract & Commercial"),
    "HSE": ("assurance", "HSE"),
    "Quality": ("assurance", "Quality"),
    "Compliance": ("assurance", "Compliance & Permits"),
}
_DEFAULT_DOMAIN = ("commercial", "Contract & Commercial")

_DOMAIN_BY_ID = {d["id"]: d for d in INTELLIGENCE_DOMAINS}
_PROF_NAME_BY_EN = {en: bi(en, zh) for en, zh, *_ in PROFESSIONAL_DOMAINS}
_LIFECYCLE_BY_ID = {s["id"]: s for s in LIFECYCLE_STAGES}


def _prof_slug(en_name: str) -> str:
    return en_name.lower().replace(" & ", "-").replace(" ", "-")


# (keyword tuple, bilingual issue label). Keywords are lowercase; Chinese is
# matched as-is. A single text may surface several issues.
ISSUE_SIGNALS: list[tuple[tuple[str, ...], dict]] = [
    (("unprotected edge", "fall protection", "working at height", "fall arrest",
      "无防护", "坠落", "高处作业"), bi("Fall protection / working at height", "坠落防护 / 高处作业")),
    (("no ppe", "without ppe", "ppe"), bi("PPE compliance", "个人防护装备合规")),
    (("concrete crack", "structural crack", "crack", "裂缝"), bi("Structural crack", "结构裂缝")),
    (("honeycomb", "surface defect", "spalling", "蜂窝", "表面缺陷"),
     bi("Concrete surface defect", "混凝土表面缺陷")),
    (("access road", "haul road", "便道"), bi("Access road / temporary works", "施工便道 / 临时工程")),
    (("encroachment", "侵占"), bi("Earthwork encroachment", "土方侵占")),
    (("rectification", "rectify", "整改"), bi("Rectification request", "整改要求")),
    (("method statement", "施工方案"), bi("Method statement review", "施工方案审查")),
    (("permit", "local law", "local compliance", "regulation", "合规", "许可", "当地法规"),
     bi("Local compliance / permit", "当地合规 / 许可")),
    (("variation order", "variation request", "request for variation", "change order", "变更令", "变更申请", "签证"),
     bi("Variation / change request", "变更 / 签证申请")),
    (("owner notice", "employer notice", "通知函", "通知"), bi("Owner notice", "业主通知")),
    (("delay", "extension of time", "eot", "延误", "工期"), bi("Schedule / delay impact", "进度 / 延误影响")),
    (("ncr", "non-conformance", "不符合"), bi("Non-conformance (NCR)", "不符合项（NCR）")),
]

# (country code, bilingual label, keyword tuple). First match wins; drives the
# project a new Case is attached to when a matching project exists.
COUNTRY_SIGNALS: list[tuple[str, dict, tuple[str, ...]]] = [
    ("MY", bi("Malaysia", "马来西亚"), ("malaysia", "malaysian", "kuala lumpur", "马来西亚")),
    ("ID", bi("Indonesia", "印度尼西亚"), ("indonesia", "jakarta", "nusantara", "印度尼西亚", "印尼")),
    ("SA", bi("Saudi Arabia", "沙特阿拉伯"), ("saudi", "riyadh", "沙特")),
    ("AE", bi("United Arab Emirates", "阿拉伯联合酋长国"), ("uae", "dubai", "abu dhabi", "阿联酋", "迪拜")),
]

# Reverse lookups used when a Layer-3 (M3) LLM extraction injects a country code
# / issue key: the LLM vocabulary is constrained to exactly these tables (see
# ``llm_extract``), so a validated code/key always resolves to a bilingual label.
_COUNTRY_LABEL_BY_CODE: dict[str, dict] = {code: label for code, label, _ in COUNTRY_SIGNALS}
_ISSUE_LABEL_BY_EN: dict[str, dict] = {label["en"]: label for _, label in ISSUE_SIGNALS}

# (lifecycle-stage id, keyword tuple). Falls back to "construction".
LIFECYCLE_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("design", ("design", "drawing", "rfi", "设计", "图纸")),
    ("procurement", ("procurement", "supplier", "material", "采购", "供应商")),
    ("commissioning", ("commissioning", "testing", "punch list", "调试", "测试")),
    ("handover", ("handover", "taking-over", "移交")),
    ("operations", ("maintenance", "operation", "运维", "运行", "维护")),
    ("planning", ("tender", "bid", "planning", "投标", "规划")),
]
_DEFAULT_LIFECYCLE = "construction"

# Reference-like identifiers, e.g. NCR-2026-084, SI-028, RM-03, VO-027, C-14.2.
_ENTITY_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-/][A-Z0-9][A-Z0-9.]*)+\b")
_DEADLINE_HOURS_RE = re.compile(r"(\d+)\s*(?:hours?|hrs?|小时)", re.IGNORECASE)
_DEADLINE_DAYS_RE = re.compile(r"(\d+)\s*(?:days?|天)", re.IGNORECASE)
_IMMEDIATE_RE = re.compile(r"immediate|立即|即刻", re.IGNORECASE)

APPROVER_PM = bi("Project Manager approval", "项目经理审批")
APPROVER_HSE = bi("HSE Manager sign-off", "HSE 经理会签")

LANGUAGE_DISPLAY = {"en": bi("English", "英语"), "zh": bi("Chinese", "中文")}


def detect_language(text: str) -> str:
    """Deterministic language detection: Chinese if any CJK character is
    present, otherwise English (the two languages the platform supports)."""
    return "zh" if _CJK_RE.search(text or "") else "en"


def _detect_issues(lowered: str) -> tuple[list[dict], bool]:
    issues: list[dict] = []
    seen = set()
    for keywords, label in ISSUE_SIGNALS:
        if any(k in lowered for k in keywords):
            key = label["en"]
            if key not in seen:
                seen.add(key)
                issues.append(label)
    return issues, bool(issues)


def _detect_country(lowered: str) -> tuple[str | None, dict | None]:
    for code, label, keywords in COUNTRY_SIGNALS:
        if any(k in lowered for k in keywords):
            return code, label
    return None, None


def _detect_lifecycle(lowered: str) -> str:
    for stage_id, keywords in LIFECYCLE_SIGNALS:
        if any(k in lowered for k in keywords):
            return stage_id
    return _DEFAULT_LIFECYCLE


def _detect_entities(text: str) -> list[str]:
    seen: list[str] = []
    for match in _ENTITY_RE.findall(text or ""):
        if match not in seen:
            seen.append(match)
    return seen[:8]


def format_deadline(amount: int | None, unit: str) -> dict | None:
    """Bilingual deadline label for a parsed ``(amount, unit)`` pair.

    Single source of truth for how a deadline is rendered, shared by the
    deterministic regex path (``_detect_deadline``) and the Layer-3/M4 LLM
    extraction (``llm_extract``), so both paths produce byte-identical labels.
    Returns ``None`` for an unrecognised unit / missing amount."""
    if unit == "immediate":
        return bi("Immediate", "立即处理")
    if unit == "hours" and amount is not None:
        return bi(f"{amount} hours", f"{amount} 小时")
    if unit == "days" and amount is not None:
        return bi(f"{amount} days", f"{amount} 天")
    return None


def _detect_deadline(text: str) -> dict | None:
    if _IMMEDIATE_RE.search(text or ""):
        return format_deadline(None, "immediate")
    hours = _DEADLINE_HOURS_RE.search(text or "")
    if hours:
        return format_deadline(int(hours.group(1)), "hours")
    days = _DEADLINE_DAYS_RE.search(text or "")
    if days:
        return format_deadline(int(days.group(1)), "days")
    return None


def _required_approvals(case_type: str, risk: str) -> list[dict]:
    approvals = [APPROVER_PM]
    if case_type == "HSE" and risk == "CRITICAL":
        approvals.append(APPROVER_HSE)
    return approvals


def build_intake_result(
    text: str,
    language: str | None = None,
    classification: dict | None = None,
    extraction: dict | None = None,
) -> dict:
    """Produce a structured, bilingual ``IntakeResult`` from free text.

    ``language`` may be supplied (e.g. from a request hint); otherwise it is
    detected deterministically. ``case_type``/``risk`` are never re-decided
    here: by default they come from the deterministic ``classify`` wrapper
    (Layer 1). The async intake pipeline may instead pass ``classification`` --
    a ``{"type", "risk", "method"?}`` dict from ``llm_classify.classify_text_llm``
    (Layer 2) -- in which case those authoritative values are used verbatim and
    ``classification_method`` reports how they were produced.

    Likewise ``country``/``issues``/``entities`` (M3) and ``lifecycle``/``deadline``
    (M4) are derived deterministically by default, but the pipeline may pass
    ``extraction`` -- a ``{"country", "issues", "entities", "lifecycle", "deadline"}``
    dict from ``llm_extract.extract_fields_llm``, already constrained to the same
    vocabularies and grounded against the text -- in which case those values are used
    and ``extraction_method`` reports ``"llm"`` instead of ``"rules"``. ``lifecycle``
    and ``deadline`` fall back per-field to the deterministic heuristic when the
    model leaves them empty.
    """
    text = text or ""
    lowered = text.lower()

    # --- authoritative case_type + risk (Layer 1 rules, or injected Layer 2) ---
    classified = classification or classify_text(text)
    case_type = classified["type"]
    risk = classified["risk"]
    method = classified.get("method", "rules")
    matched_rule = (case_type, risk) != (DEFAULT_TYPE, DEFAULT_RISK)

    case_type_label = CASE_TYPE_LABELS.get(case_type, bi(case_type))
    risk_label = RISK_LABELS.get(risk, bi(risk.title()))

    # --- deterministic enrichment ---
    lang = (language or "").lower()
    if lang not in ("en", "zh"):
        lang = detect_language(text)

    intel_id, prof_en = CASE_TYPE_DOMAIN.get(case_type, _DEFAULT_DOMAIN)
    primary_domain = {"id": intel_id, "name": _DOMAIN_BY_ID[intel_id]["name"]}
    professional_domain = {"id": _prof_slug(prof_en), "name": _PROF_NAME_BY_EN[prof_en]}

    # country / issues / entities / lifecycle / deadline: deterministic (Layer 1)
    # by default, or an injected Layer-3 (M3/M4) LLM extraction -- already
    # vocabulary-constrained and text-grounded by ``llm_extract`` -- used verbatim
    # when provided. ``lifecycle``/``deadline`` (added in M4) fall back per-field
    # to the deterministic heuristic when the model legitimately leaves them empty,
    # so the LLM path can refine them without ever losing a value the regex finds.
    if extraction is not None:
        extraction_method = "llm"
        country_code = extraction.get("country") or None
        country_label = _COUNTRY_LABEL_BY_CODE.get(country_code) if country_code else None
        issues = [_ISSUE_LABEL_BY_EN[k] for k in extraction.get("issues", []) if k in _ISSUE_LABEL_BY_EN]
        real_issues = bool(issues)
        entities = list(extraction.get("entities", []))
        extracted_lifecycle = extraction.get("lifecycle")
        lifecycle_id = extracted_lifecycle if extracted_lifecycle in _LIFECYCLE_BY_ID else _detect_lifecycle(lowered)
        deadline = extraction.get("deadline") or _detect_deadline(text)
    else:
        extraction_method = "rules"
        country_code, country_label = _detect_country(lowered)
        issues, real_issues = _detect_issues(lowered)
        entities = _detect_entities(text)
        lifecycle_id = _detect_lifecycle(lowered)
        deadline = _detect_deadline(text)
    lifecycle_stage = {"id": lifecycle_id, "name": _LIFECYCLE_BY_ID[lifecycle_id]["name"]}
    if not issues:
        issues = [case_type_label]
    recommended_agents = list(SPECIALISTS_BY_CASE_TYPE.get(case_type, DEFAULT_SPECIALISTS))
    required_approvals = _required_approvals(case_type, risk)

    # An LLM-refined classification (Layer 2) is more trustworthy than a bare
    # keyword hit; a default rule fallback is the least certain.
    if method == "llm":
        confidence = 0.75
    else:
        confidence = 0.6 if matched_rule else 0.45
    if country_code:
        confidence += 0.1
    if deadline:
        confidence += 0.1
    if real_issues:
        confidence += 0.1
    confidence = round(min(confidence, 0.95), 2)

    return {
        "primary_domain": primary_domain,
        "professional_domain": professional_domain,
        "case_type": case_type,            # canonical machine value (Layer 1/2)
        "case_type_label": case_type_label,  # bilingual display
        "classification_method": method,   # "llm" (Layer 2) or "rules" (Layer 1)
        "extraction_method": extraction_method,  # "llm" (Layer 3) or "rules"
        "lifecycle_stage": lifecycle_stage,
        "risk": risk,                      # canonical level code (Layer 1)
        "risk_label": risk_label,          # bilingual display
        "country": country_code,
        "country_label": country_label,
        "language": lang,
        "issues": issues,                  # bilingual list
        "entities": entities,
        "deadline": deadline,
        "recommended_agents": recommended_agents,
        "required_approvals": required_approvals,
        "confidence": confidence,
    }
