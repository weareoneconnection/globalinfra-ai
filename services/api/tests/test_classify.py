import pytest

from app.classify import classify_text


@pytest.mark.parametrize(
    "text,expected_type,expected_risk",
    [
        (
            "Owner notice alleges access road damage and asks for rectification within 48 hours.",
            "Contract / Technical Interface",
            "HIGH",
        ),
        (
            "Worker observed near unprotected edge at elevated workface.",
            "HSE",
            "CRITICAL",
        ),
        (
            "Concrete surface honeycombing observed at drainage wall after formwork removal.",
            "Quality",
            "MEDIUM",
        ),
        (
            "业主通知函指出施工便道损坏，并要求在 48 小时内整改。",
            "Contract / Technical Interface",
            "HIGH",
        ),
        (
            "在高处作业面发现工人靠近无防护边缘。",
            "HSE",
            "CRITICAL",
        ),
        (
            "排水墙拆模后发现混凝土表面蜂窝状缺陷。",
            "Quality",
            "MEDIUM",
        ),
    ],
)
def test_classify_matches_the_eval_dataset_labels(text, expected_type, expected_risk):
    # These are the same (text, expected_*) pairs as evals/datasets/cases.jsonl;
    # keeping both gives us the assertion at unit-test speed *and* as a
    # reviewable eval report (see evals/run_eval.py).
    assert classify_text(text) == {"type": expected_type, "risk": expected_risk}


def test_classify_falls_back_to_default_for_unrecognized_text():
    assert classify_text("Completely unrelated text with no known signal words.") == {
        "type": "Contract / Technical Interface",
        "risk": "MEDIUM",
    }


def test_classify_handles_empty_and_none_input():
    assert classify_text("") == {"type": "Contract / Technical Interface", "risk": "MEDIUM"}
    assert classify_text(None) == {"type": "Contract / Technical Interface", "risk": "MEDIUM"}
