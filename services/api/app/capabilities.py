"""What the assistant can and cannot answer, computed from what it actually has.

The dispatcher's self-description used to be a fixed paragraph. It now comes
from two live sources: the sub-agent roster and the clause library. Each
lifecycle domain (contract, labour law, building codes, safety, quality,
schedule, ...) is mapped to clause topics, and the clauses for each country
are counted, so "can you answer Saudi quality questions?" is answered from
the data and stays true when clauses are added or removed.

Coverage levels per domain and country:
- ``covered``: at least ``COVERED_MIN`` clauses;
- ``thin``: some clauses, not enough to answer most questions;
- ``none``: no clause.

Building codes are a special case. The library holds the laws that make
building codes binding, not the technical provisions (cover, loads, fire
ratings), so that domain is ``legal_only`` whatever the counts say.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .country_knowledge import load_clause_library, load_glossary
from .i18n import bi, localize
from .intake import COUNTRY_SIGNALS

COUNTRIES = [code for code, _, _ in COUNTRY_SIGNALS]
COUNTRY_NAMES = {code: label for code, label, _ in COUNTRY_SIGNALS}
COVERED_MIN = 5

DOMAINS: list[dict] = [
    {
        "id": "contract", "name": bi("Contract, payment & claims", "合同、付款与索赔"),
        "agents": ["contract_review", "knowledge", "compare", "intake", "draft", "precedents"],
        "topics": {"construction contract", "contract", "contract terms", "variation", "subcontract", "payment",
                   "progress payment", "payment claim", "payment response", "payment terms", "interim payment",
                   "adjudication", "adjudication decision", "claims", "claim", "liquidated damages", "force majeure",
                   "hardship", "extension of time", "liability", "decennial liability", "muqawala", "lump sum",
                   "remeasurement", "price escalation", "retention", "pay when paid", "direct payment",
                   "dispute resolution", "dispute board", "arbitration", "warranty", "guarantee", "substitute contractor",
                   "default", "remedy", "contract sum", "joint liability", "limitation", "scope"},
        "keywords": r"合同|契约|付款|工程款|进度款|索赔|违约|变更|仲裁|争议|保函|质保金|不可抗力|"
                    r"contract|payment|claim|variation|arbitration|dispute|force majeure|liquidated damages|kontrak|عقد",
        "note": bi("Clauses of the civil, contract-payment and adjudication laws. Paste contract clauses and the contract "
                   "review agent gives a first-pass review (payment, delay damages, claim notice, variations, liability, "
                   "retention, termination, disputes) checked against these laws; an uploaded contract file still goes "
                   "through intake. A first pass for the contracts team, not legal advice.",
                   "覆盖各国民法、工程款支付和裁决法中的相关条款。粘贴合同条款后，合同审查智能体逐项初审（付款、误期违约金、"
                   "索赔通知、变更、责任、保留金、解除、争议解决），并对照这些法律；上传的合同文件目前仍走建案流程。"
                   "仅供合同团队初审，不构成法律意见。"),
    },
    {
        "id": "labour", "name": bi("Labour & workforce law", "劳工与用工法"),
        "agents": ["knowledge", "compare", "glossary"],
        "topics": {"workforce", "foreign worker", "wages", "working hours", "overtime", "termination", "end of service",
                   "gratuity", "employment contract", "work permit", "recruitment", "accommodation", "labour camp",
                   "welfare", "worker welfare", "leave", "annual leave", "sick leave", "Ramadan", "rest day",
                   "rest break", "midday break", "RPTKA", "levy", "probation", "WPS", "labour supply", "manpower supply",
                   "local workforce", "redundancy", "discrimination", "forced labour", "public holiday", "GOSI"},
        "keywords": r"劳工|劳动|用工|工人|员工|外籍|工资|加班|工时|休假|年假|解雇|签证|工作许可|宿舍|"
                    r"labour|labor|worker|employee|wage|overtime|working hours|leave|visa|work permit|pekerja|عمال|العمل",
        "note": bi("Labour codes of all four countries.", "四国劳动法典的相关条款。"),
    },
    {
        "id": "licensing", "name": bi("Licensing, permits & market entry", "资质、许可与市场准入"),
        "agents": ["knowledge", "gates"],
        "topics": {"CIDB", "contractor registration", "licensing", "foreign contractor", "market entry", "local content",
                   "joint operation", "certification", "professional licence", "permit", "construction permit",
                   "operating permit", "railway permit", "site registration", "contractor grade", "registration",
                   "personnel registration", "green card", "accreditation", "approval", "installation approval"},
        "keywords": r"资质|许可|执照|牌照|注册|准入|审批|报建|licen[cs]e|permit|registration|market entry|lesen|izin|ترخيص|رخصة",
        "note": bi("Licensing clauses plus the permit gates of each country pack, by lifecycle stage.",
                   "资质许可条款，加上各国家包按生命周期阶段列出的许可关口。"),
    },
    {
        "id": "building_codes", "name": bi("Building & design codes", "建筑与设计规范"),
        "agents": ["knowledge"],
        "topics": {"code of practice", "standards", "safety standard", "structural safety", "building failure",
                   "safety in design", "design", "specification"},
        "keywords": r"建筑规范|设计规范|技术规范|施工规范|规范要求|标准图|保护层|荷载|抗震|配筋|混凝土强度|防火等级|耐火|桥梁设计|"
                    r"building code|design code|design standard|eurocode|concrete cover|seismic|load combination|"
                    r"fire rating|SBC|SNI|UBBL|kod bangunan|كود البناء",
        "legal_only": True,
        "note": bi("Only the laws that make codes binding and some design-safety duties. Technical provisions "
                   "(concrete cover, loads, seismic, fire ratings) are not in the library, so such questions are "
                   "answered with that gap stated, never with a guessed number.",
                   "只有让规范具有约束力的法律和部分设计安全责任条款。技术条文（保护层、荷载、抗震、防火等级等）不在库里，"
                   "这类问题会明确说明缺口，不会给出猜测的数值。"),
    },
    {
        "id": "safety", "name": bi("Occupational safety", "施工安全"),
        "agents": ["knowledge", "compare", "intake", "field"],
        "topics": {"OSH", "PPE", "working at height", "fall protection", "scaffold", "scaffolding", "lifting", "crane",
                   "hoist", "excavation", "shoring", "trench", "confined space", "fire", "fire safety", "incident reporting",
                   "accident notification", "safety committee", "SMKK", "safety plan", "safety management system",
                   "HIRARC", "risk assessment", "temporary works", "falsework", "electrical", "traffic management",
                   "heat stress", "work injury", "induction", "toolbox talk", "competent person", "edge protection",
                   "demolition", "blasting", "explosives", "first aid", "emergency procedure", "near miss",
                   "stop work order", "safety officer", "P2K3", "K4", "occupational disease"},
        "keywords": r"安全|事故|伤亡|高处|脚手架|吊装|起重|基坑|有限空间|防护|劳保|工伤|应急|"
                    r"safety|accident|injur|height|scaffold|lifting|crane|excavation|PPE|keselamatan|سلامة",
        "note": bi("The strongest domain for Malaysia and Indonesia (OSH acts and construction regulations).",
                   "马来西亚和印尼覆盖最全（职业安全法和施工安全法规）。"),
    },
    {
        "id": "quality", "name": bi("Quality, defects & acceptance", "质量、缺陷与验收"),
        "agents": ["knowledge", "commissioning", "intake", "precedents"],
        "topics": {"quality", "defects", "inspection", "testing", "materials", "construction materials", "acceptance",
                   "handover", "as-built", "certificate of fitness", "plant inspection", "inspection report",
                   "decennial liability", "building failure", "warranty"},
        "keywords": r"质量|缺陷|验收|检验|检测|试验|材料|返工|移交|保修|quality|defect|inspection|testing|acceptance|"
                    r"handover|material|kualiti|kualitas|جودة|عيوب",
        "note": bi("Defect liability and acceptance clauses of the civil laws; commissioning punch items and handover "
                   "readiness from the commissioning register. Inspection-and-test plans and NCRs are not connected yet.",
                   "民法中的缺陷责任和验收条款；调试登记中的整改项和移交就绪度。检验试验计划和不合格报告尚未接入。"),
    },
    {
        "id": "schedule", "name": bi("Schedule & delay", "进度与工期"),
        "agents": ["progress", "briefing", "knowledge", "intake"], "project_data": True,
        "topics": {"delay", "extension of time", "programme", "liquidated damages", "suspension", "deadline"},
        "keywords": r"进度|工期|延误|延期|拖期|赶工|里程碑|节点|计划|schedule|delay|programme|milestone|"
                    r"extension of time|jadual|jadwal|تأخير|الجدول",
        "note": bi("Progress, schedule variance, next gate, cost forecast against budget and the effect of a requested "
                   "extension come from the project records; delay and extension-of-time rules from the clause library.",
                   "进度、工期偏差、下一个关口、预测成本与预算、顺延申请对工期的影响来自项目数据；延误和工期顺延规则来自条款库。"),
    },
    {
        "id": "environment", "name": bi("Environment", "环境保护"),
        "agents": ["knowledge", "compare"],
        "topics": {"EIA", "emissions", "dust", "noise", "waste", "scheduled waste", "hazardous waste", "wastewater",
                   "water pollution", "air pollution", "environmental licence", "environmental approval",
                   "environmental permit", "dewatering", "dredging", "land clearing", "open burning", "spoil disposal",
                   "silt", "drainage", "pollution", "reclamation", "borrow pit"},
        "keywords": r"环境|环保|环评|扬尘|噪音|噪声|废水|废弃物|排放|污染|environment|EIA|dust|noise|waste|emission|"
                    r"pollution|alam sekitar|lingkungan|البيئة",
        "note": bi("Environmental laws of Malaysia and Saudi Arabia.", "马来西亚和沙特的环境法条款。"),
    },
    {
        "id": "data", "name": bi("Data protection", "数据合规"),
        "agents": ["knowledge", "compare"],
        "topics": {"data protection", "privacy", "worker data", "consent", "lawful processing", "data security",
                   "data breach", "data protection officer", "DPO", "cross-border transfer", "data residency",
                   "sensitive data", "biometric", "DPIA", "data subject rights"},
        "keywords": r"数据|隐私|个人信息|跨境|data protection|privacy|personal data|PDPA|PDP|perlindungan data|البيانات",
        "note": bi("Personal data laws of Malaysia and Indonesia.", "马来西亚和印尼的个人数据保护法。"),
    },
    {
        "id": "railway", "name": bi("Railway interface & operations", "铁路接口与运营"),
        "agents": ["knowledge", "gates", "twin", "commissioning"],
        "topics": {"railway", "railway safety", "operating licence", "railway opening", "railway corridor",
                   "works near railway", "level crossing", "grade separation", "railway scheme", "railway permit",
                   "operations", "maintenance", "trespass", "obstruction", "accident investigation"},
        "keywords": r"铁路|轨道|地铁|平交道口|开通|运营|运维|railway|rail|metro|level crossing|operation|keretapi|kereta api|سكك",
        "note": bi("Railway acts of Malaysia and Indonesia; asset status, sensors and maintenance from the digital twin.",
                   "马来西亚和印尼的铁路法；资产状态、传感器和维护来自数字孪生。"),
    },
]
DOMAIN_IDS = [d["id"] for d in DOMAINS]
_DOMAIN_RE = {d["id"]: re.compile(d["keywords"], re.IGNORECASE) for d in DOMAINS}

# Questions about the assistant itself: what it is, what it can do, whether it
# can answer a kind of question.
CAPABILITY_RE = re.compile(
    r"你能|你会|你可以|能不能|能否|可不可以|是否(?:能|可以|支持)|支持(?:哪些|什么)|覆盖(?:哪些|什么)|有哪些能力|你是谁|你是什么|"
    r"自我介绍|介绍一下你|你的能力|你懂|能回答|能分析|能查|"
    r"\bcan you\b|are you able|do you (?:support|cover|know)|what can|who are you|your capabilit|"
    r"boleh(?:kah)? anda|bisakah|apa yang (?:anda|kamu) boleh|هل يمكنك|ماذا يمكنك|من أنت",
    re.IGNORECASE)
# "Can you answer / handle / cover X?" is about the assistant even when it names a country.
ABOUT_SELF_RE = re.compile(
    r"(?:你|您)?(?:能不能|能否|可不可以|能|可以|会不会|是否能)(?:回答|解答|处理|覆盖|支持)(?:.{0,24})(?:问题|方面|领域|吗|么|？|\?)|"
    r"(?:can|could) you (?:answer|handle|cover|analy[sz]e|deal with)|do you (?:cover|support|handle)|"
    r"boleh(?:kah)? anda (?:jawab|menjawab)|هل يمكنك (?:الإجابة|تحليل)", re.IGNORECASE)
# "analyse this contract" with no contract in the message.
REVIEW_RE = re.compile(r"(?:分析|审查|审核|审阅|看看|检查|review|analy[sz]e|check)\S{0,6}(?:这份|这个|我的|the|this|my)?\s*"
                       r"(?:合同|协议|contract|agreement)", re.IGNORECASE)


def detect_domains(text: str) -> list[str]:
    return [domain_id for domain_id, pattern in _DOMAIN_RE.items() if pattern.search(text or "")]


@lru_cache(maxsize=1)
def _counts() -> dict[str, dict[str, int]]:
    counts = {d["id"]: dict.fromkeys(COUNTRIES, 0) for d in DOMAINS}
    for row in load_clause_library():
        topics = set(row.get("topics") or [])
        for domain in DOMAINS:
            if topics & domain["topics"] and row["country"] in counts[domain["id"]]:
                counts[domain["id"]][row["country"]] += 1
    return counts


def level(domain_id: str, country: str) -> str:
    domain = next(d for d in DOMAINS if d["id"] == domain_id)
    count = _counts()[domain_id].get(country, 0)
    if domain.get("legal_only"):
        return "legal_only" if count else "none"
    return "covered" if count >= COVERED_MIN else "thin" if count else "none"


def coverage(lang: str) -> list[dict]:
    rows = []
    for domain in DOMAINS:
        counts = _counts()[domain["id"]]
        rows.append({
            "id": domain["id"], "name": localize(domain["name"], lang), "agents": domain["agents"],
            "note": localize(domain["note"], lang), "project_data": bool(domain.get("project_data")),
            "countries": {code: {"clauses": counts[code], "level": level(domain["id"], code)} for code in COUNTRIES},
        })
    return rows


@lru_cache(maxsize=1)
def library_stats() -> dict:
    rows = load_clause_library()
    return {
        "clauses": len(rows), "countries": len(COUNTRIES),
        "instruments": len({(r["country"], r["instrument"]) for r in rows}),
        "glossary_terms": sum(len(load_glossary(code)) for code in COUNTRIES),
    }


LEVEL_TEXT = {
    "covered": bi("covered", "有依据"), "thin": bi("thin", "较少"), "none": bi("none", "无"),
    "legal_only": bi("laws only, no technical provisions", "仅有法律，无技术条文"),
}

BOUNDARIES = [
    bi("Answers cite paraphrased clause summaries that need expert review; they are not legal advice.",
       "回答引用的是条款意译摘要，须专业复核，不构成法律意见。"),
    bi("Approval, execution, verification and closure stay with people; replies are drafts and are never sent.",
       "审批、执行、核验、关闭由人决定；回函只出草稿，不代发。"),
    bi("When the library has no clause, the assistant says so instead of answering from general knowledge.",
       "库中没有依据时如实说明，不凭常识作答。"),
]


def coverage_gaps(domain_ids: list[str], countries: list[str], lang: str) -> list[str]:
    """Sentences naming the domain/country cells this question falls into that the library cannot answer."""
    gaps = []
    for domain_id in domain_ids:
        domain = next(d for d in DOMAINS if d["id"] == domain_id)
        name = localize(domain["name"], lang)
        for code in countries or []:
            cell = level(domain_id, code)
            country = localize(COUNTRY_NAMES.get(code, {"en": code, "zh": code}), lang)
            if cell == "legal_only":
                gaps.append(localize(bi(
                    f"The library has no technical provisions of the {country} {name.lower()}; the sources below are "
                    "the laws around them and cannot give technical values.",
                    f"条款库没有{country}{name}的技术条文；下面的来源只是相关法律，不能给出具体技术数值。"), lang))
            elif cell == "none":
                gaps.append(localize(bi(f"The library has no {country} clause on {name.lower()}.",
                                        f"条款库没有{country}「{name}」方面的条款。"), lang))
    return gaps
