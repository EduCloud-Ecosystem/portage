# SPDX-License-Identifier: Apache-2.0
"""Hermetic provider and real HTTP gateway controls; never load a real API key."""

import importlib.util
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src/portage"))
from openrouter_adapter import (  # noqa: E402
    CANONICAL,
    CASES,
    ENDPOINT,
    MODEL,
    SmokeGuard,
    case_body,
    load_key,
    manifest,
    validate_catalog,
)
from pilot_ledger import Denied  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "openrouter_gateway", Path(__file__).parents[1] / "integrations/ai_pilot/gateway.py"
)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def catalog():
    return {"model": MODEL, "observed_at": time.time()}


def result():
    return {
        "model": CANONICAL,
        "provider": "OpenAI",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 10,
            "total_tokens": 20,
            "cost": 0.0001,
        },
        "choices": [{"message": {"content": '{"answer": 5}'}}],
    }


def test_key_loader_private_file_no_shell_or_symlink(tmp_path):
    path = tmp_path / ".env"
    path.write_text('# comment\nOPENROUTER_API_KEY="sk-or-fixture"\n')
    path.chmod(0o600)
    assert load_key(path) == "sk-or-fixture"
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_key(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        load_key(link)
    path.write_text("OPENROUTER_API_KEY=sk-or-fixture\nOPENROUTER_API_KEY=duplicate")
    with pytest.raises(ValueError):
        load_key(path)


def test_stale_catalog_and_run_replay(tmp_path):
    with pytest.raises(ValueError):
        SmokeGuard(tmp_path / "stale", {"observed_at": time.time() - 301})
    SmokeGuard(tmp_path / "run", catalog())
    with pytest.raises(FileExistsError):
        SmokeGuard(tmp_path / "run", catalog())


def test_catalog_price_parameter_and_revision_checks():
    endpoint = {
        "tag": "openai",
        "name": CANONICAL,
        "status": 0,
        "pricing": {"prompt": "0.0000004", "completion": "0.0000016"},
        "supported_parameters": ["max_tokens", "response_format"],
    }
    value = {"data": {"id": MODEL, "endpoints": [endpoint]}}
    assert validate_catalog(value)["canonical"] == CANONICAL
    for price in ["NaN", "-1", "1"]:
        endpoint["pricing"]["prompt"] = price
        with pytest.raises(ValueError):
            validate_catalog(value)
    endpoint["pricing"]["prompt"] = "0.0000004"
    endpoint["name"] = "unknown"
    with pytest.raises(ValueError):
        validate_catalog(value)


def test_durable_claim_and_failure_stop(tmp_path):
    guard = SmokeGuard(tmp_path / "run", catalog())
    name = guard.start(case_body(CASES[0]), "request01")
    guard.claim(name)
    with pytest.raises(Denied):
        guard.claim(name)
    assert guard.finish(name) is False
    with pytest.raises(Denied):
        guard.start(case_body(CASES[1]), "request02")
    assert guard.summary()["unknown_liability_usd"] == 0.0125
    events = [
        json.loads(line)
        for line in (guard.directory / "journal.jsonl").read_text().splitlines()
    ]
    assert [e["event"] for e in events] == [
        "created",
        "admitted",
        "dispatch_claim",
        "finished",
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "Other"),
        ("model", "Other"),
        ("usage", {}),
        ("usage", {"total_tokens": True, "cost": 0}),
        ("usage", {"total_tokens": 20, "cost": -1}),
        ("usage", {"total_tokens": 2049, "cost": 0}),
        ("usage", {"total_tokens": 20, "cost": 1}),
    ],
)
def test_invalid_identity_usage_or_cost_remains_unknown(tmp_path, field, value):
    guard = SmokeGuard(tmp_path / "run", catalog())
    name = guard.start(case_body(CASES[0]), "request01")
    guard.claim(name)
    response = result()
    response[field] = value
    guard.observe(name, response)
    assert not guard.finish(name, complete=True)
    assert guard.summary()["unknown_liability_usd"] > 0


def test_finite_four_case_budget_and_no_replay(tmp_path):
    guard = SmokeGuard(tmp_path / "run", catalog())
    for case in CASES:
        name = guard.start(case_body(case), case["name"])
        guard.claim(name)
        guard.observe(name, result())
        assert guard.finish(name, complete=True)
    with pytest.raises(Denied):
        guard.start(case_body(CASES[0]), "again")
    assert guard.summary()["dispatch_claims"] == 4
    guard.deadline = time.time() - 1
    with pytest.raises(Denied):
        guard.check_body(case_body(CASES[0]))


@pytest.fixture
def connected(tmp_path, monkeypatch):
    state = {
        "active": True,
        "requests": [],
        "response": result(),
        "failure": False,
        "terminal": True,
    }

    class Authority(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            data = json.dumps({"active": state["active"], "project": "smoke001"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    @contextmanager
    def inference(request, timeout, approval_window, dispatch_check):
        approval_window.check()
        dispatch_check()
        state["requests"].append(request)
        if state["failure"]:
            raise TimeoutError("fixture transport failed")
        body = json.loads(request.data)
        if body["stream"]:
            raw = b": keepalive\n\n"
            raw += b"data: " + json.dumps(state["response"]).encode() + b"\n\n"
            if state["terminal"]:
                raw += b"data: [DONE]\n\n"
        else:
            raw = json.dumps(state["response"]).encode()
        yield io.BytesIO(raw)

    monkeypatch.setattr(gateway, "inference_attempt", inference)
    authority = ThreadingHTTPServer(("127.0.0.1", 0), Authority)
    authority_thread = threading.Thread(target=authority.serve_forever, daemon=True)
    authority_thread.start()
    guard = SmokeGuard(tmp_path / "run", catalog())
    ledger = gateway.Ledger(tmp_path / "ledger.sqlite")
    ledger.project("smoke001", 8192, 1)
    ledger.member("smoke001", "synthetic01", 8192)
    token = ledger.issue("smoke001", subject="synthetic01")
    service = gateway.Gateway(
        ("127.0.0.1", 0),
        ledger,
        manifest(),
        "control",
        "sk-or-test-only",
        f"http://127.0.0.1:{authority.server_port}",
        "authority",
        external_guard=guard,
    )
    worker = threading.Thread(target=service.serve_forever, daemon=True)
    worker.start()

    def request(body, credential=token):
        req = urllib.request.Request(
            f"http://127.0.0.1:{service.server_port}/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + credential},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    state["origin"] = f"http://127.0.0.1:{service.server_port}"
    state["token"] = token
    yield state, guard, ledger, request
    service.shutdown()
    worker.join(timeout=5)
    service.server_close()
    authority.shutdown()
    authority_thread.join(timeout=5)
    authority.server_close()


def test_gateway_alias_auth_provider_policy_and_settlement(connected):
    state, guard, ledger, request = connected
    assert request(case_body(CASES[0]))[0] == 200
    assert len(state["requests"]) == 1
    req = state["requests"][0]
    assert req.full_url == ENDPOINT + "/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer sk-or-test-only"
    body = json.loads(req.data)
    assert body["model"] == MODEL
    assert body["provider"]["only"] == ["openai"]
    assert body["provider"]["allow_fallbacks"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert guard.summary()["reported_cost_usd"] == 0.0001
    assert ledger.usage("smoke001", "synthetic01")["committed"] == 20


@pytest.mark.parametrize("mode", ["invalid_key", "revoked", "override", "arbitrary_text"])
def test_pre_admission_controls_make_no_external_request(connected, mode):
    state, guard, ledger, request = connected
    body = case_body(CASES[0])
    if mode == "revoked":
        state["active"] = False
    elif mode == "override":
        body["provider"] = {"only": ["unapproved"]}
    elif mode == "arbitrary_text":
        body["messages"][0]["content"] = "not an approved synthetic case"
    status, _ = request(body, "invalid") if mode == "invalid_key" else request(body)
    assert status in {400, 401, 403}
    assert not state["requests"] and not guard.attempts
    assert ledger.usage("smoke001", "synthetic01")["committed"] == 0


@pytest.mark.parametrize("stream,terminal", [(False, True), (True, True), (True, False)])
def test_stream_and_unknown_accounting(connected, stream, terminal):
    state, guard, ledger, request = connected
    case = CASES[2] if stream else CASES[0]
    state["terminal"] = terminal
    if not stream:
        state["response"].pop("usage")
    status, _ = request(case_body(case))
    assert status == 200
    complete = stream and terminal
    assert (guard.attempts[case["name"]]["state"] == "complete") == complete
    assert (ledger.usage("smoke001", "synthetic01")["committed"] == 20) == complete
    assert len(state["requests"]) == 1


def test_transport_failure_no_retry_unknown_hold(connected):
    state, guard, ledger, request = connected
    state["failure"] = True
    assert request(case_body(CASES[0]))[0] == 503
    assert len(state["requests"]) == 1
    assert guard.summary()["unknown_liability_usd"] == 0.0125
    assert ledger.usage("smoke001", "synthetic01")["committed"] > 20


def test_external_mode_cannot_start_without_guard(tmp_path):
    with pytest.raises(ValueError):
        gateway.Gateway(("127.0.0.1", 0), None, manifest(), "", "", "", "")
    changed = manifest()
    changed["models"]["code_small"]["endpoint"] = "https://example.org"
    with pytest.raises(ValueError):
        gateway.validate_manifest(changed, "external-smoke")


def test_actual_belay_consumer_when_environment_available(connected, tmp_path):
    import os

    source = os.environ.get("OPENROUTER_TEST_BELAY_SOURCE")
    if not source:
        pytest.skip("run separately in pinned Belay environment")
    sys.path.insert(0, str(Path(__file__).parents[1] / "integrations/ai_pilot"))
    from openrouter_pilot import belay_call

    state, guard, ledger, _ = connected
    state["response"]["choices"][0]["message"]["content"] = json.dumps(
        CASES[3]["expected"]
    )
    value, summary = belay_call(
        Path(source), tmp_path, state["origin"], state["token"], CASES[3]
    )
    assert value == CASES[3]["expected"]
    assert len(state["requests"]) == 1
    assert guard.summary()["dispatch_claims"] == 1
    assert summary["attempts"] == 1
    assert summary["consumed"]["tokens"] == 20
    assert ledger.usage("smoke001", "synthetic01")["committed"] == 20


def test_remaining_cases_cannot_replay_or_extend_prior_envelope(tmp_path):
    deadline = time.time() + 50
    prior = {"cases": ["arithmetic_json", "extraction_json"], "deadline": deadline}
    guard = SmokeGuard(tmp_path / "continued", catalog(), prior=prior)
    assert guard.deadline == deadline
    assert guard.summary()["prior_reserved_usd"] == 0.025
    for case in CASES[:2]:
        with pytest.raises(Denied):
            guard.check_body(case_body(case))
    assert guard.check_body(case_body(CASES[2])) == "stream_terminal"
    with pytest.raises(FileExistsError):
        SmokeGuard(tmp_path / "continued", catalog(), prior=prior)
