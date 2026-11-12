#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Four fixed synthetic requests through real Portage; explicit execution only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gateway import Gateway, Ledger, inference_attempt, open_once
from openrouter_adapter import (
    BELAY_SYSTEM,
    CASES,
    SmokeGuard,
    case_body,
    load_key,
    manifest,
    validate_catalog,
)

BELAY_REVISION = "c5a27073e74b9eeb7ab697190915378b50132883"


def belay_call(source, directory, origin, token, case):
    """Existing provider and controls, isolated synthetic ledger, no app edits."""
    from sqlalchemy import create_engine

    os.environ["DATABASE_URL"] = "sqlite:///" + str(directory.resolve() / "app.sqlite")
    sys.path.insert(0, str(source.resolve() / "backend"))
    from app.agent.llm import PortageProvider
    from app.config import settings
    from app.controls.contracts import Limits, Policy, Scope
    from app.controls.ledger import Ledger as BelayLedger
    from app.controls.runtime import operation

    for key, value in {
        "controls_mode": "enforced",
        "provider": "portage",
        "portage_deployment": "synthetic",
        "portage_institution": "synthetic",
        "portage_classroom": "smoke001",
        "openai_base_url": origin + "/v1",
        "openai_api_key": token,
        "openai_response_format": "json_object",
        "openai_thinking_mode": "",
        "openai_reasoning": False,
        "llm_temperature": 0.0,
    }.items():
        setattr(settings, key, value)
    engine = create_engine("sqlite:///" + str(directory.resolve() / "belay.sqlite"))
    ledger = BelayLedger(engine)
    ledger.initialize(
        Policy(
            version="openrouter-smoke-v1",
            price_version="cap-v1",
            currency="USD",
            input_price=1,
            output_price=2,
            deployment=Limits(tokens=2048, microunits=12500),
            institution=Limits(),
            classroom=Limits(),
            learner=Limits(),
        )
    )
    provider = PortageProvider()
    try:
        with operation(
            ledger,
            Scope("synthetic", "synthetic", "smoke001", "synthetic01"),
            "fixed-hint-check",
        ):
            value = provider.json(
                role="planner",
                tier="fast",
                system=BELAY_SYSTEM,
                user=case["prompt"],
                max_tokens=128,
            )
        return value, ledger.summary()
    finally:
        provider._client.close()
        engine.dispose()


def evaluate(case, raw):
    if case["stream"]:
        parts, terminal = [], False
        for line in raw.decode().splitlines():
            if line == "data: [DONE]":
                terminal = True
            elif line.startswith("data: "):
                value = json.loads(line[6:])
                if value.get("error"):
                    return False
                for choice in value.get("choices", []):
                    parts.append(choice.get("delta", {}).get("content") or "")
        return terminal and "".join(parts).strip() == case["expected"]
    value = json.loads(raw)
    return json.loads(value["choices"][0]["message"]["content"]) == case["expected"]


def serve(stack, server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stack.callback(server.server_close)
    stack.callback(lambda: thread.join(timeout=5))
    stack.callback(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}"


def metadata(path, key=None):
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/" + path,
        headers={"Authorization": "Bearer " + key} if key else {},
    )
    with inference_attempt(request, timeout=20) as response:
        raw = response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError("metadata too large")
        return json.loads(raw)


def run(env_file, directory, belay_source=None, continue_from=None):
    directory = Path(directory)
    if directory.exists():
        raise ValueError("run directory exists; no resume or replay")
    if belay_source:
        revision = subprocess.check_output(
            ["git", "-C", str(belay_source), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(belay_source), "status", "--porcelain", "--", "backend"],
            text=True,
        ).strip()
        if revision != BELAY_REVISION or dirty:
            raise ValueError("Belay source pin or clean backend check failed")
        __import__("openai")
        __import__("sqlalchemy")
    prior = None
    if continue_from:
        original = json.loads((continue_from / "result.json").read_text())
        diagnostic = json.loads(
            (continue_from.parent / "planned-case-02-diagnostic.json").read_text()
        )
        created = json.loads(
            (continue_from / "journal.jsonl").read_text().splitlines()[0]
        )
        if (
            original["accounting"]["dispatch_claims"] != 1
            or original["cases"][0]["name"] != "arithmetic_json"
            or diagnostic["dispatch_claims"] != 1
            or diagnostic["case"] != "extraction_json"
            or diagnostic["http_status"] != 404
        ):
            raise ValueError("unexpected prior evidence")
        prior = {
            "cases": ["arithmetic_json", "extraction_json"],
            "deadline": created["deadline"],
            "evidence": str(continue_from.resolve()),
        }
        if time.time() >= prior["deadline"]:
            raise ValueError("original deadline expired")
    key = load_key(env_file)
    key_data = metadata("key", key)["data"]
    catalog_raw = metadata("models/openai/gpt-4.1-mini/endpoints")
    catalog = validate_catalog(catalog_raw)
    guard = SmokeGuard(directory, catalog, prior=prior)
    (directory / "catalog.json").write_text(json.dumps(catalog_raw, indent=2))
    record = {
        "scope": "external_model_fixed_synthetic_transport_only",
        "source": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "metadata_requests": 2,
        "key_limit": key_data.get("limit"),
        "account_cap_configured": key_data.get("limit") is not None,
        "checks": {},
        "cases": [],
        "all_passed": False,
        "continuation": prior,
        "retention": "ZDR unavailable; fixed synthetic inputs only",
        "python": platform.python_version(),
        "belay_revision": BELAY_REVISION if belay_source else None,
        "portage_lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
    }
    state = {"active": True}

    class Authority(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            raw = json.dumps({"active": state["active"], "project": "smoke001"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    try:
        with ExitStack() as stack:
            authority = serve(stack, ThreadingHTTPServer(("127.0.0.1", 0), Authority))
            ledger = Ledger(directory / "ledger.sqlite")
            ledger.project("smoke001", 8192, 1)
            ledger.member("smoke001", "synthetic01", 8192)
            token = ledger.issue("smoke001", subject="synthetic01")
            gateway = Gateway(
                ("127.0.0.1", 0),
                ledger,
                manifest(),
                secrets.token_urlsafe(),
                key,
                authority,
                secrets.token_urlsafe(),
                external_guard=guard,
            )
            origin = serve(stack, gateway)

            def request(body, credential=token):
                req = urllib.request.Request(
                    origin + "/v1/chat/completions",
                    data=json.dumps(body).encode(),
                    headers={
                        "Authorization": "Bearer " + credential,
                        "Content-Type": "application/json",
                    },
                )
                try:
                    with open_once(req, timeout=70) as response:
                        return response.status, response.read(262145)
                except urllib.error.HTTPError as error:
                    return error.code, error.read(262145)

            selected = [case for case in CASES if case["name"] not in guard.blocked_cases]
            status, raw = request(case_body(selected[0]), "invalid")
            (directory / "invalid-credential.json").write_bytes(raw)
            record["checks"]["invalid_credential_no_dispatch"] = (
                status == 401 and not guard.attempts
            )
            if not record["checks"]["invalid_credential_no_dispatch"]:
                raise ValueError("pre-admission control failed")
            for case in selected:
                started = time.monotonic()
                if belay_source and case["name"] == "hint_json":
                    value, record["belay_ledger"] = belay_call(
                        belay_source, directory, origin, token, case
                    )
                    status = 200
                    raw = json.dumps(
                        {"choices": [{"message": {"content": json.dumps(value)}}]}
                    ).encode()
                else:
                    status, raw = request(case_body(case))
                (directory / (case["name"] + ".response")).write_bytes(raw)
                try:
                    passed = status == 200 and evaluate(case, raw)
                except (ValueError, KeyError, IndexError, TypeError):
                    passed = False
                passed = (
                    passed
                    and guard.attempts.get(case["name"], {}).get("state") == "complete"
                )
                record["cases"].append(
                    {
                        "name": case["name"],
                        "status": status,
                        "passed": passed,
                        "elapsed_seconds": time.monotonic() - started,
                    }
                )
                if not passed:
                    break
            before = guard.summary()["dispatch_claims"]
            state["active"] = False
            status, raw = request(case_body(selected[0]))
            (directory / "revoked-member.json").write_bytes(raw)
            record["checks"]["revoked_member_no_dispatch"] = (
                status == 403 and guard.summary()["dispatch_claims"] == before
            )
            record["ledger_usage"] = ledger.usage("smoke001", "synthetic01")
        record["owned_servers_closed"] = True
        record["selected_cases_passed"] = (
            len(record["cases"]) == len(selected)
            and all(x["passed"] for x in record["cases"])
            and all(record["checks"].values())
        )
        record["all_passed"] = record["selected_cases_passed"] and prior is None
    except Exception as error:
        record["error_type"] = type(error).__name__
    finally:
        record["accounting"] = guard.summary()
        (directory / "result.json").write_text(
            json.dumps(record, indent=2, allow_nan=False)
        )
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--belay-source", type=Path)
    parser.add_argument("--continue-from", type=Path)
    parser.add_argument("--execute-approved", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved:
        parser.error(
            "explicit --execute-approved required; "
            "four synthetic requests, $0.05 application budget"
        )
    try:
        result = run(args.env_file, args.output, args.belay_source, args.continue_from)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["all_passed"] else 1)
    except Exception as error:
        print(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "executed": "see durable evidence if created",
                }
            )
        )
        raise SystemExit(1) from None
