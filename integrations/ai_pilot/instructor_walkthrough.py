#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Local synthetic instructor console, two tier calls, USD 0.025 maximum reserve."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import subprocess
import threading
import time
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gateway import Gateway, Ledger
from openrouter_adapter import (
    MODEL,
    WALKTHROUGH_CASES,
    WALKTHROUGH_SYSTEM,
    WalkthroughGuard,
    load_key,
    validate_catalog,
    walkthrough_manifest,
)
from openrouter_pilot import BELAY_REVISION, metadata, serve


class BelaySession:
    """Use the real Belay SDK and enforced accounting; no application monkeypatch."""

    def __init__(self, source, directory, origin, token):
        import sys

        from sqlalchemy import create_engine

        os.environ["DATABASE_URL"] = "sqlite:///" + str(directory / "app.sqlite")
        sys.path.insert(0, str(source / "backend"))
        from app.agent.llm import PortageProvider
        from app.config import settings
        from app.controls.contracts import Limits, Policy
        from app.controls.ledger import Ledger as BelayLedger

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
            "openai_final_content_only": True,
        }.items():
            setattr(settings, key, value)
        self.engine = create_engine("sqlite:///" + str(directory / "belay.sqlite"))
        self.ledger = BelayLedger(self.engine)
        self.ledger.initialize(
            Policy(
                version="instructor-tier-walkthrough-v1",
                price_version="cap-v1",
                currency="USD",
                input_price=1,
                output_price=2,
                deployment=Limits(tokens=4096, microunits=25000),
                institution=Limits(),
                classroom=Limits(),
                learner=Limits(),
            )
        )
        self.provider = PortageProvider()

    def call(self, case):
        from app.controls.contracts import Scope
        from app.controls.runtime import operation

        with operation(
            self.ledger,
            Scope("synthetic", "synthetic", "smoke001", "synthetic01"),
            "walkthrough-" + case["name"],
        ):
            return self.provider.json(
                role=case["role"],
                tier=case["tier"],
                system=WALKTHROUGH_SYSTEM,
                user=case["prompt"],
                max_tokens=128,
            )

    def close(self):
        self.provider._client.close()
        self.engine.dispose()


def accepted_hint(value):
    """Structural acceptance only. Human review determines instructional quality."""
    return (
        type(value) is dict
        and set(value) == {"hint"}
        and type(value["hint"]) is str
        and 0 < len(value["hint"].strip()) <= 600
    )


class Walkthrough:
    def __init__(self, guard, session, ledger, membership, source):
        self.guard, self.session, self.ledger = guard, session, ledger
        self.membership = membership
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.nonce = secrets.token_urlsafe(32)
        self.record = {
            "profile": "synthetic-instructor-tier-walkthrough-v1",
            "source": source,
            "belay_revision": BELAY_REVISION,
            "model": MODEL,
            "shared_model_for_both_tiers": True,
            "results": {},
            "owned_servers_closed": False,
            "instructional_acceptance": "pending_human_review",
            "prior_unknown_liability_usd": 0.025,
            "python": platform.python_version(),
            "portage_lock_sha256": hashlib.sha256(
                (Path(__file__).parents[2] / "uv.lock").read_bytes()
            ).hexdigest(),
            "browser_sha256": hashlib.sha256(
                Path(__file__).with_suffix(".html").read_bytes()
            ).hexdigest(),
        }
        self.save()

    def snapshot(self):
        return {
            **self.record,
            "accounting": self.guard.summary(),
            "belay_ledger": self.session.ledger.summary(),
            "portage_ledger": self.ledger.usage("smoke001", "synthetic01"),
            "remaining_seconds": int(self.guard.remaining()),
            "active": self.membership["active"] and not self.stop.is_set(),
            "cases": WALKTHROUGH_CASES,
        }

    def save(self):
        # Private directory and source-fixed inputs only; never credentials.
        target = self.guard.directory / "result.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.snapshot(), indent=2, allow_nan=False))
        temporary.replace(target)

    def execute(self, name):
        if not self.lock.acquire(blocking=False):
            return 409, {"error": "request_in_progress"}
        try:
            if name not in {c["name"] for c in WALKTHROUGH_CASES}:
                return 400, {"error": "unknown_case"}
            if name in self.record["results"]:
                return 409, {"error": "already_attempted"}
            if self.stop.is_set() or not self.membership["active"]:
                return 403, {"error": "session_stopped_or_revoked"}
            if self.guard.remaining() <= 0:
                return 403, {"error": "session_expired"}
            if any(not r["passed"] for r in self.record["results"].values()):
                return 403, {"error": "prior_failure_requires_review"}
            case = next(c for c in WALKTHROUGH_CASES if c["name"] == name)
            entry = {"passed": False, "status": "started", "tier": case["tier"]}
            self.record["results"][name] = entry
            self.save()  # consume UI action before provider, including failed work
            started = time.monotonic()
            try:
                value = self.session.call(case)
                passed = (
                    accepted_hint(value)
                    and self.guard.attempts.get(name, {}).get("state") == "complete"
                )
                entry.update(
                    passed=passed,
                    status="passed" if passed else "failed",
                    output=value,
                )
            except Exception as error:
                entry.update(status="failed", error_type=type(error).__name__)
            entry["elapsed_seconds"] = time.monotonic() - started
            self.save()
            return 200 if entry["passed"] else 502, self.snapshot()
        finally:
            self.lock.release()


class ConsoleServer(ThreadingHTTPServer):
    """Bound slow clients so shutdown cannot hang on an incomplete request."""

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address


def console_handler(walkthrough):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, raw, kind="application/json"):
            if isinstance(raw, dict):
                raw = json.dumps(raw, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; "
                "script-src 'nonce-" + walkthrough.nonce + "'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "host_refused"})
            if self.path == "/":
                page = Path(__file__).with_suffix(".html").read_text()
                page = page.replace("__NONCE__", walkthrough.nonce)
                return self.reply(200, page.encode(), "text/html; charset=utf-8")
            if self.path == "/status":
                with walkthrough.lock:
                    return self.reply(200, walkthrough.snapshot())
            return self.reply(404, {"error": "not_found"})

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if (
                not self.valid_host()
                or self.headers.get("Origin") != origin
                or self.headers.get("X-Walkthrough-Nonce") != walkthrough.nonce
                or self.headers.get("Content-Type") != "application/json"
            ):
                return self.reply(403, {"error": "origin_or_nonce_refused"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 128 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("bounded JSON required")
                self.connection.settimeout(3)
                raw = self.rfile.read(size)
                body = json.loads(raw)
            except (ValueError, OSError):
                return self.reply(400, {"error": "invalid_body"})
            if self.path == "/run" and type(body) is dict and set(body) == {"case"}:
                if type(body["case"]) is not str:
                    return self.reply(400, {"error": "invalid_case"})
                status, value = walkthrough.execute(body["case"])
                return self.reply(status, value)
            if self.path in {"/stop", "/revoke"} and body == {}:
                walkthrough.membership["active"] = False
                if self.path == "/stop":
                    walkthrough.stop.set()
                with walkthrough.lock:
                    walkthrough.save()
                return self.reply(200, {"status": "stopped_or_revoked"})
            return self.reply(400, {"error": "operation_refused"})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--belay-source", type=Path, required=True)
    parser.add_argument("--execute-approved", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved:
        parser.error("explicit --execute-approved required: two requests, USD 0.025")
    os.umask(0o077)
    source, directory = args.belay_source.resolve(), args.output.resolve()
    if directory.exists():
        raise ValueError("fresh directory required; no resume or replay")
    if (
        subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        != BELAY_REVISION
        or subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain", "--", "backend"],
            text=True,
        ).strip()
    ):
        raise ValueError("Belay source pin or clean backend check failed")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise ValueError("commit walkthrough source before live execution")
    __import__("openai")
    __import__("sqlalchemy")
    key = load_key(args.env_file)
    catalog_raw = metadata("models/openai/gpt-4.1-mini/endpoints")
    guard = WalkthroughGuard(directory, validate_catalog(catalog_raw))
    (directory / "catalog.json").write_text(json.dumps(catalog_raw, indent=2))
    membership = {"active": True}

    class Authority(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            raw = json.dumps({"active": membership["active"], "project": "smoke001"})
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw.encode())

    walkthrough = None
    try:
        with ExitStack() as stack:
            authority = serve(stack, ThreadingHTTPServer(("127.0.0.1", 0), Authority))
            ledger = Ledger(directory / "portage.sqlite")
            ledger.project("smoke001", 4096, 1)
            ledger.member("smoke001", "synthetic01", 4096)
            token = ledger.issue("smoke001", subject="synthetic01")
            gateway = Gateway(
                ("127.0.0.1", 0),
                ledger,
                walkthrough_manifest(),
                secrets.token_urlsafe(),
                key,
                authority,
                secrets.token_urlsafe(),
                external_guard=guard,
            )
            origin = serve(stack, gateway)
            session = BelaySession(source, directory, origin, token)
            stack.callback(session.close)
            walkthrough = Walkthrough(guard, session, ledger, membership, revision)
            console = ConsoleServer(("127.0.0.1", 0), console_handler(walkthrough))
            console.daemon_threads = False
            url = serve(stack, console)
            print(
                json.dumps(
                    {"url": url, "synthetic_only": True, "deadline": guard.deadline}
                ),
                flush=True,
            )
            while guard.remaining() > 0 and not walkthrough.stop.wait(timeout=1):
                pass
            membership["active"] = False
            walkthrough.stop.set()
        walkthrough.record["owned_servers_closed"] = True
    finally:
        if walkthrough:
            walkthrough.save()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            json.dumps(
                {"error_type": type(error).__name__, "see_retained_evidence": True}
            )
        )
        raise SystemExit(1) from None
