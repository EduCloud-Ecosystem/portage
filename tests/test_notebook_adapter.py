# SPDX-License-Identifier: Apache-2.0
"""No network: immutable input, bounded loop, failure accounting and replay controls."""

import json
import sys
from pathlib import Path

import pytest
from test_openrouter_pilot import catalog, result

sys.path.insert(0, str(Path(__file__).parents[1] / "src/portage"))
from notebook_adapter import NotebookGuard, notebook_manifest  # noqa: E402
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
