#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finite synthetic HTTP walkthrough; stdlib only, no external services/models."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "portage"))
from decisions import ShadowDecider  # noqa: E402
from gateway import Gateway, Ledger, open_once, validate_manifest  # noqa: E402


def run():
    state = {"active": True, "transport_requests": 0, "aliases": []}

    class SyntheticService(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_json(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.send_json({"active": state["active"], "project": "course01"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["transport_requests"] += 1
            state["aliases"].append(body["model"])
            self.send_json(
                {
                    "usage": {"total_tokens": 12},
                    "choices": [
                        {"message": {"role": "assistant", "content": "Synthetic fixture"}}
                    ],
                }
            )

    def serve(stack, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(server.server_close)
        stack.callback(lambda: thread.join(timeout=5))
        stack.callback(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    with (
        tempfile.TemporaryDirectory(prefix="portage-decision-demo-") as directory,
        ExitStack() as stack,
    ):
        upstream = serve(stack, ThreadingHTTPServer(("127.0.0.1", 0), SyntheticService))
        models = {
            alias: {
                "operation": "embeddings" if alias == "embedding" else "chat/completions",
                "endpoint": upstream,
                "max_output_tokens": 100,
                "max_request_tokens": 1000,
                "revision": "synthetic-v1",
                "provenance": "fabricated local fixture",
                "resource_limits": {"cpus": 1, "memory_mb": 128},
                "synthetic": True,
                "institutional_only": True,
            }
            for alias in (
                "classifier",
                "code_small",
                "code_large",
                "research_synthesis",
                "embedding",
            )
        }
        manifest = {
            "project": "course01",
            "mode": "synthetic",
            "models": models,
            "project_allowance": 10000,
            "participant_allowance": 10000,
            "concurrency": 1,
        }
        validate_manifest(manifest, "synthetic")
        ledger = Ledger(Path(directory) / "ledger.sqlite")
        ledger.project("course01", 10000, 1)
        ledger.member("course01", "learner1", 10000)
        token = ledger.issue("course01", subject="learner1")
        service = Gateway(
            ("127.0.0.1", 0),
            ledger,
            manifest,
            "synthetic-control",
            "synthetic-upstream",
            upstream,
            "synthetic-authority",
            shadow_decider=ShadowDecider(),
        )
        origin = serve(stack, service)

        def request(text):
            req = urllib.request.Request(
                origin + "/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": "code_small",
                        "messages": [{"role": "user", "content": text}],
                    }
                ).encode(),
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                },
            )
            try:
                with open_once(req, timeout=5) as response:
                    response.read()
                    return response.status
            except urllib.error.HTTPError as exc:
                exc.read()
                return exc.code

        statuses = [
            request(text)
            for text in (
                "Explain a Python loop",
                "Find evidence for this hypothesis",
                "unclear request",
            )
        ]
        state["active"] = False
        statuses.append(request("Explain a Python loop"))
        with ledger.db() as db:
            reports = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT report FROM shadow_decisions ORDER BY rowid"
                )
            ]
        usage = ledger.usage("course01", "learner1")
        checks = {
            "http_success_and_revocation": statuses == [200, 200, 200, 403],
            "typed_rules_advice": reports[0]["decisions"]["recommended_tier"]["value"]
            == "code_small",
            "strong_advice_does_not_reroute": (
                reports[1]["decisions"]["recommended_tier"]["value"] == "code_large"
                and state["aliases"] == ["code_small"] * 3
            ),
            "unknown_abstains": reports[2]["status"] == "abstained",
            "one_event_per_admitted_chat": len(reports) == 3,
            "revoked_request_has_no_transport": state["transport_requests"] == 3,
            "settled_synthetic_usage": usage["committed"] == 36,
        }
        result = {
            "readiness": "synthetic_software_only",
            "passed": all(checks.values()),
            "checks": checks,
            "http_statuses": statuses,
            "actual_loopback_inference_requests": state["transport_requests"],
            "external_model_requests": 0,
            "sdk_retries": 0,
            "trained_decision_model_executed": False,
            "decisions": reports,
        }
    # All owned servers and the temporary ledger are closed before returning.
    result["cleanup"] = "owned_servers_closed_and_temporary_state_removed"
    return result


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)
