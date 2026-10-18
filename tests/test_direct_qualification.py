# SPDX-License-Identifier: Apache-2.0
"""Synthetic loopback controls. No weights, external network or provider calls."""

import concurrent.futures
import importlib.util
import json
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import qualification_fixtures as guarded_fixture

spec = importlib.util.spec_from_file_location(
    "direct_gateway", Path(__file__).parents[1] / "integrations/ai_pilot/gateway.py"
)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def manifest(endpoint):
    return {
        "mode": "qualification",
        "project": "project01",
        "project_allowance": 10000,
        "participant_allowance": 5000,
        "concurrency": 2,
        "models": {
            "code_small": {
                "operation": "chat/completions",
                "endpoint": endpoint,
                "upstream_model": "synthetic-engine-model",
                "revision": "fixture-v1",
                "provenance": "deterministic fixture, not model evidence",
                "template_sha256": "a" * 64,
                "quantization": "fixture-only",
                "context_tokens": 2048,
                "max_request_tokens": 1024,
                "request_timeout_seconds": 4,
                "max_output_tokens": 32,
                "resource_limits": {"cpus": 1, "memory_mb": 128},
                "institutional_only": True,
                "synthetic": True,
            }
        },
    }


class Authority(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        subject = self.path.rsplit("/", 1)[-1]
        self.server.checks.append(subject)
        value = self.server.members.get(subject, {"active": False})
        data = json.dumps(value).encode()
        self.send_response(self.server.status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.server.checked.set()


class Engine(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append((body, self.headers.get("X-Portage-Request-Id")))
        mode = self.server.mode
        self.server.started.set()
        if mode in {"hold", "headers_hold"}:
            assert self.server.release.wait(5)
        if mode in {"redirect", "failure"}:
            self.send_response(307 if mode == "redirect" else 503)
            self.send_header("Location", self.server.foreign)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        usage = {"total_tokens": self.server.usage}
        content = "42"
        if mode == "qualified" and "color" in body["messages"][0]["content"]:
            content = "blue"
        try:
            if body.get("stream"):
                chunk = {"choices": [{"delta": {"content": content}}]}
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                self.wfile.flush()
                if mode == "cancel":
                    assert self.server.release.wait(5)
                    for _ in range(256):
                        self.wfile.write(
                            b"data: "
                            + json.dumps(
                                {"choices": [{"delta": {"content": "x" * 16384}}]}
                            ).encode()
                            + b"\n\n"
                        )
                        self.wfile.flush()
                if mode != "missing":
                    self.wfile.write(
                        b"data: "
                        + json.dumps({"choices": [], "usage": usage}).encode()
                        + b"\n\n"
                    )
                if mode == "error_chunk":
                    self.wfile.write(b'data: {"error":{"message":"synthetic"}}\n\n')
                if mode != "truncated":
                    self.wfile.write(b"data: [DONE]\n\n")
            else:
                result = {"choices": [{"message": {"content": content}}]}
                if mode != "missing":
                    result["usage"] = usage
                self.wfile.write(json.dumps(result).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


def start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def env(tmp_path):
    authority = ThreadingHTTPServer(("127.0.0.1", 0), Authority)
    authority.members = {
        "member01": {"active": True, "project": "project01"},
        "member02": {"active": True, "project": "project01"},
        "member03": {"active": True, "project": "project02"},
    }
    authority.status, authority.checks, authority.checked = 200, [], threading.Event()
    engine = ThreadingHTTPServer(("127.0.0.1", 0), Engine)
    engine.mode, engine.usage, engine.calls = "normal", 12, []
    engine.started, engine.release = threading.Event(), threading.Event()
    foreign = ThreadingHTTPServer(("127.0.0.1", 0), Engine)
    foreign.mode, foreign.usage, foreign.calls = "normal", 12, []
    foreign.started = threading.Event()
    engine.foreign = start(foreign) + "/v1/chat/completions"
    config = manifest(start(engine))
    gateway.validate_manifest(config, "qualification")
    # These general adapter regressions retain arbitrary prompts, retries and
    # multiple members. The fixed qualification protocol has separate guard tests.
    config["mode"] = "synthetic"
    base = config["models"]["code_small"]
    config["models"] = {
        alias: dict(
            base, operation=("embeddings" if alias == "embedding" else "chat/completions")
        )
        for alias in (
            "classifier",
            "code_small",
            "code_large",
            "research_synthesis",
            "embedding",
        )
    }
    gateway.validate_manifest(config, "synthetic")
    ledger = gateway.Ledger(tmp_path / "ledger.sqlite")
    ledger.project("project01", 10000, 2)
    ledger.project("project02", 10000, 2)
    for subject, membership in authority.members.items():
        ledger.member(membership["project"], subject, 5000, 2)
    token = ledger.issue("project01", subject="member01")
    service = gateway.Gateway(
        ("127.0.0.1", 0),
        ledger,
        config,
        "control",
        "engine",
        start(authority),
        "authority",
    )
    url = start(service)

    class Environment:
        def request(self, *, stream=False, key=token, subject="member02", **overrides):
            body = {
                "model": "code_small",
                "messages": [{"role": "user", "content": "Return 42"}],
                "max_tokens": 32,
                "stream": stream,
                **overrides,
            }
            req = urllib.request.Request(
                url + "/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={
                    "Authorization": "Bearer " + key,
                    "X-Portage-Subject": subject,
                    "Content-Type": "application/json",
                },
            )
            try:
                with gateway.open_once(req, timeout=6) as response:
                    return response.status, response.read(), response.headers
            except urllib.error.HTTPError as error:
                return error.code, error.read(), error.headers

        def rows(self):
            with ledger.db() as db:
                return [dict(row) for row in db.execute("SELECT * FROM requests")]

    obj = Environment()
    obj.authority, obj.engine, obj.foreign = authority, engine, foreign
    obj.service, obj.ledger, obj.token, obj.url = service, ledger, token, url
    yield obj
    engine.release.set()
    for server in (service, engine, authority, foreign):
        server.shutdown()
        server.server_close()


def await_rows(env, state, count=1):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        rows = env.rows()
        if len(rows) == count and all(row["state"] == state for row in rows):
            return rows
        time.sleep(0.01)
    pytest.fail(f"expected {count} {state} rows; got {env.rows()}")


@pytest.mark.parametrize("stream", [False, True])
def test_identity_mapping_and_spoofing(env, stream):
    status, data, headers = env.request(
        stream=stream,
        project="project02",
        user="member03",
        owner="member03",
        api_base=env.engine.foreign,
        metadata={"project": "project02"},
    )
    assert status == 200 and b"42" in data
    row = await_rows(env, "complete")[0]
    assert (row["project"], row["subject"], row["model"], row["actual"]) == (
        "project01",
        "member01",
        "code_small",
        12,
    )
    body, request_id = env.engine.calls[0]
    assert body["model"] == "code_small"
    assert request_id == row["id"] == headers["X-Portage-Request-Id"]
    assert not {"project", "user", "owner", "metadata", "api_base"} & body.keys()
    assert env.ledger.usage("project02")["committed"] == 0
    assert not env.foreign.calls


def test_application_attribution_is_scoped(env):
    key = env.ledger.issue("project01", kind="application")
    assert env.request(key=key, subject="member02")[0] == 200
    assert env.rows()[0]["subject"] == "member02"
    assert env.request(key=key, subject="member03")[0] == 403
    assert len(env.engine.calls) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "forbidden"},
        {"model": "embedding"},
        {"max_tokens": 33},
        {"messages": [{"role": "user", "content": "x" * 3000}]},
        {"tools": [{"type": "function"}]},
    ],
)
def test_forbidden_work_never_dispatches(env, overrides):
    assert env.request(**overrides)[0] in {400, 403, 413}
    assert not env.rows() and not env.engine.calls


def test_redirect_never_dispatches_to_foreign_destination(env):
    env.engine.mode = "redirect"
    assert env.request()[0] == 503
    await_rows(env, "unknown")
    assert len(env.engine.calls) == 1 and not env.foreign.calls


def test_proxy_environment_cannot_change_destination(env, monkeypatch):
    monkeypatch.setenv("http_proxy", env.engine.foreign)
    monkeypatch.setenv("no_proxy", "")
    assert env.request()[0] == 200
    assert len(env.engine.calls) == 1 and not env.foreign.calls


@pytest.mark.parametrize("which", ["authority", "ledger", "unavailable", "expired"])
def test_revocation_and_unavailable_authority_fail_closed(env, which, monkeypatch):
    if which == "authority":
        env.authority.members["member01"]["active"] = False
    elif which == "ledger":
        env.ledger.revoke("project01", "member01")
    elif which == "unavailable":
        env.authority.status = 503
    else:
        now = gateway.Ledger.issue.__globals__["time"].time()
        monkeypatch.setattr(
            gateway.Ledger.issue.__globals__["time"], "time", lambda: now + 7200
        )
    assert env.request()[0] in {401, 403, 503}
    assert not env.engine.calls and not env.rows()


def test_membership_rechecked_after_body_receipt(env):
    body = json.dumps(
        {"model": "code_small", "messages": [{"role": "user", "content": "42"}]}
    ).encode()
    with socket.create_connection(
        ("127.0.0.1", env.service.server_port), timeout=3
    ) as sock:
        sock.sendall(
            (
                f"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
                f"Authorization: Bearer {env.token}\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode()
        )
        assert env.authority.checked.wait(2)
        env.authority.members["member01"]["active"] = False
        sock.sendall(body)
        assert b"403" in sock.recv(4096)
    assert not env.engine.calls and not env.rows()


@pytest.mark.parametrize("scope", ["member", "project"])
def test_exhausted_allowance_blocks_before_dispatch(env, scope):
    if scope == "member":
        env.ledger.member("project01", "member01", 1)
    else:
        env.ledger.project("project01", 1, 2)
    assert env.request()[0] == 429
    assert not env.engine.calls and not env.rows()


def test_concurrency_and_every_retry_are_admitted(env):
    env.engine.mode = "hold"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(env.request)
        assert env.engine.started.wait(2)
        second = pool.submit(env.request, stream=True)
        deadline = time.monotonic() + 2
        while len(env.engine.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(env.engine.calls) == 2
        assert env.request()[0] == 429
        env.engine.release.set()
        assert first.result()[0] == second.result()[0] == 200
    env.engine.mode = "normal"
    for purpose in ("retry", "background title", "background summary"):
        assert env.request(messages=[{"role": "user", "content": purpose}])[0] == 200
    rows = await_rows(env, "complete", count=5)
    assert len({row["id"] for row in rows}) == len(env.engine.calls) == 5
    assert env.ledger.usage("project01")["committed"] == 60


@pytest.mark.parametrize(
    "stream,mode,usage",
    [
        (False, "missing", 12),
        (True, "missing", 12),
        (True, "truncated", 12),
        (True, "error_chunk", 12),
        (False, "normal", -1),
        (True, "normal", True),
        (False, "normal", "12"),
        (False, "failure", 12),
    ],
)
def test_unknown_usage_retains_budget_and_slot_across_restart(env, stream, mode, usage):
    env.ledger.project("project01", 10000, 1)
    env.engine.mode, env.engine.usage = mode, usage
    env.request(stream=stream)
    row = await_rows(env, "unknown")[0]
    env.service.ledger = gateway.Ledger(env.ledger.path)
    assert env.service.ledger.usage("project01") == {
        "committed": row["reserved"],
        "active": 1,
        "unresolved": 1,
    }
    assert env.request()[0] == 429
    assert len(env.engine.calls) == 1
    env.ledger.settle(row["id"], 0)
    assert env.rows()[0]["state"] == "unknown"
    env.ledger.reconcile(row["id"], 12, "a" * 64)
    assert env.ledger.usage("project01")["active"] == 0


def test_client_cancellation_retains_unknown_liability(env):
    env.engine.mode = "cancel"
    body = json.dumps(
        {
            "model": "code_small",
            "stream": True,
            "messages": [{"role": "user", "content": "42"}],
        }
    ).encode()
    sock = socket.create_connection(("127.0.0.1", env.service.server_port), timeout=3)
    sock.sendall(
        (
            f"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
            f"Authorization: Bearer {env.token}\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode()
        + body
    )
    received = b""
    while b"data:" not in received:
        received += sock.recv(4096)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.close()
    env.engine.release.set()
    row = await_rows(env, "unknown")[0]
    assert env.ledger.usage("project01")["committed"] == row["reserved"]


def test_stream_deadline_retains_reservation(env):
    env.engine.mode = "cancel"
    env.service.manifest["models"]["code_small"]["request_timeout_seconds"] = 0.1
    started = time.monotonic()
    status, data, _ = env.request(stream=True)
    assert status == 200 and b"[DONE]" not in data
    assert time.monotonic() - started < 2
    await_rows(env, "unknown")
    env.engine.release.set()


def test_header_deadline_retains_reservation(env):
    env.engine.mode = "headers_hold"
    env.service.manifest["models"]["code_small"]["request_timeout_seconds"] = 0.1
    started = time.monotonic()
    assert env.request()[0] == 503
    assert time.monotonic() - started < 2
    await_rows(env, "unknown")
    env.engine.release.set()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com",
        "http://localhost:11434",
        "http://127.0.0.1/v1",
        "http://user:secret@127.0.0.1",
        "http://127.0.0.1?model=x",
    ],
)
def test_qualification_cannot_select_external_or_ambiguous_origin(endpoint):
    with pytest.raises(ValueError):
        gateway.validate_manifest(manifest(endpoint), "qualification")


def test_qualification_cannot_be_promoted_or_claim_embeddings():
    config = manifest("http://127.0.0.1:11434")
    config["mode"] = "hosted"
    with pytest.raises(ValueError):
        gateway.validate_manifest(config, "hosted")


@pytest.fixture
def runner(monkeypatch):
    directory = Path(__file__).parents[1] / "integrations/ai_pilot"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("qualifier", directory / "qualify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def live_config(endpoint):
    config = manifest(endpoint)
    config["models"]["code_small"].update(
        synthetic=False, revision="b" * 64, template_sha256=gateway.secrets.token_hex(32)
    )
    config["approved_capacity"] = {
        "operator": "synthetic test",
        "approval_reference": "synthetic test only",
        "host": "synthetic fixture",
        "resource_limit_evidence": "synthetic test only",
        "engine_version": "fixture",
        "license_review": "synthetic test only",
        "ledger_path": "/nonexistent/synthetic-test-only.sqlite",
        "local_only": True,
        "egress_blocked": True,
        "existing_installed_model": True,
        "deadline_utc": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    }
    return config


@pytest.mark.parametrize(
    "size,vram,memory_status", [(128, 0, "PASS"), (None, None, "FAIL"), (-1, 0, "FAIL")]
)
def test_live_protocol_against_synthetic_engine_only(
    runner, monkeypatch, tmp_path, size, vram, memory_status
):
    """Actual guarded runner, fabricated responses; NOT real-capacity acceptance."""
    fake = guarded_fixture.setup(tmp_path, monkeypatch, runner=runner)
    fake.size, fake.vram = size, vram
    report = fake.run()
    assert len([url for url in fake.calls if url.endswith("/v1/chat/completions")]) == 16
    assert len(report["attempts"]) == 16
    assert report["usage"] == {"committed": 192, "active": 0, "unresolved": 0}
    assert report["runtime"]["attempt_accounting"] == "PASS"
    assert report["runtime"]["bounded_task_quality"] == "PASS"
    assert report["runtime"]["resident_memory_samples"] == memory_status
    for key in (
        "engine_peak_memory",
        "engine_attempt_visibility",
        "token_reservation_bound",
        "operator_restart",
    ):
        assert report["runtime"][key] == "NOT RUN"


def test_live_protocol_stops_after_ambiguous_usage(runner, monkeypatch, tmp_path):
    fake = guarded_fixture.setup(tmp_path, monkeypatch, runner=runner, usage=None)
    report = fake.run()
    assert len([url for url in fake.calls if url.endswith("/v1/chat/completions")]) == 1
    assert report["runtime"]["attempt_accounting"] == "FAIL"
    assert report["usage"]["unresolved"] == 1
    before = list(fake.calls)
    with pytest.raises(runner.gateway.Denied, match="held"):
        fake.run("repeat")
    assert fake.calls == before


@pytest.mark.parametrize("change", ["no_approval", "synthetic", "deadline", "budget"])
def test_live_manifest_fails_before_engine_contact(runner, change):
    config = live_config("http://127.0.0.1:11434")
    if change == "no_approval":
        config["approved_capacity"]["approval_reference"] = None
    elif change == "synthetic":
        config["models"]["code_small"]["synthetic"] = True
    elif change == "deadline":
        config["approved_capacity"]["deadline_utc"] = "2000-01-01T00:00:00+00:00"
    else:
        config["project_allowance"] = 100000
    with pytest.raises(ValueError):
        runner.validate_live(config)


@pytest.mark.parametrize("mismatch", ["version", "digest", "cloud", "template", "quant"])
def test_model_pin_mismatches_fail_without_generation(runner, monkeypatch, mismatch):
    config = live_config("http://127.0.0.1:11434")
    config["models"]["code_small"]["template_sha256"] = runner.digest(b"template")
    calls = []

    def metadata(_origin, path, _body=None):
        calls.append(path)
        if path == "/api/version":
            return {"version": "changed" if mismatch == "version" else "fixture"}
        if path == "/api/tags":
            return {
                "models": [
                    {
                        "name": "synthetic-engine-model",
                        "size": 100,
                        "digest": ("c" if mismatch == "digest" else "b") * 64,
                    }
                ]
            }
        return {
            "remote_host": "cloud" if mismatch == "cloud" else "",
            "template": "changed" if mismatch == "template" else "template",
            "details": {
                "quantization_level": (
                    "changed" if mismatch == "quant" else "fixture-only"
                )
            },
        }

    monkeypatch.setattr(runner, "engine_json", metadata)
    with pytest.raises(ValueError):
        runner.pin_engine(config)
    assert set(calls) <= {"/api/version", "/api/tags", "/api/show"}


@pytest.mark.parametrize(
    "case,expected",
    [
        ("<testcase name='passed'/>", "PASS"),
        ("<testcase name='skipped'><skipped/></testcase>", "FAIL"),
        ("<testcase name='failed'><failure/></testcase>", "FAIL"),
        ("<testcase name='error'><error/></testcase>", "FAIL"),
        ("", "FAIL"),
    ],
)
def test_controls_require_every_selected_case_to_pass(
    runner, monkeypatch, tmp_path, case, expected
):
    def completed(*_args, **_kwargs):
        (tmp_path / "controls.xml").write_text(f"<testsuite>{case}</testsuite>")
        return runner.subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", completed)
    result = runner.controls(tmp_path)
    assert result["status"] == expected
    if "skipped" in case:
        assert result["cases"][0]["status"] == "NOT RUN"
