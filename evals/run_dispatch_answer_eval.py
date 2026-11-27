#!/usr/bin/env python3
"""Answer-level evaluation of the dispatching assistant (deterministic, offline).

``run_dispatch_eval.py`` checks only which sub-agents a message is routed
to. This suite checks what comes back. Each of the 68 team-written messages
(Chinese, English, Arabic, Malay, Indonesian) goes to ``/assistant/dispatch``
with no model, so the rule planner and the retrieval path are measured:

- routing: the expected sub-agents, in order;
- evidence: a knowledge step returns at least one of the expected clauses
  (hit), or, for a comparison, sources from every named country;
- jurisdiction: no source from a country the question did not name
  (cross-country leakage);
- abstention: a question outside the corpus returns no source;
- progress: a progress step lists exactly the projects of the named country;
- sub-agents (P1): a comparison reports a country the library has no clause
  for instead of filling its cell; the glossary returns the expected local term, the permit
  gates come from the right stage and country, a drawing question without a
  drawing number never guesses one, and a reply draft is marked not sent,
  waits for the steps it depends on and cites only clauses they retrieved;
- self-knowledge: "what can you do?" lists every sub-agent and names the
  domains the library cannot answer; "can you answer Saudi quality
  questions?" is scoped to that domain and country; a building-code question
  states that the library has no technical provisions;
- lifecycle agents: contract review flags pay-when-paid and an exclusion of
  structural liability with the clause that voids them (synthetic contract
  texts); the twin reports the named element; commissioning applies the
  handover rule; precedents find the related work order and never return the
  one just created; the briefing stays in the named project; progress sets
  a requested extension against the schedule variance;
- focus (P2): a follow-up in the same session ("and overtime?") searches the
  country the conversation is about, or the one the follow-up names.

Clause ids were chosen by the team from the shipped clause library. With a
model configured the planner and the wording of the answer change; that run
is reported separately and is not part of this gate:

- ``--dry-run`` counts the model calls and prompt sizes a live run would
  make, without any network call (every call fails over to the rules), so
  the cost can be estimated before spending anything;
- ``--live`` uses the model configured in the environment (``LLM_MODE``,
  ``OPENAI_COMPAT_*``) and reports the same metrics plus the token usage the
  endpoint returned. Its exit code is always 0: it is a measurement, not a
  CI gate.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))
MODE = "live" if "--live" in sys.argv else "dry-run" if "--dry-run" in sys.argv else "offline"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/dispatch_answer_eval.db")
if MODE == "offline":
    os.environ["LLM_MODE"] = "mock"
elif MODE == "dry-run":
    # A model route must exist for the calls to be attempted; none leaves the process.
    os.environ["LLM_MODE"] = "openai"
    os.environ.setdefault("OPENAI_COMPAT_API_KEY", "dry-run-no-network")
elif os.environ.get("LLM_MODE", "mock").lower() == "mock" or not os.environ.get("OPENAI_COMPAT_API_KEY"):
    sys.exit("--live needs LLM_MODE and OPENAI_COMPAT_API_KEY in the environment")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

from app import llm  # noqa: E402

DATASET = API / "evals" / "dispatch_answers.jsonl"
USAGE = {"calls": 0, "failed": 0, "prompt_chars": 0, "completion_chars": 0, "prompt_tokens": 0, "completion_tokens": 0}
_provider_call = llm._generate_messages_with_provider


async def _counted_call(provider, messages, response_format=None):
    USAGE["calls"] += 1
    USAGE["prompt_chars"] += sum(len(m.get("content") or "") for m in messages if isinstance(m.get("content"), str))
    if MODE == "dry-run":
        USAGE["failed"] += 1
        raise llm.LLMError("dry run: no network call")
    try:
        text = await _provider_call(provider, messages, response_format)
    except llm.LLMError:
        USAGE["failed"] += 1
        raise
    USAGE["completion_chars"] += len(text or "")
    return text


if MODE != "offline":
    llm._generate_messages_with_provider = _counted_call
    if MODE == "live":
        # Exact token counts come from the endpoint's ``usage`` field.
        _post = llm.httpx.AsyncClient.post

        async def _post_with_usage(self, url, *args, **kwargs):
            response = await _post(self, url, *args, **kwargs)
            try:
                usage = response.json().get("usage") or {}
            except ValueError:
                usage = {}
            USAGE["prompt_tokens"] += usage.get("prompt_tokens", 0)
            USAGE["completion_tokens"] += usage.get("completion_tokens", 0)
            return response

        llm.httpx.AsyncClient.post = _post_with_usage
GATE_THRESHOLDS = {"routing": 95.0, "evidence_hit": 90.0, "no_leakage": 100.0, "abstention": 100.0, "progress_scope": 100.0,
                   "sub_agents": 100.0, "draft_grounded": 100.0, "focus": 100.0, "self_knowledge": 100.0,
                   "lifecycle_agents": 100.0}


def _dispatch(client, message, session_id=None):
    body = {"message": message, **({"session_id": session_id} if session_id else {})}
    response = client.post("/assistant/dispatch?lang=zh", json=body)
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _step(agents, done, agent):
    return next((done.get(i) for i, a in enumerate(agents) if a == agent), None)


def _rate(values: list[bool]) -> float | None:
    return round(100 * sum(values) / len(values), 1) if values else None


def main() -> int:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    with TestClient(app) as client:
        for row in rows:
            events = _dispatch(client, row["message"])
            plan = next(e for e in events if e["type"] == "plan")
            agents = [s["agent"] for s in plan["steps"]]
            done = {e["index"]: e for e in events if e["type"] == "step_done"}
            expect = row["expect"]
            result = {"id": row["id"], "agents": agents, "routing": agents == row["agents"]}
            if MODE != "offline":
                trace = next((e for e in events if e["type"] == "trace"), {})
                result.update(plan_method=plan.get("method"), model_calls=trace.get("model_calls"))
            knowledge = _step(agents, done, "knowledge") or _step(agents, done, "compare")
            if knowledge is not None:
                data = knowledge.get("data") or {}
                hits = data.get("hits") or [c for row_ in data.get("table") or [] for c in row_["clauses"]]
                refs = [h["source_ref"] for h in hits]
                countries = {h["country_code"] for h in hits if h.get("country_code")}
                result.update(refs=refs, searched=(knowledge.get("data") or {}).get("countries"))
                if expect.get("abstain"):
                    result["abstention"] = not refs
                if expect.get("refs"):
                    result["evidence_hit"] = any(ref in refs for ref in expect["refs"])
                if expect.get("refs_from_countries"):
                    result["evidence_hit"] = set(expect["refs_from_countries"]) <= countries
                if expect.get("countries"):
                    result["no_leakage"] = countries <= set(expect["countries"])
            progress = next((done.get(i) for i, a in enumerate(agents) if a == "progress"), None)
            if progress is not None and "projects" in expect:
                codes = [p["code"] for p in (progress.get("data") or {}).get("projects", [])]
                result.update(projects=codes, progress_scope=sorted(codes) == sorted(expect["projects"]))
            if expect.get("gap_countries"):
                # The library has no clause for that country: the comparison must say so, not fill the cell.
                table = {row_["country"]: row_["clauses"] for row_ in ((knowledge or {}).get("data") or {}).get("table") or []}
                result["sub_agents"] = all(c in table and not table[c] for c in expect["gap_countries"]) and \
                    "未找到" in (knowledge or {}).get("summary", "")
            if "self" in expect:
                own = _step(agents, done, "self") or {}
                data, want = own.get("data") or {}, expect["self"]
                checks = [own.get("status") == "ok"]
                if want.get("all_agents"):
                    from app.dispatcher import AGENTS
                    checks.append({a["id"] for a in data.get("agents") or []} == set(AGENTS))
                for domain in want.get("gap_domains", []):
                    row = next((r for r in data.get("coverage") or [] if r["id"] == domain), None)
                    checks.append(bool(row) and all(c["level"] != "covered" for c in row["countries"].values())
                                  and row["name"] in own.get("summary", "").split("较少或没有")[-1])
                if "domains" in want:
                    checks.append(data.get("focus_domains") == want["domains"])
                if "countries" in want:
                    checks.append(all(sorted(r["countries"]) == want["countries"] for r in data.get("coverage") or []))
                result["self_knowledge"] = all(checks)
            lifecycle = []
            if "contract" in expect:
                step = _step(agents, done, "contract_review") or {}
                findings = (step.get("data") or {}).get("findings") or []
                high = {f["category"] for f in findings if f["risk"] == "high"}
                lifecycle.append(step.get("status") == "ok" and set(expect["contract"]["basis"]) <= set(step.get("refs") or [])
                                 and set(expect["contract"]["high_categories"]) <= high)
            if "twin_element" in expect:
                matched = ((_step(agents, done, "twin") or {}).get("data") or {}).get("matched") or []
                lifecycle.append(bool(matched) and all(m.endswith("-" + expect["twin_element"]) for m in matched))
            if expect.get("commissioning"):
                items = ((_step(agents, done, "commissioning") or {}).get("data") or {}).get("items") or []
                lifecycle.append(bool(items) and all(i["ready"] == (i["readiness"] >= 95 and i["punch_open"] == 0) for i in items))
            if "precedent" in expect:
                rows_ = ((_step(agents, done, "precedents") or {}).get("data") or {}).get("precedents") or []
                lifecycle.append(expect["precedent"] in [r["case_id"] for r in rows_])
            if expect.get("precedent_excludes_new"):
                new_case = (_step(agents, done, "intake") or {}).get("case_id")
                rows_ = ((_step(agents, done, "precedents") or {}).get("data") or {}).get("precedents") or []
                lifecycle.append(bool(new_case) and new_case not in [r["case_id"] for r in rows_])
            if "briefing_projects" in expect:
                lifecycle.append(((_step(agents, done, "briefing") or {}).get("data") or {}).get("project_ids") == expect["briefing_projects"])
            if "eot_days" in expect:
                data = (_step(agents, done, "progress") or {}).get("data") or {}
                lifecycle.append(data.get("eot_requested_days") == expect["eot_days"] and all(
                    p["variance_after_eot"] == p["schedule_variance"] + expect["eot_days"] for p in data.get("projects") or []))
            if lifecycle:
                result["lifecycle_agents"] = all(lifecycle)
            if expect.get("coverage_gap"):
                gaps = ((knowledge or {}).get("data") or {}).get("coverage_gaps") or []
                result["self_knowledge"] = bool(gaps) and not any(ch.isdigit() for ch in " ".join(gaps))
            glossary, gates, drawing, draft = (_step(agents, done, a) for a in ("glossary", "gates", "drawing", "draft"))
            if "terms" in expect and glossary is not None:
                terms = (glossary.get("data") or {}).get("terms") or []
                result["terms"] = [(t["country"], t["local"]) for t in terms]
                result["sub_agents"] = all(any(t["country"] == c and (local is None or t["local"] == local) for t in terms)
                                           for c, local in expect["terms"].items())
            elif "terms" in expect:
                result["sub_agents"] = False
            if "gates_fallback_refs" in expect:
                result["sub_agents"] = set(expect["gates_fallback_refs"]) <= set((gates or {}).get("refs") or [])
            if "gates" in expect:
                data = (gates or {}).get("data") or {}
                result["sub_agents"] = (data.get("stage") == expect["gates"]["stage"]
                                        and data.get("countries") == expect["gates"]["countries"]
                                        and all(row_["gates"] for row_ in data.get("gates") or [{}]))
            if expect.get("drawing_no_guess"):
                result["sub_agents"] = drawing is not None and "drawing_id" not in (drawing.get("data") or {})
            if expect.get("draft"):
                retrieved = {ref for i, a in enumerate(agents) if a != "draft" for ref in (done.get(i) or {}).get("refs") or []}
                data = (draft or {}).get("data") or {}
                starts = [e["index"] for e in events if e["type"] == "step_start"]
                draft_index = agents.index("draft") if "draft" in agents else None
                result["draft_grounded"] = bool(
                    draft and draft["status"] == "ok" and data.get("status") == "DRAFT_NOT_SENT"
                    and all(set(p["refs"]) <= retrieved for p in data.get("points") or [])
                    and draft_index is not None
                    and all(starts.index(d) < starts.index(draft_index) for d in plan["steps"][draft_index]["depends_on"]))
            if row.get("follow_up"):
                session_id = next(e for e in events if e["type"] == "session")["session_id"]
                follow = _dispatch(client, row["follow_up"], session_id)
                follow_plan = next(e for e in follow if e["type"] == "plan")["steps"]
                follow_done = {e["index"]: e for e in follow if e["type"] == "step_done"}
                step = _step([s["agent"] for s in follow_plan], follow_done, "knowledge") or {}
                data = step.get("data") or {}
                found = {h["country_code"] for h in data.get("hits") or [] if h.get("country_code")}
                result.update(follow_up_countries=data.get("countries"),
                              focus=data.get("countries") == expect["follow_up_countries"]
                              and bool(found) and found <= set(expect["follow_up_countries"]))
            results.append(result)
    metrics = {key: _rate([r[key] for r in results if key in r]) for key in GATE_THRESHOLDS}
    for lang, ids in {"ar": ("A13", "A14", "A15", "A20"), "ms_id": ("A16", "A17", "A18", "A19")}.items():
        metrics[f"evidence_hit_{lang}"] = _rate([r["evidence_hit"] for r in results if r["id"] in ids and "evidence_hit" in r])
    gates = {key: metrics[key] is not None and metrics[key] >= threshold for key, threshold in GATE_THRESHOLDS.items()}
    passed = all(gates.values())
    report = {"suite": "DISPATCH_ANSWERS" if MODE == "offline" else f"DISPATCH_ANSWERS_{MODE.upper().replace('-', '_')}",
              "total_cases": len(results), "status": "PASSED" if passed else "FAILED",
              "metrics": metrics, "thresholds": GATE_THRESHOLDS, "gates": gates}
    if MODE != "offline":
        report["model"] = {"mode": os.environ.get("LLM_MODE"), "name": llm.settings.openai_compat_model, **USAGE}
        report["plan_methods"] = {m: sum(r.get("plan_method") == m for r in results) for m in {r.get("plan_method") for r in results}}
    report["cases"] = results
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed or MODE == "live" else 1


if __name__ == "__main__":
    sys.exit(main())
