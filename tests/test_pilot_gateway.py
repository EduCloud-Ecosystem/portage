# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pilot_gateway", Path(__file__).parents[1] / "integrations/ai_pilot/gateway.py"
)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class Fixture(BaseHTTPRequestHandler):
    active = True
    calls = []

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(
            json.dumps({"active": self.active, "project": "course01"}).encode()
        )

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(body)
        self.send_response(200)
        self.end_headers()
        if body.get("stream"):
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"test"}}]}\n\n')
            self.wfile.write(b'data: {"choices":[],"usage":{"total_tokens":12}}\n\n')
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(b'{"usage":{"total_tokens":12},"choices":[]}')


@pytest.fixture
def server(tmp_path):
    Fixture.active, Fixture.calls = True, []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{upstream.server_port}"
    models = {
        name: {
            "operation": "embeddings" if name == "embedding" else "chat/completions",
            "endpoint": url,
            "max_output_tokens": 100,
            "max_request_tokens": 1000,
            "revision": "synthetic-v1",
            "provenance": "local fixture",
            "resource_limits": {"cpus": 1, "memory_mb": 128},
            "synthetic": True,
            "institutional_only": True,
        }
        for name in [
            "classifier",
            "code_small",
            "code_large",
            "research_synthesis",
            "embedding",
        ]
    }
    manifest = {
        "project": "course01",
        "mode": "synthetic",
        "models": models,
        "project_allowance": 2000,
        "participant_allowance": 1000,
        "concurrency": 2,
    }
    ledger = gateway.Ledger(tmp_path / "ledger.sqlite")
    ledger.project("course01", 2000, 2)
    ledger.member("course01", "learner1", 1000)
    token = ledger.issue("course01", subject="learner1")
    service = gateway.Gateway(
        ("127.0.0.1", 0), ledger, manifest, "control", "inference", url, "authority"
    )
    threading.Thread(target=service.serve_forever, daemon=True).start()

    def request(path, body=None, key=token):
        req = urllib.request.Request(
            f"http://127.0.0.1:{service.server_port}" + path,
            data=json.dumps(body).encode() if body else None,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "X-Portage-Subject": "spoofed_subject",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    yield service, request
    service.shutdown()
    upstream.shutdown()
    service.server_close()
    upstream.server_close()


def test_http_models_and_streaming_accounting(server):
    service, request = server
    assert request("/v1/models")[0] == 200
    assert request("/v1/models", key="invalid")[0] == 401
    status, body = request(
        "/v1/chat/completions",
        {
            "model": "classifier",
            "stream": True,
            "messages": [
                {"role": "user", "content": "title this synthetic conversation"}
            ],
            "owner": "victim",
            "project": "victim",
        },
    )
    assert status == 200 and b"[DONE]" in body
    assert service.ledger.usage("course01", "learner1")["committed"] == 12
    assert not {"owner", "project"} & Fixture.calls[0].keys()


def test_each_background_call_and_embedding_is_accounted(server):
    service, request = server
    for _ in range(3):
        assert (
            request(
                "/v1/chat/completions",
                {
                    "model": "classifier",
                    "messages": [{"role": "user", "content": "title summary or retry"}],
                },
            )[0]
            == 200
        )
    assert (
        request("/v1/embeddings", {"model": "embedding", "input": ["a source"]})[0] == 200
    )
    assert service.ledger.usage("course01", "learner1")["committed"] == 48
    assert len(Fixture.calls) == 4


def test_membership_checked_on_next_request(server):
    _, request = server
    assert request("/v1/models")[0] == 200
    Fixture.active = False
    assert request("/v1/models")[0] == 403
    assert len(Fixture.calls) == 0


def test_forbidden_alias_never_reaches_inference(server):
    _, request = server
    assert (
        request(
            "/v1/chat/completions",
            {"model": "commercial", "messages": [{"role": "user", "content": "test"}]},
        )[0]
        == 403
    )
    assert not Fixture.calls


def test_synthetic_cannot_be_promoted_by_mode_change(server):
    service, _ = server
    gateway.validate_manifest(service.manifest, "synthetic")
    with pytest.raises(ValueError):
        gateway.validate_manifest(service.manifest, "hosted")
    service.manifest["mode"] = "hosted"
    with pytest.raises(ValueError, match="qualification"):
        gateway.validate_manifest(service.manifest, "hosted")
    service.manifest["models"] = {}
    with pytest.raises(ValueError):
        gateway.validate_manifest(service.manifest, "hosted")


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {"cpus": 0, "memory_mb": 128},
        {"cpus": 1, "memory_mb": -1},
        {"cpus": True, "memory_mb": 128},
        {"cpus": float("inf"), "memory_mb": 128},
        {"cpus": 1, "memory_mb": float("nan")},
    ],
)
def test_manifest_requires_positive_resource_ceiling(server, limits):
    service, _ = server
    service.manifest["models"]["embedding"]["resource_limits"] = limits
    with pytest.raises(ValueError):
        gateway.validate_manifest(service.manifest, "synthetic")


@pytest.fixture
def hosted_manifest():
    qualification = dict.fromkeys(
        (
            "provenance",
            "compatibility",
            "streaming",
            "retrieval_quality",
            "latency",
            "concurrency",
            "resource_usage",
            "token_bound",
        ),
        True,
    )
    return {
        "project": "course01",
        "mode": "hosted",
        "project_allowance": 2000,
        "participant_allowance": 1000,
        "concurrency": 2,
        "acceptance": dict.fromkeys(
            ("institution", "data_destinations", "retention", "restore", "accessibility"),
            True,
        ),
        "models": {
            alias: {
                "operation": "embeddings" if alias == "embedding" else "chat/completions",
                "endpoint": "http://127.0.0.1:11434",
                "revision": "reviewed-revision",
                "provenance": "reviewed artifact",
                "resource_limits": {"cpus": 1, "memory_mb": 128},
                "max_output_tokens": 100,
                "max_request_tokens": 1000,
                "synthetic": False,
                "institutional_only": True,
                "qualification": qualification.copy(),
            }
            for alias in (
                "classifier",
                "code_small",
                "code_large",
                "research_synthesis",
                "embedding",
            )
        },
    }


def test_hosted_manifest_accepts_explicit_completed_gates(hosted_manifest):
    gateway.validate_manifest(hosted_manifest, "hosted")


@pytest.mark.parametrize("value", ["NOT RUN", "FAIL", "false", 1, {}, None])
@pytest.mark.parametrize("gate", ["qualification", "acceptance", "institutional_only"])
def test_hosted_manifest_rejects_truthy_non_boolean_gates(hosted_manifest, gate, value):
    model = hosted_manifest["models"]["code_small"]
    if gate == "qualification":
        model[gate]["token_bound"] = value
    elif gate == "acceptance":
        hosted_manifest[gate]["institution"] = value
    else:
        model[gate] = value
    with pytest.raises(ValueError):
        gateway.validate_manifest(hosted_manifest, "hosted")


@pytest.mark.parametrize("value", [None, 0, "false", True])
def test_hosted_manifest_requires_explicit_non_synthetic_model(hosted_manifest, value):
    hosted_manifest["models"]["code_small"]["synthetic"] = value
    with pytest.raises(ValueError):
        gateway.validate_manifest(hosted_manifest, "hosted")
