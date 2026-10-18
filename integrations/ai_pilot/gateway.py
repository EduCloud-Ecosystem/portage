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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "portage"))
from pilot_ledger import Denied, Ledger, prepare_request  # noqa: E402


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def open_once(request, timeout):
    # Neither environment proxies nor redirects may change the approved destination.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    ).open(request, timeout=timeout)


@contextmanager
def inference_attempt(request, timeout):
    """One destination, no retry, absolute response deadline including connect."""
    deadline = time.monotonic() + timeout
    endpoint = urlsplit(request.full_url)
    connection_type = (
        http.client.HTTPSConnection
        if endpoint.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_type(endpoint.hostname, endpoint.port, timeout=timeout)
    timer = None
    try:
        connection.connect()
        transport = connection.sock

        def interrupt():
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(max(0, deadline - time.monotonic()), interrupt)
        timer.daemon = True
        timer.start()
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
    ):
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
        value = json.loads(self.rfile.read(length))
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
        self.admitted = None
        self.response_started = False
        streaming = False
        try:
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
                self.body(), self.server.manifest["models"], self.path[4:]
            )
            # Body receipt may block. Recheck the current authority immediately
            # before admission; the ledger then rechecks local revocation atomically.
            token, asserted, project, member = self.identity()
            admitted = self.server.ledger.admit(token, body["model"], reserved, asserted)
            self.admitted = admitted
            spec = self.server.manifest["models"][body["model"]]
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
                request, timeout=spec.get("request_timeout_seconds", 120)
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
                            chunk = json.loads(line[6:])
                            if chunk.get("error"):
                                raise ValueError("upstream stream failed")
                            if chunk.get("usage"):
                                usage = chunk["usage"].get("total_tokens")
                        self.wfile.write(line)
                        self.wfile.flush()
                        if done:
                            break
                    if not done:
                        usage = None
                else:
                    result = json.load(upstream)
                    usage = (
                        (result.get("usage") or {}).get("total_tokens")
                        if not result.get("error")
                        else None
                    )
                    # Commit reported usage before acknowledging completion;
                    # an immediate usage read must observe the completed call.
                    self.server.ledger.settle(admitted, usage)
                    self.reply(200, result)
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
            if admitted:
                self.server.ledger.settle(admitted, None)


if __name__ == "__main__":
    manifest = json.loads(Path(os.environ["PILOT_MANIFEST"]).read_text())
    validate_manifest(manifest, os.environ["PILOT_MODE"])
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
