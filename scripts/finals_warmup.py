#!/usr/bin/env python3
"""Run one full five-party judge session against a deployment.

The competition demo uses ephemeral storage, so after every redeploy the
finals Mission Control page (`/competition/finals`) has no completed judge
run to show. This script walks the public sandbox exactly as a judge would —
PM analysis, PM approval, HSE countersign, document controller execution,
independent verification, closure — and then prints what the finals page now
projects. It uses only the public sandbox API and the role tickets that the
session itself issues; it never forges a ticket or skips a step.

Usage:
    python scripts/finals_warmup.py https://<web-domain>          # via Web BFF
    python scripts/finals_warmup.py http://localhost:8001 --direct  # API directly
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _call(base: str, method: str, path: str, ticket: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if ticket:
        headers["X-Competition-Role-Ticket"] = ticket
    request = urllib.request.Request(base + path, method=method, headers=headers, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {body}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", help="Web origin (uses /backend) or API origin with --direct")
    parser.add_argument("--direct", action="store_true", help="base_url is the API itself, not the Web BFF")
    args = parser.parse_args()
    base = args.base_url.rstrip("/") + ("" if args.direct else "/backend")

    started = time.perf_counter()
    created = _call(base, "POST", "/competition/sessions")
    sid = created["session"]["id"]
    tickets = {role: row["ticket"] for role, row in created["role_tickets"].items()}
    print(f"session {sid}")

    state = _call(base, "POST", f"/competition/sessions/{sid}/analyze", tickets["project_manager"])
    approvals = {row["required_role"]: row["id"] for row in state["approvals"]}
    print(f"  analyze      evidence={len(state['evidence'])} approvals={sorted(approvals)}")
    for role in ("project_manager", "hse_manager"):
        state = _call(base, "POST", f"/competition/sessions/{sid}/approvals/{approvals[role]}/approve", tickets[role])
        print(f"  approve      {role}")
    for step, role in (("execute", "engineer"), ("verify", "verifier"), ("close", "closer")):
        state = _call(base, "POST", f"/competition/sessions/{sid}/{step}", tickets[role])
        print(f"  {step:<12} {role} -> action {state['action']['status']}")
    if not state.get("complete"):
        print("FAILED: session did not reach an intact signed closure", file=sys.stderr)
        return 1

    overview = _call(base, "GET", "/competition/finals/overview?lang=zh")
    source = overview["mission"].get("source", {})
    print(f"done in {time.perf_counter() - started:.1f}s")
    print(f"finals page source: {source.get('kind')} {source.get('session_id')} actors={source.get('distinct_actors')}")
    for step in overview["mission"]["steps"]:
        print(f"  {step['index']} {step['status']:<24} {step['detail']}")
    return 0 if source.get("session_id") == sid else 1


if __name__ == "__main__":
    raise SystemExit(main())
