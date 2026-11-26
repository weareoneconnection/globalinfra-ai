"""Deterministic first-pass review of pasted contract clauses.

The contract review agent reads the clauses a user pastes (or a work
order's text), finds the commercial terms a contracts team checks first —
payment, delay damages, claim notice, variations, liability, retention,
termination, dispute resolution, force majeure, price adjustment — and flags
the patterns that are risky in any jurisdiction (uncapped delay damages, a
short claim time bar, pay-when-paid, an exclusion of structural liability).

Two flags rest on the clause library itself, because the clause heading
states the rule: Malaysia's CIPAA s.35 prohibits conditional payment, and the
UAE Civil Transactions Law voids a term excluding decennial liability. Every
other flag is a contracting risk, not a statement of law; local clauses on
the same topic are attached as related sources for the contracts team.

It is a first pass for a person to review, never legal advice and never a
substitute for reading the contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .i18n import bi, localize

MIN_REVIEW_LENGTH = 60
MAX_EXCERPT = 220
SHORT_TIME_BAR_DAYS = 28
LONG_PAYMENT_DAYS = 60
HIGH_RETENTION_PERCENT = 10

_DAYS = r"(\d{1,3})\s*(?:个)?(?:天|日|days?|calendar days|working days|hari|يوم|أيام)"
_PERCENT = r"(\d{1,2}(?:\.\d+)?)\s*(?:%|％|percent|per cent)"

# Markers that the text is contract wording rather than a letter or a question.
CONTRACT_MARKER_RE = re.compile(
    r"第[一二三四五六七八九十百\d]+(?:\.\d+)?条|(?:Clause|Article|Sub-?clause)\s*\d|甲方|乙方|分包方|承包方应|承包人应|发包人|"
    r"\bthe (?:Employer|Contractor|Subcontractor|Owner) shall\b|本合同|本协议|\bthis (?:Contract|Agreement|Subcontract)\b|"
    r"\bperjanjian ini\b|\bkontrak ini\b|هذا العقد", re.IGNORECASE)
REVIEW_VERB_RE = re.compile(r"审查|审核|审阅|分析|看看|检查|风险|有没有问题|review|check|risk|analy[sz]e|semak|tinjau|راجع",
                            re.IGNORECASE)


@dataclass
class Category:
    id: str
    name: dict
    pattern: re.Pattern
    query: str                                # clause-library search for related local clauses
    required: bool = False                    # a contract without it is itself a finding
    found: list[str] = field(default_factory=list)


def _re(text: str) -> re.Pattern:
    return re.compile(text, re.IGNORECASE)


def categories() -> list[Category]:
    return [
        Category("payment", bi("Payment terms", "付款条件"),
                 _re(r"付款|支付|工程款|进度款|payment|paid|pay\b|bayaran|pembayaran|الدفع|دفعة"), "payment claim progress payment terms",
                 required=True),
        Category("delay_damages", bi("Delay damages", "误期违约金"),
                 _re(r"违约金|误期|逾期.{0,6}(?:赔偿|罚)|liquidated damages|delay damages|per day of delay|ganti rugi|denda|غرامة التأخير"),
                 "liquidated damages delay penalty", required=True),
        Category("claims", bi("Claim notice & time extension", "索赔通知与工期顺延"),
                 _re(r"索赔|顺延|延期|延长工期|claim|extension of time|notice of|tuntutan|klaim|مطالبة|تمديد"),
                 "extension of time claim notice"),
        Category("variation", bi("Variations", "变更"),
                 _re(r"变更|增减|variation|change order|instruction to vary|perubahan|تغيير|أعمال إضافية"), "variation change remeasurement"),
        Category("liability", bi("Liability & defects", "责任与缺陷"),
                 _re(r"缺陷|保修|质保期|责任|liab|defect|warrant|kecacatan|cacat|مسؤولية|عيوب"), "defects liability decennial"),
        Category("retention", bi("Retention", "保留金"),
                 _re(r"保留金|质保金|保证金|retention|wang tahanan|retensi|محتجزات"), "retention"),
        Category("termination", bi("Termination", "解除合同"),
                 _re(r"解除|终止|terminat|penamatan|pemutusan|فسخ|إنهاء"), "termination"),
        Category("dispute", bi("Disputes & governing law", "争议解决与适用法律"),
                 _re(r"仲裁|诉讼|争议|适用.{0,10}法律|管辖|arbitrat|dispute|governing law|jurisdiction|adjudicat|timbang tara|arbitrase|تحكيم|نزاع"),
                 "dispute resolution arbitration adjudication", required=True),
        Category("force_majeure", bi("Force majeure", "不可抗力"),
                 _re(r"不可抗力|force majeure|keadaan kahar|القوة القاهرة"), "force majeure", required=True),
        Category("price", bi("Price adjustment", "调价"),
                 _re(r"调价|价格调整|物价|固定总价|不调整价格|escalation|price adjustment|fluctuation|fixed price|lump sum|harga tetap|تعديل الأسعار"),
                 "price escalation hardship lump sum"),
    ]


_PAY_WHEN_PAID_RE = _re(r"背靠背|收到(?:业主|发包人|甲方)?.{0,8}(?:付款|款项)后|业主付款后|pay[- ]when[- ]paid|pay[- ]if[- ]paid|"
                        r"upon receipt of (?:payment|funds) from the (?:Employer|Owner|Client)|"
                        r"subject to (?:the )?(?:Contractor|Main Contractor) receiving payment")
_CAP_RE = _re(r"上限|封顶|不超过|最高不超过|最多|cap(?:ped)?\b|maximum|not exceed|limited to|had maksimum|الحد الأقصى")
_EXCLUDE_RE = _re(r"免除|排除|不承担|概不负责|不负责|exclud|shall not be liable|no liability|waive|tidak bertanggungjawab|لا يتحمل|إعفاء")
_STRUCTURAL_RE = _re(r"结构|倒塌|坍塌|十年|structur|collapse|decennial|struktur|انهيار|عشري")
_NO_ADJUST_RE = _re(r"不(?:予)?调整|不得(?:因此)?(?:索赔|要求增加)|不另行(?:计价|付款)|no (?:adjustment|additional (?:cost|payment))|"
                    r"without (?:additional|extra) (?:cost|payment)|at no cost")
_CONVENIENCE_RE = _re(r"任意解除|随时解除|无需理由|for (?:its )?convenience|at any time without cause|tanpa sebab")
_TIME_BAR_RE = _re(r"(?:索赔|claim|notice).{0,40}?" + _DAYS + r"|" + _DAYS + r".{0,30}?(?:内.{0,8})?(?:索赔|claim|notice)")
_FIXED_RE = _re(r"不调价|不调整价格|固定(?:总)?价|no (?:price )?(?:escalation|adjustment)|fixed price|harga tetap")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。；;！？!?])|\n+|(?<=\.)\s+(?=[A-Z0-9第(（])", text)
    return [p.strip() for p in parts if p and p.strip()]


def _days(sentence: str) -> list[int]:
    return [int(n) for n in re.findall(_DAYS, sentence, re.IGNORECASE)]


def looks_like_contract(text: str) -> bool:
    """Pasted contract wording to review, as opposed to an owner letter or a question."""
    if len(text) < MIN_REVIEW_LENGTH or not CONTRACT_MARKER_RE.search(text):
        return False
    found = sum(1 for c in categories() if c.pattern.search(text))
    markers = len(CONTRACT_MARKER_RE.findall(text))
    letter = re.search(r"^\s*(?:尊敬的|致|dear|to:)", text, re.IGNORECASE)
    return found >= 2 and (bool(REVIEW_VERB_RE.search(text)) or (markers >= 3 and found >= 3 and not letter))


def review(text: str, country: str | None, lang: str) -> dict:
    """Find the commercial terms and flag risks. Returns findings, each with its excerpt and any legal basis."""
    cats = categories()
    first = CONTRACT_MARKER_RE.search(text)
    if first and first.start() > 0 and REVIEW_VERB_RE.search(text[:first.start()]):
        text = text[first.start():]  # drop "please review the following:" before the first clause
    for sentence in _sentences(text):
        for cat in cats:
            if cat.pattern.search(sentence):
                cat.found.append(sentence)
    findings: list[dict] = []

    def add(cat: Category, risk: str, en: str, zh: str, excerpt: str | None = None, basis: list[str] | None = None):
        findings.append({"category": cat.id, "name": localize(cat.name, lang), "risk": risk,
                         "finding": localize(bi(en, zh), lang), "excerpt": (excerpt or "")[:MAX_EXCERPT],
                         "basis": basis or []})

    by_id = {c.id: c for c in cats}
    for sentence in by_id["payment"].found:
        if _PAY_WHEN_PAID_RE.search(sentence):
            if country == "MY":
                add(by_id["payment"], "high",
                    "Conditional (pay-when-paid) payment. CIPAA s.35 prohibits conditional payment in Malaysian "
                    "construction contracts; such a term is void.",
                    "附条件付款（背靠背）。马来西亚 CIPAA 第 35 条禁止施工合同中的附条件付款，该条款无效。",
                    sentence, ["MY-ACT746-S35"])
            else:
                add(by_id["payment"], "high", "Conditional (pay-when-paid) payment shifts the employer's credit risk to you.",
                    "附条件付款（背靠背），把业主的付款风险转嫁给我方。", sentence)
        long_terms = [d for d in _days(sentence) if d > LONG_PAYMENT_DAYS]
        if long_terms:
            add(by_id["payment"], "medium", f"Payment period of {max(long_terms)} days strains cash flow.",
                f"付款期限 {max(long_terms)} 天，现金流压力大。", sentence)
    for sentence in by_id["delay_damages"].found:
        if not _CAP_RE.search(" ".join(by_id["delay_damages"].found)):
            add(by_id["delay_damages"], "high", "Delay damages have no cap.", "误期违约金没有上限。", sentence)
            break
    for sentence in by_id["claims"].found:
        days = [int(d) for match in _TIME_BAR_RE.findall(sentence) for d in match if d]
        if days and min(days) < SHORT_TIME_BAR_DAYS:
            add(by_id["claims"], "high" if min(days) <= 14 else "medium",
                f"Claim notice within {min(days)} days, shorter than the usual 28; a late notice may lose the claim.",
                f"索赔通知期限 {min(days)} 天，短于常见的 28 天，逾期可能丧失索赔权。", sentence)
    for sentence in by_id["variation"].found:
        if _NO_ADJUST_RE.search(sentence):
            add(by_id["variation"], "medium", "Variations without adjustment of price or time.",
                "变更不调整价格或工期。", sentence)
    for sentence in by_id["liability"].found:
        if _EXCLUDE_RE.search(sentence) and _STRUCTURAL_RE.search(sentence) and country == "AE":
            add(by_id["liability"], "high",
                "Excludes or limits liability for structural defects. Under the UAE Civil Transactions Law a term "
                "excluding decennial liability is void.",
                "排除或限制结构缺陷责任。依阿联酋民事交易法，排除十年责任的条款无效。", sentence, ["AE-FDL25-2025-ART-823"])
        elif _EXCLUDE_RE.search(sentence) and _STRUCTURAL_RE.search(sentence) and country == "SA":
            add(by_id["liability"], "medium", "Excludes or limits liability for structural defects; check the Saudi "
                "rules on contractor liability.", "排除或限制结构缺陷责任，须对照沙特关于承包方责任的规定。", sentence)
    for sentence in by_id["retention"].found:
        percents = [float(p) for p in re.findall(_PERCENT, sentence, re.IGNORECASE)]
        if percents and max(percents) > HIGH_RETENTION_PERCENT:
            add(by_id["retention"], "medium", f"Retention of {max(percents):g}% is above the usual 5-10%.",
                f"保留金比例 {max(percents):g}%，高于常见的 5%–10%。", sentence)
    for sentence in by_id["termination"].found:
        if _CONVENIENCE_RE.search(sentence):
            add(by_id["termination"], "medium", "The other party may terminate for convenience; check what is paid on termination.",
                "对方可任意解除合同，须确认解除后的结算和补偿。", sentence)
    for sentence in by_id["price"].found:
        if _FIXED_RE.search(sentence):
            add(by_id["price"], "low", "Fixed price with no adjustment: material and labour price risk stays with you.",
                "固定价格、不调价：材料和人工涨价风险由我方承担。", sentence)
    for cat in cats:
        if cat.required and not cat.found:
            add(cat, "medium", f"No {localize(cat.name, 'en').lower()} clause in the text reviewed.",
                f"所审文本中没有「{localize(cat.name, 'zh')}」条款。")
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order[f["risk"]])
    return {
        "terms": [{"category": c.id, "name": localize(c.name, lang), "excerpt": c.found[0][:MAX_EXCERPT]} for c in cats if c.found],
        "findings": findings,
        "queries": {c.id: c.query for c in cats if c.found},
    }
