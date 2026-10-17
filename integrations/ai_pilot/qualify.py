# SPDX-License-Identifier: Apache-2.0
"""Bounded, opt-in direct Ollama qualification; no installation or service lifecycle.

Default: synthetic HTTP controls and an honest NOT RUN capacity record.
The live path requires an operator-completed manifest and --execute-approved.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import platform
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import gateway

ROOT = Path(__file__).resolve().parents[2]
TASKS = (
    ("arithmetic", "What is 6 times 7? Reply with only the integer.", "42"),
    ("extraction", "From 'red, blue, green', return only the second color.", "blue"),
)
LIVE_GATES = (
    "model_identity",
    "availability",
    "bounded_task_quality",
    "latency",
    "concurrency_1_and_2",
    "attempt_accounting",
    "effective_context",
    "resident_memory_samples",
    "engine_peak_memory",
    "engine_attempt_visibility",
    "token_reservation_bound",
    "operator_restart",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def source_identity():
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    paths = [
        "integrations/ai_pilot/gateway.py",
        "integrations/ai_pilot/qualify.py",
        "src/portage/pilot_ledger.py",
        "tests/test_direct_qualification.py",
        "tests/test_pilot_gateway.py",
        "tests/test_pilot_ledger.py",
    ]
    return {
        "revision": revision,
        "sha256": {path: digest((ROOT / path).read_bytes()) for path in paths},
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def controls(output):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_direct_qualification.py",
            "tests/test_pilot_gateway.py",
            "tests/test_pilot_ledger.py",
            f"--junitxml={output / 'controls.xml'}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    (output / "controls.log").write_text(result.stdout + result.stderr)
    cases = []
    if (output / "controls.xml").exists():
        for case in ET.parse(output / "controls.xml").iter("testcase"):
            status = "PASS"
            if case.find("failure") is not None or case.find("error") is not None:
                status = "FAIL"
            elif case.find("skipped") is not None:
                status = "NOT RUN"
            cases.append({"control": case.attrib["name"], "status": status})
    return {
        "status": "PASS" if result.returncode == 0 and cases else "FAIL",
        "evidence_class": "synthetic loopback HTTP; no model",
        "cases": cases,
    }


def validate_live(config):
    gateway.validate_manifest(config, "qualification")
    model = config["models"]["code_small"]
    if model.get("synthetic") is not False:
        raise ValueError("live qualification requires a non-synthetic model")
    if not re.fullmatch(r"[a-f0-9]{64}", model["revision"]):
        raise ValueError("record the exact installed Ollama model digest")
    if not re.fullmatch(r"[a-f0-9]{64}", model["template_sha256"]):
        raise ValueError("record the exact template SHA256")
    capacity = config.get("approved_capacity", {})
    for field in (
        "operator",
        "approval_reference",
        "host",
        "resource_limit_evidence",
        "engine_version",
        "license_review",
    ):
        if not isinstance(capacity.get(field), str) or not capacity[field].strip():
            raise ValueError(f"complete approved_capacity.{field}")
    for field in ("local_only", "egress_blocked", "existing_installed_model"):
        if capacity.get(field) is not True:
            raise ValueError(f"capacity must attest {field}")
    deadline_time = datetime.fromisoformat(capacity["deadline_utc"])
    if deadline_time.tzinfo is None:
        raise ValueError("deadline must include a timezone")
    deadline = deadline_time.timestamp()
    if not 0 < deadline - time.time() <= 1800:
        raise ValueError("deadline must be in the next 30 minutes")
    if config["concurrency"] != 2:
        raise ValueError("this frozen protocol tests concurrency 1 and 2 only")
    if model["max_output_tokens"] > 128 or model["max_request_tokens"] > 4096:
        raise ValueError("protocol caps output at 128 and each reservation at 4096")
    # Exactly 16 attempted calls: two tasks, two transport modes, two
    # concurrency cells, two repetitions. No warmup, retry or background call.
    if config["project_allowance"] > 65536 or config["participant_allowance"] > 65536:
        raise ValueError("qualification allowance cannot exceed 65536 tokens")
    required = (
        sum(
            gateway.prepare_request(
                {
                    "model": "code_small",
                    "messages": [{"role": "user", "content": prompt}],
                },
                config["models"],
                "chat/completions",
            )[1]
            for _, prompt, _ in TASKS
        )
        * 8
    )
    if min(config["project_allowance"], config["participant_allowance"]) < required:
        raise ValueError("allowance must reserve all 16 attempts conservatively")
    return deadline


def engine_json(origin, path, body=None):
    request = urllib.request.Request(
        origin.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with gateway.open_once(request, timeout=5) as response:
        return json.load(response)


def pin_engine(config):
    model = config["models"]["code_small"]
    origin, name = model["endpoint"], model["upstream_model"]
    version = engine_json(origin, "/api/version").get("version")
    if version != config["approved_capacity"]["engine_version"]:
        raise ValueError("engine version differs from approved manifest")
    tags = engine_json(origin, "/api/tags").get("models", [])
    candidates = [row for row in tags if row.get("name") == name]
    if len(candidates) != 1:
        raise ValueError("exact approved model must already be installed")
    installed = candidates[0]
    if installed.get("digest") != model["revision"] or installed.get("size", 0) <= 0:
        raise ValueError("installed artifact digest or local size disagrees")
    shown = engine_json(origin, "/api/show", {"model": name})
    if any(shown.get(k) or installed.get(k) for k in ("remote_host", "remote_model")):
        raise ValueError("cloud-backed models are excluded")
    if digest(shown.get("template", "").encode()) != model["template_sha256"]:
        raise ValueError("template differs from approved manifest")
    if shown.get("details", {}).get("quantization_level") != model["quantization"]:
        raise ValueError("quantization differs from approved manifest")
    return {
        "engine_version": version,
        "model_digest": installed["digest"],
        "template_sha256": model["template_sha256"],
        "quantization": model["quantization"],
        "installed_bytes": installed["size"],
    }


class SyntheticAuthority(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        active = self.path == "/internal/member/qualifier01"
        body = json.dumps({"active": active, "project": self.server.project}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}"


def measured_call(url, token, task, stream, timeout):
    name, prompt, expected = task
    begin = time.monotonic()
    row = {"task": name, "stream": stream, "availability": "FAIL", "quality": "NOT RUN"}
    content, first = "", None
    request = urllib.request.Request(
        url + "/v1/chat/completions",
        data=json.dumps(
            {
                "model": "code_small",
                "stream": stream,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with gateway.open_once(request, timeout=timeout + 10) as response:
            row["request_id"] = response.headers.get("X-Portage-Request-Id")
            complete = not stream
            if stream:
                for line in response:
                    if line.strip() == b"data: [DONE]":
                        complete = True
                        break
                    if line.startswith(b"data: "):
                        chunk = json.loads(line[6:])
                        for choice in chunk.get("choices", []):
                            text = choice.get("delta", {}).get("content") or ""
                            if text and first is None:
                                first = time.monotonic() - begin
                            content += text
            else:
                result = json.load(response)
                content = result["choices"][0]["message"]["content"]
            if complete and content:
                row["availability"] = "PASS"
                row["quality"] = "PASS" if content.strip() == expected else "FAIL"
            row["output_sha256"] = digest(content.encode())
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        # No payloads, credentials or upstream response/error bodies in evidence.
        row["error_type"] = type(error).__name__
    row["seconds"] = time.monotonic() - begin
    row["first_content_seconds"] = first
    return row


def live(config, output, report):
    deadline = validate_live(config)
    report["manifest_sha256"] = digest(json.dumps(config, sort_keys=True).encode())
    report["model"] = config["models"]["code_small"]
    # Pin checks are metadata-only. They do not load or download a model.
    report["observed_model"] = pin_engine(config)
    report["runtime"]["model_identity"] = "PASS"
    ledger = gateway.Ledger(output / "ledger.sqlite")
    project = config["project"]
    ledger.project(project, config["project_allowance"], 2)
    ledger.member(project, "qualifier01", config["participant_allowance"], 2)
    token = ledger.issue(project, subject="qualifier01", lifetime=1800)
    authority = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticAuthority)
    authority.project = project
    service = gateway.Gateway(
        ("127.0.0.1", 0),
        ledger,
        config,
        secrets.token_hex(32),
        "local-qualification",
        start(authority),
        secrets.token_hex(32),
    )
    url = start(service)
    rows, memory = [], []
    model = config["models"]["code_small"]
    try:
        for concurrency in (1, 2):
            for repetition in range(2):
                jobs = [(task, stream) for task in TASKS for stream in (False, True)]
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=concurrency
                ) as pool:
                    for offset in range(0, len(jobs), concurrency):
                        # No queue crosses the deadline. Stop after any ambiguous call.
                        if time.time() + model["request_timeout_seconds"] + 10 > deadline:
                            return
                        try:
                            pin_engine(config)
                        except Exception:
                            report["runtime"]["model_identity"] = "FAIL"
                            raise
                        futures = [
                            pool.submit(
                                measured_call,
                                url,
                                token,
                                task,
                                stream,
                                model["request_timeout_seconds"],
                            )
                            for task, stream in jobs[offset : offset + concurrency]
                        ]
                        for future in futures:
                            row = future.result()
                            row.update(concurrency=concurrency, repetition=repetition)
                            rows.append(row)
                        # Streaming delivery may precede the final ledger write by a
                        # few milliseconds. Wait for settlement; never redispatch.
                        wait_until = time.monotonic() + 2
                        while time.monotonic() < wait_until:
                            with ledger.db() as db:
                                pending = db.execute(
                                    "SELECT count(*) FROM requests WHERE state='pending'"
                                ).fetchone()[0]
                            if not pending:
                                break
                            time.sleep(0.01)
                        with ledger.db() as db:
                            attempts = {
                                r["id"]: dict(r)
                                for r in db.execute(
                                    "SELECT id,state,reserved,actual FROM requests"
                                )
                            }
                        for row in rows:
                            row["accounting"] = attempts.get(row.get("request_id"))
                        save(output / "attempts.json", rows)
                        if ledger.usage(project)["active"]:
                            return
                        if any(row["availability"] != "PASS" for row in rows):
                            return
                        sample = engine_json(model["endpoint"], "/api/ps")
                        for resident in sample.get("models", []):
                            if resident.get("digest") == model["revision"]:
                                memory.append(
                                    {
                                        k: resident.get(k)
                                        for k in ("size", "size_vram", "context_length")
                                    }
                                )
    finally:
        report["attempts"] = rows
        report["usage"] = ledger.usage(project)
        report["resident_samples"] = memory
        report["runtime"]["availability"] = (
            "PASS"
            if len(rows) == 16 and all(r["availability"] == "PASS" for r in rows)
            else "FAIL"
        )
        report["runtime"]["bounded_task_quality"] = (
            "PASS"
            if len(rows) == 16 and all(r["quality"] == "PASS" for r in rows)
            else "FAIL"
            if any(r["quality"] == "FAIL" for r in rows)
            else "NOT RUN"
        )
        if rows:
            times = sorted(r["seconds"] for r in rows if r["availability"] == "PASS")
            if times:
                report["latency_seconds"] = {
                    "n": len(times),
                    "p50": times[math.ceil(len(times) * 0.5) - 1],
                    "p95": times[math.ceil(len(times) * 0.95) - 1],
                }
                report["runtime"]["latency"] = "PASS"
        report["runtime"]["concurrency_1_and_2"] = report["runtime"]["availability"]
        report["runtime"]["attempt_accounting"] = (
            "PASS"
            if len(rows) == 16
            and report["usage"]["active"] == 0
            and all((r.get("accounting") or {}).get("state") == "complete" for r in rows)
            else "FAIL"
        )
        if memory:
            report["runtime"]["resident_memory_samples"] = "PASS"
            report["runtime"]["effective_context"] = (
                "PASS"
                if all(m["context_length"] == model["context_tokens"] for m in memory)
                else "FAIL"
            )
        ledger.disable_credential(token)
        for server in (service, authority):
            server.shutdown()
            server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--execute-approved", action="store_true")
    args = parser.parse_args()
    if bool(args.manifest) != args.execute_approved:
        parser.error("live mode requires both --manifest and --execute-approved")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    report = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "source": source_identity(),
        "runtime": dict.fromkeys(LIVE_GATES, "NOT RUN"),
        "decision": "DEFER: no model or capacity qualified; no deployment authorized",
        "model": None,
        "observed_model": None,
    }
    try:
        report["controls"] = controls(output)
        if report["controls"]["status"] == "PASS" and args.manifest:
            config = json.loads(args.manifest.read_text())
            save(output / "manifest.json", config)
            live(config, output, report)
        elif not args.manifest:
            report["reason"] = (
                "No approved capacity manifest supplied; no engine contacted"
            )
    except Exception as error:
        report["execution_error"] = type(error).__name__
        report["reason"] = (
            "Qualification stopped; inspect local operator inputs and controls"
        )
    finally:
        save(output / "record.json", report)
    print(
        json.dumps(
            {
                "record": str(output / "record.json"),
                "controls": report.get("controls", {}).get("status", "FAIL"),
                "runtime": report["runtime"],
            },
            indent=2,
        )
    )
    return int(
        bool(report.get("execution_error"))
        or report.get("controls", {}).get("status") != "PASS"
        or "FAIL" in report["runtime"].values()
    )


if __name__ == "__main__":
    raise SystemExit(main())
