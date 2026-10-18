# SPDX-License-Identifier: Apache-2.0
"""Explicit offline operator setup and in-memory transport for approval controls."""

import hashlib
import importlib.util
import io
import json
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "integrations" / "ai_pilot"))
import gateway  # noqa: E402
from qualification_guard import QualificationGuard, migrate, register  # noqa: E402


class Clock:
    def __init__(self):
        self.wall, self.mono = time.time(), time.monotonic()

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, value):
        self.wall += value
        self.mono += value


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "guarded_qualifier_fixture", ROOT / "integrations/ai_pilot/qualify.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def setup(tmp_path, monkeypatch, *, runner=None, usage=12, seconds=600):
    runner = runner or load_runner()
    clock = Clock()
    monkeypatch.setattr(runner, "time", clock)
    monkeypatch.setattr(runner.gateway, "time", clock)
    config = json.loads(
        (ROOT / "integrations/ai_pilot/qualification.example.json").read_text()
    )
    config["models"]["code_small"].update(
        endpoint="http://127.0.0.1:1",
        upstream_model="fixture-model",
        revision="b" * 64,
        template_sha256=hashlib.sha256(b"fixture-template").hexdigest(),
        quantization="fixture-only",
        context_tokens=2048,
        provenance="fabricated fixture only",
        request_timeout_seconds=4,
        resource_limits={"cpus": 1, "memory_mb": 128},
    )
    path = tmp_path / "existing.sqlite"
    config["approved_capacity"].update(
        operator="fixture-operator",
        approval_reference="fixture-approval",
        host="fixture-host",
        resource_limit_evidence="fixture",
        engine_version="fixture",
        license_review="fixture",
        ledger_path=str(path),
        local_only=True,
        egress_blocked=True,
        existing_installed_model=True,
        deadline_utc=datetime.fromtimestamp(clock.wall + seconds, UTC).isoformat(),
    )
    ledger = gateway.Ledger(path)
    ledger.project("qualify01", 32768, 2)
    ledger.member("qualify01", "qualifier01", 32768, 2)
    token = ledger.issue("qualify01", subject="qualifier01")
    migrate(path, "fixture_authority", "fixture_epoch")
    registry = tmp_path / "operator-registry.json"

    def identity():
        return "fixture-host", "fixture-boot"

    pin = register(
        registry,
        path,
        config,
        grant_id="fixture_grant",
        capacity_budget_id="fixture_budget",
        token=token,
        subject="qualifier01",
        authority_url="http://127.0.0.1:2",
        identity=identity,
        clock=clock,
    )
    env = SimpleNamespace(
        runner=runner,
        clock=clock,
        config=config,
        ledger=ledger,
        registry=registry,
        pin=pin,
        token=token,
        identity=identity,
        usage=usage,
        calls=[],
        hook=None,
        size=128,
        vram=0,
        connect_delay=0,
        authority_active=True,
    )
    install_transport(env, monkeypatch)

    def guard():
        return QualificationGuard(registry, pin, config, identity=identity, clock=clock)

    def run(label="run"):
        output = tmp_path / label
        output.mkdir()
        report = {"runtime": dict.fromkeys(runner.LIVE_GATES, "NOT RUN")}
        runner.live(
            config, output, report, guard=guard(), token=token, authority_key="fixture"
        )
        return report

    env.guard, env.run = guard, run
    return env


def install_transport(env, monkeypatch):
    clock = env.clock
    lock = threading.Lock()

    @contextmanager
    def transport(request, timeout, approval_window=None, dispatch_check=None):
        if env.hook:
            env.hook(request)
        clock.advance(env.connect_delay)
        approval_window.check()
        dispatch_check()
        with lock:
            env.calls.append(request.full_url)
        override = getattr(env, "raw_override", None)
        raw = override(request) if override else None
        if raw is not None:
            with io.BytesIO(raw) as response:
                yield response
            return
        if request.full_url.startswith("http://127.0.0.1:2/"):
            value = {"active": env.authority_active, "project": "qualify01"}
        elif "/api/" in request.full_url:
            op = request.full_url.rsplit("/", 1)[-1]
            value = {
                "version": {"version": "fixture"},
                "tags": {
                    "models": [{"name": "fixture-model", "digest": "b" * 64, "size": 128}]
                },
                "show": {
                    "template": "fixture-template",
                    "details": {"quantization_level": "fixture-only"},
                },
                "ps": {
                    "models": [
                        {
                            "digest": "b" * 64,
                            "size": env.size,
                            "size_vram": env.vram,
                            "context_length": 2048,
                        }
                    ]
                },
            }[op]
        else:
            body = json.loads(request.data)
            answer = "blue" if "color" in body["messages"][0]["content"] else "42"
            usage_value = (
                {"usage": {"total_tokens": env.usage}} if env.usage is not None else {}
            )
            if body["stream"]:
                raw = (
                    b"data: "
                    + json.dumps(
                        {"choices": [{"delta": {"content": answer}}], **usage_value}
                    ).encode()
                    + b"\n\ndata: [DONE]\n\n"
                )
                with io.BytesIO(raw) as response:
                    yield response
                return
            value = {"choices": [{"message": {"content": answer}}], **usage_value}
        with io.BytesIO(json.dumps(value).encode()) as response:
            yield response

    monkeypatch.setattr(env.runner.gateway, "inference_attempt", transport)
