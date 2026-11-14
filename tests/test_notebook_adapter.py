# SPDX-License-Identifier: Apache-2.0
"""No network: immutable input, bounded loop, failure accounting and replay controls."""

import json
import sys
from pathlib import Path

import pytest
from test_openrouter_pilot import catalog, gateway, result

sys.path.insert(0, str(Path(__file__).parents[1] / "src/portage"))
from notebook_adapter import (  # noqa: E402
    NhanesNotebookGuard,
    NotebookGuard,
    nhanes_manifest,
    notebook_manifest,
)
from openrouter_adapter import (  # noqa: E402
    SmokeGuard,
    manifest,
    validate_external_manifest,
)
from pilot_ledger import Denied, prepare_request  # noqa: E402

CONTEXT = {
    "exercise": {"title": "synthetic"},
    "current_functional_model": "print('ok')\n",
    "last_result": "no run yet",
    "attempt_signals": {"attempts": 0},
}
SYSTEMS = {
    "planner": "fixed planner",
    "reasoner": "fixed reasoner",
    "self_eval": "fixed eval",
}


def test_nhanes_context_ceiling_is_separate_and_transport_budget_unchanged(tmp_path):
    context = {**CONTEXT, "current_functional_model": "x" * 16000}
    raw = body("planner")
    raw["messages"][1]["content"] = json.dumps(context)
    with pytest.raises(Denied):
        prepare_request(raw, notebook_manifest()["models"], "chat/completions")
    _, reserved = prepare_request(raw, nhanes_manifest()["models"], "chat/completions")
    assert 16384 < reserved <= 24576
    guard = NhanesNotebookGuard(tmp_path / "nhanes", catalog(), context, SYSTEMS)
    guard.validate_manifest(nhanes_manifest())
    with pytest.raises(ValueError):
        guard.validate_manifest(notebook_manifest())
    assert guard.budget == 0.175 and guard.request_limit == 7
    assert notebook_manifest()["models"]["code_small"]["max_request_tokens"] == 16384
    assert nhanes_manifest()["project"] == "nhanes01"
    name = guard.start(raw, "nhanes")
    guard.claim(name)
    assert not guard.finish(name)
    assert guard.summary()["unknown_liability_usd"] == pytest.approx(0.025)
    with pytest.raises(Denied):
        guard.start(raw, "repeat")
    assert guard.summary()["dispatch_claims"] == 1


def test_nhanes_rejects_oversize_and_changed_context_before_dispatch(tmp_path):
    guard = NhanesNotebookGuard(tmp_path / "nhanes", catalog(), CONTEXT, SYSTEMS)
    raw = body("planner")
    raw["messages"][1]["content"] = json.dumps({**CONTEXT, "extra": "unapproved"})
    with pytest.raises(Denied):
        guard.start(raw, "tampered")
    raw["messages"][1]["content"] = "x" * 24576
    with pytest.raises(Denied):
        prepare_request(raw, nhanes_manifest()["models"], "chat/completions")
    assert guard.summary()["dispatch_claims"] == 0


def body(stage):
    if stage == "planner":
        user = json.dumps(CONTEXT)
    elif stage == "reasoner":
        user = "CONTEXT:\n" + json.dumps(CONTEXT) + "\n\nCHOSEN PLAN FOR THIS TURN:\n{}"
    else:
        user = json.dumps(
            {
                "exercise": CONTEXT["exercise"],
                "student_state": {
                    k: CONTEXT[k]
                    for k in (
                        "current_functional_model",
                        "last_result",
                        "attempt_signals",
                    )
                },
                "chosen_plan": {},
                "sol_draft": {"message": "synthetic"},
            }
        )
    return {
        "model": "code_large" if stage == "reasoner" else "code_small",
        "messages": [
            {"role": "system", "content": SYSTEMS[stage]},
            {"role": "user", "content": user},
        ],
        "max_tokens": 800 if stage == "reasoner" else 400,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }


def test_limits_accounting_and_original_profiles(tmp_path):
    g = NotebookGuard(tmp_path / "live", catalog(), CONTEXT, SYSTEMS)
    validate_external_manifest(notebook_manifest())
    with pytest.raises(ValueError):
        SmokeGuard(tmp_path / "old", catalog()).validate_manifest(notebook_manifest())
    with pytest.raises(ValueError):
        g.validate_manifest(manifest())
    for stage in g.stages:
        raw = body(stage)
        outgoing, reserved = prepare_request(
            raw, notebook_manifest()["models"], "chat/completions"
        )
        assert (
            reserved <= 16384
            and g.request_body(outgoing)["provider"]["allow_fallbacks"] is False
        )
        name = g.start(raw, stage)
        g.claim(name)
        with pytest.raises(Denied):
            g.claim(name)
        g.observe(name, result())
        assert g.finish(name, complete=True)
    assert g.summary()["dispatch_claims"] == 7
    assert sum(x["reserved_usd"] for x in g.attempts.values()) == pytest.approx(0.175)
    with pytest.raises(Denied):
        g.start(body("planner"), "replay")
    with pytest.raises(FileExistsError):
        NotebookGuard(tmp_path / "live", catalog(), CONTEXT, SYSTEMS)


@pytest.mark.parametrize(
    "change", ["code", "prompt", "role", "extra", "tier", "messages"]
)
def test_unapproved_input_never_admitted(tmp_path, change):
    g = NotebookGuard(tmp_path / "live", catalog(), CONTEXT, SYSTEMS)
    b = body("planner")
    if change == "code":
        b["messages"][1]["content"] = b["messages"][1]["content"].replace("ok", "private")
    elif change == "prompt":
        b["messages"][0]["content"] = "unapproved"
    elif change == "role":
        b["messages"][1]["role"] = "assistant"
    elif change == "extra":
        b["provider"] = {"only": ["other"]}
    elif change == "tier":
        b["model"] = "code_large"
    else:
        b["messages"].append({"role": "user", "content": "retry"})
    with pytest.raises(Denied):
        g.start(b, "bad")
    assert not g.attempts and g.summary()["dispatch_claims"] == 0


def test_unknown_holds_and_expiry(tmp_path):
    g = NotebookGuard(tmp_path / "live", catalog(), CONTEXT, SYSTEMS)
    name = g.start(body("planner"), "request")
    g.claim(name)
    assert not g.finish(name)
    assert g.summary()["unknown_liability_usd"] == pytest.approx(0.025)
    with pytest.raises(Denied):
        g.start(body("reasoner"), "next")
    other = NotebookGuard(tmp_path / "expired", catalog(), CONTEXT, SYSTEMS)
    other.deadline = 0
    with pytest.raises(Denied):
        other.start(body("planner"), "expired")
    assert not other.attempts


def test_real_gateway_accepts_only_exact_nhanes_guard_and_manifest(tmp_path):
    guard = NhanesNotebookGuard(tmp_path / "nhanes", catalog(), CONTEXT, SYSTEMS)
    value = nhanes_manifest()
    validate_external_manifest(value)
    service = gateway.Gateway(
        ("127.0.0.1", 0),
        None,
        value,
        "synthetic",
        "synthetic",
        "http://127.0.0.1:1",
        "synthetic",
        external_guard=guard,
    )
    service.server_close()
    for field, changed in (("project_allowance", 999999), ("concurrency", 2)):
        mutated = {**value, field: changed}
        with pytest.raises(ValueError):
            gateway.Gateway(
                ("127.0.0.1", 0),
                None,
                mutated,
                "",
                "",
                "http://127.0.0.1:1",
                "",
                external_guard=guard,
            )
    wrong = NotebookGuard(tmp_path / "echo", catalog(), CONTEXT, SYSTEMS)
    with pytest.raises(ValueError):
        gateway.Gateway(
            ("127.0.0.1", 0),
            None,
            value,
            "",
            "",
            "http://127.0.0.1:1",
            "",
            external_guard=wrong,
        )
    assert guard.summary()["dispatch_claims"] == 0
