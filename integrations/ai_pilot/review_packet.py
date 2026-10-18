# SPDX-License-Identifier: Apache-2.0
"""Offline, review-only projection of one hash-pinned qualification record.

No gateway/qualifier imports, execution, network, subprocesses, or ledger access.
Input paths are relative to an explicit public-evidence root. Artifact contents
are hashed, never included. A packet is not an approval or a current-state check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from collections import Counter
from datetime import datetime

LIMIT = 1024 * 1024
STATUSES = {"PASS", "FAIL", "NOT RUN"}
SOURCE_FILES = (
    "integrations/ai_pilot/gateway.py",
    "integrations/ai_pilot/qualify.py",
    "src/portage/pilot_ledger.py",
    "tests/test_direct_qualification.py",
    "tests/test_pilot_gateway.py",
    "tests/test_pilot_ledger.py",
)
RUNTIME = (
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
COST_CATEGORIES = (
    "need_and_alternatives",
    "exact_resource",
    "primary_source_terms",
    "finite_request",
    "full_exposure",
    "controls",
    "operations",
    "decision",
)
CAPACITY_FIELDS = (
    "operator_ref",
    "approval_evidence_ref",
    "host_ref",
    "engine_version",
    "model_name",
    "model_sha256",
    "template_sha256",
    "quantization",
    "context_tokens",
    "cpus",
    "memory_mb",
    "license_evidence_ref",
    "resource_limit_evidence_ref",
    "egress_evidence_ref",
    "durable_ledger_ref",
    "recovery_evidence_ref",
    "window_start_utc",
    "window_end_utc",
    "max_attempts",
    "concurrency",
    "max_request_tokens",
    "max_output_tokens",
    "aggregate_token_ceiling",
)
DECISION = (
    "DEFER live qualification. Assign one existing approved host, installed permitted "
    "model and named operator; review the pinned model/template/version/context, "
    "enforced resources, egress, durable ledger and recovery evidence; authorize a "
    "separate bounded window and native-unit ceiling. No purchase is requested. "
    "Until then, retain live NOT RUN and continue offline work."
)


def require(condition):
    if not condition:
        raise ValueError("invalid or incomplete input structure")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text(value, pattern, maximum=256):
    require(isinstance(value, str) and len(value) <= maximum)
    require(re.fullmatch(pattern, value) is not None)
    return value


def digest(value):
    return text(value, r"[a-f0-9]{64}", 64)


def number(value, *, integer=False, minimum=0, maximum=10**15):
    require(type(value) in ({int} if integer else {int, float}))
    require(minimum <= value <= maximum and (type(value) is int or math.isfinite(value)))
    return value


def status(value):
    require(isinstance(value, str) and value in STATUSES)
    return value


def relative(value):
    text(value, r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
    require(all(part not in {".", ".."} for part in value.split("/")))
    return value.split("/")


def directory(base, parts):
    fd = os.dup(base)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_file(root, path, limit=LIMIT):
    parts = relative(path)
    parent = directory(root, parts[:-1])
    try:
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_size <= limit)
            with os.fdopen(os.dup(fd), "rb") as stream:
                data = stream.read(limit + 1)
            after = os.fstat(fd)
            require(len(data) <= limit and before.st_size == len(data))
            require(
                (before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_mtime_ns, after.st_ctime_ns)
            )
            return data
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def parse(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result

    def bounded(value, depth=0):
        require(depth <= 16)
        if isinstance(value, dict):
            require(len(value) <= 2048)
            for child in value.values():
                bounded(child, depth + 1)
        elif isinstance(value, list):
            require(len(value) <= 2048)
            for child in value:
                bounded(child, depth + 1)
        elif type(value) is float:
            require(math.isfinite(value))

    value = json.loads(data, object_pairs_hook=pairs)
    bounded(value)
    require(
        isinstance(value, dict)
        and type(value.get("schema_version")) is int
        and value["schema_version"] == 1
    )
    return value


def nullable(value, validator):
    return None if value is None else validator(value)


def identity(model):
    if model is None:
        return None
    require(isinstance(model, dict))
    return {
        "model_name": nullable(model.get("upstream_model"), model_name),
        "model_sha256": nullable(model.get("revision"), digest),
        "template_sha256": nullable(model.get("template_sha256"), digest),
        "quantization": nullable(model.get("quantization"), identifier),
        "context_tokens": nullable(
            model.get("context_tokens"), lambda x: number(x, integer=True, minimum=1)
        ),
    }


def identifier(value):
    return text(value, r"[A-Za-z0-9][A-Za-z0-9_.+-]*", 128)


def model_name(value):
    return text(
        value,
        r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?",
    )


def project_record(record):
    source = record["source"]
    source = {
        "revision": text(source["revision"], r"[a-f0-9]{40}", 40),
        "sha256": {path: digest(source["sha256"][path]) for path in SOURCE_FILES},
        "python": text(source["python"], r"[0-9]+\.[0-9]+\.[0-9]+", 32),
        "platform": identifier(source["platform"]),
    }
    controls = record["controls"]
    require(controls["evidence_class"] == "synthetic loopback HTTP; no model")
    require(isinstance(controls["cases"], list))
    cases, seen = [], set()
    for case in controls["cases"]:
        name = text(case["control"], r"test_[a-zA-Z0-9_]+(?:\[[^\r\n]*\])?", 1024)
        require(name not in seen)
        seen.add(name)
        # Parameter values may contain URLs/private strings. Retain their identity
        # by digest, not raw text, while keeping the readable test function name.
        cases.append(
            {
                "control": name.split("[", 1)[0],
                "case_sha256": sha(name.encode()),
                "status": status(case["status"]),
            }
        )
    counts = dict.fromkeys(sorted(STATUSES), 0)
    counts.update(Counter(case["status"] for case in cases))
    reported = status(controls["status"])
    aggregate = (
        "FAIL"
        if counts["FAIL"] or reported == "FAIL"
        else "PASS"
        if cases and not counts["NOT RUN"] and reported == "PASS"
        else "NOT RUN"
    )
    runtime = record.get("runtime", {})
    require(isinstance(runtime, dict))
    usage = record.get("usage") or {}
    require(isinstance(usage, dict))
    liabilities = {
        key: nullable(usage.get(key), lambda x: number(x, integer=True))
        for key in ("committed", "active", "unresolved")
    }
    attempts = record.get("attempts", [])
    require(isinstance(attempts, list) and len(attempts) <= 16)
    attempt_counts = {
        key: dict(Counter(status(row.get(key, "NOT RUN")) for row in attempts))
        for key in ("availability", "quality")
    }
    # Preserve native measurements and per-attempt debts, without payloads,
    # request credentials, host paths, response text or arbitrary metadata.
    accounting = []
    for row in attempts:
        entry = row.get("accounting")
        if entry is None:
            accounting.append(None)
            continue
        require(entry.get("state") in {"pending", "unknown", "complete", "reconciled"})
        accounting.append(
            {
                "state": entry["state"],
                "reserved_tokens": number(entry["reserved"], integer=True),
                "actual_tokens": nullable(
                    entry.get("actual"), lambda x: number(x, integer=True)
                ),
            }
        )
    latency = record.get("latency_seconds") or {}
    require(isinstance(latency, dict))
    samples = record.get("resident_samples", [])
    require(isinstance(samples, list) and len(samples) <= 16)
    observed = record.get("observed_model")
    if observed is not None:
        require(isinstance(observed, dict))
        observed = {
            key: nullable(observed.get(key), validator)
            for key, validator in (
                ("engine_version", identifier),
                ("model_digest", digest),
                ("template_sha256", digest),
                ("quantization", identifier),
                ("installed_bytes", lambda x: number(x, integer=True)),
            )
        }
    ambiguous = sum(
        row is None
        or row["state"] in {"pending", "unknown"}
        or row["actual_tokens"] is None
        for row in accounting
    )
    return {
        "source": source,
        "model_identity": identity(record.get("model")),
        "observed_model_identity": observed,
        "controls": {
            "evidence_class": controls["evidence_class"],
            "status": aggregate,
            "reported_status": reported,
            "total": len(cases),
            "counts": counts,
            "cases": cases,
        },
        "reported_runtime": {key: status(runtime.get(key, "NOT RUN")) for key in RUNTIME},
        "live_acceptance": "NOT RUN",
        "measurements": {
            "attempts": {
                "total": len(attempts),
                **attempt_counts,
                "accounting": accounting,
            },
            "latency_seconds": {
                key: nullable(latency.get(key), number) for key in ("n", "p50", "p95")
            },
            "resident_samples": [
                {
                    key: nullable(row.get(key), number)
                    for key in ("size", "size_vram", "context_length")
                }
                for row in samples
            ],
            "units": {"size": "bytes", "size_vram": "bytes", "context_length": "tokens"},
        },
        "liabilities": {
            "status_scope": "source-reported outstanding work; not ledger verification",
            "reported": liabilities,
            "ambiguous_attempts": ambiguous,
            "units": {
                "committed": "tokens",
                "active": "requests",
                "unresolved": "requests",
            },
            "status": "FAIL"
            if ambiguous or liabilities["active"] or liabilities["unresolved"]
            else "NOT RUN"
            if any(v is None for v in liabilities.values())
            else "PASS",
        },
    }


def project_capacity(draft, artifact_paths):
    capacity = draft.get("capacity", {})
    costs = draft.get("costs", {})
    require(isinstance(capacity, dict) and isinstance(costs, dict))

    def reference(value):
        relative(value)
        require(value in artifact_paths)
        return value

    bounds = {
        "max_attempts": 16,
        "concurrency": 2,
        "max_request_tokens": 4096,
        "max_output_tokens": 128,
        "aggregate_token_ceiling": 65536,
    }
    clean, missing = {}, []
    for key in CAPACITY_FIELDS:
        value = capacity.get(key)
        if value is None:
            missing.append("capacity." + key)
        elif key.endswith("_evidence_ref"):
            value = reference(value)
        elif key.endswith("sha256"):
            value = digest(value)
        elif key in bounds or key == "context_tokens":
            value = number(value, integer=True, minimum=1, maximum=bounds.get(key, 10**9))
        elif key in {"cpus", "memory_mb"}:
            value = number(value, minimum=0.000001)
        elif key.endswith("_utc"):
            text(value, r"[0-9T:+.Z-]+", 40)
            require(datetime.fromisoformat(value).tzinfo is not None)
        elif key == "model_name":
            value = model_name(value)
        else:
            value = identifier(value)
        clean[key] = value
    if clean["window_start_utc"] and clean["window_end_utc"]:
        seconds = (
            datetime.fromisoformat(clean["window_end_utc"])
            - datetime.fromisoformat(clean["window_start_utc"])
        ).total_seconds()
        require(0 < seconds <= 1800)
    if clean["context_tokens"] and clean["max_request_tokens"]:
        require(clean["context_tokens"] >= clean["max_request_tokens"])
    clean_costs = {}
    for category in COST_CATEGORIES:
        entry = costs.get(category) or {}
        require(isinstance(entry, dict))
        ref = nullable(entry.get("evidence_ref"), reference)
        clean_costs[category] = {"evidence_ref": ref}
        if ref is None:
            missing.append("costs." + category + ".evidence_ref")
    exposure = costs.get("full_exposure") or {}
    for key in (
        "one_time_amount",
        "recurring_amount",
        "currency",
        "billing_interval",
        "native_ceiling",
        "native_unit",
    ):
        value = exposure.get(key)
        if value is None:
            missing.append("costs.full_exposure." + key)
        elif key in {"one_time_amount", "recurring_amount", "native_ceiling"}:
            value = number(value)
        elif key == "currency":
            value = text(value, r"[A-Z]{3}", 3)
        else:
            value = identifier(value)
        clean_costs["full_exposure"][key] = value
    return {
        "capacity": clean,
        "costs": clean_costs,
        "missing_fields": missing,
        "status": "NOT RUN" if missing else "PASS",
        "status_scope": "draft field completeness only; no approval or live verification",
    }


def markdown(packet):
    evidence = packet["evidence"]
    controls = evidence["controls"]
    lines = [
        "# Offline qualification review",
        "",
        DECISION,
        "",
        "Execution, promotion and spending authorized: **false**.",
        "",
        "## Bound inputs",
        "",
        "| Input | SHA256 | Bytes |",
        "| --- | --- | --- |",
    ]
    for row in packet["inputs"]:
        lines.append(f"| {row['path']} | `{row['sha256']}` | {row['bytes']} |")
    lines += [
        "",
        "## Evidence boundary",
        "",
        f"Original source revision: `{evidence['source']['revision']}`. "
        "This is not a current-state check.",
        f"Original platform: {evidence['source']['platform']}; "
        f"Python {evidence['source']['python']}.",
        f"Synthetic controls: **{controls['status']}**, "
        f"{controls['counts']['PASS']}/{controls['total']} PASS; "
        f"{controls['counts']['FAIL']} FAIL; {controls['counts']['NOT RUN']} NOT RUN.",
        "Live acceptance: **NOT RUN**. "
        "Imported runtime statuses are unverified source claims.",
        "",
        "| Runtime class | Source-reported status |",
        "| --- | --- |",
    ]
    lines += [
        f"| {key} | {value} |" for key, value in evidence["reported_runtime"].items()
    ]
    for case in controls["cases"]:
        if case["status"] != "PASS":
            lines.append(
                f"\n{case['status']}: {case['control']} "
                f"(case SHA256 `{case['case_sha256']}`)."
            )
    lines += ["", "Source file hashes:", "", "| File | SHA256 |", "| --- | --- |"]
    lines += [
        f"| {path} | `{value}` |" for path, value in evidence["source"]["sha256"].items()
    ]
    for title, value in (
        (
            "Source model identity",
            {
                "declared": evidence["model_identity"],
                "observed": evidence["observed_model_identity"],
            },
        ),
        ("Source measurements in native units", evidence["measurements"]),
    ):
        lines += ["", title + ":", "", "```json", json.dumps(value, indent=2), "```"]
    lines += [
        "",
        "Reported liabilities (null means unknown):",
        "",
        "```json",
        json.dumps(evidence["liabilities"], indent=2),
        "```",
        "",
        "## Capacity draft",
        "",
        "| Field | Proposed value (null = unknown) |",
        "| --- | --- |",
    ]
    lines += [
        f"| {key} | {json.dumps(value)} |"
        for key, value in packet["draft"]["capacity"].items()
    ]
    lines += [
        "",
        "## Cost draft",
        "",
        "| Category | Evidence reference |",
        "| --- | --- |",
    ]
    lines += [
        f"| {key} | {json.dumps(value['evidence_ref'])} |"
        for key, value in packet["draft"]["costs"].items()
    ]
    lines += [
        "",
        "Full exposure (no conversion or inferred zero):",
        "",
        "```json",
        json.dumps(packet["draft"]["costs"]["full_exposure"], indent=2),
        "```",
        "",
        "Missing fields:",
        "",
    ]
    lines += ["- " + key for key in packet["draft"]["missing_fields"]] or [
        "No missing draft fields; independent review and explicit authorization "
        "are still required."
    ]
    lines += [
        "",
        "The eight cost categories and native measurements are retained in packet.json. "
        "Unknown cost is null, never zero. No native-unit/currency conversion "
        "or cross-record pooling is performed.",
        "",
    ]
    return "\n".join(lines)


def build(root_path, record_path, expected_sha256, capacity_path, artifacts, output_path):
    require(len(artifacts) <= 16)
    anchor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        root = directory(anchor, os.path.abspath(root_path).split("/")[1:])
    finally:
        os.close(anchor)
    try:
        raw = read_file(root, record_path)
        require(sha(raw) == digest(expected_sha256))
        capacity_raw = read_file(root, capacity_path, 65536)
        inputs = [
            {"path": path, "sha256": sha(data), "bytes": len(data)}
            for path, data in ((record_path, raw), (capacity_path, capacity_raw))
        ]
        paths = {record_path, capacity_path}
        require(len(paths) == 2)
        for path, expected in artifacts:
            require(path not in paths)
            paths.add(path)
            data = read_file(root, path)
            require(sha(data) == digest(expected))
            inputs.append({"path": path, "sha256": sha(data), "bytes": len(data)})
        require(sum(row["bytes"] for row in inputs) <= 4 * LIMIT)
        packet = {
            "schema_version": 1,
            "purpose": "offline review only",
            "decision": DECISION,
            "execution_authorized": False,
            "promotion_authorized": False,
            "spending_authorized": False,
            "inputs": inputs,
            "evidence": project_record(parse(raw)),
            "draft": project_capacity(
                parse(capacity_raw), {path for path, _ in artifacts}
            ),
        }
        payloads = {
            "packet.json": json.dumps(packet, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            "packet.md": markdown(packet),
        }
        parts = relative(output_path)
        parent = directory(root, parts[:-1])
        try:
            os.mkdir(parts[-1], mode=0o700, dir_fd=parent)
            output = directory(parent, parts[-1:])
            try:
                for name, contents in payloads.items():
                    fd = os.open(
                        name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=output,
                    )
                    with os.fdopen(fd, "w") as stream:
                        stream.write(contents)
            finally:
                os.close(output)
        finally:
            os.close(parent)
        return packet
    finally:
        os.close(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--record", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--capacity-draft", required=True)
    parser.add_argument(
        "--artifact", action="append", default=[], metavar="RELATIVE_PATH=SHA256"
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        refs = [tuple(value.split("=")) for value in args.artifact]
        require(all(len(row) == 2 for row in refs))
        build(
            args.root,
            args.record,
            args.expected_sha256,
            args.capacity_draft,
            refs,
            args.output,
        )
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError):
        # Never echo input values, private paths, payloads, or OS exception text.
        parser.exit(
            1,
            "Packet could not be completed: invalid, unpinned, unsafe, "
            "or conflicting local inputs.\n",
        )
    print(
        "Review-only packet created; execution, promotion and spending "
        "remain unauthorized."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
