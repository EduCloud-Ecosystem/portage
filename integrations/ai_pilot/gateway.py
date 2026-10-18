# SPDX-License-Identifier: Apache-2.0
"""Optional OpenAI HTTP adapter. No content logging or implicit retries.

Run on a private container network. Only Waypoint exposes /v1 to clients;
/control is an operator-only service connection, never a public route.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "portage"))
from pilot_ledger import Denied, Ledger, prepare_request  # noqa: E402
from qualification_guard import (  # noqa: E402
    QualificationGuard,
    digest,
    observe_usage,
    unique_json,
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def open_once(request, timeout):
    # Neither environment proxies nor redirects may change the approved destination.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    ).open(request, timeout=timeout)


class ApprovalWindow:
    """A finite approval cannot be extended by a wall-clock rollback."""

    def __init__(self, deadline):
        if not math.isfinite(deadline):
            raise ValueError("finite approval deadline required")
        self.deadline = deadline
        self.monotonic_deadline = time.monotonic() + max(0, deadline - time.time())
        self.expired = False

    def remaining(self):
        remaining = min(
            self.deadline - time.time(), self.monotonic_deadline - time.monotonic()
        )
        if remaining <= 0:
            self.expired = True
        return 0 if self.expired else remaining

    def check(self):
        if self.remaining() <= 0:
            raise Denied("approval_expired")


def qualification_window(manifest):
    if manifest["mode"] != "qualification" or all(
        model.get("synthetic") is True for model in manifest["models"].values()
    ):
        return None
    try:
        deadline = datetime.fromisoformat(manifest["approved_capacity"]["deadline_utc"])
        if deadline.tzinfo is None:
            raise ValueError("deadline must include a timezone")
        return ApprovalWindow(deadline.timestamp())
    except (KeyError, TypeError) as exc:
        raise ValueError("qualification requires an approved deadline") from exc


@contextmanager
def inference_attempt(request, timeout, approval_window=None, dispatch_check=None):
    """One destination, no retry, absolute response deadline including connect."""
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = deadline - time.monotonic()
        if approval_window is not None:
            approval_window.check()
            seconds = min(seconds, approval_window.remaining())
        if seconds <= 0:
            raise TimeoutError("inference deadline expired")
        return seconds

    endpoint = urlsplit(request.full_url)
    connection_type = (
        http.client.HTTPSConnection
        if endpoint.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_type(endpoint.hostname, endpoint.port, timeout=remaining())
    timer = None
    try:
        connection.connect()
        transport = connection.sock

        def interrupt():
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        # A slow connect is not permission to dispatch after either deadline.
        seconds = remaining()
        transport.settimeout(seconds)
        timer = threading.Timer(seconds, interrupt)
        timer.daemon = True
        timer.start()
        remaining()
        if dispatch_check is not None:
            dispatch_check()
        remaining()
        connection.request(
            request.get_method(),
            request.selector,
            body=request.data,
            headers=dict(request.header_items()),
        )
        with connection.getresponse() as response:
            if not 200 <= response.status < 300:
                raise urllib.error.HTTPError(
                    request.full_url,
                    response.status,
                    "upstream refused",
                    response.headers,
                    None,
                )
            yield response
    finally:
        if timer:
            timer.cancel()
        connection.close()


def qualified_json(guard, attempt, request, validate, timeout=5):
    """One consumed slot, one dispatch claim, and no retry on ambiguous metadata."""
    known = False
    try:
        with inference_attempt(
            request,
            timeout,
            approval_window=guard,
            dispatch_check=lambda: guard.claim(attempt),
        ) as response:
            raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError("metadata too large")
            result = unique_json(raw)
            if not isinstance(result, dict):
                raise ValueError("metadata object required")
            validate(result)
            known = True
            return result
    finally:
        guard.finish(attempt, known=known)


def qualified_authority(guard, kind, slot, phase, authority_key):
    attempt = guard.authority(kind, slot, phase)
    request = urllib.request.Request(
        guard.binding["authority_url"].rstrip("/")
        + "/internal/member/"
        + guard.binding["subject"],
        headers={"Authorization": "Bearer " + authority_key},
    )

    def validate(value):
        if (
            set(value) != {"active", "project"}
            or value["active"] is not True
            or value["project"] != guard.binding["project"]
        ):
            raise Denied("membership_required")

    qualified_json(guard, attempt, request, validate)


def validate_metadata(guard, op, value):
    model = guard.manifest["models"]["code_small"]
    if op == "version":
        valid = (
            value.get("version") == guard.manifest["approved_capacity"]["engine_version"]
        )
    elif op == "tags":
        candidates = [
            row for row in value["models"] if row.get("name") == model["upstream_model"]
        ]
        valid = len(candidates) == 1
        if valid:
            row = candidates[0]
            valid = (
                row.get("digest") == model["revision"]
                and type(row.get("size")) is int
                and row["size"] > 0
                and not any(row.get(key) for key in ("remote_host", "remote_model"))
            )
    elif op == "show":
        valid = (
            digest(value["template"].encode()) == model["template_sha256"]
            and value["details"].get("quantization_level") == model["quantization"]
            and not any(value.get(key) for key in ("remote_host", "remote_model"))
        )
    else:
        valid = type(value.get("models")) is list and all(
            type(row) is dict for row in value["models"]
        )
    if not valid:
        raise ValueError("engine metadata differs from approved profile")


def qualified_metadata(guard, slot, authority_key):
    item = guard._slot("metadata", slot)
    qualified_authority(guard, "metadata", slot, "pre", authority_key)
    attempt, _ = guard.admit("metadata", slot)
    model = guard.manifest["models"]["code_small"]
    body = {"model": model["upstream_model"]} if item["op"] == "show" else None
    request = urllib.request.Request(
        model["endpoint"].rstrip("/") + "/api/" + item["op"],
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    return qualified_json(
        guard, attempt, request, lambda value: validate_metadata(guard, item["op"], value)
    )


def validate_manifest(manifest, mode):
    if (
        mode not in {"synthetic", "hosted", "qualification"}
        or manifest.get("mode") != mode
    ):
        raise ValueError("deployment mode mismatch")
    for field in ("project_allowance", "participant_allowance", "concurrency"):
        if type(manifest.get(field)) is not int or manifest[field] <= 0:
            raise ValueError(f"finite {field} required")
    models = manifest.get("models", {})
    required = {
        "classifier",
        "code_small",
        "code_large",
        "research_synthesis",
        "embedding",
    }
    if set(models) != ({"code_small"} if mode == "qualification" else required):
        raise ValueError("all capability aliases must be declared")
    for alias, model in models.items():
        for field in ("revision", "provenance", "endpoint", "resource_limits"):
            if not model.get(field):
                raise ValueError(f"{alias}: missing {field}")
        if model.get("institutional_only") is not True:
            raise ValueError("pilot routes must be institutional only")
        endpoint = urlsplit(model["endpoint"])
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError(f"{alias}: invalid endpoint")
        limits = model["resource_limits"]
        if not isinstance(limits, dict) or any(
            type(limits.get(k)) not in {int, float}
            or not math.isfinite(limits[k])
            or limits[k] <= 0
            for k in ("memory_mb", "cpus")
        ):
            raise ValueError(f"{alias}: finite CPU and memory ceilings required")
        for field in ("max_output_tokens", "max_request_tokens"):
            if type(model.get(field)) is not int or model[field] <= 0:
                raise ValueError(f"{alias}: finite {field} required")
        if model.get("operation") != (
            "embeddings" if alias == "embedding" else "chat/completions"
        ):
            raise ValueError("invalid capability operation")
        if mode == "qualification":
            # An opt-in, single-engine test path, never a hosted deployment mode.
            if (
                not ipaddress.ip_address(endpoint.hostname).is_loopback
                or endpoint.scheme != "http"
                or endpoint.path not in {"", "/"}
            ):
                raise ValueError("qualification requires a literal loopback origin")
            for field in ("upstream_model", "quantization", "template_sha256"):
                if not isinstance(model.get(field), str) or not model[field].strip():
                    raise ValueError(f"{alias}: missing {field}")
            if (
                type(model.get("context_tokens")) is not int
                or model["context_tokens"] < model["max_request_tokens"]
            ):
                raise ValueError("qualification context must cover request reservation")
            if (
                type(model.get("request_timeout_seconds")) not in {int, float}
                or not 0 < model["request_timeout_seconds"] <= 120
            ):
                raise ValueError("qualification requires a deadline up to 120 seconds")
        if mode == "hosted":
            evidence = model.get("qualification", {})
            if model.get("synthetic") is not False or not all(
                evidence.get(k) is True
                for k in (
                    "provenance",
                    "compatibility",
                    "streaming",
                    "retrieval_quality",
                    "latency",
                    "concurrency",
                    "resource_usage",
                    "token_bound",
                )
            ):
                raise ValueError(f"{alias}: institutional qualification incomplete")
    if mode == "hosted" and not all(
        manifest.get("acceptance", {}).get(k) is True
        for k in (
            "institution",
            "data_destinations",
            "retention",
            "restore",
            "accessibility",
        )
    ):
        raise ValueError("whole-service acceptance incomplete")


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        ledger,
        manifest,
        control_key,
        inference_key,
        authority_url,
        authority_key,
        *,
        approval_window=None,
        qualification_guard=None,
    ):
        self.qualification_guard = qualification_guard
        if qualification_guard is not None and manifest["mode"] != "qualification":
            raise ValueError("qualification guard requires qualification mode")
        if manifest["mode"] == "qualification":
            if not isinstance(qualification_guard, QualificationGuard):
                raise ValueError("qualification requires a registered approval guard")
            qualification_guard.validate_gateway(ledger, manifest, authority_url)
            manifest = qualification_guard.manifest
            approval_window = qualification_guard
        self.approval_window = (
            approval_window
            if approval_window is not None
            else qualification_window(manifest)
        )
        super().__init__(address, Handler)
        self.ledger, self.manifest = ledger, manifest
        self.control_key, self.inference_key = control_key, inference_key
        self.authority_url, self.authority_key = authority_url, authority_key


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(180)

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.response_started = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if getattr(self, "admitted", None):
            self.send_header("X-Portage-Request-Id", self.admitted)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 262144:
            raise Denied("request_size_limit", 413)
        raw = self.rfile.read(length)
        value = unique_json(raw) if self.server.qualification_guard else json.loads(raw)
        if not isinstance(value, dict):
            raise Denied("object_required", 400)
        return value

    def token(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise Denied("invalid_credential", 401)
        return header[7:]

    def identity(self):
        token = self.token()
        asserted = self.headers.get("X-Portage-Subject")
        guard = self.server.qualification_guard
        if guard is not None:
            project, member = guard.authenticate(token)
            phase = (
                "post"
                if getattr(self, "qualification_identity_checked", False)
                else "pre"
            )
            qualified_authority(
                guard,
                "inference",
                self.qualification_slot,
                phase,
                self.server.authority_key,
            )
            self.qualification_identity_checked = True
            return token, None, project, member
        project, member = self.server.ledger.authenticate(token, asserted)
        # No cache. An unreachable authority is not permission to admit work.
        url = self.server.authority_url + "/internal/member/" + member["subject"]
        req = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + self.server.authority_key}
        )
        try:
            with open_once(req, timeout=10) as result:
                current = json.load(result)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403, 404}:
                raise Denied("membership_required", 403) from exc
            raise Denied("membership_unavailable", 503) from exc
        except (OSError, ValueError) as exc:
            raise Denied("membership_unavailable", 503) from exc
        if current.get("active") is not True or current.get("project") != project["id"]:
            raise Denied("membership_required")
        return token, asserted, project, member

    def control(self):
        if not secrets.compare_digest(self.token(), self.server.control_key):
            raise Denied("invalid_credential", 401)
        body = self.body()
        ledger = self.server.ledger
        project = self.server.manifest["project"]
        if self.path == "/control/member":
            ledger.member(
                project, body["subject"], body["allowance"], body.get("concurrency", 2)
            )
        elif self.path == "/control/application":
            ledger.install_application(project, body["token"])
        elif self.path == "/control/revoke":
            ledger.revoke(project, body["subject"])
        elif self.path == "/control/retire":
            ledger.retire(project)
        elif self.path == "/control/issue":
            token = ledger.issue(
                project,
                subject=body.get("subject"),
                kind=body.get("kind", "participant"),
                lifetime=body.get("lifetime", 3600),
            )
            return self.reply(200, {"token": token})
        elif self.path == "/control/reconcile":
            ledger.reconcile(body["request"], body["usage"], body["evidence"])
        else:
            raise Denied("not_found", 404)
        self.reply(200, {"ok": True})

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        admitted = None
        self.qualification_identity_checked = False
        self.admitted = None
        self.response_started = False
        streaming = False
        guarded_attempt = None
        guard = self.server.qualification_guard
        try:
            if guard is not None:
                guard.validate_gateway(
                    self.server.ledger, self.server.manifest, self.server.authority_url
                )
                if self.command != "POST" or self.path != "/v1/chat/completions":
                    raise Denied("qualification_operation_not_allowed")
                self.qualification_slot = self.headers.get("X-Portage-Qualification-Slot")
                self.qualification_body = self.body()
                guard.check_body(self.qualification_slot, self.qualification_body)
            if self.path == "/health" and self.command == "GET":
                return self.reply(
                    200, {"status": "ok", "mode": self.server.manifest["mode"]}
                )
            if self.path.startswith("/control/") and self.command == "POST":
                return self.control()
            token, asserted, project, member = self.identity()
            if self.path == "/v1/models" and self.command == "GET":
                return self.reply(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {"id": m, "object": "model", "owned_by": "portage"}
                            for m in self.server.manifest["models"]
                        ],
                    },
                )
            if self.path == "/v1/usage" and self.command == "GET":
                return self.reply(
                    200,
                    {
                        "participant": self.server.ledger.usage(
                            project["id"], member["subject"]
                        ),
                        "allowance": member["allowance"],
                    },
                )
            if self.command != "POST" or self.path not in {
                "/v1/chat/completions",
                "/v1/embeddings",
            }:
                raise Denied("not_found", 404)
            body, reserved = prepare_request(
                self.qualification_body if guard else self.body(),
                self.server.manifest["models"],
                self.path[4:],
            )
            # Body receipt may block. Recheck the current authority immediately
            # before admission; the ledger then rechecks local revocation atomically.
            token, asserted, project, member = self.identity()
            window = self.server.approval_window
            if window is not None:
                window.check()
            if guard is not None:
                guarded_attempt, admitted = guard.admit(
                    "inference",
                    self.qualification_slot,
                    token=token,
                    body=self.qualification_body,
                )
            else:
                admitted = self.server.ledger.admit(
                    token,
                    body["model"],
                    reserved,
                    asserted,
                    admission_check=window.check if window is not None else None,
                )
            self.admitted = admitted
            spec = self.server.manifest["models"][body["model"]]
            if guard is not None:
                guard.validate_gateway(
                    self.server.ledger, self.server.manifest, self.server.authority_url
                )
            if self.server.manifest["mode"] == "qualification":
                body["model"] = spec["upstream_model"]
            request = urllib.request.Request(
                spec["endpoint"].rstrip("/") + self.path,
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.server.inference_key,
                    "X-Portage-Request-Id": admitted,
                },
            )
            usage = None
            # One HTTP attempt only; every application retry is a new admission.
            with inference_attempt(
                request,
                timeout=spec.get("request_timeout_seconds", 120),
                approval_window=window,
                dispatch_check=(lambda: guard.claim(guarded_attempt)) if guard else None,
            ) as upstream:
                if body.get("stream"):
                    streaming = True
                    self.response_started = True
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.send_header("X-Portage-Request-Id", admitted)
                    self.end_headers()
                    self.close_connection = True
                    done = False
                    while line := upstream.readline(262145):
                        if len(line) > 262144:
                            raise ValueError("upstream event too large")
                        if line.strip() == b"data: [DONE]":
                            done = True
                        elif line.startswith(b"data: "):
                            chunk = (
                                unique_json(line[6:]) if guard else json.loads(line[6:])
                            )
                            if chunk.get("error"):
                                raise ValueError("upstream stream failed")
                            if guard:
                                usage = observe_usage(usage, chunk)
                            elif chunk.get("usage"):
                                usage = chunk["usage"].get("total_tokens")
                        self.wfile.write(line)
                        self.wfile.flush()
                        if done:
                            break
                    if not done:
                        usage = None
                else:
                    if guard:
                        raw = upstream.read(262145)
                        if len(raw) > 262144:
                            raise ValueError("response too large")
                        result = unique_json(raw)
                    else:
                        result = json.load(upstream)
                    usage = (
                        observe_usage(None, result)
                        if guard and not result.get("error")
                        else (
                            (result.get("usage") or {}).get("total_tokens")
                            if not result.get("error")
                            else None
                        )
                    )
                    # Commit reported usage before acknowledging completion;
                    # an immediate usage read must observe the completed call.
                    if guard:
                        guard.finish(guarded_attempt, known=True, usage=usage)
                    else:
                        self.server.ledger.settle(admitted, usage)
                    self.reply(200, result)
            if guard:
                guard.finish(guarded_attempt, known=True, usage=usage)
            else:
                self.server.ledger.settle(admitted, usage)
        except (BrokenPipeError, ConnectionResetError):
            # RemoteDisconnected also inherits ConnectionResetError. Before
            # response headers this may be the engine, not the caller.
            if not self.response_started:
                try:
                    self.reply(503, {"error": {"code": "inference_unavailable"}})
                except (BrokenPipeError, ConnectionResetError):
                    pass
        except Denied as exc:
            if not streaming:
                self.reply(exc.status, {"error": {"code": exc.code, "message": exc.code}})
        except (ValueError, KeyError, TypeError):
            if not streaming:
                self.reply(400, {"error": {"code": "invalid_request"}})
        except Exception:
            if not streaming:
                self.reply(503, {"error": {"code": "inference_unavailable"}})
        finally:
            if guarded_attempt:
                guard.finish(guarded_attempt, known=False)
            elif admitted:
                self.server.ledger.settle(admitted, None)


if __name__ == "__main__":
    manifest = json.loads(Path(os.environ["PILOT_MANIFEST"]).read_text())
    validate_manifest(manifest, os.environ["PILOT_MODE"])
    if manifest["mode"] == "qualification":
        raise SystemExit("Use the registered, guarded qualification runner")
    ledger = Ledger(os.environ["PILOT_LEDGER"])
    ledger.project(
        manifest["project"], manifest["project_allowance"], manifest["concurrency"]
    )
    Gateway(
        ("127.0.0.1" if manifest["mode"] == "qualification" else "0.0.0.0", 8090),
        ledger,
        manifest,
        os.environ["PILOT_CONTROL_KEY"],
        os.environ["LITELLM_MASTER_KEY"],
        os.environ["PILOT_AUTHORITY_URL"],
        os.environ["PILOT_AUTHORITY_KEY"],
    ).serve_forever()
