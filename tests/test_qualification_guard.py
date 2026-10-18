# SPDX-License-Identifier: Apache-2.0
"""Durable approval regressions; temporary stores and fake transport only."""

import copy
import io
import json
import multiprocessing
import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import qualification_fixtures as fixture
import qualification_guard as qg
from qualification_guard import BATCHES, INFERENCE, LIMITS, METADATA, Denied, Ledger


def body_for(slot):
    item = INFERENCE[slot]
    return {
        "model": "code_small",
        "messages": [{"role": "user", "content": item["task"][1]}],
        "stream": item["stream"],
    }


def prime(env, guard=None, slot=None, *, admit=True):
    guard = guard or env.guard().acquire(env.token)
    slot = slot or next(iter(INFERENCE))
    for op in ("version", "tags", "show"):
        fixture.gateway.qualified_metadata(guard, "initial." + op, "fixture")
    for batch, slots in BATCHES:
        for op in ("version", "tags", "show"):
            fixture.gateway.qualified_metadata(guard, batch + "." + op, "fixture")
        if slot in slots:
            break
        for earlier in slots:
            env.runner.guarded_call(guard, earlier, "fixture")
        fixture.gateway.qualified_metadata(guard, batch + ".ps", "fixture")
    if not admit:
        return guard, slot
    for phase in ("pre", "post"):
        fixture.gateway.qualified_authority(guard, "inference", slot, phase, "fixture")
    attempt, request = guard.admit("inference", slot, body=body_for(slot))
    return guard, attempt, request


def state(env):
    with env.ledger.db() as db:
        return db.execute("SELECT state FROM qualification_grants").fetchone()[0]


def assert_repeat_denied(env, label="repeat"):
    before = list(env.calls)
    with pytest.raises(Denied):
        env.run(label)
    assert env.calls == before


def test_full_plan_and_completed_repeat_have_no_new_contact(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    report = env.run()
    assert len(report["attempts"]) == 16
    assert report["usage"] == {"committed": 192, "active": 0, "unresolved": 0}
    assert len(env.calls) == 150  # 16 inference + 51 metadata + 83 authority
    assert env.calls[-1].endswith("/api/ps")
    before = list(env.calls)
    with pytest.raises(Denied):
        env.run("repeat")
    assert env.calls == before
    with env.ledger.db() as db:
        rows = dict(
            db.execute("SELECT kind,count(*) FROM qualification_attempts GROUP BY kind")
        )
    assert rows == LIMITS


def test_unknown_repeat_retains_hold_before_any_contact(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch, usage=None)
    report = env.run()
    assert len(report["attempts"]) == 1
    assert report["usage"] == {"committed": 176, "active": 1, "unresolved": 1}
    before = list(env.calls)
    with pytest.raises(Denied):
        env.run("repeat")
    assert env.calls == before
    assert (
        Ledger.open_existing(str(tmp_path / "existing.sqlite")).usage("qualify01")
        == report["usage"]
    )


def test_fixed_plan_sizes():
    assert len(INFERENCE) == 16 and len(METADATA) == 51


def test_noncreating_open_missing_path(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises((OSError, Denied)):
        Ledger.open_existing(str(path))
    assert not path.exists()


def test_direct_gateway_requires_guard_before_listener(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("listener opened without a guard")

    monkeypatch.setattr(fixture.gateway.ThreadingHTTPServer, "__init__", forbidden)
    with pytest.raises(ValueError, match="registered approval guard"):
        fixture.gateway.Gateway(
            ("127.0.0.1", 0), None, {"mode": "qualification"}, "", "", "", ""
        )


@pytest.mark.parametrize("mode", ["synthetic", "hosted"])
def test_guard_rejected_in_other_gateway_modes(tmp_path, monkeypatch, mode):
    env = fixture.setup(tmp_path, monkeypatch)
    guard = env.guard().acquire(env.token)

    def forbidden(*args, **kwargs):
        pytest.fail("listener opened with mismatched mode")

    monkeypatch.setattr(fixture.gateway.ThreadingHTTPServer, "__init__", forbidden)
    with pytest.raises(ValueError, match="qualification mode"):
        fixture.gateway.Gateway(
            ("127.0.0.1", 0),
            guard.ledger,
            {"mode": mode},
            "",
            "",
            "",
            "",
            qualification_guard=guard,
        )
    guard.close()


def test_gateway_cannot_dispatch_using_separate_mutated_manifest(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    guard = env.guard().acquire(env.token)
    supplied = copy.deepcopy(env.config)
    monkeypatch.setattr(
        fixture.gateway.ThreadingHTTPServer, "__init__", lambda *args: None
    )
    server = fixture.gateway.Gateway(
        ("127.0.0.1", 0),
        guard.ledger,
        supplied,
        "",
        "",
        "http://127.0.0.1:2",
        "fixture",
        qualification_guard=guard,
    )
    supplied["models"]["code_small"]["endpoint"] = "http://127.0.0.1:3"
    assert server.manifest is guard.manifest
    server.manifest = supplied
    handler = fixture.gateway.Handler.__new__(fixture.gateway.Handler)
    handler.server = server
    handler.command, handler.path = "POST", "/v1/chat/completions"
    handler.wfile = io.BytesIO()
    handler.send_response = lambda *args: None
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler.handle_request()
    assert b"approval_binding_changed" in handler.wfile.getvalue()
    assert not env.calls
    guard.close()


@pytest.mark.parametrize("usage", [0, 1, 1025])
def test_usage_does_not_refund_permanent_slots(tmp_path, monkeypatch, usage):
    env = fixture.setup(tmp_path, monkeypatch, usage=usage)
    report = env.run()
    assert len(report["attempts"]) == 16
    assert report["usage"]["committed"] == 16 * usage
    assert len(env.calls) == 150
    assert_repeat_denied(env)


@pytest.mark.parametrize("usage", [None, True, -1, 1.5, 2**80])
def test_unsupported_usage_retains_full_reservation(tmp_path, monkeypatch, usage):
    env = fixture.setup(tmp_path, monkeypatch, usage=usage)
    report = env.run()
    assert len(report["attempts"]) == 1
    assert report["usage"] == {"committed": 176, "active": 1, "unresolved": 1}
    assert_repeat_denied(env)


def test_supported_over_allowance_usage_is_not_clipped(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch, usage=65536)
    report = env.run()
    assert report["usage"] == {"committed": 65536, "active": 0, "unresolved": 0}
    assert sum("/v1/" in url for url in env.calls) == 1
    assert_repeat_denied(env)


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_ambiguous_usage_holds_both_transports(tmp_path, monkeypatch, direct, stream):
    env = fixture.setup(tmp_path, monkeypatch)
    slot = list(INFERENCE)[int(stream)]
    guard, slot = prime(env, slot=slot, admit=False)
    duplicate = (
        b'{"choices":[{"message":{"content":"42"}}],'
        b'"usage":{"total_tokens":500,"total_tokens":0}}'
    )
    conflict = (
        b'data: {"choices":[],"usage":{"total_tokens":500}}\n\n'
        b'data: {"choices":[],"usage":{"total_tokens":0}}\n\n'
        b"data: [DONE]\n\n"
    )
    env.raw_override = lambda req: (
        (conflict if stream else duplicate) if "/v1/" in req.full_url else None
    )
    if direct:
        handler = fixture.gateway.Handler.__new__(fixture.gateway.Handler)
        raw = json.dumps(body_for(slot)).encode()
        handler.headers = {
            "Authorization": "Bearer " + env.token,
            "Content-Length": str(len(raw)),
            "X-Portage-Qualification-Slot": slot,
        }
        handler.command, handler.path = "POST", "/v1/chat/completions"
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.server = SimpleNamespace(
            qualification_guard=guard,
            ledger=guard.ledger,
            manifest=env.config,
            authority_key="fixture",
            authority_url="http://127.0.0.1:2",
            inference_key="",
            approval_window=guard,
        )
        handler.send_response = lambda *args: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.handle_request()
    else:
        env.runner.guarded_call(guard, slot, "fixture")
    guard.close()
    assert env.ledger.usage("qualify01")["unresolved"] == 1
    assert state(env) == "held"
    assert_repeat_denied(env)


@pytest.mark.parametrize("op", ["version", "tags", "show"])
def test_bad_pin_cannot_satisfy_inference_prerequisite(tmp_path, monkeypatch, op):
    env = fixture.setup(tmp_path, monkeypatch)
    env.raw_override = lambda req: b"{}" if req.full_url.endswith("/api/" + op) else None
    with pytest.raises((KeyError, ValueError)):
        env.run()
    assert not any("/v1/" in url for url in env.calls)
    assert state(env) == "held"
    assert_repeat_denied(env)


@pytest.mark.parametrize("kind", ["authority", "metadata"])
def test_ambiguous_noninference_holds_without_tokens(tmp_path, monkeypatch, kind):
    env = fixture.setup(tmp_path, monkeypatch)

    def raw(req):
        if (":2/" in req.full_url) == (kind == "authority"):
            raise ConnectionResetError("fixture lost acknowledgement")

    env.raw_override = raw
    with pytest.raises(ConnectionResetError):
        env.run()
    assert state(env) == "held"
    assert env.ledger.usage("qualify01") == {"committed": 0, "active": 0, "unresolved": 0}
    assert_repeat_denied(env)


def test_inactive_authority_cannot_complete_lookup(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    env.authority_active = False
    with pytest.raises(Denied, match="membership_required"):
        env.run()
    assert len(env.calls) == 1 and state(env) == "held"
    assert_repeat_denied(env)


def test_duplicate_claim_never_dispatches_twice(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    guard, attempt, request = prime(env)
    guard.claim(attempt)
    with pytest.raises(Denied, match="dispatch_claim_consumed"):
        guard.claim(attempt)
    guard.finish(attempt, known=True, usage=0)
    guard.close()
    with env.ledger.db() as db:
        assert (
            db.execute("SELECT actual FROM requests WHERE id=?", (request,)).fetchone()[0]
            == 0
        )
    assert_repeat_denied(env)


def test_unclaimed_success_cannot_refund_unknown_work(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    guard, attempt, _ = prime(env)
    guard.finish(attempt, known=True, usage=0)
    guard.close()
    assert env.ledger.usage("qualify01")["committed"] == 176
    assert_repeat_denied(env)


@pytest.mark.parametrize("lost_ack", [False, True])
def test_admission_commit_failure_holds_without_attempt_return(
    tmp_path, monkeypatch, lost_ack
):
    env = fixture.setup(tmp_path, monkeypatch)
    guard, slot = prime(env, admit=False)
    for phase in ("pre", "post"):
        fixture.gateway.qualified_authority(guard, "inference", slot, phase, "fixture")
    original = guard.ledger.transaction
    fail = True

    @contextmanager
    def transaction():
        nonlocal fail
        firing, fail = fail, False
        with original() as db:
            yield db
            if firing and not lost_ack:
                raise sqlite3.OperationalError("fixture failed commit")
        if firing and lost_ack:
            raise sqlite3.OperationalError("fixture lost commit acknowledgement")

    monkeypatch.setattr(guard.ledger, "transaction", transaction)
    with pytest.raises(sqlite3.Error):
        guard.admit("inference", slot, body=body_for(slot))
    with pytest.raises(Denied):
        guard.check()
    assert state(env) == "held"
    assert env.ledger.usage("qualify01")["unresolved"] == int(lost_ack)
    with env.ledger.db() as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == int(lost_ack)
        assert db.execute(
            "SELECT count(*) FROM qualification_attempts WHERE kind='inference'"
        ).fetchone()[0] == int(lost_ack)
    guard.close()
    assert_repeat_denied(env)


def test_expiry_during_usage_query_blocks_atomic_admission(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    guard, slot = prime(env, admit=False)
    for phase in ("pre", "post"):
        fixture.gateway.qualified_authority(guard, "inference", slot, phase, "fixture")
    original = guard.ledger._usage

    def delayed(*args):
        result = original(*args)
        env.clock.advance(601)
        return result

    monkeypatch.setattr(guard.ledger, "_usage", delayed)
    with pytest.raises(Denied, match="approval_expired"):
        guard.admit("inference", slot, body=body_for(slot))
    assert env.ledger.usage("qualify01")["committed"] == 0
    guard.close()
    assert_repeat_denied(env)


@pytest.mark.parametrize("cutoff", ["expiry", "revoke", "membership"])
def test_cutoff_after_connect_before_claim_prevents_send(tmp_path, monkeypatch, cutoff):
    env = fixture.setup(tmp_path, monkeypatch)
    guard, slot = prime(env, admit=False)

    def hook(req):
        if "/v1/" not in req.full_url:
            return
        if cutoff == "expiry":
            env.clock.advance(601)
        elif cutoff == "revoke":
            qg.revoke(
                env.registry, env.pin, env.config, identity=env.identity, clock=env.clock
            )
        else:
            env.ledger.revoke("qualify01", "qualifier01")

    env.hook = hook
    env.runner.guarded_call(guard, slot, "fixture")
    assert not any("/v1/" in url for url in env.calls)
    guard.close()
    assert env.ledger.usage("qualify01")["unresolved"] == 1
    assert_repeat_denied(env)


@pytest.mark.parametrize(
    "change",
    ["missing", "copy", "symlink", "epoch", "registry", "profile", "runtime", "boot"],
)
def test_binding_failure_precedes_ledger_construction(tmp_path, monkeypatch, change):
    env = fixture.setup(tmp_path, monkeypatch)
    path = tmp_path / "existing.sqlite"
    if change == "missing":
        path.rename(tmp_path / "held.sqlite")
    elif change in {"copy", "symlink"}:
        target = tmp_path / "replacement.sqlite"
        shutil.copy2(path, target)
        path.rename(tmp_path / "held.sqlite")
        if change == "copy":
            target.rename(path)
        else:
            path.symlink_to(target)
    elif change == "epoch":
        with env.ledger.transaction() as db:
            db.execute("UPDATE qualification_store SET epoch='changed'")
    elif change == "registry":
        env.registry.write_text("{}")
    elif change == "profile":
        env.config["approved_capacity"]["approval_reference"] = "new-label"
    elif change == "runtime":
        monkeypatch.setattr(qg, "runtime_digest", lambda: "changed")
    elif change == "boot":
        env.guard = lambda: qg.QualificationGuard(
            env.registry,
            env.pin,
            env.config,
            identity=lambda: ("fixture-host", "another-boot"),
            clock=env.clock,
        )

    def forbidden(*args, **kwargs):
        pytest.fail("Ledger constructed before binding resolution")

    monkeypatch.setattr(Ledger, "open_existing", forbidden)
    with pytest.raises((Denied, OSError)):
        env.guard()
    assert not env.calls
    if change == "missing":
        assert not path.exists()


@pytest.mark.parametrize(
    "clock_change", ["wall_back", "mono_back", "wall_expiry", "mono_expiry"]
)
def test_original_clock_constraints_survive_new_object(
    tmp_path, monkeypatch, clock_change
):
    env = fixture.setup(tmp_path, monkeypatch)
    if clock_change == "wall_back":
        env.clock.wall -= 1
    elif clock_change == "mono_back":
        env.clock.mono -= 1
    elif clock_change == "wall_expiry":
        env.clock.wall += 601
    else:
        env.clock.mono += 601
    guard = env.guard()
    with pytest.raises(Denied):
        guard.acquire(env.token)
    assert state(env) == "held" and not env.calls


def test_foreign_owned_ancestor_rejected(tmp_path, monkeypatch):
    path = tmp_path / "state"
    path.write_text("fixture")
    original = Path.stat

    def stat_path(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self == tmp_path:
            values = list(result)
            values[4] = os.geteuid() + 12345
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", stat_path)
    with pytest.raises(Denied, match="protected_file_required"):
        qg.protected_file(path)


def test_runtime_never_provisions_or_migrates(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("runtime attempted provisioning")

    for name in ("__init__", "project", "member", "issue"):
        monkeypatch.setattr(Ledger, name, forbidden)
    monkeypatch.setattr(qg, "migrate", forbidden)
    monkeypatch.setattr(qg, "register", forbidden)
    assert len(env.run()["attempts"]) == 16


def test_failed_durable_hold_cannot_revive_same_guard(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    guard = env.guard().acquire(env.token)
    original = guard.ledger.transaction
    writes = 0

    @contextmanager
    def fail_hold():
        nonlocal writes
        writes += 1
        if writes == 2:
            raise sqlite3.OperationalError("fixture failed hold write")
        with original() as db:
            yield db

    monkeypatch.setattr(guard.ledger, "transaction", fail_hold)
    env.clock.wall += 601
    with pytest.raises(sqlite3.Error):
        guard.check()
    env.clock.wall -= 601
    with pytest.raises(Denied, match="approval_held"):
        guard.check()
    guard.close()
    assert not env.calls


def test_one_canonical_grant_per_budget(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    with pytest.raises(sqlite3.IntegrityError):
        qg.register(
            tmp_path / "wrapper.json",
            tmp_path / "existing.sqlite",
            env.config,
            grant_id="wrapper_grant",
            capacity_budget_id="fixture_budget",
            token=env.token,
            subject="qualifier01",
            authority_url="http://127.0.0.1:2",
            identity=env.identity,
            clock=env.clock,
        )
    assert not (tmp_path / "wrapper.json").exists()
    with env.ledger.db() as db:
        assert db.execute("SELECT count(*) FROM qualification_grants").fetchone()[0] == 1


def test_reconciliation_does_not_reactivate_or_refund_slots(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch, usage=None)
    report = env.run()
    env.ledger.reconcile(report["attempts"][0]["request_id"], 0, "c" * 64)
    assert env.ledger.usage("qualify01")["committed"] == 0
    assert state(env) == "held"
    assert_repeat_denied(env)


def test_migration_preserves_all_historical_rows_and_refuses_attribution(
    tmp_path, monkeypatch
):
    env = fixture.setup(tmp_path, monkeypatch)
    first = env.ledger.admit(env.token, "code_small", 176)
    env.ledger.settle(first, None)
    second = env.ledger.admit(env.token, "code_small", 176)
    env.ledger.settle(second, None)
    env.ledger.reconcile(second, 1000, "d" * 64)
    tables = ("projects", "members", "credentials", "requests", "reconciliations")

    def snapshot():
        with env.ledger.db() as db:
            return {
                name: [tuple(row) for row in db.execute("SELECT * FROM " + name)]
                for name in tables
            }

    before = snapshot()
    qg.migrate(tmp_path / "existing.sqlite", "fixture_authority", "fixture_epoch")
    assert snapshot() == before
    with pytest.raises(Denied, match="unbound_work"):
        qg.register(
            tmp_path / "another-registry.json",
            tmp_path / "existing.sqlite",
            env.config,
            grant_id="another_grant",
            capacity_budget_id="another_budget",
            token=env.token,
            subject="qualifier01",
            authority_url="http://127.0.0.1:2",
            identity=env.identity,
            clock=env.clock,
        )
    assert snapshot() == before
    assert_repeat_denied(env)


def worker(data, pipe, action):
    """Spawned process: existing fixture state only, no startup provisioning."""
    patch = pytest.MonkeyPatch()
    clock = fixture.Clock()
    clock.wall, clock.mono = data["wall"], data["mono"]
    runner = fixture.load_runner()
    patch.setattr(runner, "time", clock)
    patch.setattr(runner.gateway, "time", clock)
    env = SimpleNamespace(
        runner=runner,
        clock=clock,
        calls=[],
        hook=None,
        size=128,
        vram=0,
        connect_delay=0,
        authority_active=True,
        usage=data["usage"],
        token=data["token"],
    )
    fixture.install_transport(env, patch)
    guard = qg.QualificationGuard(
        data["registry"],
        data["pin"],
        data["config"],
        identity=lambda: ("fixture-host", "fixture-boot"),
        clock=clock,
    )
    try:
        if action.startswith("crash"):
            guard.acquire(data["token"])
            guard, attempt, _ = prime(env, guard=guard)
            if action == "crash_claimed":
                guard.claim(attempt)
            pipe.send({"calls": len(env.calls), "state": "crash"})
            pipe.close()
            os._exit(0)
        if action == "acquire":
            guard.acquire(data["token"])
            result = "acquired"
        else:
            output = Path(data["output"])
            output.mkdir()
            report = {"runtime": dict.fromkeys(runner.LIVE_GATES, "NOT RUN")}
            runner.live(
                data["config"],
                output,
                report,
                guard=guard,
                token=data["token"],
                authority_key="fixture",
            )
            result = report["usage"]
    except Denied as error:
        result = error.code
    finally:
        guard.close()
    pipe.send({"calls": len(env.calls), "state": result})
    pipe.close()
    patch.undo()


def child(env, tmp_path, action="run", label="child"):
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    data = {
        "registry": str(env.registry),
        "pin": env.pin,
        "config": env.config,
        "token": env.token,
        "wall": env.clock.wall,
        "mono": env.clock.mono,
        "usage": env.usage,
        "output": str(tmp_path / label),
    }
    process = ctx.Process(target=worker, args=(data, send, action))
    process.start()
    send.close()
    try:
        assert receive.poll(30), "fixture worker did not report"
        result = receive.recv()
        process.join(10)
        assert process.exitcode == 0
        return result
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        receive.close()


@pytest.mark.parametrize("usage,calls", [(12, 150), (None, 15)])
def test_fresh_process_repeat_makes_zero_contact(tmp_path, monkeypatch, usage, calls):
    env = fixture.setup(tmp_path, monkeypatch, usage=usage)
    first = child(env, tmp_path)
    assert first["calls"] == calls
    second = child(env, tmp_path, label="repeat")
    assert second["calls"] == 0
    assert second["state"] in {"approval_closed", "approval_held"}


@pytest.mark.parametrize("stage", ["crash_admitted", "crash_claimed"])
def test_crash_abandons_pending_work_with_no_replay(tmp_path, monkeypatch, stage):
    env = fixture.setup(tmp_path, monkeypatch)
    child(env, tmp_path, action=stage)
    repeated = child(env, tmp_path, label="repeat")
    assert repeated["calls"] == 0 and repeated["state"] == "abandoned_work"
    assert env.ledger.usage("qualify01") == {
        "committed": 176,
        "active": 1,
        "unresolved": 1,
    }
    assert state(env) == "held"


def test_second_process_at_last_inference_slot_refused_busy(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    races = []

    def hook(req):
        if "/v1/" in req.full_url and sum("/v1/" in url for url in env.calls) == 15:
            races.append(child(env, tmp_path, action="acquire"))

    env.hook = hook
    assert len(env.run()["attempts"]) == 16
    assert races == [{"calls": 0, "state": "approval_busy"}]
    assert len(env.calls) == 150 and env.calls[-1].endswith("/api/ps")


def test_exhausted_actions_cannot_spend_more_authority_before_final_ps(
    tmp_path, monkeypatch
):
    env = fixture.setup(tmp_path, monkeypatch)
    original = fixture.gateway.qualified_metadata
    seen = []

    def metadata(guard, slot, key):
        if slot == "batch11.ps":
            before = len(env.calls)
            for kind, consumed in (
                ("inference", next(iter(INFERENCE))),
                ("metadata", "initial.version"),
            ):
                for _ in range(3):
                    with pytest.raises(Denied, match="slot_consumed"):
                        fixture.gateway.qualified_authority(
                            guard, kind, consumed, "pre", key
                        )
            for kind, extra in (
                ("inference", "seventeenth"),
                ("metadata", "fifty_second"),
            ):
                with pytest.raises(Denied, match="slot_not_allowed"):
                    fixture.gateway.qualified_authority(guard, kind, extra, "pre", key)
            assert len(env.calls) == before
            seen.append(slot)
        return original(guard, slot, key)

    monkeypatch.setattr(fixture.gateway, "qualified_metadata", metadata)
    env.run()
    assert seen == ["batch11.ps"] and len(env.calls) == 150


def test_claim_lost_commit_ack_holds_without_send(tmp_path, monkeypatch):
    env = fixture.setup(tmp_path, monkeypatch)
    guard, attempt, _ = prime(env)
    original = guard.ledger.transaction
    fail = True

    @contextmanager
    def transaction():
        nonlocal fail
        firing, fail = fail, False
        with original() as db:
            yield db
        if firing:
            raise sqlite3.OperationalError("fixture lost claim commit acknowledgement")

    monkeypatch.setattr(guard.ledger, "transaction", transaction)
    with pytest.raises(sqlite3.Error):
        guard.claim(attempt)
    with pytest.raises(Denied):
        guard.claim(attempt)
    assert state(env) == "held" and not any("/v1/" in url for url in env.calls)
    guard.close()
    assert env.ledger.usage("qualify01")["unresolved"] == 1
    assert_repeat_denied(env)


def test_lock_descriptor_identity_is_checked(tmp_path, monkeypatch):
    path, other = tmp_path / "lock", tmp_path / "other"
    qg.create_file(path, b"")
    qg.create_file(other, b"")
    original = os.open

    def substituted(name, flags, *args, **kwargs):
        return original(other if name == path else name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", substituted)
    with pytest.raises(Denied, match="store_identity_changed"):
        with qg.file_lock(path):
            pytest.fail("wrong lock descriptor acquired")


def test_keepalive_handler_rechecks_both_authority_phases_for_next_slot(
    tmp_path, monkeypatch
):
    env = fixture.setup(tmp_path, monkeypatch)
    guard, slot = prime(env, admit=False)
    handler = fixture.gateway.Handler.__new__(fixture.gateway.Handler)
    handler.command, handler.path = "POST", "/v1/chat/completions"
    handler.server = SimpleNamespace(
        qualification_guard=guard,
        ledger=guard.ledger,
        manifest=env.config,
        authority_key="fixture",
        authority_url="http://127.0.0.1:2",
        inference_key="",
        approval_window=guard,
    )
    statuses = []
    handler.send_response = lambda status: statuses.append(status)
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    for index, slot in enumerate(list(INFERENCE)[:2]):
        if index:
            fixture.gateway.qualified_metadata(guard, "batch00.ps", "fixture")
            for op in ("version", "tags", "show"):
                fixture.gateway.qualified_metadata(guard, "batch01." + op, "fixture")
        raw = json.dumps(body_for(slot)).encode()
        handler.headers = {
            "Authorization": "Bearer " + env.token,
            "Content-Length": str(len(raw)),
            "X-Portage-Qualification-Slot": slot,
        }
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.handle_request()
    assert statuses == [200, 200]
    assert sum("/v1/" in url for url in env.calls) == 2
    assert env.ledger.usage("qualify01") == {
        "committed": 24,
        "active": 0,
        "unresolved": 0,
    }
    guard.close()
