# SPDX-License-Identifier: Apache-2.0
"""Explicit real OpenBao + real Portage transport controls; synthetic provider only."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gateway import Gateway, Ledger
from openbao_credentials import OpenBaoCredential
from openbao_local import SECRET_PATH, LocalBao, private
from openrouter_pilot import serve


def run(binary, output):
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {
        "synthetic_only": True,
        "paid_requests": 0,
        "passed": [],
        "failed": [],
        "cleanup": False,
        "source": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    bao = None
    calls = []
    raw_keys = ["sk-or-local-" + secrets.token_hex(16) for _ in range(2)]
    state = {"key": raw_keys[0], "active": True, "fail": False}

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps({"active": state["active"], "project": "course01"}).encode()
            )

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            matched = secrets.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + state["key"]
            )
            calls.append(
                {
                    "credential_matched": matched,
                    "generation": raw_keys.index(state["key"]) + 1,
                }
            )
            self.send_response(503 if state["fail"] else 200 if matched else 401)
            self.end_headers()
            self.wfile.write(b'{"usage":{"total_tokens":12},"choices":[]}')

    try:
        bao = LocalBao(binary, output / "bao")
        bao.start()
        bao.initialize()
        bao.put(state["key"])
        source = OpenBaoCredential(bao.address, bao.ca, bao.token_file)
        report["openbao"] = {"version": bao.version, "binary_sha256": bao.binary_sha256}
        with ExitStack() as stack:
            origin = serve(stack, ThreadingHTTPServer(("127.0.0.1", 0), Upstream))
            model = {
                "operation": "chat/completions",
                "endpoint": origin,
                "max_output_tokens": 100,
                "max_request_tokens": 1000,
                "revision": "fixture-v1",
                "synthetic": True,
                "institutional_only": True,
            }
            manifest = {
                "mode": "synthetic",
                "project": "course01",
                "models": {"code_small": model},
            }
            ledger = Ledger(output / "portage.sqlite")
            ledger.project("course01", 100000, 2)
            ledger.member("course01", "learner1", 100000)
            token = ledger.issue("course01", subject="learner1")
            gateway = Gateway(
                ("127.0.0.1", 0),
                ledger,
                manifest,
                "control",
                "",
                origin,
                "authority",
                credential_source=source,
            )
            url = serve(stack, gateway)

            def request(key=token):
                body = {
                    "model": "code_small",
                    "messages": [{"role": "user", "content": "synthetic"}],
                    "max_tokens": 20,
                }
                req = urllib.request.Request(
                    url + "/v1/chat/completions",
                    data=json.dumps(body).encode(),
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                    },
                )
                try:
                    with urllib.request.urlopen(req, timeout=6) as response:
                        return response.status, response.read()
                except urllib.error.HTTPError as exc:
                    return exc.code, exc.read()

            def success(name):
                before = len(calls)
                status, _ = request()
                assert status == 200
                assert len(calls) == before + 1 and calls[-1]["credential_matched"]
                report["passed"].append(name)

            def refusal(name, status=503, key=token):
                before, usage = len(calls), ledger.usage("course01", "learner1")
                actual, body = request(key)
                assert actual == status
                assert (
                    len(calls) == before and ledger.usage("course01", "learner1") == usage
                )
                assert all(value.encode() not in body for value in raw_keys)
                report["passed"].append(name)

            success("initial-secret-authenticates-at-actual-upstream")
            state["key"] = raw_keys[1]
            bao.put(state["key"])
            success("rotation-without-gateway-restart")
            limited = bao.token_file.read_text()
            for name, method, path, body in (
                ("cross-component-read-denied", "GET", "secret/data/cairn/signing", None),
                (
                    "credential-write-denied",
                    "POST",
                    SECRET_PATH,
                    {"data": {"api_key": "tamper"}},
                ),
                ("secret-enumeration-denied", "LIST", "secret/metadata", None),
                (
                    "policy-escalation-denied",
                    "PUT",
                    "sys/policies/acl/portage-reader",
                    {"policy": 'path "*" {capabilities=["sudo"]}'},
                ),
            ):
                assert bao.request(method, path, body, limited)[0] == 403
                report["passed"].append(name)
            refusal("unauthenticated-client-no-transport", 401, "wrong-token")
            state["active"] = False
            refusal("revoked-membership-no-transport", 403)
            state["active"] = True
            bao.install_token(policy="no-provider")
            refusal("wrong-service-role-before-admission")
            token_to_revoke = bao.install_token()
            bao.admin("POST", "auth/token/revoke", {"token": token_to_revoke})
            refusal("revoked-bao-token-no-cached-key-fallback")
            bao.install_token(ttl="1s")
            time.sleep(1.2)
            refusal("expired-bao-token-before-admission")
            bao.install_token()
            bao.token_file.chmod(0o644)
            refusal("unsafe-token-file-before-admission")
            bao.token_file.chmod(0o600)
            bao.put("bad\r\nInjected: value")
            refusal("malformed-key-before-admission")
            bao.put(state["key"])
            bao.admin("POST", "sys/seal")
            refusal("sealed-bao-before-admission")
            bao.unseal_server()
            success("unseal-recovery-preserves-ledger")
            bao.stop()
            refusal("unreachable-bao-before-admission")
            backup = bao.backup()
            bao.start()
            refusal("restarted-server-remains-sealed")
            bao.unseal_server()
            success("persistent-restart-recovery")
            # Save a known value, mutate live storage, then restore the stopped backup.
            bao.put(raw_keys[0])
            assert source() == raw_keys[0]
            bao.stop()
            bao.restore(backup)
            bao.start()
            bao.unseal_server()
            assert source() == state["key"]
            # A backup can restore old tokens: revoke the restored service token
            # before resuming, and issue a fresh one with the same narrow policy.
            bao.admin("POST", "auth/token/revoke", {"token": bao.token_file.read_text()})
            refusal("restored-service-token-revoked-before-resume")
            bao.install_token()
            success("cold-backup-restoration-same-portage-ledger")
            state["fail"] = True
            before = len(calls)
            assert request()[0] == 503
            assert len(calls) == before + 1
            usage = ledger.usage("course01", "learner1")
            # The existing handler finalizes failures after writing its response.
            # Observe the durable finalizer rather than racing response receipt.
            for _ in range(40):
                if usage["unresolved"] > 0:
                    break
                time.sleep(0.05)
                usage = ledger.usage("course01", "learner1")
            assert usage["unresolved"] > 0
            report["passed"].append(
                "admitted-provider-failure-retains-unknown-usage-no-retry"
            )
            report["ledger"] = usage
            report["transport_observations"] = calls
            report["provider_transports"] = len(calls)
            # Audit proves allowed and denied access; keep raw audit private.
            lines = [json.loads(line) for line in bao.audit.read_text().splitlines()]
            assert any(row.get("error") for row in lines)
            assert any(row.get("request", {}).get("path") == SECRET_PATH for row in lines)
            assert all(key not in bao.audit.read_text() for key in raw_keys)
            report["audit"] = {
                "records": len(lines),
                "sha256": hashlib.sha256(bao.audit.read_bytes()).hexdigest(),
            }
            report["passed"].append(
                "audit-records-allow-and-deny-without-plaintext-provider-key"
            )
    except BaseException as exc:
        report["failed"].append(
            {"type": type(exc).__name__, "after_passed": len(report["passed"])}
        )
        raise
    finally:
        if bao:
            bao.close()
            report["cleanup"] = bao.proc is None and not bao.token_file.exists()
        private(output / "result.json", json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bao", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-local", action="store_true", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    run(args.bao, args.output)
