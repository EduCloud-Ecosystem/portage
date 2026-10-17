# SPDX-License-Identifier: Apache-2.0
"""Optional OpenAI HTTP adapter. No content logging or implicit retries.

Run on a private container network. Only Waypoint exposes /v1 to clients;
/control is an operator-only service connection, never a public route.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "portage"))
from pilot_ledger import Denied, Ledger, prepare_request  # noqa: E402


def validate_manifest(manifest, mode):
    if mode not in {"synthetic", "hosted"} or manifest.get("mode") != mode:
        raise ValueError("deployment mode mismatch")
    for field in ("project_allowance", "participant_allowance", "concurrency"):
        if type(manifest.get(field)) is not int or manifest[field] <= 0:
            raise ValueError(f"finite {field} required")
    models = manifest.get("models", {})
    if set(models) != {
        "classifier",
        "code_small",
        "code_large",
        "research_synthesis",
        "embedding",
    }:
        raise ValueError("all capability aliases must be declared")
    for alias, model in models.items():
        for field in ("revision", "provenance", "endpoint", "resource_limits"):
            if not model.get(field):
                raise ValueError(f"{alias}: missing {field}")
        if not model.get("institutional_only"):
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
        if mode == "hosted":
            evidence = model.get("qualification", {})
            if model.get("synthetic") or not all(
                evidence.get(k)
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
        manifest.get("acceptance", {}).get(k)
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
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
            with urllib.request.urlopen(req, timeout=10) as result:
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
            admitted = self.server.ledger.admit(token, body["model"], reserved, asserted)
            spec = self.server.manifest["models"][body["model"]]
            request = urllib.request.Request(
                spec["endpoint"].rstrip("/") + self.path,
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.server.inference_key,
                },
            )
            usage = None
            # One HTTP attempt only; every application retry is a new admission.
            with urllib.request.urlopen(request, timeout=120) as upstream:
                if body.get("stream"):
                    streaming = True
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    for line in upstream:
                        if line.startswith(b"data: ") and line.strip() != b"data: [DONE]":
                            chunk = json.loads(line[6:])
                            if chunk.get("usage"):
                                usage = chunk["usage"].get("total_tokens")
                        self.wfile.write(line)
                        self.wfile.flush()
                else:
                    result = json.load(upstream)
                    usage = (result.get("usage") or {}).get("total_tokens")
                    # Commit reported usage before acknowledging completion;
                    # an immediate usage read must observe the completed call.
                    self.server.ledger.settle(admitted, usage)
                    self.reply(200, result)
            self.server.ledger.settle(admitted, usage)
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
        ("0.0.0.0", 8090),
        ledger,
        manifest,
        os.environ["PILOT_CONTROL_KEY"],
        os.environ["LITELLM_MASTER_KEY"],
        os.environ["PILOT_AUTHORITY_URL"],
        os.environ["PILOT_AUTHORITY_KEY"],
    ).serve_forever()
