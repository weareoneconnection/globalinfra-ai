#!/usr/bin/env python3
"""Clause-level regulation retrieval evaluation (deterministic, offline).

Each case is a short English or Chinese question an engineer might ask. It is
sent to the public ``/knowledge/search`` API restricted to the case's
country and to clause summaries (``document_type=CLAUSE_SUMMARY``). The expected answer is
the provision the question is about. Checks:

- the clause library loads completely and every row keeps its provenance
  (official source URL, version, source language, paraphrase and
  expert-review flags);
- hit@3 and top-1 accuracy, overall, per language and per country.

The queries were written by the project team, not collected from users, so
this measures retrieval over a known corpus. It does not show that answers
are legally correct: every clause is a paraphrase that needs expert review.
"""
import json
import os
from collections import Counter
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/clause_retrieval_eval.db")
os.environ["LLM_MODE"] = "mock"
os.environ.setdefault("REQUIRE_API_KEY", "false")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.country_knowledge import CLAUSE_DOCUMENT_TYPE, load_clause_library  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KnowledgeDocument  # noqa: E402

DATASET = API / "evals" / "clause_retrieval.jsonl"
GATE_THRESHOLDS = {"hit_at_3": 95.0, "top_1": 85.0, "provenance_complete": 100.0}
REQUIRED_PROVENANCE = ("source_url", "read_from", "read_quality", "version", "source_language", "authority", "instrument", "provision")


def _rate(values: list[bool]) -> float:
    return round(100 * sum(values) / max(len(values), 1), 1)


def main() -> int:
    library = load_clause_library()
    provenance_ok = [
        all(row.get(key) for key in REQUIRED_PROVENANCE)
        and row["source_url"].startswith("https://")
        and row["text_type"] == "PARAPHRASE_NOT_AUTHENTIC_TEXT"
        and row["review_status"] == "EXPERT_REVIEW_REQUIRED"
        for row in library
    ]
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    with TestClient(app) as client:
        with SessionLocal() as db:
            loaded = db.scalar(select(func.count()).select_from(KnowledgeDocument).where(
                KnowledgeDocument.document_type == CLAUSE_DOCUMENT_TYPE, KnowledgeDocument.status == "CURRENT"))
        for row in rows:
            body = client.get("/knowledge/search", params={
                "q": row["query"], "country_code": row["country"], "document_type": "CLAUSE_SUMMARY", "limit": 3,
            }).json()
            refs = [hit["source_ref"] for hit in body["results"]]
            results.append({"id": row["id"], "country": row["country"], "lang": row["lang"], "expected": row["expected"], "retrieved": refs,
                            "hit_at_3": row["expected"] in refs, "top_1": bool(refs) and refs[0] == row["expected"]})
    metrics = {
        "clauses_in_library": len(library),
        "clauses_seeded": loaded,
        "instruments": len({row["instrument"] for row in library}),
        "countries": dict(sorted(Counter(row["country"] for row in library).items())),
        "provenance_complete": _rate(provenance_ok),
        "hit_at_3": _rate([r["hit_at_3"] for r in results]),
        "top_1": _rate([r["top_1"] for r in results]),
    }
    for country in sorted({r["country"] for r in results}):
        subset = [r for r in results if r["country"] == country]
        metrics[f"hit_at_3_{country}"] = _rate([r["hit_at_3"] for r in subset])
        metrics[f"top_1_{country}"] = _rate([r["top_1"] for r in subset])
    for lang in sorted({r["lang"] for r in results}):
        subset = [r for r in results if r["lang"] == lang]
        metrics[f"hit_at_3_{lang}"] = _rate([r["hit_at_3"] for r in subset])
        metrics[f"top_1_{lang}"] = _rate([r["top_1"] for r in subset])
    gates = {key: metrics[key] >= threshold for key, threshold in GATE_THRESHOLDS.items()}
    gates["library_loaded"] = loaded == len(library)
    passed = all(gates.values())
    print(json.dumps({"suite": "CLAUSE_RETRIEVAL", "total_cases": len(results), "status": "PASSED" if passed else "FAILED",
                      "metrics": metrics, "thresholds": GATE_THRESHOLDS, "gates": gates,
                      "cases": results}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
