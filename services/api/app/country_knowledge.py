"""Country-pack registry and governed, jurisdiction-aware knowledge APIs.

Country packs route work to official sources and approval gates. They do not
turn a model response into legal advice: every pack is an operational index
that still requires project-specific confirmation by an authorized reviewer.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .i18n import bi, get_lang, localize
from .models import CountryPack, KnowledgeDocument, Project
from .retrieval import KnowledgeIndex

router = APIRouter(tags=["country-packs", "knowledge-fabric"])

LEGAL_DISCLAIMER = bi(
    "Operational source index for project planning; not legal advice. Confirm applicability, current revision and authority requirements with qualified local counsel or the responsible authority.",
    "用于项目策划的官方来源索引，不构成法律意见。须由合格的当地法律顾问或主管机关确认适用性、现行版本及审批要求。",
)


def _authority(code: str, name: str, scope: str, url: str) -> dict:
    return {"code": code, "name": name, "scope": scope, "url": url, "verification": "OFFICIAL_SOURCE"}


def _permit(code: str, name: str, authority: str, stages: list[str], gate: str, evidence: list[str]) -> dict:
    return {"code": code, "name": name, "authority": authority, "stages": stages, "gate": gate, "evidence": evidence, "applicability": "PROJECT_REVIEW_REQUIRED"}


COUNTRY_PACKS = {
    "MY": {
        "name": bi("Malaysia", "马来西亚"), "region": "APAC", "version": "2026.10.1", "languages": ["en", "ms", "zh"],
        "default_locale": "en-MY", "timezone": "Asia/Kuala_Lumpur", "currency": "MYR", "domains": ["rail", "highway", "bridge", "port", "building"],
        "authorities": [
            _authority("DOSH", "Department of Occupational Safety and Health", "occupational safety and health", "https://dosh.gov.my/"),
            _authority("CIDB", "Construction Industry Development Board Malaysia", "contractor, personnel and construction-industry registration", "https://www.cidb.gov.my/eng/"),
            _authority("LOCAL", "Local authority / OSC", "planning and building approvals", "https://www.malaysia.gov.my/"),
        ],
        "permits": [
            _permit("MY-CONTRACTOR", "CIDB contractor registration", "CIDB", ["tender", "mobilization", "construction"], "BEFORE_CONSTRUCTION", ["valid registration", "scope/category/grade", "project declaration"]),
            _permit("MY-PERSONNEL", "Construction personnel registration", "CIDB", ["mobilization", "construction"], "BEFORE_SITE_ACCESS", ["registration certificate", "recognized safety certificate", "work authorization"]),
            _permit("MY-OSH", "Project OSH applicability review", "DOSH", ["design", "mobilization", "construction", "commissioning"], "BEFORE_HIGH_RISK_WORK", ["risk assessment", "competent-person record", "inspection evidence"]),
            _permit("MY-LOCAL", "Planning / building / local approvals", "Local authority / OSC", ["feasibility", "design", "construction", "handover"], "AUTHORITY_GATE", ["submission register", "approved drawings", "conditions closeout"]),
        ],
        "topics": ["occupational safety", "contractor registration", "construction personnel", "local authority approvals", "environment", "workforce"],
        "glossary": {"working at height": {"ms": "kerja di tempat tinggi", "zh": "高处作业"}, "method statement": {"ms": "pernyataan kaedah", "zh": "施工方案"}, "non-conformance report": {"ms": "laporan ketidakpatuhan", "zh": "不符合项报告"}, "permit to work": {"ms": "permit untuk bekerja", "zh": "作业许可证"}},
        "data_policy": {"preferred_region": "apac", "external_model_default": "review-required", "restricted_data": "local-or-approved-region"},
    },
    "ID": {
        "name": bi("Indonesia", "印度尼西亚"), "region": "APAC", "version": "2026.10.1", "languages": ["id", "en"],
        "default_locale": "id-ID", "timezone": "Asia/Jakarta", "currency": "IDR", "domains": ["highway", "rail", "port", "building", "energy"],
        "authorities": [
            _authority("PUPR", "Ministry of Public Works", "public works and building requirements", "https://pu.go.id/"),
            _authority("OSS", "OSS Risk-Based Approach", "business licensing", "https://oss.go.id/"),
            _authority("LOCAL", "Regional government", "building and local approvals", "https://indonesia.go.id/"),
        ],
        "permits": [
            _permit("ID-NIB", "Business identification and risk-based licensing route", "OSS", ["market-entry", "tender", "mobilization"], "BEFORE_OPERATION", ["NIB", "risk classification", "sector licenses"]),
            _permit("ID-PBG", "Building approval applicability review", "Regional government / PUPR framework", ["design", "construction"], "BEFORE_BUILD", ["technical plan", "approval record", "licensed professional evidence"]),
            _permit("ID-SLF", "Function-worthiness certificate applicability review", "Regional government", ["commissioning", "handover", "operations"], "BEFORE_OCCUPANCY", ["as-built records", "inspection/testing", "operations readiness"]),
            _permit("ID-K3", "Construction safety and workforce compliance review", "PUPR / manpower authority", ["mobilization", "construction"], "BEFORE_HIGH_RISK_WORK", ["SMKK/K3 plan", "competency evidence", "inspection records"]),
        ],
        "topics": ["risk-based licensing", "building approval", "function-worthiness", "construction safety", "local content", "environment"],
        "glossary": {"building approval": {"id": "Persetujuan Bangunan Gedung (PBG)", "zh": "建筑审批"}, "function-worthiness certificate": {"id": "Sertifikat Laik Fungsi (SLF)", "zh": "功能适用证书"}, "occupational safety": {"id": "keselamatan dan kesehatan kerja", "zh": "职业安全健康"}},
        "data_policy": {"preferred_region": "apac", "external_model_default": "review-required", "restricted_data": "approved-region"},
    },
    "SA": {
        "name": bi("Saudi Arabia", "沙特阿拉伯"), "region": "MEA", "version": "2026.10.1", "languages": ["ar", "en"],
        "default_locale": "ar-SA", "timezone": "Asia/Riyadh", "currency": "SAR", "domains": ["rail", "metro", "highway", "airport", "building"],
        "authorities": [
            _authority("SBC", "Saudi Building Code Center", "building code", "https://sbc.gov.sa/en/Main/Pages/"),
            _authority("BALADY", "Balady", "municipal and construction licensing", "https://balady.gov.sa/"),
            _authority("MHRSD", "Ministry of Human Resources and Social Development", "labor and occupational safety", "https://www.hrsd.gov.sa/"),
        ],
        "permits": [
            _permit("SA-BUILD", "Construction license", "Balady / competent municipality", ["design", "construction"], "BEFORE_BUILD", ["licensed designer", "code-compliant documents", "license record"]),
            _permit("SA-SBC", "Saudi Building Code compliance", "SBC / competent authority", ["design", "construction", "commissioning"], "DESIGN_AND_INSPECTION_GATE", ["applicable code schedule", "design review", "inspection/test records"]),
            _permit("SA-OCCUPANCY", "Completion / occupancy approval route", "Balady / competent municipality", ["commissioning", "handover"], "BEFORE_USE", ["completion evidence", "as-built documents", "life-safety closeout"]),
            _permit("SA-WORKFORCE", "Workforce and occupational-safety applicability review", "MHRSD", ["mobilization", "construction", "operations"], "BEFORE_MOBILIZATION", ["work authorization", "competency evidence", "OSH controls"]),
        ],
        "topics": ["building code", "construction licensing", "municipal approvals", "occupational safety", "workforce", "fire and life safety"],
        "glossary": {"building permit": {"ar": "رخصة بناء", "zh": "施工许可证"}, "occupancy": {"ar": "إشغال", "zh": "投入使用"}, "method statement": {"ar": "بيان طريقة التنفيذ", "zh": "施工方案"}},
        "data_policy": {"preferred_region": "mea", "external_model_default": "review-required", "restricted_data": "approved-region"},
    },
    "AE": {
        "name": bi("United Arab Emirates", "阿拉伯联合酋长国"), "region": "MEA", "version": "2026.10.1", "languages": ["ar", "en"],
        "default_locale": "en-AE", "timezone": "Asia/Dubai", "currency": "AED", "domains": ["rail", "airport", "port", "highway", "building", "energy"],
        "authorities": [
            _authority("MOHRE", "Ministry of Human Resources and Emiratisation", "labor and occupational health and safety", "https://www.mohre.gov.ae/"),
            _authority("DCD", "Dubai Civil Defence", "fire and life safety", "https://www.dcd.gov.ae/"),
            _authority("LOCAL", "Competent emirate municipality / authority", "planning and construction licensing", "https://u.ae/"),
        ],
        "permits": [
            _permit("AE-BUILD", "Emirate-specific building permit route", "Competent local authority", ["design", "construction"], "BEFORE_BUILD", ["land/developer authority", "design NOCs", "permit record"]),
            _permit("AE-FIRE", "Fire and life-safety approval", "Civil Defence / competent authority", ["design", "construction", "commissioning"], "LIFE_SAFETY_GATE", ["approved fire strategy", "system tests", "completion certificate"]),
            _permit("AE-OHS", "Occupational health and safety applicability review", "MOHRE / competent local authority", ["mobilization", "construction", "operations"], "BEFORE_MOBILIZATION", ["OHS management plan", "qualified personnel", "training and inspection records"]),
            _permit("AE-NOC", "Utility and stakeholder NOC register", "Relevant utilities / asset owners", ["design", "construction"], "INTERFACE_GATE", ["NOC matrix", "approved diversions", "closeout evidence"]),
        ],
        "topics": ["emirate-specific licensing", "fire and life safety", "occupational health", "worker welfare", "NOC management", "environment"],
        "glossary": {"no objection certificate": {"ar": "شهادة عدم ممانعة", "zh": "无异议证明"}, "fire and life safety": {"ar": "السلامة من الحريق وسلامة الأرواح", "zh": "消防与生命安全"}, "permit to work": {"ar": "تصريح عمل", "zh": "作业许可证"}},
        "data_policy": {"preferred_region": "mea", "external_model_default": "review-required", "restricted_data": "approved-region"},
    },
}


OFFICIAL_KNOWLEDGE = [
    ("MY-CIDB-CONTRACTOR", "MY", "Compliance & Permits", "REGULATION_INDEX", "CIDB Malaysia", "2026.10", "https://www.cidb.gov.my/eng/contractor-registration/", ["tender", "mobilization", "construction"], ["contractor", "registration", "CIDB"], "CIDB contractor registration official source", "Official registration entry point and evidence checklist for contractor eligibility and project declaration.", "CIDB 承包商注册官方来源", "承包商准入、注册范围及项目申报证据的官方入口。"),
    ("MY-CIDB-PERSONNEL", "MY", "Workforce", "REGULATION_INDEX", "CIDB Malaysia", "2026.10", "https://www.cidb.gov.my/eng/construction-personnel-registration/", ["mobilization", "construction"], ["personnel", "competency", "site access"], "CIDB construction personnel registration", "Official source for personnel registration, recognized safety certificates and site-access evidence.", "CIDB 建筑人员注册", "人员注册、安全证书及现场准入证据的官方来源。"),
    ("MY-DOSH-OSHA", "MY", "HSE", "LAW_INDEX", "DOSH Malaysia", "Reprint 2024", "https://dosh.gov.my/wp-content/uploads/2025/01/Occupational-Safety-and-Health-Act-1994-Act-514_Reprint-Version-1.6.2024_English.pdf", ["design", "mobilization", "construction", "commissioning", "operations"], ["OSH", "risk", "competent person"], "Malaysia Occupational Safety and Health Act source", "Official Act 514 source index. Project teams must confirm applicable duties and current subsidiary requirements.", "马来西亚职业安全与健康法来源", "Act 514 官方来源索引；项目团队须确认具体义务及现行附属要求。"),
    ("ID-OSS-RBA", "ID", "Compliance & Permits", "REGULATION_INDEX", "OSS Indonesia", "Current portal", "https://oss.go.id/", ["market-entry", "tender", "mobilization", "operations"], ["NIB", "risk-based licensing", "business"], "Indonesia OSS risk-based licensing", "Official portal for NIB and risk-based business-licensing routing; exact obligations depend on business classification.", "印度尼西亚 OSS 风险分级许可", "NIB 与风险分级经营许可的官方入口；具体义务取决于业务分类。"),
    ("ID-PBG-SLF", "ID", "Compliance & Permits", "REGULATION_INDEX", "Ministry of Public Works / regional authority", "Current framework", "https://pu.go.id/", ["design", "construction", "commissioning", "handover"], ["PBG", "SLF", "building"], "Indonesia PBG / SLF source route", "Authority-source route for building approval and function-worthiness applicability; local implementation must be confirmed.", "印度尼西亚 PBG / SLF 来源路径", "建筑审批与功能适用性审查的主管机关路径；须确认地方实施要求。"),
    ("SA-SBC-LAW", "SA", "Engineering Standards", "CODE_INDEX", "Saudi Building Code Center", "Current portal", "https://sbc.gov.sa/En/BuildingCode/Lists/SBCRuglationsSystems/Attachments/14/law.pdf", ["design", "construction", "commissioning", "operations"], ["SBC", "design", "inspection"], "Saudi Building Code Application Law", "Official source index for code applicability across design, construction, commissioning and maintenance.", "沙特建筑规范实施法", "覆盖设计、施工、调试与维护阶段规范适用性的官方来源索引。"),
    ("SA-BALADY-LICENSE", "SA", "Compliance & Permits", "PORTAL_INDEX", "Balady", "Current portal", "https://smart-guide.balady.gov.sa/", ["design", "construction", "handover"], ["construction license", "municipality", "occupancy"], "Saudi construction licensing route", "Official municipal smart-guide route for determining construction-license services and requirements.", "沙特施工许可路径", "用于判断施工许可服务及要求的官方市政智能指南入口。"),
    ("AE-DCD-FIRE", "AE", "Fire & Life Safety", "CODE_INDEX", "Dubai Civil Defence", "2018 source portal", "https://www.dcd.gov.ae/portal/en/item/82-uaeslscp.jsp", ["design", "construction", "commissioning", "operations"], ["fire", "life safety", "civil defence"], "UAE Fire and Life Safety Code source", "Official Civil Defence code source; the competent emirate and current approval route must be confirmed for each project.", "阿联酋消防与生命安全规范来源", "民防官方规范来源；每个项目须确认主管酋长国及现行审批路径。"),
    ("AE-MOHRE-OHS", "AE", "HSE", "REGULATION_INDEX", "MOHRE", "Current guidance", "https://www.mohre.gov.ae/assets/download/93e5ccb/Occupational%20Health%20and%20Safety%20System%20in%20the%20UAE%20-%20EN_638983811445415191.pdf.aspx", ["mobilization", "construction", "operations"], ["OHS", "worker welfare", "qualified officer"], "UAE occupational health and safety source", "Official MOHRE guidance index for workplace OHS controls; local-system requirements may also apply.", "阿联酋职业健康安全来源", "MOHRE 工作场所职业健康安全官方指南索引；还可能适用地方体系要求。"),
]


# Synthetic project-level contract procedures (not official sources). They give
# variation / change-request correspondence something relevant to cite instead
# of the nearest unrelated record.
PROJECT_PROCEDURES = [
    (
        "CTR-A / Clause 13", "Contract", "CONTRACT_CLAUSE", ["construction", "commissioning"], ["variation", "change order", "instruction"],
        "Synthetic Contract Conditions - Variations", "模拟合同条件 - 变更",
        "Synthetic clause: variations are valid only when instructed in writing; requests must be substantiated before valuation.",
        "模拟条款：变更须有书面指令方为有效；变更申请须先提交证明材料方可计价。",
        "A variation is valid only when instructed in writing by the Contractor's Representative. A subcontractor request for a variation "
        "must state the instruction reference, the changed scope with drawings and quantities, a rate build-up based on the Bill of Quantities "
        "and any time impact, and must be submitted within 28 days of the event. A request without a written instruction is registered as a "
        "claim for evaluation and is not an accepted variation; no cost or time is agreed until valuation is complete.",
        "变更须经承包商代表书面指令方为有效。分包商提出变更申请时，须说明指令编号、变更范围（附图纸与工程量）、以工程量清单为基础的单价分析及工期影响，"
        "并须在事件发生后 28 天内提交。没有书面指令的申请将登记为待评估的索赔，不视为已接受的变更；计价完成前不确认任何费用或工期。",
    ),
    (
        "PROC-VO-02", "Project Procedure", "PROCEDURE", ["construction", "commissioning"], ["variation", "valuation", "correspondence"],
        "Synthetic Variation Order Procedure", "模拟变更令处理程序",
        "Synthetic procedure for registering, reviewing, valuing and answering variation requests.",
        "关于变更申请登记、审查、计价与答复的模拟程序。",
        "On receipt of a variation request: register it, acknowledge receipt in writing within 7 days without accepting entitlement, check "
        "whether a written instruction or design change exists, obtain an engineering review of the technical necessity, have the quantity "
        "surveyor value it against contract rates, and obtain project manager approval before any acknowledgement of cost or time. The "
        "acknowledgement letter should list missing substantiation and reserve the contractor's rights.",
        "收到变更申请后：登记；在 7 天内书面确认收悉，但不承认任何权利主张；核查是否存在书面指令或设计变更；由工程部门审查技术必要性；"
        "由造价人员按合同单价计价；在确认任何费用或工期前须经项目经理批准。确认函应列明缺失的证明材料，并保留承包商的合同权利。",
    ),
]


def _seed_project_procedures(db: Session) -> None:
    for ref, category, document_type, stages, tags, title_en, title_zh, summary_en, summary_zh, content_en, content_zh in PROJECT_PROCEDURES:
        content = bi(content_en, content_zh)
        values = dict(
            title=bi(title_en, title_zh), category=bi(category, {"Contract": "合同", "Project Procedure": "项目程序"}[category]),
            jurisdiction=bi("Project", "项目"), language=bi("English", "英语"), source_ref=ref, content=content,
            summary=bi(summary_en, summary_zh), country_code=None, document_type=document_type, authority=None, version="1.0",
            status="CURRENT", effective_date=None, review_due=None, source_url=None, content_hash=_digest(content, ref, "1.0"),
            tags=tags, lifecycle_stages=stages, confidentiality="PUBLIC", updated_at=datetime(2026, 10, 15),
        )
        document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == ref))
        if document is None:
            db.add(KnowledgeDocument(**values))
        else:
            for key, value in values.items():
                setattr(document, key, value)


def _digest(content: dict, source_ref: str, version: str) -> str:
    payload = json.dumps([content, source_ref, version], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def seed_country_knowledge(db: Session) -> None:
    for code, config in COUNTRY_PACKS.items():
        pack = db.get(CountryPack, code)
        values = dict(
            name=config["name"], region=config["region"], version=config["version"], status="REVIEWED_DEMO",
            languages=config["languages"], default_locale=config["default_locale"], timezone=config["timezone"], currency=config["currency"], units="metric",
            supported_domains=config["domains"], authorities=config["authorities"], permit_catalog=config["permits"], compliance_topics=config["topics"], glossary=config["glossary"],
            data_policy=config["data_policy"], approval_policy={"external_correspondence": "project_manager", "contractual_position": "project_manager+evidence", "critical_hse_action": "human_mandatory", "legal_interpretation": "qualified_local_review"},
            source_registry=config["authorities"], disclaimer=LEGAL_DISCLAIMER,
            reviewed_at=datetime(2026, 10, 14),
        )
        if pack is None:
            db.add(CountryPack(code=code, **values))
        else:
            for key, value in values.items():
                setattr(pack, key, value)

    # Upgrade legacy records without changing their authored content.
    for doc in db.scalars(select(KnowledgeDocument)).all():
        if not doc.country_code and doc.source_ref.startswith("MY-"):
            doc.country_code = "MY"
        if not doc.content_hash:
            doc.content_hash = _digest(doc.content, doc.source_ref, doc.version or "1.0")
        if not doc.tags:
            doc.tags = []
        if not doc.lifecycle_stages:
            doc.lifecycle_stages = ["construction"]

    for ref, country, category, document_type, authority, version, url, stages, tags, title_en, summary_en, title_zh, summary_zh in OFFICIAL_KNOWLEDGE:
        document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == ref))
        content = bi(
            f"Official-source index for {title_en}. Verify the live source, project applicability and current revision before relying on it.",
            f"{title_zh}的官方来源索引。使用前须核验实时来源、项目适用性与现行版本。",
        )
        values = dict(
            title=bi(title_en, title_zh), category=bi(category, {"Compliance & Permits":"合规与许可", "Workforce":"人力资源", "HSE":"健康安全环保", "Engineering Standards":"工程标准", "Fire & Life Safety":"消防与生命安全"}.get(category, category)),
            jurisdiction=bi(country, country), language=bi("Official source language", "官方来源语言"), source_ref=ref, content=content, summary=bi(summary_en, summary_zh),
            country_code=country, document_type=document_type, authority=authority, version=version, status="CURRENT", effective_date=None, review_due="2027-04-01", source_url=url,
            content_hash=_digest(content, ref, version), tags=tags, lifecycle_stages=stages, confidentiality="PUBLIC", updated_at=datetime(2026, 10, 14),
        )
        if document is None:
            db.add(KnowledgeDocument(**values))
        else:
            for key, value in values.items():
                setattr(document, key, value)
    _seed_project_procedures(db)
    db.commit()


def _pack_payload(pack: CountryPack, db: Session, include_detail: bool = False) -> dict:
    project_count = db.scalar(select(func.count(Project.id)).where(Project.country_code == pack.code)) or 0
    knowledge_count = db.scalar(select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.country_code == pack.code)) or 0
    required = [pack.languages, pack.authorities, pack.permit_catalog, pack.compliance_topics, pack.glossary, pack.source_registry, pack.data_policy, pack.approval_policy]
    payload = {
        "code": pack.code, "name": pack.name, "region": pack.region, "version": pack.version, "status": pack.status,
        "languages": pack.languages, "default_locale": pack.default_locale, "timezone": pack.timezone, "currency": pack.currency, "units": pack.units,
        "project_count": project_count, "knowledge_count": knowledge_count, "permit_count": len(pack.permit_catalog), "authority_count": len(pack.authorities),
        "coverage_percent": round(sum(bool(item) for item in required) / len(required) * 100), "reviewed_at": pack.reviewed_at.isoformat(), "disclaimer": pack.disclaimer,
    }
    if include_detail:
        projects = db.scalars(select(Project).where(Project.country_code == pack.code).order_by(Project.id)).all()
        payload.update({"supported_domains": pack.supported_domains, "authorities": pack.authorities, "permit_catalog": pack.permit_catalog, "compliance_topics": pack.compliance_topics, "glossary": pack.glossary, "data_policy": pack.data_policy, "approval_policy": pack.approval_policy, "source_registry": pack.source_registry, "projects": [{"id": p.id, "code": p.code, "name": p.name, "domain": p.domain, "status": p.status} for p in projects]})
    return payload


@router.get("/country-packs")
def country_packs(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows = db.scalars(select(CountryPack).order_by(CountryPack.region, CountryPack.code)).all()
    return localize([_pack_payload(row, db) for row in rows], lang)


@router.get("/country-packs/{code}")
def country_pack(code: str, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    pack = db.get(CountryPack, code.upper())
    if not pack:
        raise HTTPException(404, "Country pack not found")
    return localize(_pack_payload(pack, db, include_detail=True), lang)


@router.get("/country-packs/{code}/applicability")
def pack_applicability(code: str, stage: str | None = None, domain: str | None = None, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    pack = db.get(CountryPack, code.upper())
    if not pack:
        raise HTTPException(404, "Country pack not found")
    permits = [item for item in pack.permit_catalog if not stage or stage.lower() in [value.lower() for value in item.get("stages", [])]]
    return localize({"country_code": pack.code, "stage": stage, "domain": domain, "applicable_items": permits, "count": len(permits), "authority_review_required": True, "disclaimer": pack.disclaimer}, lang)


def _document_payload(doc: KnowledgeDocument, score: float | None = None) -> dict:
    payload = {
        "id": doc.id, "title": doc.title, "category": doc.category, "jurisdiction": doc.jurisdiction, "country_code": doc.country_code,
        "language": doc.language, "source_ref": doc.source_ref, "summary": doc.summary, "document_type": doc.document_type, "authority": doc.authority,
        "version": doc.version, "status": doc.status, "effective_date": doc.effective_date, "review_due": doc.review_due, "source_url": doc.source_url,
        "content_hash": doc.content_hash, "tags": doc.tags, "lifecycle_stages": doc.lifecycle_stages, "confidentiality": doc.confidentiality,
        "updated_at": doc.updated_at.isoformat(),
        "citation": {"document_id": doc.id, "source_ref": doc.source_ref, "version": doc.version, "country_code": doc.country_code, "content_hash": doc.content_hash, "source_url": doc.source_url},
    }
    if score is not None:
        payload["relevance"] = round(score, 4)
    return payload


@router.get("/knowledge/stats")
def knowledge_stats(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    docs = db.scalars(select(KnowledgeDocument)).all()
    countries = sorted({doc.country_code for doc in docs if doc.country_code})
    categories = Counter(str((doc.category or {}).get(lang) or (doc.category or {}).get("en") or doc.category) for doc in docs)
    current = sum(doc.status == "CURRENT" for doc in docs)
    sourced = sum(bool(doc.source_url or doc.source_ref) for doc in docs)
    return {"documents": len(docs), "countries": len(countries), "current": current, "official_or_referenced": sourced, "traceability_percent": round(sourced / max(len(docs), 1) * 100), "categories": [{"name": name, "count": count} for name, count in categories.most_common()], "country_codes": countries}


@router.get("/knowledge/search")
def knowledge_search(
    q: str = Query(default="", max_length=500), country_code: str | None = None, category: str | None = None,
    stage: str | None = None, status: str = "CURRENT", limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db), lang: str = Depends(get_lang),
):
    docs = list(db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())))
    filtered = [doc for doc in docs if (not country_code or doc.country_code == country_code.upper()) and (not status or doc.status == status.upper()) and (not category or category.lower() in json.dumps(doc.category, ensure_ascii=False).lower()) and (not stage or stage.lower() in [item.lower() for item in (doc.lifecycle_stages or [])])]
    if q.strip():
        ranked = KnowledgeIndex(filtered).search(q, top_k=limit)
    else:
        ranked = [(1.0, doc) for doc in filtered[:limit]]
    facets = {"countries": Counter(doc.country_code or "GLOBAL" for doc in filtered), "types": Counter(doc.document_type for doc in filtered), "stages": Counter(stage_name for doc in filtered for stage_name in (doc.lifecycle_stages or []))}
    result = {
        "query": q, "filters": {"country_code": country_code, "category": category, "stage": stage, "status": status}, "total": len(ranked),
        "results": [_document_payload(doc, score) for score, doc in ranked],
        "facets": {name: [{"value": value, "count": count} for value, count in values.most_common()] for name, values in facets.items()},
        "retrieval": {"method": "deterministic-tfidf", "jurisdiction_aware": True, "version_aware": True, "authority_review_required": True},
    }
    return localize(result, lang)


@router.get("/knowledge/{document_id}")
def knowledge_document(document_id: int, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    doc = db.get(KnowledgeDocument, document_id)
    if not doc:
        raise HTTPException(404, "Knowledge document not found")
    payload = _document_payload(doc)
    payload["content"] = doc.content
    return localize(payload, lang)
