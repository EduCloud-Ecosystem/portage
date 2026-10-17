# SPDX-License-Identifier: Apache-2.0
import concurrent.futures
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pilot_ledger", Path(__file__).parents[1] / "src/portage/pilot_ledger.py"
)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


@pytest.fixture
def setup(tmp_path):
    ledger = pilot.Ledger(tmp_path / "ledger.sqlite")
    ledger.project("course01", 1000, 3)
    ledger.project("research01", 1000, 3)
    ledger.member("course01", "learner1", 700)
    ledger.member("course01", "learner2", 700)
    ledger.member("research01", "learner3", 700)
    return ledger, ledger.issue("course01", subject="learner1")


def test_credential_attribution_and_revocation(setup):
    ledger, token = setup
    _, member = ledger.authenticate(token, "learner2")
    assert member["subject"] == "learner1"
    app = ledger.issue("course01", kind="application")
    with pytest.raises(pilot.Denied, match="membership_required"):
        ledger.authenticate(app, "learner3")
    with pytest.raises(pilot.Denied, match="trusted_subject_required"):
        ledger.authenticate(app)
    ledger.revoke("course01", "learner1")
    with pytest.raises(pilot.Denied):
        ledger.admit(token, "code_small", 20)
    ledger.member("course01", "learner1", 700)
    with pytest.raises(pilot.Denied):
        ledger.authenticate(token)


def test_concurrent_reservation_atomic_across_connections(setup):
    ledger, token = setup

    def admit(_):
        try:
            return pilot.Ledger(ledger.path).admit(token, "code_small", 350)
        except pilot.Denied:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        accepted = [r for r in pool.map(admit, range(20)) if r]
    assert len(accepted) == 2
    assert ledger.usage("course01")["committed"] == 700
    assert ledger.usage("research01")["committed"] == 0


def test_project_allowance_aggregates_members(setup):
    ledger, token = setup
    other = ledger.issue("course01", subject="learner2")
    ledger.admit(token, "code_small", 600)
    with pytest.raises(pilot.Denied, match="allowance_exhausted"):
        ledger.admit(other, "code_small", 600)


def test_unknown_usage_survives_restart_and_needs_evidence(setup):
    ledger, token = setup
    request = ledger.admit(token, "embedding", 600)
    ledger.settle(request, None)
    ledger = pilot.Ledger(ledger.path)
    assert ledger.usage("course01") == {"committed": 600, "active": 0, "unresolved": 1}
    ledger.settle(request, 0)  # retry cannot erase an unresolved liability
    assert ledger.usage("course01")["committed"] == 600
    with pytest.raises(ValueError):
        ledger.reconcile(request, 0, "operator guessed")
    ledger.reconcile(request, 200, "a" * 64)
    assert ledger.usage("course01")["committed"] == 200


def test_disabled_expired_and_retired_fail_closed(setup, monkeypatch):
    ledger, token = setup
    disabled = ledger.issue("course01", subject="learner1")
    ledger.disable_credential(disabled)
    with pytest.raises(pilot.Denied):
        ledger.authenticate(disabled)
    now = pilot.time.time()
    monkeypatch.setattr(pilot.time, "time", lambda: now + 4000)
    with pytest.raises(pilot.Denied):
        ledger.authenticate(token)
    monkeypatch.setattr(pilot.time, "time", lambda: now)
    ledger.retire("course01")
    with pytest.raises(pilot.Denied):
        ledger.authenticate(token)


def test_pending_crash_reservation_is_not_released(setup):
    ledger, token = setup
    ledger.admit(token, "classifier", 700)
    with pytest.raises(pilot.Denied):
        pilot.Ledger(ledger.path).admit(token, "classifier", 1)


def test_no_payload_or_credential_in_database(setup):
    ledger, token = setup
    ledger.admit(token, "code_small", 30)
    with ledger.db() as db:
        dump = "\n".join(db.iterdump())
    assert token not in dump
    assert "messages" not in dump


def test_model_allowlist_and_spoofed_fields():
    models = {
        "code_small": {
            "operation": "chat/completions",
            "max_output_tokens": 100,
            "max_request_tokens": 1000,
        }
    }
    body = {
        "model": "code_small",
        "messages": [{"role": "user", "content": "hi"}],
        "user": "victim",
        "project": "victim",
        "api_base": "https://forbidden",
        "metadata": {"owner": "victim"},
        "stream": True,
    }
    clean, reserve = pilot.prepare_request(body, models, "chat/completions")
    assert reserve > 100
    assert not {"user", "project", "api_base", "metadata"} & clean.keys()
    assert clean["stream_options"] == {"include_usage": True}
    with pytest.raises(pilot.Denied):
        pilot.prepare_request({**body, "model": "forbidden"}, models, "chat/completions")
    with pytest.raises(pilot.Denied):
        pilot.prepare_request({**body, "max_tokens": 1000}, models, "chat/completions")
    assert "victim" not in json.dumps(clean)
