"""Dispatcher sub-agents added in the P1 upgrade.

Each wraps a capability the platform already has, so its governance is the
platform's:

- ``compare``  -- clause library, searched country by country;
- ``draft``    -- reply points built from the work order and the clauses
                  found earlier in the same plan; a draft, never sent;
- ``glossary`` -- the four country glossaries;
- ``drawing``  -- the governed drawing question endpoint;
- ``gates``    -- the country packs' permit catalogue for a lifecycle stage.

All of them are read-only. ``draft`` writes nothing either: a reply that
leaves the company still goes through the work order's approval, execution
and verification buttons.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .assistant import _JSON_RE, _grounded_answer, _hit_payload, _model_available, core_query, search_knowledge
from .capabilities import BOUNDARIES, DOMAINS, LEVEL_TEXT, REVIEW_RE, coverage, detect_domains, library_stats
from .country_knowledge import load_glossary
from .dispatcher import (
    AGENTS, MAX_KNOWLEDGE_ANSWERS, Dispatch, Step, StepFailed, _resolve_case, _t, focus_countries,
)
from .i18n import localize
from .intake import COUNTRY_SIGNALS, _detect_lifecycle, detect_countries
from .llm import LLMError, generate
from .models import Case, CountryPack
from .multilingual import normalize
from .security import require_project

COUNTRY_NAMES = {code: label for code, label, _ in COUNTRY_SIGNALS}
ALL_COUNTRIES = [code for code, _, _ in COUNTRY_SIGNALS]
MAX_TERMS_PER_COUNTRY = 3
MAX_DRAFT_REFS = 4
MAX_TITLE = 40


def _countries_for(step: Step, run: Dispatch, db: Session, *, project_id: int | None = None) -> list[str]:
    """The step's countries, else the message's, else the conversation's focus."""
    found = detect_countries(step.query) or detect_countries(run.payload.message)
    if not found and project_id is not None:
        from .models import Project
        code = db.scalar(select(Project.country_code).where(Project.id == project_id))
        found = [code.upper()] if code else []
    return found or focus_countries(run)


def _name(code: str, lang: str) -> str:
    return localize(COUNTRY_NAMES.get(code, {"en": code, "zh": code}), lang)


# --- compare -------------------------------------------------------------------

async def agent_compare(step: Step, run: Dispatch, db: Session) -> dict:
    countries = _countries_for(step, run, db)
    if len(countries) < 2:
        raise StepFailed(_t(run.lang, "Name at least two countries to compare (for example Malaysia and Saudi Arabia).",
                            "请说明要对比的至少两个国家（例如马来西亚和沙特）。"))
    hits, countries = search_knowledge(db, step.query or run.payload.message, principal=run.principal, countries=countries)
    table = []
    for code in countries:
        rows = [(s, d) for s, d in hits if d.country_code == code]
        table.append({"country": code, "country_name": _name(code, run.lang),
                      "clauses": [_hit_payload(s, d, run.lang) for s, d in rows]})
    missing = [row["country_name"] for row in table if not row["clauses"]]
    answer = None
    if hits and run.knowledge_answers < MAX_KNOWLEDGE_ANSWERS:
        run.knowledge_answers += 1
        answer = await _grounded_answer(step.query or run.payload.message, hits, run.lang, run)
    parts = [f"{row['country_name']}：" + "、".join(f"{c['source_ref']}" for c in row["clauses"]) for row in table if row["clauses"]]
    summary = answer or _t(run.lang, "Clauses found — " + "; ".join(parts) + ".", "找到的条款——" + "；".join(parts) + "。")
    if missing:
        summary += _t(run.lang, f" No confident clause for: {', '.join(missing)}.", f" 未找到足够相关条款：{'、'.join(missing)}。")
    return {"summary": summary, "refs": [d.source_ref for _, d in hits],
            "data": {"query": step.query, "countries": countries, "table": table, "answer": answer,
                     "answer_method": "llm" if answer else "sources"}}


# --- glossary ------------------------------------------------------------------

_TERM_QUESTION_RE = re.compile(
    r"用?(?:阿拉伯语|阿语|马来语|印尼语|英语|当地语言)?(?:怎么说|怎么讲|叫什么|翻译)|术语|"
    r"\bin (?:arabic|malay|indonesian|bahasa)\b|\btranslate\b|\bterm\b|istilah|مصطلح", re.IGNORECASE)


def _term_matches(rows: list[dict], query: str) -> list[dict]:
    text = query.lower()
    norm = normalize(query)
    exact = [r for r in rows if (r["zh"] and r["zh"] in query) or (len(r["en"]) > 3 and re.sub(r"\s*\(.*?\)", "", r["en"]).lower() in text)
             or (len(r["local"]) > 2 and normalize(r["local"]) in norm)]
    if exact:
        return sorted(exact, key=lambda r: len(r["zh"] or r["en"]), reverse=True)
    words = set(core_query(query).split())
    scored = [(sum(w in f"{r['en']} {r['zh']} {r['local']}".lower() for w in words if len(w) > 2), r) for r in rows]
    return [r for s, r in sorted(scored, key=lambda x: -x[0]) if s > 0]


# "in Malay" names the language, which names the countries that use it.
_LANGUAGE_COUNTRIES = [
    (re.compile(r"马来语|\bmalay\b|bahasa melayu", re.IGNORECASE), ["MY"]),
    (re.compile(r"印尼语|\bindonesian\b|bahasa indonesia", re.IGNORECASE), ["ID"]),
    (re.compile(r"阿拉伯语|阿语|\barabic\b|العربية", re.IGNORECASE), ["AE", "SA"]),
]


async def agent_glossary(step: Step, run: Dispatch, db: Session) -> dict:
    # The step's own country, then the language it asks for, then the rest of the message.
    by_language = next((codes for pattern, codes in _LANGUAGE_COUNTRIES if pattern.search(step.query or run.payload.message)), [])
    countries = detect_countries(step.query) or by_language or detect_countries(run.payload.message) \
        or focus_countries(run) or ALL_COUNTRIES
    query = _TERM_QUESTION_RE.sub(" ", step.query or run.payload.message)
    for code in countries:
        for keyword in COUNTRY_SIGNALS[ALL_COUNTRIES.index(code)][2]:
            query = query.replace(keyword, " ")
    found = []
    for code in countries:
        for row in _term_matches(load_glossary(code), query)[:MAX_TERMS_PER_COUNTRY]:
            found.append({"country": code, "id": row["id"], "en": row["en"], "zh": row["zh"], "local": row["local"],
                          "local_lang": row["local_lang"], "attested": row["local_basis"].startswith("ATTESTED_IN:"),
                          "local_basis": row["local_basis"], "review_status": row["review_status"]})
    if not found:
        return {"summary": _t(run.lang, "No matching glossary term.", "术语库中没有匹配的词条。"), "data": {"terms": [], "countries": countries}}
    lines = [f"{_name(t['country'], run.lang)} {t['zh'] if run.lang == 'zh' else t['en']} → {t['local']}"
             + _t(run.lang, " (found in official text)" if t["attested"] else " (team-compiled)",
                  "（官方文本可查）" if t["attested"] else "（团队整理，待母语复核）") for t in found]
    return {"summary": "；".join(lines) if run.lang == "zh" else "; ".join(lines),
            "data": {"terms": found, "countries": countries}}


# --- drawing -------------------------------------------------------------------

_DRAWING_REF_RE = re.compile(r"\b(?:DWG|DRW)[-_][A-Z0-9][A-Z0-9._-]*\b", re.IGNORECASE)


async def agent_drawing(step: Step, run: Dispatch, db: Session) -> dict:
    from .drawings import AskDrawingRequest, DrawingDocument, _scoped_documents, ask_drawing

    text = f"{step.query} {run.payload.message}"
    scoped = _scoped_documents(run.principal)
    wanted = {m.upper() for m in _DRAWING_REF_RE.findall(text)}
    document = None
    if wanted:
        for doc in db.scalars(scoped.order_by(DrawingDocument.created_at.desc()).limit(200)):
            if doc.id.upper() in wanted or (doc.drawing_number or "").upper() in wanted:
                document = doc
                break
    if document is None:
        recent = list(db.scalars(scoped.order_by(DrawingDocument.created_at.desc()).limit(5)))
        listing = [{"id": d.id, "drawing_number": d.drawing_number, "title": d.title, "status": d.status} for d in recent]
        return {"summary": _t(run.lang,
                              f"Which drawing? {len(listing)} recent: " + ", ".join(d["drawing_number"] or d["id"] for d in listing) + "." if listing
                              else "No drawing has been uploaded yet.",
                              f"请指明图纸编号。最近 {len(listing)} 张：" + "、".join(d["drawing_number"] or d["id"] for d in listing) + "。" if listing
                              else "还没有上传图纸。"),
                "data": {"drawings": listing, "needs_choice": bool(listing)}}
    question = (step.query or run.payload.message)[:1000]
    if len(question) < 2:
        question = "summary"
    body = ask_drawing(document.id, AskDrawingRequest(question=question), run.principal, db)
    return {"summary": body.get("answer") or _t(run.lang, "The drawing does not answer this.", "图纸中没有可回答该问题的信息。"),
            "data": {"drawing_id": document.id, "drawing_number": document.drawing_number, "grounded": body.get("grounded"),
                     "citations": body.get("citations", []), "boundary": body.get("boundary")}}


# --- permit gates --------------------------------------------------------------

async def agent_gates(step: Step, run: Dispatch, db: Session) -> dict:
    project_id = step.project_id or run.payload.project_id
    countries = _countries_for(step, run, db, project_id=project_id)
    if not countries:
        raise StepFailed(_t(run.lang, "Which country? Permit gates differ by country.", "请说明国家：不同国家的许可关口不同。"))
    stage = _detect_lifecycle(normalize(f"{step.query} {run.payload.message}"))
    rows, lines = [], []
    for code in countries:
        pack = db.get(CountryPack, code)
        if pack is None:
            continue
        gates = [localize({"code": p["code"], "name": p["name"], "authority": p["authority"], "gate": p["gate"]}, run.lang)
                 for p in pack.permit_catalog or [] if stage in (p.get("stages") or [])]
        rows.append({"country": code, "stage": stage, "gates": gates})
        lines.append(f"{_name(code, run.lang)}：" + ("、".join(f"{g['code']} {g['name']}" for g in gates) or _t(run.lang, "none", "无")))
    from .domain import LIFECYCLE_STAGES
    label = next((localize(x["name"], run.lang) for x in LIFECYCLE_STAGES if x["id"] == stage and "name" in x), stage)
    summary = _t(run.lang, f"Permit gates at the {label} stage — ", f"{label}阶段的许可关口——") + "；".join(lines)
    hits: list = []
    if not any(row["gates"] for row in rows):
        # The country pack lists no gate for this stage; the clause library may
        # still hold the licensing rule (e.g. a railway operating licence).
        hits, _ = search_knowledge(db, step.query or run.payload.message, principal=run.principal, countries=countries)
        if hits:
            summary += _t(run.lang, ". Related clauses: ", "。条款库中的相关条款：") + "、".join(d.source_ref for _, d in hits) + \
                _t(run.lang, ".", "。")
    return {"summary": summary, "refs": [d.source_ref for _, d in hits],
            "data": {"stage": stage, "countries": [r["country"] for r in rows], "gates": rows,
                     "hits": [_hit_payload(score, d, run.lang) for score, d in hits]}}


# --- draft ---------------------------------------------------------------------

DRAFT_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "reply_points", "strict": True,
        "schema": {
            "type": "object", "additionalProperties": False, "required": ["points"],
            "properties": {"points": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["text", "refs"],
                "properties": {"text": {"type": "string"}, "refs": {"type": "array", "items": {"type": "string"}}},
            }}},
        },
    },
}


def _upstream(run: Dispatch, step: Step) -> tuple[str | None, list[dict]]:
    """The work order and clause hits produced by the steps this draft depends on."""
    case_id, hits = None, []
    for index in step.depends_on:
        result = run.results.get(index) or {}
        if result.get("status") != "ok":
            continue
        case_id = result.get("case_id") or case_id
        data = result.get("data") or {}
        hits += data.get("hits") or [c for row in data.get("table") or [] for c in row["clauses"]]
    seen, unique = set(), []
    for hit in hits:
        if hit["source_ref"] not in seen:
            seen.add(hit["source_ref"])
            unique.append(hit)
    return case_id, unique[:MAX_DRAFT_REFS]


def _deterministic_points(case: Case | None, hits: list[dict], lang: str) -> list[dict]:
    points = []
    if case is not None:
        title = localize(case.title, lang)
        title = title if len(title) <= MAX_TITLE else title[:MAX_TITLE].rstrip() + "…"
        points.append({"text": _t(lang, f"Acknowledge receipt of the notice on “{title}” and state that the facts are being verified.",
                                  f"确认已收到关于“{title}”的来函，说明我方正在核实事实。"), "refs": []})
        points.append({"text": _t(lang, "Propose a joint site inspection and request the owner's supporting records.",
                                  "提议联合现场检查，并请业主提供相关记录与依据。"), "refs": []})
    for hit in hits:
        points.append({"text": _t(lang, f"Refer to {hit['title']} as the applicable provision, to be confirmed by the contracts team.",
                                  f"引用《{hit['title']}》作为适用依据，由合同团队确认适用性。"), "refs": [hit["source_ref"]]})
    points.append({"text": _t(lang, "Reserve all rights: no admission of liability, cost or time until verification is complete.",
                              "保留一切权利：核实完成前不承认任何责任、费用或工期。"), "refs": []})
    deadline = localize(case.deadline, lang) if case is not None and case.deadline else ""
    if deadline and not re.search(r"未指定|未明确|not specified|unspecified|none", deadline, re.IGNORECASE):
        points.append({"text": _t(lang, f"Respond within the requested period ({deadline}).", f"在对方要求的期限内回复（{deadline}）。"), "refs": []})
    return points


def _valid_points(raw: str, refs: set[str]) -> list[dict] | None:
    match = _JSON_RE.search(raw or "")
    if not match:
        return None
    try:
        points = json.loads(match.group(0)).get("points")
    except (ValueError, AttributeError):
        return None
    if not isinstance(points, list) or not 2 <= len(points) <= 8:
        return None
    clean = []
    for point in points:
        text, cited = str(point.get("text", "")).strip(), [str(r) for r in point.get("refs") or []]
        if not text or len(text) > 400 or not set(cited) <= refs:
            return None
        clean.append({"text": text, "refs": cited})
    return clean


async def agent_draft(step: Step, run: Dispatch, db: Session) -> dict:
    case_id, hits = _upstream(run, step)
    if case_id is None and step.case_id:
        case_id = await _resolve_case(step, run)
    case = db.get(Case, case_id) if case_id else None
    if case is not None:
        if "platform_admin" not in run.principal.roles and case.organization_id != run.principal.organization_id:
            case = None
        elif case.project_id is not None:
            require_project(run.principal, case.project_id, db)
    if case is None and not hits:
        raise StepFailed(_t(run.lang, "Nothing to draft from: no work order or clause was found earlier in this request.",
                            "没有可依据的工单或条款，无法起草回函要点。"))
    points, method = _deterministic_points(case, hits, run.lang), "rules"
    if _model_available(run.payload):
        language = "Simplified Chinese" if run.lang == "zh" else "English"
        facts = {"work_order": {"id": case.id, "title": localize(case.title, "en"), "risk": case.risk,
                                "deadline": localize(case.deadline, "en") if case.deadline else None,
                                "issues": [localize(i, "en") for i in case.detected_issues or []]} if case else None,
                 "clauses": [{"ref": h["source_ref"], "title": h["title"], "summary": (h.get("summary") or "")[:400]} for h in hits]}
        system = ("Draft 3-6 reply points to an owner's notice for an overseas construction contractor. Use ONLY the facts "
                  "given. Each point may cite clause refs from the list in `refs`; cite nothing else. Do not admit "
                  "liability, cost or time; do not invent facts, numbers or deadlines. Points are a draft for the "
                  f"contracts team. Write the text in {language}.")
        try:
            raw = await generate(system, json.dumps(facts, ensure_ascii=False), response_format=DRAFT_FORMAT,
                                 route=run.payload.model_route, sensitivity=run.payload.data_classification)
            checked = _valid_points(raw, {h["source_ref"] for h in hits})
            if checked:
                points, method = checked, "llm"
        except LLMError:
            pass
    lines = "\n".join(f"{i + 1}. {p['text']}" + "".join(f" [{r}]" for r in p["refs"]) for i, p in enumerate(points))
    note = _t(run.lang, "Draft only, not sent. The formal reply goes through the work order's approval.",
              "仅为草稿，未发送。正式回函须走工单审批。")
    return {"summary": f"{note}\n{lines}", "refs": [h["source_ref"] for h in hits], "case_id": case.id if case else None,
            "data": {"status": "DRAFT_NOT_SENT", "case_id": case.id if case else None, "points": points, "method": method,
                     "clauses": hits}}


# --- self-knowledge ------------------------------------------------------------

async def agent_self(step: Step, run: Dispatch, db: Session) -> dict:
    """What the assistant can and cannot answer, from the live roster and clause coverage."""
    lang = run.lang
    text = step.query or run.payload.message
    domains = detect_domains(text)
    named = detect_countries(text)
    rows = coverage(lang)
    if named:  # "can you answer Saudi quality questions?" is about Saudi Arabia only
        rows = [{**row, "countries": {c: v for c, v in row["countries"].items() if c in named}} for row in rows]
    stats = library_stats()
    agents = [{"id": agent_id, "name": localize(spec["name"], lang), "role": localize(spec["role"], lang),
               "authority": spec["authority"]} for agent_id, spec in AGENTS.items()]
    name = lambda code: _name(code, lang)  # noqa: E731
    if domains:
        lines = []
        for row in (r for r in rows if r["id"] in domains):
            cells = "、".join(f"{name(c)} {LEVEL_TEXT[v['level']][lang if lang == 'zh' else 'en']}（{v['clauses']}）"
                             for c, v in row["countries"].items()) if lang == "zh" else \
                ", ".join(f"{name(c)} {LEVEL_TEXT[v['level']]['en']} ({v['clauses']})" for c, v in row["countries"].items())
            lines.append(_t(lang, f"{row['name']}: {cells}. {row['note']}", f"{row['name']}：{cells}。{row['note']}"))
        if REVIEW_RE.search(text):
            lines.append(_t(lang, "To have a contract looked at, paste the clauses or letter here, or attach the file.",
                            "如需分析合同，请把相关条款或来函粘贴到这里，或上传文件。"))
        summary = "\n".join(lines)
    else:
        strong = lambda r: any(v["level"] == "covered" for v in r["countries"].values())  # noqa: E731
        covered = [r["name"] for r in rows if strong(r)] + [
            r["name"] + _t(lang, " (project data)", "（项目数据）") for r in rows if not strong(r) and r["project_data"]]
        gaps = [r["name"] + (_t(lang, " (clauses)", "（条款）") if r["project_data"] else "")
                for r in rows if not strong(r)]
        summary = _t(
            lang,
            f"I am the dispatcher of GlobalInfra AI. I split a request into tasks for {len(agents)} sub-agents and "
            f"answer from a clause library of {stats['clauses']} provisions ({stats['instruments']} laws, "
            f"{stats['countries']} countries) and {stats['glossary_terms']} glossary terms, citing every source. "
            f"Strongest: {', '.join(covered)}. Thin or missing: {', '.join(gaps) or 'none'}. "
            "Approvals and sending stay with you.",
            f"我是 GlobalInfra AI 的总调度。我把你的请求拆成任务，交给 {len(agents)} 个子智能体；依据是 "
            f"{stats['countries']} 国 {stats['instruments']} 部法律中的 {stats['clauses']} 条条款，以及 "
            f"{stats['glossary_terms']} 个术语，每个结论都标来源。覆盖较好：{''.join(f'「{n}」' for n in covered)}。较少或没有："
            f"{''.join(f'「{n}」' for n in gaps) or '无'}。审批和对外发送由你决定。")
    return {"summary": summary,
            "data": {"agents": agents, "coverage": rows, "focus_domains": domains, "stats": stats,
                     "boundaries": [localize(b, lang) for b in BOUNDARIES]}}


EXTRA_RUNNERS = {
    "compare": agent_compare, "glossary": agent_glossary, "drawing": agent_drawing,
    "gates": agent_gates, "draft": agent_draft, "self": agent_self,
}
