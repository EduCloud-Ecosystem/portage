# SPDX-License-Identifier: Apache-2.0
"""Approval-window regression evidence: fake clocks and synthetic loopback only."""

import concurrent.futures
import threading
import time
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import test_direct_qualification as direct

env, runner = direct.env, direct.runner
gateway, live_config = direct.gateway, direct.live_config


class Clock:
    sleep = staticmethod(time.sleep)

    def __init__(self):
        self.wall = time.time()
        self.elapsed = 1000.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.elapsed

    def advance(self, seconds):
        self.wall += seconds
        self.elapsed += seconds


@pytest.mark.parametrize("slow_pin,seconds", [(1, 31), (2, 31), (2, 20)])
def test_slow_metadata_cannot_dispatch_without_remaining_window(
    env, runner, monkeypatch, tmp_path, slow_pin, seconds
):
    clock = Clock()
    monkeypatch.setattr(runner, "time", clock)
    monkeypatch.setattr(runner.gateway, "time", clock)
    config = live_config(env.service.manifest["models"]["code_small"]["endpoint"])
    config["approved_capacity"].update(
        ledger_path=str(tmp_path / "approved.sqlite"),
        deadline_utc=datetime.fromtimestamp(clock.wall + 30, UTC).isoformat(),
    )
    pins = []

    def slow_metadata(_):
        pins.append(clock.time())
        if len(pins) == slow_pin:
            clock.advance(seconds)
        return {"evidence": "synthetic metadata only"}

    monkeypatch.setattr(runner, "pin_engine", slow_metadata)
    monkeypatch.setattr(runner, "engine_json", lambda *_: {"models": []})
    report = {"runtime": dict.fromkeys(runner.LIVE_GATES, "NOT RUN")}
    runner.live(config, tmp_path, report)
    assert len(pins) == slow_pin
    assert env.engine.calls == []
    assert report.get("attempts", []) == []
    ledger = runner.gateway.Ledger(config["approved_capacity"]["ledger_path"])
    assert ledger.usage(config["project"]) == {
        "committed": 0,
        "active": 0,
        "unresolved": 0,
    }


def approved_window(monkeypatch, seconds=30):
    clock = Clock()
    monkeypatch.setattr(gateway, "time", clock)
    return clock, gateway.ApprovalWindow(clock.wall + seconds)


@pytest.mark.parametrize("change", ["elapsed", "rollback", "forward_then_rollback"])
def test_expired_window_never_reopens(monkeypatch, change):
    clock, window = approved_window(monkeypatch)
    if change == "forward_then_rollback":
        clock.wall += 31
        with pytest.raises(gateway.Denied, match="approval_expired"):
            window.check()
        clock.wall -= 31
    else:
        clock.advance(30)
        if change == "rollback":
            clock.wall -= 600
    with pytest.raises(gateway.Denied, match="approval_expired"):
        window.check()
    assert window.remaining() == 0


def test_authority_delay_cannot_admit_after_expiry(env, monkeypatch):
    clock, window = approved_window(monkeypatch)
    env.service.approval_window = window
    original = gateway.Handler.identity
    checks = []

    def delayed_identity(handler):
        identity = original(handler)
        checks.append(True)
        if len(checks) == 2:
            clock.advance(31)
        return identity

    monkeypatch.setattr(gateway.Handler, "identity", delayed_identity)
    assert env.request()[0] == 403
    assert env.rows() == env.engine.calls == []


def test_sqlite_lock_wait_rechecks_before_reservation(env, monkeypatch):
    clock, window = approved_window(monkeypatch)
    env.service.approval_window = window
    waiting = threading.Event()
    original = env.ledger.db

    @contextmanager
    def traced_db():
        with original() as db:
            db.set_trace_callback(
                lambda sql: waiting.set() if sql == "BEGIN IMMEDIATE" else None
            )
            yield db

    monkeypatch.setattr(env.ledger, "db", traced_db)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with env.ledger.transaction():
            waiting.clear()
            future = pool.submit(env.request)
            assert waiting.wait(3), "request never reached the held SQLite write lock"
            clock.advance(31)
        assert future.result(timeout=3)[0] == 403
    assert env.rows() == env.engine.calls == []


def test_expiry_after_admission_retains_unknown_reservation(env, monkeypatch):
    clock, window = approved_window(monkeypatch)
    env.service.approval_window = window
    original = env.ledger.admit

    def delayed_admit(*args, **kwargs):
        request_id = original(*args, **kwargs)
        clock.advance(31)
        return request_id

    monkeypatch.setattr(env.ledger, "admit", delayed_admit)
    status, _, headers = env.request()
    assert status == 403
    row = direct.await_rows(env, "unknown")[0]
    assert row["id"] == headers["X-Portage-Request-Id"]
    assert row["actual"] is None and row["reserved"] > 0
    assert env.engine.calls == []
    assert gateway.Ledger(env.ledger.path).usage("project01") == {
        "committed": row["reserved"],
        "active": 1,
        "unresolved": 1,
    }


def fake_transport(
    monkeypatch, clock, *, connect_delay=0, timer_delay=0, response_factory=None
):
    """No sockets: advance a clock at the last pre-dispatch boundaries."""
    calls, timers, connections = [], [], []

    class Connection:
        def __init__(self, host, port, timeout):
            self.timeout = timeout
            self.sock = self
            self.closed = False
            self.shutdowns = []
            connections.append(self)

        def connect(self):
            clock.advance(connect_delay)

        def settimeout(self, timeout):
            self.timeout = timeout

        def shutdown(self, how):
            self.shutdowns.append(how)

        def request(self, *args, **kwargs):
            calls.append(clock.time())

        @contextmanager
        def getresponse(self):
            yield response_factory() if response_factory else SimpleNamespace(status=200)

        def close(self):
            self.closed = True

    class Timer:
        def __init__(self, seconds, callback):
            self.seconds, self.callback = seconds, callback
            self.cancelled = False
            timers.append(self)

        def start(self):
            clock.advance(timer_delay)

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(
        gateway,
        "http",
        SimpleNamespace(
            client=SimpleNamespace(HTTPConnection=Connection, HTTPSConnection=Connection)
        ),
    )
    monkeypatch.setattr(gateway, "threading", SimpleNamespace(Timer=Timer))
    return calls, timers, connections


@pytest.mark.parametrize("phase", ["connect", "timer"])
def test_expiry_immediately_before_transport_dispatch_sends_nothing(monkeypatch, phase):
    clock, window = approved_window(monkeypatch)
    calls, timers, connections = fake_transport(
        monkeypatch,
        clock,
        connect_delay=31 if phase == "connect" else 0,
        timer_delay=31 if phase == "timer" else 0,
    )
    request = urllib.request.Request("http://127.0.0.1:1/v1/chat/completions", data=b"{}")
    with pytest.raises(gateway.Denied, match="approval_expired"):
        with gateway.inference_attempt(request, timeout=120, approval_window=window):
            pytest.fail("expired request reached a response")
    assert calls == []
    assert connections[0].closed
    assert all(timer.cancelled for timer in timers)


def test_inflight_transport_timer_is_capped_by_approval(monkeypatch):
    clock, window = approved_window(monkeypatch, seconds=3)
    calls, timers, connections = fake_transport(monkeypatch, clock, connect_delay=1)
    request = urllib.request.Request("http://127.0.0.1:1/v1/chat/completions", data=b"{}")
    with gateway.inference_attempt(request, timeout=120, approval_window=window):
        assert len(calls) == 1 and calls[0] < window.deadline
        assert connections[0].timeout == timers[0].seconds == 2
        clock.advance(2)
        timers[0].callback()
        assert connections[0].shutdowns == [gateway.socket.SHUT_RDWR]
    assert timers[0].cancelled and connections[0].closed


@pytest.mark.parametrize("stream", [False, True])
def test_expiry_during_response_keeps_unknown_usage_and_slot(env, monkeypatch, stream):
    clock, window = approved_window(monkeypatch, seconds=3)
    env.service.approval_window = window

    class InterruptedResponse:
        status = 200

        def read(self, *_):
            clock.advance(3)
            timers[0].callback()
            raise OSError("synthetic deadline interruption")

        def readline(self, *_):
            clock.advance(3)
            timers[0].callback()
            return b""  # No terminal completion marker or measured usage.

    calls, timers, connections = fake_transport(
        monkeypatch, clock, response_factory=InterruptedResponse
    )
    status, _, headers = env.request(stream=stream)
    assert status == (200 if stream else 503)
    row = direct.await_rows(env, "unknown")[0]
    assert row["id"] == headers["X-Portage-Request-Id"]
    assert row["actual"] is None
    assert len(calls) == 1 and calls[0] < window.deadline
    assert timers[0].seconds == 3 and timers[0].cancelled
    assert connections[0].shutdowns == [gateway.socket.SHUT_RDWR]
    assert env.ledger.usage("project01") == {
        "committed": row["reserved"],
        "active": 1,
        "unresolved": 1,
    }
    assert env.request()[0] == 403
    assert len(calls) == len(env.rows()) == 1


def test_slow_connect_also_respects_request_deadline_without_approval(monkeypatch):
    clock, _ = approved_window(monkeypatch)
    calls, _, connections = fake_transport(monkeypatch, clock, connect_delay=5)
    request = urllib.request.Request("http://127.0.0.1:1/v1/chat/completions", data=b"{}")
    with pytest.raises(TimeoutError):
        with gateway.inference_attempt(request, timeout=4):
            pytest.fail("request deadline ignored")
    assert calls == [] and connections[0].closed


def test_direct_qualification_gateway_inherits_manifest_expiry(monkeypatch):
    clock, _ = approved_window(monkeypatch)
    config = live_config("http://127.0.0.1:1")
    config["approved_capacity"]["deadline_utc"] = datetime.fromtimestamp(
        clock.wall + 30, UTC
    ).isoformat()
    service = gateway.Gateway(("127.0.0.1", 0), None, config, "", "", "", "")
    try:
        clock.advance(31)
        with pytest.raises(gateway.Denied, match="approval_expired"):
            service.approval_window.check()
    finally:
        service.server_close()


def test_direct_qualification_gateway_requires_deadline():
    config = live_config("http://127.0.0.1:1")
    del config["approved_capacity"]
    with pytest.raises(ValueError, match="approved deadline"):
        gateway.Gateway(("127.0.0.1", 0), None, config, "", "", "", "")
