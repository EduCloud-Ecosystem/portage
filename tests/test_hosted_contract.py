# SPDX-License-Identifier: Apache-2.0
"""Fictional inputs only. No hosted access, transport or capacity qualification."""

import ast
import builtins
import copy
import hashlib
import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures/hosted_contract"
MODULE = ROOT / "integrations/ai_pilot/hosted_contract.py"
spec = importlib.util.spec_from_file_location("hosted_contract", MODULE)
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)


@pytest.fixture
def profile_data():
    return json.loads((FIXTURES / "profile.json").read_text())


@pytest.fixture
def profile(profile_data):
    return contract.validate_profile(profile_data)


@pytest.fixture
def response():
    return json.loads((FIXTURES / "arithmetic.json").read_text())


def classify(profile, response, *, status=200, content_type="application/json"):
    return contract.classify_response(
        profile, "arithmetic", status, content_type, json.dumps(response).encode()
    )


def assert_unknown(result):
    assert result.accounting_action == "retain_unknown"
    assert result.provider_reported_usage is None
    assert result.usage_status == "UNKNOWN" and result.stop
    assert result.evidence()["provider_termination"] == "UNVERIFIED"
    assert result.evidence()["execution_authorized"] is False


def test_prompt_literals_match_direct_protocol_without_importing_transport():
    source = (ROOT / "integrations/ai_pilot/qualify.py").read_text()
    tree = ast.parse(source)
    tasks = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TASKS"
            for target in node.targets
        )
    )
    assert contract.TASKS == tasks
    imports = []
    for node in ast.walk(ast.parse(MODULE.read_text())):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert set(imports) == {"__future__", "hashlib", "json", "re", "dataclasses"}


@pytest.mark.parametrize("task", ["arithmetic", "extraction"])
def test_fixed_request_and_fictional_response(profile, task):
    plan = contract.build_chat_plan(profile, task)
    assert plan.method == "POST"
    assert plan.url == "https://llm.jetstream-cloud.org/api/chat/completions"
    body = json.loads(plan.body)
    prompt = next(prompt for name, prompt, _ in contract.TASKS if name == task)
    assert body == {
        "model": "fixture_model_01",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32,
        "stream": False,
        "n": 1,
    }
    result = contract.classify_response(
        profile, task, 200, "application/json", (FIXTURES / f"{task}.json").read_bytes()
    )
    assert result.task == result.transport == "PASS"
    assert result.provider_reported_usage == 12
    assert result.usage_status == "PROVIDER_REPORTED"
    assert result.accounting_action == "record_provider_reported_usage"
    assert result.bound == "UNVERIFIED" and not result.stop
    assert "messages" not in repr(plan) and prompt not in repr(plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin", "http://llm.jetstream-cloud.org"),
        ("origin", "https://llm.jetstream-cloud.org:444"),
        ("origin", "https://fixture.invalid"),
        ("origin", "https://secret@llm.jetstream-cloud.org"),
        ("origin", "https://llm.jetstream-cloud.org?route=x"),
        ("origin", "https://llm.jetstream-cloud.org/api/"),
        ("chat_path", "/v1/chat/completions"),
        ("chat_path", "/api/api/chat/completions"),
        ("chat_path", "/fixture-model/v1/chat/completions"),
        ("chat_path", "/api/chat/completions?fallback=true"),
        ("catalog_path", "/api/v1/models"),
        ("model_id", None),
        ("model_id", ""),
        ("credential_owner_ref", None),
        ("returned_model_ids", []),
        ("returned_model_ids", ["fixture", "fixture"]),
        ("returned_model_ids", "fixture"),
        ("returned_model_ids", [None]),
    ],
)
def test_invalid_profile_and_exact_destination(profile_data, field, value):
    profile_data[field] = value
    with pytest.raises(contract.ContractError):
        contract.validate_profile(profile_data)


@pytest.mark.parametrize(
    "field",
    [
        "api_key",
        "authorization",
        "headers",
        "base_url",
        "fallback",
        "proxy",
        "verify_tls",
        "tools",
        "functions",
        "tool_ids",
        "task_id",
        "files",
        "search",
        "knowledge",
        "chat_id",
        "endpoint",
        "execute",
        "default_route",
    ],
)
def test_profile_rejects_overrides_and_credentials(profile_data, field):
    profile_data[field] = "FICTIONAL_SECRET_SENTINEL"
    with pytest.raises(contract.ContractError, match="^profile_fields$"):
        contract.validate_profile(profile_data)


@pytest.mark.parametrize("task", [None, {}, "", "custom", "https://fixture.invalid"])
def test_only_fixed_task_ids_can_be_planned(profile, task):
    with pytest.raises(contract.ContractError, match="task_not_allowed"):
        contract.build_chat_plan(profile, task)


def test_approval_fields_never_enable_execution():
    evidence = {name: True for name in contract.UNVERIFIED}
    evidence.update(
        execute=True, enabled=True, operator="fixture_owner_01", deadline=9999999999
    )
    for supplied in (None, {}, evidence):
        result = contract.assess_readiness(supplied)
        assert result["execution_authorized"] is False
        assert result["provider_observations"] == "NOT RUN"
        assert result["status"] == "FIXTURE_ONLY"
        assert set(result["unverified"]) == set(contract.UNVERIFIED)


@pytest.mark.parametrize(
    "status", [None, True, 0, 301, 302, 307, 308, 401, 403, 429, 500, 502, 503, 504]
)
def test_unknown_http_outcomes_never_retry(profile, response, status):
    result = classify(profile, response, status=status)
    assert_unknown(result)
    assert result.code in {"disconnected", "http_rejected"}
    assert "retry" not in result.accounting_action


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "text/event-stream",
        "text/html",
        "application/octet-stream",
        "application/json; charset=utf-16",
    ],
)
def test_streaming_or_unexpected_content_type_is_unknown(profile, response, content_type):
    assert_unknown(classify(profile, response, content_type=content_type))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"null",
        b"[]",
        b"{}",
        b"\xff",
        b"data: [DONE]",
        b'{"model":"fixture_model_01","model":"fixture_model_01","choices":[]}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e999}',
        b'{"x":1.0}',
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_malformed_duplicate_nonfinite_and_incomplete_json(profile, raw):
    assert_unknown(
        contract.classify_response(profile, "arithmetic", 200, "application/json", raw)
    )


def test_nested_duplicate_usage_is_rejected(profile, response):
    raw = (
        json.dumps(response)
        .replace('"total_tokens": 12', '"total_tokens": 12, "total_tokens": 0')
        .encode()
    )
    result = contract.classify_response(
        profile, "arithmetic", 200, "application/json", raw
    )
    assert_unknown(result)
    assert result.code == "duplicate_json_key"


@pytest.mark.parametrize(
    "field",
    [
        "error",
        "task_id",
        "task_ids",
        "tool_calls",
        "function_call",
        "usage_metadata",
        "retry_after",
    ],
)
def test_unknown_response_fields_are_not_forwarded(profile, response, field):
    response[field] = "FICTIONAL_PRIVATE_PAYLOAD"
    assert_unknown(classify(profile, response))


@pytest.mark.parametrize(
    "change",
    [
        "wrong_model",
        "missing_model",
        "two_choices",
        "no_choices",
        "wrong_index",
        "bool_index",
        "wrong_role",
        "nontext",
        "long_text",
        "missing_reason",
        "tool_reason",
        "null_reason",
        "tool_message",
        "function_message",
        "extra_choice",
        "bad_object",
        "negative_created",
        "bool_created",
        "overflow_created",
        "long_id",
        "long_fingerprint",
    ],
)
def test_exact_response_schema(profile, response, change):
    choice = response["choices"][0]
    if change == "wrong_model":
        response["model"] = "fixture_unapproved_model"
    elif change == "missing_model":
        del response["model"]
    elif change == "two_choices":
        response["choices"].append(copy.deepcopy(choice))
    elif change == "no_choices":
        response["choices"] = []
    elif change == "wrong_index":
        choice["index"] = 1
    elif change == "bool_index":
        choice["index"] = False
    elif change == "wrong_role":
        choice["message"]["role"] = "tool"
    elif change == "nontext":
        choice["message"]["content"] = [{"text": "42"}]
    elif change == "long_text":
        choice["message"]["content"] = "x" * 8193
    elif change == "missing_reason":
        del choice["finish_reason"]
    elif change == "tool_reason":
        choice["finish_reason"] = "tool_calls"
    elif change == "null_reason":
        choice["finish_reason"] = None
    elif change == "tool_message":
        choice["message"]["tool_calls"] = []
    elif change == "function_message":
        choice["message"]["function_call"] = {}
    elif change == "extra_choice":
        choice["task_id"] = "fixture"
    elif change == "bad_object":
        response["object"] = "chat.completion.chunk"
    elif change == "negative_created":
        response["created"] = -1
    elif change == "bool_created":
        response["created"] = True
    elif change == "overflow_created":
        response["created"] = 1 << 63
    elif change == "long_id":
        response["id"] = "x" * 257
    elif change == "long_fingerprint":
        response["system_fingerprint"] = "x" * 129
    assert_unknown(classify(profile, response))


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        [],
        True,
        {"total_tokens": None},
        {"total_tokens": -1},
        {"total_tokens": True},
        {"total_tokens": 12.0},
        {"total_tokens": "12"},
        {"total_tokens": 65537},
        {"total_tokens": 1 << 63},
        {"total_tokens": 10**100},
        {"total_tokens": 12, "prompt_tokens": 10},
        {"total_tokens": 12, "completion_tokens": 2},
        {"total_tokens": 12, "prompt_tokens": 10, "completion_tokens": 3},
        {"total_tokens": 12, "prompt_tokens": -1, "completion_tokens": 13},
        {"total_tokens": 12, "prompt_tokens": True, "completion_tokens": 11},
        {"total_tokens": 12, "prompt_tokens": 65537, "completion_tokens": 0},
        {"total_tokens": 12, "completion_tokens_details": {"reasoning_tokens": 1}},
    ],
)
def test_invalid_or_unsupported_usage_never_becomes_a_charge(profile, response, usage):
    response["usage"] = usage
    assert_unknown(classify(profile, response))


def test_missing_usage_keeps_correct_task_separate(profile, response):
    del response["usage"]
    result = classify(profile, response)
    assert_unknown(result)
    assert result.task == result.transport == "PASS"


@pytest.mark.parametrize("total", [0, 12, 1024, 1025, 65536])
def test_supported_reported_usage_is_not_clamped_or_promoted(profile, response, total):
    response["usage"] = {"total_tokens": total}
    result = classify(profile, response)
    assert result.provider_reported_usage == total
    assert result.task == "PASS"
    assert result.bound == ("FAIL" if total > 1024 else "UNVERIFIED")
    assert result.stop == (total > 1024)
    assert result.accounting_action == (
        "record_provider_reported_usage_and_stop"
        if total > 1024
        else "record_provider_reported_usage"
    )


@pytest.mark.parametrize(
    "text,reason", [("wrong", "stop"), ("42", "length"), ("", "length")]
)
def test_quality_failure_and_usage_are_independent(profile, response, text, reason):
    response["choices"][0]["message"]["content"] = text
    response["choices"][0]["finish_reason"] = reason
    result = classify(profile, response)
    assert result.task == "FAIL" and result.stop
    assert result.provider_reported_usage == 12
    assert result.accounting_action == "record_provider_reported_usage"


def test_exact_preapproved_returned_model_mapping(profile, response):
    response["model"] = "fixture_model_alias_01"
    assert classify(profile, response).usage_status == "PROVIDER_REPORTED"


def test_bounded_evidence_never_contains_payload_ids_headers_or_amounts(
    profile, response
):
    sentinel = "FICTIONAL_SECRET_private@example.invalid"
    response["id"] = sentinel
    response["system_fingerprint"] = sentinel
    response["choices"][0]["message"]["content"] = sentinel
    result = classify(profile, response)
    evidence = json.dumps(result.evidence())
    assert len(evidence) < 1024
    for forbidden in (
        sentinel,
        "fixture_model",
        "fixture_owner",
        "total_tokens",
        "headers",
    ):
        assert forbidden not in evidence
    assert (
        result.evidence()["body_sha256"]
        == hashlib.sha256(json.dumps(response).encode()).hexdigest()
    )
    assert "provider_reported_usage" not in result.evidence()
    assert "reconcile" not in result.accounting_action
    plan = contract.build_chat_plan(profile, "arithmetic")
    assert "What is" not in json.dumps(plan.evidence())
    assert "fixture_owner" not in repr(profile)


def test_oversized_response_is_unknown_without_hashing_payload(profile):
    result = contract.classify_response(
        profile,
        "arithmetic",
        200,
        "application/json",
        b"x" * (contract.MAX_BODY_BYTES + 1),
    )
    assert_unknown(result)
    assert result.body_sha256 is None


def test_manually_constructed_evidence_is_still_sanitized():
    sentinel = "FICTIONAL_SECRET_private@example.invalid"
    forged = contract.Classification(sentinel, body_sha256=sentinel)
    assert sentinel not in json.dumps(forged.evidence())
    assert forged.evidence()["code"] == "invalid_classification"
    forged_hash = contract.Classification("http_rejected", profile_sha256=sentinel)
    assert forged_hash.evidence()["profile_sha256"] is None
    plan = contract.RequestPlan("POST", sentinel, b"{}", sentinel)
    assert sentinel not in json.dumps(plan.evidence())


def test_retry_after_cannot_create_a_retry_or_execution_path(profile, response):
    # The classifier does not accept arbitrary headers, retry configuration or I/O.
    with pytest.raises(TypeError):
        contract.classify_response(
            profile,
            "arithmetic",
            429,
            "application/json",
            json.dumps(response).encode(),
            headers={"Retry-After": "0", "Location": "https://fixture.invalid"},
        )
    result = classify(profile, response, status=429)
    assert_unknown(result)
    assert result.accounting_action == "retain_unknown"


def test_no_io_or_secret_lookup_during_validation_planning_or_classification(
    monkeypatch, profile_data, response
):
    raw = json.dumps(response).encode()

    def forbidden(*_, **__):
        raise AssertionError("fixture module attempted forbidden I/O")

    class NoEnvironment:
        __getitem__ = get = __iter__ = forbidden

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(Path, "read_text", forbidden)
        guard.setattr(Path, "read_bytes", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(socket, "getaddrinfo", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(http.client, "HTTPConnection", forbidden)
        guard.setattr(http.client, "HTTPSConnection", forbidden)
        guard.setattr(urllib.request, "urlopen", forbidden)
        guard.setattr(urllib.request, "build_opener", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(os, "getenv", forbidden)
        guard.setattr(os, "environ", NoEnvironment())
        profile = contract.validate_profile(profile_data)
        contract.build_chat_plan(profile, "arithmetic").evidence()
        result = contract.classify_response(
            profile, "arithmetic", 200, "application/json", raw
        )
        assert result.evidence()["execution_authorized"] is False
        assert (
            contract.assess_readiness({"all_approvals": True})["execution_authorized"]
            is False
        )


@pytest.fixture
def ledger(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "hosted_test_ledger", ROOT / "src/portage/pilot_ledger.py"
    )
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    value = pilot.Ledger(tmp_path / "ledger.sqlite")
    value.project("fixture_project", 2048, 1)
    value.member("fixture_project", "fixture_owner", 2048, 1)
    token = value.issue("fixture_project", subject="fixture_owner")
    return pilot, value, token


@pytest.mark.parametrize(
    "outcome",
    ["missing_usage", "overflow_usage", "http_error", "disconnect", "streaming"],
)
def test_unknown_liability_survives_reopen_without_settlement_side_effects(
    profile, response, ledger, monkeypatch, outcome
):
    pilot, value, token = ledger
    request_id = value.admit(token, "code_small", 1024)
    status, content_type = 200, "application/json"
    if outcome == "missing_usage":
        del response["usage"]
    elif outcome == "overflow_usage":
        response["usage"] = {"total_tokens": 1 << 100}
    elif outcome == "http_error":
        status = 503
    elif outcome == "disconnect":
        status = None
    elif outcome == "streaming":
        content_type = "text/event-stream"

    def forbidden(*_, **__):
        pytest.fail("classification attempted ledger settlement/reconciliation")

    with monkeypatch.context() as guard:
        guard.setattr(pilot.Ledger, "settle", forbidden)
        guard.setattr(pilot.Ledger, "reconcile", forbidden)
        result = classify(profile, response, status=status, content_type=content_type)
        assert_unknown(result)
        assert value.usage("fixture_project") == {
            "committed": 1024,
            "active": 1,
            "unresolved": 0,
        }
    # Test harness explicitly records ambiguity, not the pure adapter.
    value.settle(request_id, None)
    reopened = pilot.Ledger(value.path)
    assert reopened.usage("fixture_project") == {
        "committed": 1024,
        "active": 1,
        "unresolved": 1,
    }
    reopened.settle(request_id, 0)
    assert reopened.usage("fixture_project")["committed"] == 1024
    with pytest.raises(pilot.Denied):
        reopened.admit(token, "code_small", 1)


def test_supported_over_reservation_usage_fits_existing_ledger_without_clamping(
    profile, response, ledger
):
    _, value, token = ledger
    request_id = value.admit(token, "code_small", 1024)
    response["usage"] = {"total_tokens": 65536}
    result = classify(profile, response)
    assert result.stop and result.bound == "FAIL"
    # Explicit test action; classification itself never writes the ledger.
    value.settle(request_id, result.provider_reported_usage)
    assert value.usage("fixture_project") == {
        "committed": 65536,
        "active": 0,
        "unresolved": 0,
    }
