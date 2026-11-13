# SPDX-License-Identifier: Apache-2.0
"""Offline controls and optional actual Belay SDK, never external inference."""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_openrouter_pilot import catalog, result
from test_openrouter_pilot import connected as connected_fixture

connected = connected_fixture

sys.path.insert(0, str(Path(__file__).parents[1] / "integrations/ai_pilot"))
from instructor_walkthrough import (  # noqa: E402
    BelaySession,
    ConsoleServer,
    Walkthrough,
    accepted_hint,
    console_handler,
    serve,
)
from openrouter_adapter import (  # noqa: E402
    CASES,
    WALKTHROUGH_CASES,
    SmokeGuard,
    WalkthroughGuard,
    case_body,
    manifest,
    walkthrough_body,
    walkthrough_manifest,
)
from pilot_ledger import Denied  # noqa: E402


def test_guard_profiles_are_separate_and_budget_is_finite(tmp_path):
    guard = WalkthroughGuard(tmp_path / "walkthrough", catalog())
    smoke = SmokeGuard(tmp_path / "smoke", catalog())
    with pytest.raises(ValueError):
        guard.validate_manifest(manifest())
    with pytest.raises(ValueError):
        smoke.validate_manifest(walkthrough_manifest())
    with pytest.raises(Denied):
        guard.check_body(case_body(CASES[3]))
    with pytest.raises(Denied):
        smoke.check_body(walkthrough_body(WALKTHROUGH_CASES[0]))
    for case in WALKTHROUGH_CASES:
        name = guard.start(walkthrough_body(case), case["name"])
        guard.claim(name)
        guard.observe(name, result())
        assert guard.finish(name, complete=True)
    assert guard.summary()["dispatch_claims"] == 2
    assert sum(a["reserved_usd"] for a in guard.attempts.values()) == 0.025
    with pytest.raises(Denied):
        guard.start(walkthrough_body(WALKTHROUGH_CASES[0]), "replay")


@pytest.mark.parametrize("connected", [WalkthroughGuard], indirect=True)
def test_both_aliases_and_refusal_controls(connected):
    state, guard, ledger, request = connected
    for case in WALKTHROUGH_CASES:
        body = walkthrough_body(case)
        changed = {**body, "provider": {"only": ["anything"]}}
        assert request(changed)[0] == 400
        assert request(body, "invalid")[0] == 401
        assert request(body)[0] == 200
        assert guard.attempts[case["name"]]["state"] == "complete"
    assert len(state["requests"]) == 2
    assert ledger.usage("smoke001", "synthetic01")["committed"] == 40
    state["active"] = False
    assert request(walkthrough_body(WALKTHROUGH_CASES[0]))[0] == 403
    assert len(state["requests"]) == 2


@pytest.mark.parametrize("connected", [WalkthroughGuard], indirect=True)
@pytest.mark.parametrize("failure", ["transport", "usage"])
def test_unknown_failure_stops_second_tier(connected, failure):
    state, guard, ledger, request = connected
    if failure == "transport":
        state["failure"] = True
    else:
        state["response"].pop("usage")
    request(walkthrough_body(WALKTHROUGH_CASES[0]))
    assert guard.summary()["unknown_liability_usd"] == 0.0125
    status, raw = request(walkthrough_body(WALKTHROUGH_CASES[1]))
    assert status == 429  # existing ledger concurrency hold refuses before dispatch
    assert json.loads(raw)["error"]["code"] == "concurrency_exhausted"
    assert len(state["requests"]) == 1


@pytest.mark.parametrize("value", [None, {}, {"hint": ""}, {"hint": "x", "grade": 100}])
def test_structural_acceptance_rejects_bad_hints(value):
    assert not accepted_hint(value)


@pytest.fixture
def console(tmp_path):
    guard = WalkthroughGuard(tmp_path / "console", catalog())
    state = {"active": True}
    called = []

    def call(case):
        called.append(case["tier"])
        name = guard.start(walkthrough_body(case), case["name"])
        guard.claim(name)
        guard.observe(name, result())
        guard.finish(name, complete=True)
        return {"hint": "Consider one observation per station and day."}

    session = SimpleNamespace(call=call, ledger=SimpleNamespace(summary=lambda: {}))
    ledger = SimpleNamespace(usage=lambda *_: {})
    walkthrough = Walkthrough(guard, session, ledger, state, "fixture")
    with ExitStack() as stack:
        service = ConsoleServer(("127.0.0.1", 0), console_handler(walkthrough))
        origin = serve(stack, service)

        def request(path, body=None, **overrides):
            headers = {
                "Content-Type": "application/json",
                "Origin": origin,
                "X-Walkthrough-Nonce": walkthrough.nonce,
                **overrides,
            }
            req = urllib.request.Request(
                origin + path,
                data=None if body is None else json.dumps(body).encode(),
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as error:
                return error.code, error.read()

        yield walkthrough, called, request


def test_console_origin_host_input_duplicate_refresh_and_revoke(console):
    walkthrough, called, request = console
    assert request("/")[0] == 200
    assert request("/", Host="evil.example")[0] == 403
    assert request("/run", {"case": "fast_hint"}, Origin="http://evil.example")[0] == 403
    assert request("/run", {"case": "fast_hint", "prompt": "unapproved"})[0] == 400
    assert not called
    assert request("/run", {"case": "fast_hint"})[0] == 200
    assert request("/run", {"case": "fast_hint"})[0] == 409
    assert request("/status")[0] == 200
    assert called == ["fast"]
    assert request("/revoke", {})[0] == 200
    assert request("/run", {"case": "strong_hint"})[0] == 403
    assert called == ["fast"]
    assert request("/stop", {})[0] == 200
    assert walkthrough.stop.is_set()


def test_console_expiry_failure_and_concurrency(console):
    walkthrough, called, request = console
    walkthrough.lock.acquire()
    try:
        assert request("/run", {"case": "fast_hint"})[0] == 409
    finally:
        walkthrough.lock.release()
    walkthrough.guard.deadline = time.time() - 1
    assert request("/run", {"case": "fast_hint"})[0] == 403
    assert not called


@pytest.mark.parametrize("connected", [WalkthroughGuard], indirect=True)
def test_actual_belay_tiers_and_shared_ledger(connected, tmp_path):
    source = os.environ.get("OPENROUTER_TEST_BELAY_SOURCE")
    if not source:
        pytest.skip("run separately with pinned Belay environment")
    state, guard, ledger, _ = connected
    state["response"]["choices"][0]["message"]["content"] = json.dumps(
        {"hint": "Count missing values before and after reshaping."}
    )
    session = BelaySession(Path(source), tmp_path, state["origin"], state["token"])
    try:
        for case in WALKTHROUGH_CASES:
            assert accepted_hint(session.call(case))
        summary = session.ledger.summary()
        assert summary["states"]["settled"] == 2
        assert summary["consumed"]["tokens"] == 40
        assert guard.summary()["dispatch_claims"] == 2
        assert len(state["requests"]) == 2
        assert ledger.usage("smoke001", "synthetic01")["committed"] == 40
    finally:
        session.close()


@pytest.mark.parametrize("connected", [WalkthroughGuard], indirect=True)
def test_belay_reformat_attempt_cannot_escape_fixed_input_boundary(connected, tmp_path):
    source = os.environ.get("OPENROUTER_TEST_BELAY_SOURCE")
    if not source:
        pytest.skip("run separately with pinned Belay environment")
    state, guard, ledger, _ = connected
    state["response"]["choices"][0]["message"]["content"] = "not JSON"
    session = BelaySession(Path(source), tmp_path, state["origin"], state["token"])
    try:
        with pytest.raises(Exception) as caught:
            session.call(WALKTHROUGH_CASES[0])
        assert getattr(caught.value, "code", None) == "portage_request_refused"
        assert len(state["requests"]) == 1
        assert guard.summary()["dispatch_claims"] == 1
        assert session.ledger.summary()["attempts"] == 2
        # Provider's first result had known usage, but malformed content. The
        # application's second attempt was refused before upstream dispatch.
        assert ledger.usage("smoke001", "synthetic01")["committed"] == 20
    finally:
        session.close()
