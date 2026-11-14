# SPDX-License-Identifier: Apache-2.0
import json
import sqlite3
import time

import pytest
from conftest import SCRIPTS, _load
from test_pilot_gateway import Fixture, gateway
from test_pilot_gateway import server as server

decisions = _load("system_one_tests", SCRIPTS / "decisions.py")
MAX_INPUT_BYTES, QUESTIONS, ShadowDecider = (
    decisions.MAX_INPUT_BYTES,
    decisions.QUESTIONS,
    decisions.ShadowDecider,
)


def messages(text):
    return [{"role": "user", "content": text}]


def body(text="Explain a Python loop", **extra):
    return {"model": "code_small", "messages": messages(text), **extra}


def events(service):
    with service.ledger.db() as db:
        return [
            json.loads(row[0])
            for row in db.execute("SELECT report FROM shadow_decisions")
        ]


class SyntheticScores:
    backend_id = "synthetic-score-fixture-v1"
    artifact_sha256 = "0" * 64
    kind = "synthetic_model"

    def __init__(self, raw=None):
        self.calls = 0
        self.raw = (
            raw
            if raw is not None
            else {
                "task_class": [0, 0, 1],
                "recommended_tier": [0, 1],
                "needs_retrieval": [0, 1],
            }
        )

    def score(self, text, questions):
        self.calls += 1
        assert questions == QUESTIONS
        return self.raw


def test_rules_are_typed_bounded_and_not_a_learned_model():
    decider = ShadowDecider()
    result = decider.decide(messages("Explain a Python loop"))
    assert result["status"] == "answered"
    assert result["decisions"]["recommended_tier"]["value"] == "code_small"
    assert result["decisions"]["needs_retrieval"]["value"] is False
    assert result["backend_kind"] == "rules"
    assert result["backend_calls"] == 1 and result["model_forward_calls"] == 0
    assert result["score_semantics"] == "uncalibrated"
    assert "Explain a Python loop" not in json.dumps(result)
    assert decider.decide(messages("hello"))["status"] == "abstained"
    assert decider.decide(messages("explain this traceback"))["status"] == "abstained"
    for text in ("", "x" * (MAX_INPUT_BYTES + 1), "é" * MAX_INPUT_BYTES):
        assert decider.decide(messages(text))["backend_calls"] == 0


def test_one_forward_call_answers_all_questions():
    backend = SyntheticScores()
    result = ShadowDecider(backend).decide(messages("fabricated input"))
    assert backend.calls == result["model_forward_calls"] == 1
    assert result["decisions"]["needs_retrieval"]["value"] is True
    assert result["decisions"]["recommended_tier"]["value"] == "code_large"


@pytest.mark.parametrize(
    "raw",
    [
        {},
        [],
        {"permissions": "allow"},
        {
            "task_class": [0, 0, 1],
            "recommended_tier": [0, float("nan")],
            "needs_retrieval": [0, 1],
        },
        {
            "task_class": [0, float("inf"), 1],
            "recommended_tier": [0, 1],
            "needs_retrieval": [0, 1],
        },
        {
            "task_class": [True, 0, 1],
            "recommended_tier": [0, 1],
            "needs_retrieval": [0, 1],
        },
        {
            "task_class": [0, 0, 1],
            "recommended_tier": [0, 10**400],
            "needs_retrieval": [0, 1],
        },
        {
            "task_class": [0, 0, 1],
            "recommended_tier": [0, "source text"],
            "needs_retrieval": [0, 1],
        },
    ],
)
def test_invalid_scores_abstain_without_persisting_backend_payload(raw):
    backend = SyntheticScores(raw)
    result = ShadowDecider(backend).decide(messages("private-marker"))
    assert result["status"] == "abstained"
    assert result["reason"] == "invalid_scores" and result["decisions"] == {}
    assert result["backend_calls"] == backend.calls == 1
    assert "private-marker" not in json.dumps(result)


def test_backend_failure_retains_work_count_but_not_exception_text():
    class Fails(SyntheticScores):
        def score(self, *_):
            raise RuntimeError("secret-input-and-credential")

    result = ShadowDecider(Fails()).decide(messages("private-marker"))
    assert result["status"] == "failed"
    assert result["model_forward_calls"] == 1
    assert "secret" not in json.dumps(result) and "private-marker" not in json.dumps(
        result
    )


def test_disabled_default_preserves_response_and_creates_no_event(server):
    service, request = server
    assert service.shadow_decider is None
    status, response = request("/v1/chat/completions", body())
    assert status == 200 and json.loads(response) == {
        "usage": {"total_tokens": 12},
        "choices": [],
    }
    assert events(service) == []


def test_advisory_model_cannot_change_route_or_accounting(server):
    service, request = server
    backend = SyntheticScores()
    service.shadow_decider = ShadowDecider(backend)
    assert request("/v1/chat/completions", body())[0] == 200
    assert len(Fixture.calls) == backend.calls == 1
    assert Fixture.calls[0]["model"] == "code_small"
    assert events(service)[0]["decisions"]["recommended_tier"]["value"] == "code_large"
    assert service.ledger.usage("course01", "learner1")["committed"] == 12
    with service.ledger.db() as db:
        row = db.execute("SELECT id FROM requests").fetchone()
    with pytest.raises(gateway.Denied):
        service.ledger.record_shadow_decision(row[0], events(service)[0])


@pytest.mark.parametrize(
    "case", ["membership", "alias", "malformed", "budget", "credential"]
)
def test_pre_admission_refusal_has_no_backend_or_transport(server, case):
    service, request = server
    backend = SyntheticScores()
    service.shadow_decider = ShadowDecider(backend)
    payload, kwargs = body(), {}
    if case == "membership":
        Fixture.active = False
    elif case == "alias":
        payload["model"] = "commercial"
    elif case == "malformed":
        payload["messages"] = "not messages"
    elif case == "budget":
        service.ledger.member("course01", "learner1", 1)
    else:
        kwargs["key"] = "invalid"
    assert request("/v1/chat/completions", payload, **kwargs)[0] >= 400
    assert not events(service) and not Fixture.calls and backend.calls == 0


def test_revocation_during_decision_prevents_transport_and_retains_liability(server):
    service, request = server

    class Revokes(SyntheticScores):
        def score(self, text, questions):
            Fixture.active = False
            return super().score(text, questions)

    backend = Revokes()
    service.shadow_decider = ShadowDecider(backend)
    assert request("/v1/chat/completions", body())[0] == 403
    assert not Fixture.calls and backend.calls == 1 and len(events(service)) == 1
    with service.ledger.db() as db:
        row = db.execute("SELECT state,actual,reserved FROM requests").fetchone()
    assert row["state"] == "unknown" and row["actual"] is None and row["reserved"] > 0


def test_failed_shadow_does_not_break_allowed_inference(server):
    service, request = server

    class Fails(SyntheticScores):
        def score(self, *_):
            raise RuntimeError("private-marker")

    service.shadow_decider = ShadowDecider(Fails())
    assert request("/v1/chat/completions", body())[0] == 200
    assert events(service)[0]["status"] == "failed" and len(Fixture.calls) == 1


def test_shadow_with_streaming_and_embedding_exclusion(server):
    service, request = server
    service.shadow_decider = ShadowDecider()
    status, result = request("/v1/chat/completions", body(stream=True))
    assert status == 200 and b"[DONE]" in result and len(events(service)) == 1
    assert (
        request("/v1/embeddings", {"model": "embedding", "input": "synthetic"})[0] == 200
    )
    assert len(events(service)) == 1 and len(Fixture.calls) == 2


def test_deadline_expiry_during_decision_prevents_transport(server):
    service, request = server
    window = gateway.ApprovalWindow(time.time() + 30)
    service.approval_window = window

    class Expires(SyntheticScores):
        def score(self, text, questions):
            window.expired = True
            return super().score(text, questions)

    service.shadow_decider = ShadowDecider(Expires())
    assert request("/v1/chat/completions", body())[0] == 403
    assert len(events(service)) == 1 and not Fixture.calls
    with service.ledger.db() as db:
        assert db.execute("SELECT state FROM requests").fetchone()[0] == "unknown"


def test_unknown_upstream_usage_is_not_erased_by_a_decision(server, monkeypatch):
    service, request = server
    service.shadow_decider = ShadowDecider()

    def no_usage(handler):
        payload = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
        Fixture.calls.append(payload)
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b'{"choices":[]}')

    monkeypatch.setattr(Fixture, "do_POST", no_usage)
    assert request("/v1/chat/completions", body())[0] == 200
    assert len(events(service)) == len(Fixture.calls) == 1
    with service.ledger.db() as db:
        row = db.execute("SELECT state,actual,reserved FROM requests").fetchone()
    assert row["state"] == "unknown" and row["actual"] is None and row["reserved"] > 0


@pytest.mark.parametrize("mode", ["hosted", "qualification"])
def test_shadow_cannot_enter_hosted_or_qualification_mode(server, mode):
    service, _ = server
    manifest = {**service.manifest, "mode": mode}
    with pytest.raises(ValueError, match="synthetic"):
        gateway.Gateway(
            ("127.0.0.1", 0),
            service.ledger,
            manifest,
            "control",
            "inference",
            "http://127.0.0.1",
            "authority",
            shadow_decider=ShadowDecider(),
        )


def test_ledger_migrates_without_rewriting_existing_attempts(tmp_path):
    path = tmp_path / "legacy.sqlite"
    ledger = gateway.Ledger(path)
    ledger.project("course01", 100, 2)
    ledger.member("course01", "learner1", 100)
    token = ledger.issue("course01", subject="learner1")
    attempt = ledger.admit(token, "code_small", 10)
    ledger.settle(attempt, None)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE shadow_decisions")
    gateway.Ledger(path)
    with ledger.db() as db:
        row = db.execute(
            "SELECT state, reserved FROM requests WHERE id=?", (attempt,)
        ).fetchone()
    assert tuple(row) == ("unknown", 10)
