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
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import gateway
from qualification_guard import (
    BATCHES,
    INFERENCE,
    QualificationGuard,
    observe_usage,
    protected_file,
    unique_json,
)

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
        "src/portage/qualification_guard.py",
        "tests/test_qualification_guard.py",
        "tests/qualification_fixtures.py",
        "tests/test_qualification_expiry.py",
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
            "tests/test_qualification_guard.py",
            "tests/test_qualification_expiry.py",
            f"--basetemp={output / 'tmp'}",
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
        "status": (
            "PASS"
            if result.returncode == 0
            and cases
            and all(case["status"] == "PASS" for case in cases)
            else "FAIL"
        ),
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
        "ledger_path",
    ):
        if not isinstance(capacity.get(field), str) or not capacity[field].strip():
            raise ValueError(f"complete approved_capacity.{field}")
    if not Path(capacity["ledger_path"]).is_absolute():
        raise ValueError("approved capacity needs an absolute durable local ledger path")
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


def pin_engine(config, fetch=None):
    fetch = fetch or engine_json
    model = config["models"]["code_small"]
    origin, name = model["endpoint"], model["upstream_model"]
    version = fetch(origin, "/api/version").get("version")
    if version != config["approved_capacity"]["engine_version"]:
        raise ValueError("engine version differs from approved manifest")
    tags = fetch(origin, "/api/tags").get("models", [])
    candidates = [row for row in tags if row.get("name") == name]
    if len(candidates) != 1:
        raise ValueError("exact approved model must already be installed")
    installed = candidates[0]
    if installed.get("digest") != model["revision"] or installed.get("size", 0) <= 0:
        raise ValueError("installed artifact digest or local size disagrees")
    shown = fetch(origin, "/api/show", {"model": name})
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


def guarded_call(guard, slot, authority_key):
    item = INFERENCE[slot]
    task, stream = item["task"], item["stream"]
    begin = time.monotonic()
    row = {
        "task": task[0],
        "stream": stream,
        "availability": "FAIL",
        "quality": "NOT RUN",
    }
    attempt, request_id, usage = None, None, None
    content, first, complete = "", None, False
    try:
        for phase in ("pre", "post"):
            gateway.qualified_authority(guard, "inference", slot, phase, authority_key)
        body = {
            "model": "code_small",
            "messages": [{"role": "user", "content": task[1]}],
            "stream": stream,
        }
        attempt, request_id = guard.admit("inference", slot, body=body)
        row["request_id"] = request_id
        outgoing, _ = gateway.prepare_request(
            body, guard.manifest["models"], "chat/completions"
        )
        model = guard.manifest["models"]["code_small"]
        outgoing["model"] = model["upstream_model"]
        request = urllib.request.Request(
            model["endpoint"].rstrip("/") + "/v1/chat/completions",
            data=json.dumps(outgoing).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Portage-Request-Id": request_id,
            },
        )
        with gateway.inference_attempt(
            request,
            model["request_timeout_seconds"],
            approval_window=guard,
            dispatch_check=lambda: guard.claim(attempt),
        ) as response:
            if stream:
                while line := response.readline(262145):
                    if len(line) > 262144:
                        raise ValueError("event too large")
                    if line.strip() == b"data: [DONE]":
                        complete = True
                        break
                    if line.startswith(b"data: "):
                        chunk = unique_json(line[6:])
                        if chunk.get("error"):
                            raise ValueError("stream failed")
                        usage = observe_usage(usage, chunk)
                        for choice in chunk.get("choices", []):
                            text = choice.get("delta", {}).get("content") or ""
                            if text and first is None:
                                first = time.monotonic() - begin
                            content += text
            else:
                raw = response.read(262145)
                if len(raw) > 262144:
                    raise ValueError("response too large")
                result = unique_json(raw)
                if result.get("error"):
                    raise ValueError("completion failed")
                content = result["choices"][0]["message"]["content"]
                usage = observe_usage(None, result)
                complete = True
        if complete and content:
            row["availability"] = "PASS"
            row["quality"] = "PASS" if content.strip() == task[2] else "FAIL"
        row["output_sha256"] = digest(content.encode())
    except Exception as error:
        row["error_type"] = type(error).__name__
    finally:
        if attempt:
            guard.finish(attempt, known=complete, usage=usage)
    row["seconds"] = time.monotonic() - begin
    row["first_content_seconds"] = first
    return row


def live(config, output, report, *, guard=None, token=None, authority_key=None):
    if not isinstance(guard, QualificationGuard) or not token or not authority_key:
        raise ValueError("registered guard and existing credentials required")
    if guard.manifest != config:
        raise ValueError("guard manifest mismatch")
    guard.acquire(token)
    ledger, project = guard.ledger, config["project"]
    model = config["models"]["code_small"]
    rows, memory = [], []

    def batch_fits():
        guard.check()
        if guard.remaining() < model["request_timeout_seconds"] + 10:
            report["stop_reason"] = "approval_window_insufficient"
            return False
        return True

    def pin(prefix):
        def fetch(_origin, path, _body=None):
            return gateway.qualified_metadata(
                guard, prefix + "." + path.rsplit("/", 1)[-1], authority_key
            )

        return pin_engine(config, fetch=fetch)

    try:
        validate_live(config)
        report["manifest_sha256"] = digest(json.dumps(config, sort_keys=True).encode())
        report["model"] = model
        if not batch_fits():
            return
        report["observed_model"] = pin("initial")
        report["runtime"]["model_identity"] = "PASS"
        for batch, slots in BATCHES:
            if not batch_fits():
                return
            try:
                pin(batch)
            except Exception:
                report["runtime"]["model_identity"] = "FAIL"
                raise
            if not batch_fits():
                return
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(slots)) as pool:
                futures = [
                    pool.submit(guarded_call, guard, slot, authority_key)
                    for slot in slots
                ]
                for slot, future in zip(slots, futures, strict=True):
                    row = future.result()
                    row.update(
                        concurrency=INFERENCE[slot]["concurrency"],
                        repetition=INFERENCE[slot]["repetition"],
                    )
                    rows.append(row)
            with ledger.db() as db:
                attempts = {
                    r["id"]: dict(r)
                    for r in db.execute(
                        "SELECT id,state,reserved,actual FROM requests WHERE project=?",
                        (project,),
                    )
                }
            for row in rows:
                row["accounting"] = attempts.get(row.get("request_id"))
            save(output / "attempts.json", rows)
            if ledger.usage(project)["active"] or any(
                row["availability"] != "PASS" for row in rows
            ):
                return
            sample = gateway.qualified_metadata(guard, batch + ".ps", authority_key)
            for resident in sample.get("models", []):
                if resident.get("digest") == model["revision"]:
                    memory.append(
                        {
                            k: resident.get(k)
                            for k in ("size", "size_vram", "context_length")
                        }
                    )
    finally:
        guard.close()
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
            report["runtime"]["resident_memory_samples"] = (
                "PASS"
                if all(
                    type(m["size"]) is int
                    and m["size"] > 0
                    and type(m["size_vram"]) is int
                    and m["size_vram"] >= 0
                    for m in memory
                )
                else "FAIL"
            )
            report["runtime"]["effective_context"] = (
                "PASS"
                if all(m["context_length"] == model["context_tokens"] for m in memory)
                else "FAIL"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--registry-sha256")
    parser.add_argument("--credential-file", type=Path)
    args = parser.parse_args()
    if bool(args.manifest) != args.execute_approved:
        parser.error("live mode requires both --manifest and --execute-approved")
    if args.execute_approved and not all(
        (args.registry, args.registry_sha256, args.credential_file)
    ):
        parser.error("execution requires pinned registry and pre-issued credential file")
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
            guard = QualificationGuard(args.registry, args.registry_sha256, config)
            protected_file(args.credential_file)
            if args.credential_file.stat().st_mode & 0o077:
                raise ValueError("credential file must be private to the operator")
            credentials = unique_json(args.credential_file.read_text())
            live(
                config,
                output,
                report,
                guard=guard,
                token=credentials["participant_token"],
                authority_key=credentials["authority_token"],
            )
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
