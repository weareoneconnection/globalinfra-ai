"""Model-composed reply drafts, letter titles and the document intake note.

Real-model paths monkeypatch ``app.reply_draft.generate`` and ``settings``;
no network call is ever made.
"""
import json

from app.config import settings
from app.main import _case_title
from app.reply_draft import validate_reply

VO_LETTER = (
    "3\nRef. No.: DEMO-SUB-2026-0042\nProject: Station Roof Steel Works, Malaysia\n"
    "Subject : Request for Variation Order due to additional anchor bolts\n"
    "Dear Sir,\nAdditional anchor bolts were installed at roof trusses T4 to T9. We request a variation order "
    "and an extension of time of 10 days.\n"
)


def _real_mode(monkeypatch, fake_generate):
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_compat_api_key", "test-key")
    monkeypatch.setattr("app.reply_draft.generate", fake_generate)


def _approved_vo_case(client, note="如何回复此信函？"):
    body = client.post(
        f"/intake/document?note={note}",
        files={"file": ("vo_letter.txt", VO_LETTER.encode(), "text/plain")},
    ).json()
    case_id = body["case_id"]
    for approval in client.get("/approvals").json():
        if approval["case_id"] == case_id:
            client.post(f"/approvals/{approval['id']}/approve")
    return case_id, client.get(f"/cases/{case_id}").json()


def _artifact(client, case_id):
    detail = client.get(f"/cases/{case_id}").json()
    return json.loads(client.get(f"/artifacts/{detail['artifact']['id']}").json()["content"])


def test_case_title_prefers_subject_then_a_real_line():
    assert _case_title(VO_LETTER) == "Request for Variation Order due to additional anchor bolts"
    assert _case_title("8\n12\nOwner notice: access road damage") == "Owner notice: access road damage"
    assert _case_title("主题：P47 墩临边防护整改\n正文") == "P47 墩临边防护整改"


def test_variation_letter_retrieves_variation_evidence(client):
    case_id, detail = _approved_vo_case(client)
    assert "Variation / change request" in detail["detected_issues"]
    refs = [item["source_ref"] for item in detail["evidence"] if item["verified"]]
    assert refs[:2] == ["CTR-A / Clause 13", "PROC-VO-02"]


def test_document_note_is_recorded_as_lineage_not_text(client):
    case_id, detail = _approved_vo_case(client, note="please draft a reply")
    assert "please draft a reply" not in detail["description"]
    receipts = client.get("/ingestion/receipts").json()
    rows = receipts["receipts"] if isinstance(receipts, dict) else receipts
    row = next(r for r in rows if r["target_id"] == case_id)
    assert row["lineage"]["user_note"] == "please draft a reply"


def test_validate_reply_requires_known_citations():
    refs = {"CTR-A / Clause 13", "PROC-VO-02"}
    good = {"en": "We acknowledge receipt [CTR-A / Clause 13] on [●].", "zh": "我们确认收悉 [PROC-VO-02]，日期 [●]。"}
    assert validate_reply(good, refs)
    assert not validate_reply({**good, "zh": "我们确认收悉。"}, refs)  # nothing cited
    assert not validate_reply({**good, "en": "Per [FIDIC 13.3] we accept."}, refs)  # foreign citation
    assert not validate_reply({"en": good["en"]}, refs)  # missing language


def test_offline_execution_uses_template(client):
    case_id, detail = _approved_vo_case(client)
    assert client.post(f"/actions/{detail['action']['id']}/execute").status_code == 200
    output = _artifact(client, case_id)
    assert output["composition"] == "template"
    assert "Dear Sir/Madam" in output["body"]["en"]


def test_model_reply_is_used_and_still_verifies(client, monkeypatch):
    case_id, detail = _approved_vo_case(client)
    seen = {}

    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        seen["user"] = user
        return json.dumps({
            "en": "Dear Sir,\nWe acknowledge your request [PROC-VO-02]. Please provide the written instruction reference [CTR-A / Clause 13] by [●].",
            "zh": "敬启者：\n我们确认收到贵司申请 [PROC-VO-02]。请于 [●] 前提供书面指令编号 [CTR-A / Clause 13]。",
        })
    _real_mode(monkeypatch, fake)
    action_id = detail["action"]["id"]
    assert client.post(f"/actions/{action_id}/execute").status_code == 200
    assert "如何回复此信函" in seen["user"] and "anchor bolts" in seen["user"]
    output = _artifact(client, case_id)
    assert output["composition"] == "llm"
    assert "written instruction reference" in output["body"]["en"]
    assert output["body"]["en"].startswith("DRAFT — NOT SENT")
    verified = client.post(f"/actions/{action_id}/verify").json()
    assert verified["status"] == "VERIFIED"


def test_model_reply_with_invented_citation_falls_back_to_template(client, monkeypatch):
    case_id, detail = _approved_vo_case(client)

    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        return json.dumps({"en": "Under [FIDIC 13.3] we accept the cost.", "zh": "根据 [FIDIC 13.3] 我们接受费用。"})
    _real_mode(monkeypatch, fake)
    assert client.post(f"/actions/{detail['action']['id']}/execute").status_code == 200
    assert _artifact(client, case_id)["composition"] == "template"


def test_model_is_not_called_before_approval(client, monkeypatch):
    body = client.post("/intake/document", files={"file": ("vo.txt", VO_LETTER.encode(), "text/plain")}).json()
    action_id = client.get(f"/cases/{body['case_id']}").json()["action"]["id"]

    async def fake(*args, **kwargs):
        raise AssertionError("no drafting before approval")
    _real_mode(monkeypatch, fake)
    assert client.post(f"/actions/{action_id}/execute").status_code == 409
