#!/usr/bin/env python3
"""Run release evaluations and produce one signed, machine-readable envelope.

The script never infers success from dataset size. It captures each runner's
actual JSON output, records the test report if supplied, binds everything to
the current Git commit and signs the canonical payload when a CI secret is
available.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import serialization


ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))

from app.evaluation_artifacts import (  # noqa: E402
    build_release_payload,
    sign_release_payload,
    write_release_evidence,
)


RUNNERS = (
    ("ai_outbound.json", ROOT / "evals" / "run_competition_eval.py"),
    ("agent_organization.json", ROOT / "evals" / "run_agent_org_eval.py"),
    ("assistant_dispatch.json", ROOT / "evals" / "run_dispatch_eval.py"),
)


def run_evaluations(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for filename, runner in RUNNERS:
        process = subprocess.run(
            [sys.executable, str(runner)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if process.stdout.strip():
            try:
                payload = json.loads(process.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{runner.name} did not emit JSON") from exc
        else:
            payload = {
                "suite": runner.stem,
                "status": "FAILED",
                "total_cases": 0,
                "metrics": {},
                "gates": {},
                "runner_error": process.stderr[-4000:],
            }
        (raw_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        if process.returncode:
            raise RuntimeError(
                f"{runner.name} failed with exit code {process.returncode}: "
                f"{process.stderr[-1000:]}"
            )


def junit_summary(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {"status": "NOT_PROVIDED", "tests": None, "failures": None, "errors": None}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))

    def total(name: str) -> int:
        return sum(int(suite.attrib.get(name, "0")) for suite in suites)

    tests = total("tests")
    failures = total("failures")
    errors = total("errors")
    skipped = total("skipped")
    return {
        "status": "PASSED" if tests > 0 and failures == 0 and errors == 0 else "FAILED",
        "tests": tests,
        "passed": max(0, tests - failures - errors - skipped),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "report_sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--ci-url")
    parser.add_argument(
        "--public-key-output",
        type=Path,
        help=(
            "Write the Ed25519 public verification key as PEM. The private "
            "key is never written to the release bundle."
        ),
    )
    parser.add_argument("--key-id", default=os.getenv("EVIDENCE_SIGNING_KEY_ID"))
    parser.add_argument(
        "--require-signature",
        action="store_true",
        help=(
            "Fail before running evaluations unless an Ed25519 private key or "
            "a >=32 character legacy HMAC key is configured."
        ),
    )
    args = parser.parse_args()

    private_key = os.getenv("EVIDENCE_SIGNING_PRIVATE_KEY")
    hmac_key = os.getenv("EVIDENCE_SIGNING_KEY")
    if args.require_signature and not private_key and (
        not hmac_key or len(hmac_key) < 32
    ):
        parser.error(
            "--require-signature needs EVIDENCE_SIGNING_PRIVATE_KEY (Ed25519 PEM) "
            "or legacy EVIDENCE_SIGNING_KEY with at least 32 characters"
        )
    if args.public_key_output and not private_key:
        parser.error("--public-key-output requires EVIDENCE_SIGNING_PRIVATE_KEY")

    run_evaluations(args.raw_dir)
    payload = build_release_payload(
        raw_dir=args.raw_dir,
        repo_root=ROOT,
        ci_url=args.ci_url or os.getenv("GITHUB_SERVER_URL", "")
        + (f"/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}" if os.getenv("GITHUB_RUN_ID") else ""),
    )
    payload["validation"] = {
        "api_tests": junit_summary(args.junit),
        "web_build": os.getenv("WEB_BUILD_STATUS", "NOT_ATTESTED"),
        "migration_check": os.getenv("MIGRATION_CHECK_STATUS", "NOT_ATTESTED"),
        "full_stack_smoke": os.getenv("SMOKE_TEST_STATUS", "NOT_ATTESTED"),
    }
    envelope = sign_release_payload(
        payload,
        ed25519_private_key=private_key,
        hmac_key=hmac_key,
        key_id=args.key_id
        or ("ci:ed25519" if private_key else "ci:hmac" if hmac_key else None),
    )
    digest = write_release_evidence(args.output, envelope)
    if args.public_key_output:
        loaded_private_key = serialization.load_pem_private_key(
            private_key.replace("\\n", "\n").strip().encode("utf-8") + b"\n",
            password=None,
        )
        public_key = loaded_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        args.public_key_output.parent.mkdir(parents=True, exist_ok=True)
        args.public_key_output.write_bytes(public_key)
    verification_mode = envelope["signature"]["scheme"]
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": digest,
                "signature": verification_mode,
                "suite_count": payload["totals"]["complete_suite_count"],
                "case_count": payload["totals"]["case_count"],
                "api_tests": payload["validation"]["api_tests"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
