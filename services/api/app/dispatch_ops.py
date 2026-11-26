"""Dispatcher sub-agents over project operations data (lifecycle coverage).

- ``twin``: an asset's status, health, sensors and maintenance from the digital twin;
- ``commissioning``: test packs, open punch items, document completeness and handover readiness;
- ``precedents``: earlier work orders like this one, closed ones first;
- ``briefing``: what needs attention in a project today, across work orders,
  approvals, sensor warnings, maintenance, commissioning and schedule;
- ``contract_review``: a first-pass review of pasted contract clauses.

All are read-only. They wrap data and tools the platform already has (the
twin, commissioning register, case store and the agent organization's
precedent search); they invent no values and say when a project has no data.
"""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select

from .assistant import _hit_payload, search_knowledge
from .contract_review import MIN_REVIEW_LENGTH, review
from .dispatcher import Dispatch, Step, StepFailed, _t, focus_countries
from .domain import PROJECT_INTELLIGENCE
from .i18n import localize
from .intake import detect_countries
from .models import Approval, Case, CommissioningItem, MaintenanceRecord, Project, TwinObject, TwinSensor
from .retrieval import tokenize_bigrams
from .models import utc_now

RESOLVED_STATUSES = {"CLOSED", "VERIFIED", "RESOLVED", "EXECUTED"}
OPEN_STATUSES_EXCLUDED = RESOLVED_STATUSES | {"REJECTED", "CANCELLED"}
MAX_PRECEDENTS = 3
MIN_SIMILARITY = 0.3   # share of the question's topic terms a case must contain
READY_FOR_HANDOVER = 95.0
MAINTENANCE_WINDOW_DAYS = 7
MAX_BRIEF_ITEMS = 6
RISK_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_ALERT_QUESTION_RE = re.compile(r"告警|报警|预警|超限|alarm|alert|warning|amaran|peringatan|إنذار", re.IGNORECASE)
# Question words that say nothing about the topic of a precedent search.
_PRECEDENT_FILLER_RE = re.compile(r"以前|之前|过去|历史上?|有没有|有无|类似|相似|的|案例|工单|案子|先例|类案|怎么|如何|处理|当时|吗|呢|[？?。，,]|"
                                  r"\b(?:any|similar|previous|past|before|cases?|work orders?|precedents?|how|was|were|handled|did|we)\b",
                                  re.IGNORECASE)
_ELEMENT_RE = re.compile(r"\b([PS]\d{1,3}|ST\d{2}|V\d{1,3}|BRG\d{1,3}[A-Z]?|AHU\d{2})\b", re.IGNORECASE)


def _accessible(run: Dispatch, project: Project) -> bool:
    return run.principal.can_access_project(project.id) and (
        "platform_admin" in run.principal.roles or project.organization_id == run.principal.organization_id)


def projects_in_scope(step: Step, run: Dispatch, db) -> list[Project]:
    """The named project, else the projects of the named (or focused) countries, else all the user can see."""
    project_id = step.project_id or run.payload.project_id
    text = f"{step.query} {run.payload.message}"
    projects = [p for p in db.scalars(select(Project).order_by(Project.id)) if _accessible(run, p)]
    if project_id:
        return [p for p in projects if p.id == project_id]
    named = [p for p in projects if p.code.upper() in text.upper()]
    if named:
        return named
    countries = detect_countries(step.query) or detect_countries(run.payload.message) or focus_countries(run)
    if countries:
        return [p for p in projects if (p.country_code or "").upper() in countries]
    return projects


def _name(obj, lang: str) -> str:
    return localize(obj.name, lang) if isinstance(obj.name, dict) else str(obj.name)


# --- twin ----------------------------------------------------------------------

def _sensor_view(sensor: TwinSensor) -> dict:
    level = ("CRITICAL" if sensor.latest_value >= sensor.threshold_critical
             else "WARNING" if sensor.latest_value >= sensor.threshold_warning else "NORMAL")
    return {"id": sensor.id, "twin_id": sensor.twin_id, "type": sensor.sensor_type, "unit": sensor.unit,
            "value": sensor.latest_value, "warning": sensor.threshold_warning, "critical": sensor.threshold_critical,
            "level": level}


async def agent_twin(step: Step, run: Dispatch, db) -> dict:
    lang = run.lang
    projects = projects_in_scope(step, run, db)
    if not projects:
        raise StepFailed(_t(lang, "No project in scope.", "没有可查看的项目。"))
    ids = [p.id for p in projects]
    objects = list(db.scalars(select(TwinObject).where(TwinObject.project_id.in_(ids))))
    if not objects:
        return {"summary": _t(lang, "These projects have no digital twin yet.", "这些项目还没有数字孪生数据。"),
                "data": {"assets": [], "project_ids": ids}}
    text = f"{step.query} {run.payload.message}".upper()
    tokens = {m.upper() for m in _ELEMENT_RE.findall(text)}
    wanted = [o for o in objects if any(o.id.upper().endswith("-" + t) or o.id.upper().endswith(t) for t in tokens)]
    sensors = {s.id: s for s in db.scalars(select(TwinSensor).where(TwinSensor.twin_id.in_([o.id for o in objects])))}
    work = list(db.scalars(select(MaintenanceRecord).where(MaintenanceRecord.twin_id.in_([o.id for o in objects]))))
    focus = wanted or [o for o in objects if o.status not in {"ACTIVE", "INSTALLED", "OPERATING", "COMPLETE"}]
    assets = []
    for obj in focus[:8]:
        own_sensors = [_sensor_view(s) for s in sensors.values() if s.twin_id == obj.id]
        own_work = [{"id": m.id, "type": m.work_type, "status": m.status, "priority": m.priority,
                     "due_at": m.due_at.date().isoformat(), "description": localize(m.description, lang)}
                    for m in work if m.twin_id == obj.id and m.status not in {"DONE", "CLOSED"}]
        assets.append({"id": obj.id, "name": _name(obj, lang), "type": obj.object_type, "status": obj.status,
                       "stage": obj.lifecycle_stage, "health": obj.health_score, "progress": obj.progress,
                       "sensors": own_sensors, "maintenance": own_work})
    scope = {o.id for o in wanted} if wanted else {o.id for o in objects}
    alerts = [view for s in sensors.values() if s.twin_id in scope and (view := _sensor_view(s))["level"] != "NORMAL"]
    if tokens and not wanted:
        summary = _t(lang, f"No twin element matches {', '.join(sorted(tokens))}.",
                     f"数字孪生中没有与 {'、'.join(sorted(tokens))} 对应的构件。")
    elif not wanted and _ALERT_QUESTION_RE.search(text):
        names = {o.id: _name(o, lang) for o in objects}
        summary = (_t(lang, f"{len(alerts)} sensor alert(s): ", f"传感器告警 {len(alerts)} 条：") + "；".join(
            _t(lang, f"{names.get(a['twin_id'], a['twin_id'])} {a['type']} {a['value']}{a['unit']} (warning {a['warning']})",
               f"{names.get(a['twin_id'], a['twin_id'])} {a['type']} {a['value']}{a['unit']}（预警值 {a['warning']}）") for a in alerts)
                   ) if alerts else _t(lang, "No sensor above its warning threshold.", "没有传感器超过预警值。")
    else:
        lines = [_t(lang, f"{a['name']}: {a['status']}, health {a['health']:.0f}, progress {a['progress']:.0f}%",
                    f"{a['name']}：{a['status']}，健康度 {a['health']:.0f}，进度 {a['progress']:.0f}%") for a in assets]
        summary = "；".join(lines) if lang == "zh" else "; ".join(lines)
        open_work = [m for a in assets for m in a["maintenance"]]
        if wanted and open_work:
            summary += _t(lang, ". Open maintenance: ", "。未完成维护：") + "、".join(
                f"{m['id']} {m['description']}（{m['due_at']}）" if lang == "zh" else f"{m['id']} {m['description']} ({m['due_at']})"
                for m in open_work)
        if alerts:
            summary += _t(lang, f". {len(alerts)} sensor alert(s): ", f"。传感器告警 {len(alerts)} 条：") + "、".join(
                f"{a['id']} {a['value']}{a['unit']}" for a in alerts)
    return {"summary": summary, "data": {"assets": assets, "alerts": alerts, "project_ids": ids,
                                         "matched": [o.id for o in wanted]}}


# --- commissioning -------------------------------------------------------------

async def agent_commissioning(step: Step, run: Dispatch, db) -> dict:
    lang = run.lang
    projects = projects_in_scope(step, run, db)
    ids = [p.id for p in projects]
    rows = db.execute(select(CommissioningItem, TwinObject).join(TwinObject, CommissioningItem.twin_id == TwinObject.id)
                      .where(TwinObject.project_id.in_(ids))).all() if ids else []
    items = [{"id": item.id, "system": localize(item.system, lang), "asset": _name(obj, lang), "test_pack": item.test_pack,
              "stage": item.stage, "punch_open": item.punch_open, "documents": item.document_completeness,
              "readiness": item.readiness,
              "ready": item.readiness >= READY_FOR_HANDOVER and item.punch_open == 0} for item, obj in rows]
    if not items:
        return {"summary": _t(lang, "No commissioning register for these projects.", "这些项目没有调试登记数据。"),
                "data": {"items": [], "project_ids": ids}}
    blocked = [i for i in items if not i["ready"]]
    punch = sum(i["punch_open"] for i in items)
    summary = _t(
        lang,
        f"{len(items)} systems in commissioning; {len(blocked)} not ready for handover, {punch} punch items open. "
        + "; ".join(f"{i['system']} {i['readiness']:.0f}% ({i['punch_open']} open)" for i in blocked[:5]),
        f"调试中系统 {len(items)} 个，其中 {len(blocked)} 个尚不具备移交条件，未关闭整改项 {punch} 项。"
        + "；".join(f"{i['system']} 就绪度 {i['readiness']:.0f}%（整改 {i['punch_open']} 项）" for i in blocked[:5]))
    return {"summary": summary, "data": {"items": items, "project_ids": ids, "ready_threshold": READY_FOR_HANDOVER}}


# --- precedents ----------------------------------------------------------------

def _scoped_cases(run: Dispatch, db):
    stmt = select(Case)
    if "platform_admin" not in run.principal.roles:
        stmt = stmt.where(Case.organization_id == run.principal.organization_id)
    if not run.principal.has_org_wide_project_access():
        stmt = stmt.where(Case.project_id.in_(run.principal.project_ids))
    return stmt


async def agent_precedents(step: Step, run: Dispatch, db) -> dict:
    lang = run.lang
    base = step.query or run.payload.message
    upstream_case = None
    for index in step.depends_on:
        upstream_case = (run.results.get(index) or {}).get("case_id") or upstream_case
    exclude = {upstream_case} if upstream_case else set()
    if upstream_case and (case := db.get(Case, upstream_case)) is not None:
        base = " ".join([localize(case.title, "zh"), localize(case.title, "en"), localize(case.description, "en"), base])
    # Match on the topic words only, and score by how much of the topic a case covers.
    own = set(tokenize_bigrams(_PRECEDENT_FILLER_RE.sub(" ", base)))
    scored = []
    for case in db.scalars(_scoped_cases(run, db)):
        if case.id in exclude:
            continue
        theirs = set(tokenize_bigrams(" ".join(localize(case.title, l) + " " + localize(case.description, l) for l in ("en", "zh"))))
        if own and theirs and (similarity := len(own & theirs) / len(own)) >= MIN_SIMILARITY:
            scored.append((case.status in RESOLVED_STATUSES, similarity, case))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    rows = [{"case_id": c.id, "title": localize(c.title, lang), "type": localize(c.type, lang), "risk": c.risk,
             "status": c.status, "resolved": resolved, "similarity": round(s, 3)} for resolved, s, c in scored[:MAX_PRECEDENTS]]
    closed = [r for r in rows if r["resolved"]]
    if not rows:
        summary = _t(lang, "No similar work order found.", "没有找到相似的工单。")
    elif not closed:
        summary = _t(lang, "No closed precedent yet; similar open work orders: ", "暂无已办结的相似案例；在办的相似工单：") + \
            "、".join(f"{r['case_id']}（{r['title']}）" if lang == "zh" else f"{r['case_id']} ({r['title']})" for r in rows)
    else:
        summary = _t(lang, "Closed precedents: ", "已办结的相似案例：") + "、".join(r["case_id"] for r in closed)
    return {"summary": summary, "refs": [r["case_id"] for r in rows],
            "data": {"precedents": rows, "excluded": sorted(exclude)}}


# --- briefing ------------------------------------------------------------------

async def agent_briefing(step: Step, run: Dispatch, db) -> dict:
    lang = run.lang
    projects = projects_in_scope(step, run, db)
    if not projects:
        raise StepFailed(_t(lang, "No project in scope.", "没有可查看的项目。"))
    ids = [p.id for p in projects]
    cases = [c for c in db.scalars(_scoped_cases(run, db).where(Case.project_id.in_(ids)))
             if c.status not in OPEN_STATUSES_EXCLUDED]
    cases.sort(key=lambda c: (RISK_ORDER.get(c.risk, 9), c.created_at), reverse=False)
    approvals = list(db.scalars(select(Approval).join(Case, Approval.case_id == Case.id)
                                .where(Approval.status == "PENDING", Case.project_id.in_(ids))))
    objects = {o.id: o for o in db.scalars(select(TwinObject).where(TwinObject.project_id.in_(ids)))}
    alerts = [_sensor_view(s) for s in db.scalars(select(TwinSensor).where(TwinSensor.twin_id.in_(list(objects))))] if objects else []
    alerts = [a for a in alerts if a["level"] != "NORMAL"]
    horizon = utc_now().replace(tzinfo=None) + timedelta(days=MAINTENANCE_WINDOW_DAYS)
    due = [m for m in db.scalars(select(MaintenanceRecord).where(MaintenanceRecord.twin_id.in_(list(objects))))
           if m.status not in {"DONE", "CLOSED"} and m.due_at.replace(tzinfo=None) <= horizon] if objects else []
    blocked = [i for i, _ in db.execute(select(CommissioningItem, TwinObject).join(TwinObject, CommissioningItem.twin_id == TwinObject.id)
                                        .where(TwinObject.project_id.in_(ids))).all()
               if not (i.readiness >= READY_FOR_HANDOVER and i.punch_open == 0)]
    schedule = []
    for project in projects:
        info = PROJECT_INTELLIGENCE.get(project.id, {})
        if info:
            schedule.append(localize({"code": project.code, "variance": info.get("schedule_variance"),
                                      "next_gate": info.get("next_gate"), "gate_date": info.get("gate_date")}, lang))
    items = []
    for case in cases[:MAX_BRIEF_ITEMS]:
        items.append({"kind": "case", "ref": case.id, "risk": case.risk,
                      "text": f"{localize(case.title, lang)}（{localize(case.deadline, lang)}）" if lang == "zh"
                      else f"{localize(case.title, lang)} ({localize(case.deadline, lang)})"})
    for alert in alerts:
        items.append({"kind": "sensor", "ref": alert["id"], "risk": "HIGH" if alert["level"] == "CRITICAL" else "MEDIUM",
                      "text": _t(lang, f"{alert['type']} {alert['value']}{alert['unit']} above warning {alert['warning']}",
                                 f"{alert['type']} {alert['value']}{alert['unit']}，超过预警值 {alert['warning']}")})
    for record in due:
        items.append({"kind": "maintenance", "ref": record.id, "risk": record.priority,
                      "text": _t(lang, f"{localize(record.description, lang)} due {record.due_at.date().isoformat()}",
                                 f"{localize(record.description, lang)}，{record.due_at.date().isoformat()} 到期")})
    for row in schedule:
        if (row["variance"] or 0) < 0:
            items.append({"kind": "schedule", "ref": row["code"], "risk": "MEDIUM",
                          "text": _t(lang, f"{row['code']} {abs(row['variance'])} days behind; next gate {row['next_gate']} {row['gate_date']}",
                                     f"{row['code']} 落后 {abs(row['variance'])} 天；下一关口 {row['next_gate']}（{row['gate_date']}）")})
    codes = "、".join(p.code for p in projects) if lang == "zh" else ", ".join(p.code for p in projects)
    summary = _t(
        lang,
        f"{codes}: {len(cases)} open work orders, {len(approvals)} approvals waiting, {len(alerts)} sensor alerts, "
        f"{len(due)} maintenance jobs due in {MAINTENANCE_WINDOW_DAYS} days, {len(blocked)} systems not ready for handover.",
        f"{codes}：在办工单 {len(cases)} 个，待审批 {len(approvals)} 项，传感器告警 {len(alerts)} 条，"
        f"{MAINTENANCE_WINDOW_DAYS} 天内到期维护 {len(due)} 项，未具备移交条件的系统 {len(blocked)} 个。")
    return {"summary": summary, "refs": [c.id for c in cases[:MAX_BRIEF_ITEMS]],
            "data": {"project_ids": ids, "items": items, "schedule": schedule,
                     "counts": {"cases": len(cases), "approvals": len(approvals), "alerts": len(alerts),
                                "maintenance_due": len(due), "commissioning_blocked": len(blocked)}}}


# --- contract review -----------------------------------------------------------

async def agent_contract_review(step: Step, run: Dispatch, db) -> dict:
    lang = run.lang
    text = (run.payload.message if len(run.payload.message) >= len(step.query or "") else step.query).strip()
    if len(text) < MIN_REVIEW_LENGTH:
        raise StepFailed(_t(lang, "Paste the contract clauses to review (payment, delay damages, claims, disputes ...).",
                            "请粘贴要审查的合同条款（付款、误期违约金、索赔、争议解决等）。"))
    countries = detect_countries(text) or [p.country_code.upper() for p in projects_in_scope(step, run, db)
                                           if step.project_id or run.payload.project_id] or focus_countries(run)
    country = countries[0] if len(countries) == 1 else None
    result = review(text, country, lang)
    if not result["terms"]:
        raise StepFailed(_t(lang, "No contract terms recognised in the text.", "文本中没有识别到合同条款。"))
    related: list = []
    seen = set()
    if country:
        for category, query in result["queries"].items():
            hits, _ = search_knowledge(db, query, principal=run.principal, countries=[country])
            for score, doc in hits[:2]:
                if doc.source_ref not in seen:
                    seen.add(doc.source_ref)
                    related.append({"category": category, **_hit_payload(score, doc, lang)})
    basis = sorted({ref for f in result["findings"] for ref in f["basis"]})
    high = sum(f["risk"] == "high" for f in result["findings"])
    medium = sum(f["risk"] == "medium" for f in result["findings"])
    head = _t(lang, f"Reviewed {len(result['terms'])} kinds of terms: {high} high and {medium} medium risk findings.",
              f"识别出 {len(result['terms'])} 类条款：高风险 {high} 项，中风险 {medium} 项。")
    if not country:
        head += _t(lang, " No single country identified, so local law was not checked.", "未识别出唯一的适用国家，未对照当地法律。")
    lines = [f"[{f['risk'].upper()}] {f['name']}：{f['finding']}" for f in result["findings"][:6]]
    note = _t(lang, "First-pass review for the contracts team; not legal advice.", "仅供合同团队初审参考，须专业复核，不构成法律意见。")
    return {"summary": "\n".join([head, *lines, note]), "refs": basis + [r["source_ref"] for r in related if r["source_ref"] not in basis],
            "data": {"country": country, "countries": countries, "terms": result["terms"], "findings": result["findings"],
                     "related": related, "method": "rules"}}


OPS_RUNNERS = {
    "twin": agent_twin, "commissioning": agent_commissioning, "precedents": agent_precedents,
    "briefing": agent_briefing, "contract_review": agent_contract_review,
}
