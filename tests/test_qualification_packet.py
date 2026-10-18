# SPDX-License-Identifier: Apache-2.0
"""Offline packet tests: public fixtures only; no inference or ledger creation."""

import builtins
import copy
import importlib.util
import json
import os
import socket
import sqlite3
import stat
import subprocess
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "integrations/ai_pilot/review_packet.py"


def load():
    spec = importlib.util.spec_from_file_location("review_packet", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packet = load()


@pytest.fixture
def inputs(tmp_path):
    record = json.loads(
        (
            ROOT / "docs/qualifications/2026-10-17-direct-local-review-controls.json"
        ).read_text()
    )
    draft = json.loads(
        (ROOT / "integrations/ai_pilot/capacity-review.example.json").read_text()
    )

    def run(
        *, record_value=None, draft_value=None, artifacts=(), output="packet", **kwargs
    ):
        record_raw = json.dumps(record if record_value is None else record_value).encode()
        (tmp_path / "record.json").write_bytes(record_raw)
        (tmp_path / "capacity.json").write_text(
            json.dumps(draft if draft_value is None else draft_value)
        )
        return packet.build(
            tmp_path,
            "record.json",
            kwargs.get("expected", packet.sha(record_raw)),
            "capacity.json",
            artifacts,
            output,
        )

    return tmp_path, record, draft, run


def test_public_record_keeps_95_controls_and_original_source(inputs):
    root, record, _, run = inputs
    result = run()
    evidence = result["evidence"]
    assert evidence["source"] == record["source"]
    assert evidence["controls"]["total"] == evidence["controls"]["counts"]["PASS"] == 95
    assert set(evidence["reported_runtime"].values()) == {"NOT RUN"}
    assert evidence["live_acceptance"] == "NOT RUN"
    assert evidence["liabilities"]["reported"] == dict.fromkeys(
        ("committed", "active", "unresolved")
    )
    assert evidence["liabilities"]["status"] == "NOT RUN"
    assert result["draft"]["status"] == "NOT RUN"
    assert set(result["draft"]["costs"]) == set(packet.COST_CATEGORIES)
    assert result["draft"]["costs"]["full_exposure"]["one_time_amount"] is None
    assert json.loads((root / "packet/packet.json").read_text()) == result
    rendered = (root / "packet/packet.md").read_text()
    assert "95/95 PASS" in rendered and "Live acceptance: **NOT RUN**" in rendered
    assert record["source"]["revision"] in rendered
    assert stat.S_IMODE((root / "packet").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "packet/packet.json").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "reported,case,expected",
    [
        ("PASS", "NOT RUN", "NOT RUN"),
        ("PASS", "FAIL", "FAIL"),
        ("FAIL", "PASS", "FAIL"),
        ("NOT RUN", "PASS", "NOT RUN"),
    ],
)
def test_incomplete_controls_never_pass(inputs, reported, case, expected):
    _, record, _, run = inputs
    record["controls"]["status"] = reported
    record["controls"]["cases"][0]["status"] = case
    result = run()
    assert result["evidence"]["controls"]["status"] == expected
    assert result["evidence"]["controls"]["total"] == 95
    assert result["evidence"]["controls"]["counts"][case] >= 1
    assert result["evidence"]["live_acceptance"] == "NOT RUN"


def test_liabilities_and_native_units_are_preserved_despite_runtime_pass(inputs):
    _, record, draft, run = inputs
    record["runtime"] = dict.fromkeys(packet.RUNTIME, "PASS")
    record["usage"] = {"committed": 317, "active": 1, "unresolved": 1}
    record["attempts"] = [
        {
            "availability": "FAIL",
            "quality": "NOT RUN",
            "accounting": {
                "state": "unknown",
                "reserved": 317,
                "actual": None,
            },
        }
    ]
    record["latency_seconds"] = {"n": 1, "p50": 0.4, "p95": 0.4}
    record["resident_samples"] = [{"size": 12345, "size_vram": 0, "context_length": 2048}]
    draft["costs"]["full_exposure"].update(native_ceiling=32768, native_unit="tokens")
    result = run()
    evidence = result["evidence"]
    assert evidence["liabilities"]["reported"] == record["usage"]
    assert evidence["liabilities"]["status"] == "FAIL"
    assert evidence["measurements"]["attempts"]["accounting"][0]["actual_tokens"] is None
    assert evidence["measurements"]["resident_samples"] == record["resident_samples"]
    assert evidence["reported_runtime"]["latency"] == "PASS"
    assert evidence["live_acceptance"] == "NOT RUN"
    assert result["draft"]["costs"]["full_exposure"]["native_ceiling"] == 32768
    assert result["draft"]["costs"]["full_exposure"]["one_time_amount"] is None


def test_unknown_attempt_cannot_be_hidden_by_zero_usage(inputs):
    _, record, _, run = inputs
    record["usage"] = dict.fromkeys(("committed", "active", "unresolved"), 0)
    record["attempts"] = [
        {"accounting": {"state": "pending", "reserved": 90, "actual": None}}
    ]
    result = run()["evidence"]
    assert result["liabilities"]["status"] == "FAIL"
    assert result["liabilities"]["ambiguous_attempts"] == 1
    assert result["measurements"]["attempts"]["accounting"][0]["reserved_tokens"] == 90


@pytest.mark.parametrize("expected", ["0" * 64, None, "", "not-a-digest"])
def test_record_requires_separately_supplied_matching_digest(inputs, expected):
    root, _, _, run = inputs
    with pytest.raises(ValueError):
        run(expected=expected)
    assert not (root / "packet").exists()


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_control",
        "nonfinite",
        "bad_status",
        "numeric_approval",
        "foreign_source",
    ],
)
def test_invalid_record_fails_before_output(inputs, change):
    root, record, _, run = inputs
    if change == "duplicate_control":
        record["controls"]["cases"].append(copy.deepcopy(record["controls"]["cases"][0]))
    elif change == "nonfinite":
        record["irrelevant"] = float("nan")
    elif change == "bad_status":
        record["runtime"]["model_identity"] = "true"
    elif change == "numeric_approval":
        record["controls"]["status"] = 1
    else:
        record["source"]["revision"] = "/private/source"
    with pytest.raises(ValueError):
        run()
    assert not (root / "packet").exists()


@pytest.mark.parametrize(
    "data",
    [
        b'{"schema_version":1,"schema_version":1}',
        b'{"schema_version":1,"nested":{"x":1,"x":2}}',
        b'{"schema_version":1,"x":NaN}',
        b'{"schema_version":1,"x":Infinity}',
        b'{"schema_version":1,"x":1e999}',
        b'{"schema_version":1,"x":' + b"[" * 20 + b"0" + b"]" * 20 + b"}",
    ],
)
def test_strict_bounded_json(data):
    with pytest.raises(ValueError):
        packet.parse(data)


@pytest.mark.parametrize(
    "kind", ["symlink", "parent_symlink", "fifo", "directory", "oversized"]
)
def test_artifacts_must_be_bounded_regular_files(inputs, kind):
    root, _, _, run = inputs
    artifact = root / "evidence.txt"
    path = "evidence.txt"
    if kind == "symlink":
        artifact.symlink_to(root / "record.json")
    elif kind == "parent_symlink":
        (root / "linked").symlink_to(root, target_is_directory=True)
        path = "linked/record.json"
    elif kind == "fifo":
        os.mkfifo(artifact)
    elif kind == "directory":
        artifact.mkdir()
    else:
        artifact.write_bytes(b"x" * (packet.LIMIT + 1))
    with pytest.raises((ValueError, OSError)):
        run(artifacts=[(path, "a" * 64)])
    assert not (root / "packet").exists()


@pytest.mark.parametrize(
    "path",
    [
        "../record.json",
        "/private/record.json",
        "a/../record.json",
        "./record.json",
        "a//b",
        "a\\b",
    ],
)
def test_traversal_and_ambiguous_paths_are_rejected(inputs, path):
    root, _, _, run = inputs
    with pytest.raises(ValueError):
        run(artifacts=[(path, "a" * 64)])
    with pytest.raises(ValueError):
        run(output=path)
    assert not (root / "packet").exists()


@pytest.mark.parametrize("kind", ["missing", "tampered", "duplicate", "aggregate_size"])
def test_artifact_hashes_and_total_read_budget(inputs, kind):
    root, _, _, run = inputs
    data = b"public operator evidence"
    (root / "evidence.txt").write_bytes(data)
    refs = [("evidence.txt", packet.sha(data))]
    if kind == "missing":
        refs = [("missing.txt", packet.sha(data))]
    elif kind == "tampered":
        (root / "evidence.txt").write_bytes(data + b"changed")
    elif kind == "duplicate":
        refs *= 2
    else:
        refs = []
        for index in range(4):
            name = f"large-{index}.txt"
            (root / name).write_bytes(b"x" * packet.LIMIT)
            refs.append((name, packet.sha(b"x" * packet.LIMIT)))
    with pytest.raises((ValueError, OSError)):
        run(artifacts=refs)
    assert not (root / "packet").exists()


@pytest.mark.parametrize("kind", ["existing", "file", "symlink", "parent_symlink"])
def test_output_is_new_only_and_does_not_follow_links(inputs, kind):
    root, _, _, run = inputs
    target = root / "packet"
    output = "packet"
    if kind == "existing":
        target.mkdir()
        (target / "packet.json").write_text("retain me")
    elif kind == "file":
        target.write_text("retain me")
    elif kind == "symlink":
        target.symlink_to(root / "record.json")
    else:
        target.symlink_to(root, target_is_directory=True)
        output = "packet/new"
    with pytest.raises(OSError):
        run(output=output)
    if kind == "existing":
        assert (target / "packet.json").read_text() == "retain me"
    elif kind == "file":
        assert target.read_text() == "retain me"
    assert not (root / "new").exists()


def test_private_fields_and_artifact_contents_never_appear_in_packet(inputs):
    root, record, draft, run = inputs
    private = "/Users/private/person/secret-ledger.sqlite"
    secret = "Bearer do-not-export-this-value"
    record.update(api_key=secret, reason=private, approval={"token": secret})
    record["model"] = {"endpoint": secret, "ledger_path": private}
    record["controls"]["cases"][0]["control"] = f"test_private_parameter[{private}]"
    record["source"]["sha256"][private] = "a" * 64
    draft.update(approved_capacity={"ledger_path": private, "key": secret})
    artifact = (secret + private).encode()
    (root / "operator.txt").write_bytes(artifact)
    draft["capacity"]["approval_evidence_ref"] = "operator.txt"
    result = run(artifacts=[("operator.txt", packet.sha(artifact))])
    for name in ("packet.json", "packet.md"):
        emitted = (root / "packet" / name).read_text()
        assert private not in emitted and secret not in emitted
    assert result["inputs"][-1]["sha256"] == packet.sha(artifact)


@pytest.mark.parametrize("value", [True, 1, "true", "PASS", "approved"])
def test_no_input_can_grant_authorization(inputs, value):
    _, record, draft, run = inputs
    for data in (record, draft):
        for key in (
            "execution_authorized",
            "promotion_authorized",
            "spending_authorized",
        ):
            data[key] = value
    draft["capacity"]["approved"] = value
    result = run()
    assert all(
        result[key] is False
        for key in ("execution_authorized", "promotion_authorized", "spending_authorized")
    )
    assert result["evidence"]["live_acceptance"] == "NOT RUN"


@pytest.mark.parametrize(
    "field,value",
    [
        ("cpus", True),
        ("memory_mb", 0),
        ("max_attempts", 17),
        ("concurrency", 3),
        ("max_output_tokens", 129),
        ("aggregate_token_ceiling", 65537),
        ("durable_ledger_ref", "/Users/private/ledger.sqlite"),
        ("model_name", "http://user:password@host"),
        ("approval_evidence_ref", "not-pinned.txt"),
        ("window_start_utc", "2026-10-17T20:00:00"),
    ],
)
def test_capacity_values_are_bounded_public_fields(inputs, field, value):
    root, _, draft, run = inputs
    draft["capacity"][field] = value
    with pytest.raises(ValueError):
        run()
    assert not (root / "packet").exists()


def test_packet_import_and_build_cannot_execute_or_contact_services(inputs, monkeypatch):
    root, _, _, run = inputs

    def forbidden(*_args, **_kwargs):
        pytest.fail("offline packet attempted external execution")

    original_import = builtins.__import__

    def restricted(name, *args, **kwargs):
        if name in {"gateway", "qualify", "pilot_ledger"}:
            forbidden()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", restricted)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    load()
    run()
    assert not list(root.rglob("*.sqlite*"))


def test_cli_errors_never_echo_private_paths(inputs, capsys):
    root, _, _, _ = inputs
    with pytest.raises(SystemExit) as caught:
        packet.main(
            [
                "--root",
                str(root),
                "--record",
                "/private/secret",
                "--expected-sha256",
                "a" * 64,
                "--capacity-draft",
                "capacity.json",
                "--output",
                "packet",
            ]
        )
    assert caught.value.code == 1
    stderr = capsys.readouterr().err
    assert "/private/secret" not in stderr and str(root) not in stderr


def test_complete_draft_is_only_complete_and_cannot_promote_old_evidence(inputs):
    root, record, draft, run = inputs
    proof = b"Public operator evidence reference; not execution permission."
    (root / "operator.txt").write_bytes(proof)
    for key in packet.CAPACITY_FIELDS:
        if key.endswith("_evidence_ref"):
            draft["capacity"][key] = "operator.txt"
    draft["capacity"].update(
        operator_ref="operator01",
        host_ref="host01",
        engine_version="fixture-v1",
        model_name="namespace/model:tag",
        model_sha256="a" * 64,
        template_sha256="b" * 64,
        quantization="Q4_K_M",
        context_tokens=2048,
        cpus=1,
        memory_mb=128,
        durable_ledger_ref="ledger01",
        window_start_utc="2026-10-17T20:00:00Z",
        window_end_utc="2026-10-17T20:30:00Z",
    )
    for entry in draft["costs"].values():
        entry["evidence_ref"] = "operator.txt"
    draft["costs"]["full_exposure"].update(
        one_time_amount=5,
        recurring_amount=2,
        currency="USD",
        billing_interval="month",
        native_ceiling=32768,
        native_unit="tokens",
    )
    result = run(artifacts=[("operator.txt", packet.sha(proof))])
    assert result["draft"]["missing_fields"] == []
    assert result["draft"]["status"] == "PASS"
    assert "field completeness only" in result["draft"]["status_scope"]
    assert result["evidence"]["source"] == record["source"]
    assert result["evidence"]["model_identity"] is None
    assert result["evidence"]["live_acceptance"] == "NOT RUN"
    assert all(
        result[key] is False
        for key in (
            "execution_authorized",
            "promotion_authorized",
            "spending_authorized",
        )
    )
    assert result["draft"]["costs"]["full_exposure"]["native_ceiling"] == 32768


def test_symlinked_root_or_record_cannot_be_read(inputs, tmp_path):
    root, record, draft, _ = inputs
    raw = json.dumps(record).encode()
    (root / "original.json").write_bytes(raw)
    (root / "capacity.json").write_text(json.dumps(draft))
    (root / "record.json").symlink_to(root / "original.json")
    (root / "root-link").symlink_to(root, target_is_directory=True)
    for selected_root, selected_record in (
        (root, "record.json"),
        (root / "root-link", "original.json"),
    ):
        with pytest.raises(OSError):
            packet.build(
                selected_root,
                selected_record,
                packet.sha(raw),
                "capacity.json",
                [],
                "packet",
            )
    assert not (root / "packet").exists()
