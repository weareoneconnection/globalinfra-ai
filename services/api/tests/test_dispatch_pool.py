"""Dispatch steps must not sit on a database connection while a model answers."""
import json

from sqlalchemy import delete, select

from app import database, dispatcher, llm
from app.config import settings
from app.database import SessionLocal, release_idle_connection, releasing_connection
from app.models import AgentRun, KnowledgeDocument


def _events(client, message):
    response = client.post("/assistant/dispatch?lang=en", json={"message": message})
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_a_read_only_session_hands_its_connection_back(client):
    db = SessionLocal(expire_on_commit=False)
    try:
        with releasing_connection(db):
            doc = db.scalars(select(KnowledgeDocument).limit(1)).first()
            assert db.in_transaction()
            assert release_idle_connection()
            assert not db.in_transaction()
            assert doc is None or doc.source_ref  # still readable
    finally:
        db.close()


def test_a_session_with_writes_keeps_its_connection(client):
    db = SessionLocal(expire_on_commit=False)
    try:
        with releasing_connection(db):
            db.execute(delete(AgentRun).where(AgentRun.case_id == "no-such-case"))
            assert not release_idle_connection() and db.in_transaction()
        db.rollback()
        with releasing_connection(db):
            db.scalar(select(AgentRun.id).limit(1))
            db.add(AgentRun(case_id="no-such-case", agent={"en": "x", "zh": "x"}, status="COMPLETED",
                            summary={"en": "x", "zh": "x"}, duration_ms=1))
            assert not release_idle_connection() and db.in_transaction()
        db.rollback()
    finally:
        db.close()


def test_nothing_is_released_outside_a_registered_session(client):
    db = SessionLocal()
    try:
        db.scalar(select(AgentRun.id).limit(1))
        assert not release_idle_connection() and db.in_transaction()
    finally:
        db.close()


def test_model_calls_in_a_step_run_without_an_open_transaction(client, monkeypatch):
    seen = []

    async def fake_model(provider, system, user, response_format):
        session = database._releasable.get()
        if session is not None:
            seen.append(session.in_transaction())
        return "Answer grounded in the sources [S1]."

    provider = llm.ModelProvider(name="openai", base_url="http://model.invalid/v1", model="fake", api_key="k")
    monkeypatch.setattr(llm, "_route_order", lambda route=None, sensitivity="internal": [provider])
    monkeypatch.setattr(llm, "_generate_with_provider", fake_model)
    _events(client, "Malaysia foreign worker permit requirements")
    assert seen and not any(seen)


def test_dispatches_over_the_limit_are_refused_at_once(client, monkeypatch):
    monkeypatch.setattr(dispatcher, "_running", settings.dispatch_max_concurrent)
    events = _events(client, "Malaysia foreign worker permit requirements")
    assert [e["type"] for e in events] == ["error"] and events[0]["code"] == "busy"
    assert dispatcher._running == settings.dispatch_max_concurrent  # a refused request takes no slot
    monkeypatch.setattr(dispatcher, "_running", 0)
    assert any(e["type"] == "done" for e in _events(client, "Malaysia foreign worker permit requirements"))
    assert dispatcher._running == 0
