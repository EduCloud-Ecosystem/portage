# SPDX-License-Identifier: Apache-2.0
"""One-shot, fixed synthetic OpenRouter probe. Not a classroom deployment mode."""

from __future__ import annotations

import copy
import json
import math
import os
import stat
import threading
import time
from pathlib import Path

from pilot_ledger import Denied

MODEL = "openai/gpt-4.1-mini"
CANONICAL = "openai/gpt-4.1-mini-2025-04-14"
ENDPOINT = "https://openrouter.ai/api"
MODE = "external-smoke"
BUDGET = 0.05
BELAY_SYSTEM = "Synthetic classroom transport check; return requested JSON only."
CASES = [
    {
        "name": "arithmetic_json",
        "prompt": 'Return only JSON: {"answer": 5}.',
        "expected": {"answer": 5},
        "stream": False,
    },
    {
        "name": "extraction_json",
        "prompt": 'Extract blue from "color: blue". Return only JSON with key color.',
        "expected": {"color": "blue"},
        "stream": False,
    },
    {
        "name": "stream_terminal",
        "prompt": "Return only the word READY.",
        "expected": "READY",
        "stream": True,
    },
    {
        "name": "hint_json",
        "prompt": "Synthetic tutoring transport check. Return only JSON: "
        '{"hint": "check the loop boundary"}.',
        "expected": {"hint": "check the loop boundary"},
        "stream": False,
    },
]


def case_body(case):
    if case["name"] == "hint_json":
        return {
            "model": "code_small",
            "messages": [
                {"role": "system", "content": BELAY_SYSTEM},
                {"role": "user", "content": case["prompt"]},
            ],
            "max_tokens": 128,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
    return {
        "model": "code_small",
        "messages": [{"role": "user", "content": case["prompt"]}],
        "max_tokens": 128,
        "stream": case["stream"],
    }


def manifest():
    return {
        "mode": MODE,
        "project": "smoke001",
        "project_allowance": 8192,
        "participant_allowance": 8192,
        "concurrency": 1,
        "models": {
            "code_small": {
                "operation": "chat/completions",
                "endpoint": ENDPOINT,
                "upstream_model": MODEL,
                "revision": CANONICAL,
                "synthetic": False,
                "input_class": "fixed_synthetic",
                "max_output_tokens": 128,
                "max_request_tokens": 2048,
                "request_timeout_seconds": 60,
            }
        },
    }


def validate_external_manifest(value):
    if value != manifest():
        raise ValueError("external smoke requires the fixed bounded profile")


def load_key(path):
    """Never source shell text, print values, follow symlinks or loosen permissions."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
        ):
            raise ValueError("credential file must be regular, owned and owner-only")
        raw = source.read(8193)
    if len(raw) > 8192:
        raise ValueError("credential file too large")
    values = [
        line.split("=", 1)[1].strip()
        for line in raw.splitlines()
        if line.startswith("OPENROUTER_API_KEY=")
    ]
    if len(values) != 1:
        raise ValueError("one OPENROUTER_API_KEY required")
    key = values[0]
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
        key = key[1:-1]
    if not key.startswith("sk-or-") or any(c.isspace() for c in key):
        raise ValueError("invalid OpenRouter credential format")
    return key


def validate_catalog(value):
    """Vendor metadata, not an independent model weights or hardware attestation."""
    data = value["data"]
    if data["id"] != MODEL:
        raise ValueError("unexpected catalog model")
    candidates = [e for e in data["endpoints"] if e.get("tag") == "openai"]
    if len(candidates) != 1:
        raise ValueError("exactly one OpenAI endpoint required")
    endpoint = candidates[0]
    if CANONICAL not in endpoint["name"] or endpoint.get("status") != 0:
        raise ValueError("canonical endpoint unavailable")
    for name, ceiling in (("prompt", 0.000001), ("completion", 0.000002)):
        price = float(endpoint["pricing"][name])
        if not math.isfinite(price) or not 0 <= price <= ceiling:
            raise ValueError("catalog price exceeds cap")
    if float(endpoint["pricing"].get("request", 0)) != 0:
        raise ValueError("per-request pricing unsupported")
    if not {"max_tokens", "response_format"} <= set(endpoint["supported_parameters"]):
        raise ValueError("required parameters unavailable")
    return {
        "model": MODEL,
        "canonical": CANONICAL,
        "provider": "openai",
        "pricing": endpoint["pricing"],
        "quantization": endpoint.get("quantization"),
        "observed_at": time.time(),
    }


class SmokeGuard:
    """Append-only consumed attempts. A used run cannot be resumed or overwritten."""

    def __init__(self, directory, catalog, prior=None):
        if not 0 <= time.time() - catalog["observed_at"] < 300:
            raise ValueError("fresh catalog required")
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.lock = threading.RLock()
        self.deadline = time.time() + 600
        self.mono_deadline = time.monotonic() + 600
        self.attempts = {}
        self.blocked_cases = set()
        self.prior_reserved_usd = 0
        if prior is not None:
            # Explicit remaining-case continuation, never replay an attempted case
            # or erase its unknown liability. Original deadline remains binding.
            if prior["cases"] != ["arithmetic_json", "extraction_json"]:
                raise ValueError("unexpected prior cases")
            self.blocked_cases = set(prior["cases"])
            self.prior_reserved_usd = 0.025
            self.deadline = min(self.deadline, prior["deadline"])
            self.mono_deadline = time.monotonic() + max(0, self.deadline - time.time())
            self.check()
        self.catalog = copy.deepcopy(catalog)
        self._append(
            {
                "event": "created",
                "catalog": catalog,
                "budget_usd": BUDGET,
                "deadline": self.deadline,
                "max_requests": 4,
                "prior": prior,
            }
        )

    def _append(self, event):
        with (self.directory / "journal.jsonl").open("a") as out:
            out.write(json.dumps(event, allow_nan=False, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())

    def remaining(self):
        return max(
            0, min(self.deadline - time.time(), self.mono_deadline - time.monotonic())
        )

    def check(self):
        if self.remaining() <= 0:
            raise Denied("smoke_deadline_expired")

    def check_body(self, body):
        self.check()
        for case in CASES:
            if body == case_body(case):
                if case["name"] in self.blocked_cases:
                    raise Denied("prior_case_already_consumed")
                return case["name"]
        raise Denied("fixed_synthetic_case_required", 400)

    def start(self, body, request_id):
        with self.lock:
            name = self.check_body(body)
            if name in self.attempts or any(
                a["state"] != "complete" for a in self.attempts.values()
            ):
                raise Denied("smoke_replay_or_unresolved_attempt")
            if len(self.attempts) + len(self.blocked_cases) >= 4:
                raise Denied("smoke_request_limit")
            attempt = {
                "case": name,
                "request_id": request_id,
                "state": "pending",
                "reserved_usd": BUDGET / 4,
                "dispatches": 0,
                "provider": None,
                "model": None,
                "usage": None,
            }
            self._append({"event": "admitted", **attempt})
            self.attempts[name] = attempt
            return name

    def claim(self, name):
        with self.lock:
            self.check()
            attempt = self.attempts[name]
            if attempt["state"] != "pending" or attempt["dispatches"]:
                raise Denied("smoke_dispatch_already_consumed")
            self._append({"event": "dispatch_claim", "case": name})
            attempt["dispatches"] = 1

    def request_body(self, body):
        result = copy.deepcopy(body)
        result["model"] = MODEL
        result.pop("stream_options", None)
        if not result["stream"]:
            result["response_format"] = {"type": "json_object"}
        result["provider"] = {
            "only": ["openai"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            # These four fixed synthetic strings carry no learner/research data.
            # The observed route refused ZDR; real-data use is not qualified.
            "zdr": False,
            "max_price": {"prompt": 1, "completion": 2},
        }
        return result

    def observe(self, name, value):
        attempt = self.attempts[name]
        if not isinstance(value, dict) or value.get("error"):
            raise ValueError("invalid upstream result")
        # Only the four source-fixed synthetic inputs can reach this path.
        with (self.directory / (name + ".upstream.jsonl")).open("a") as out:
            out.write(json.dumps(value, allow_nan=False) + "\n")
        for field in ("provider", "model"):
            if value.get(field):
                if attempt[field] and value[field] != attempt[field]:
                    raise ValueError("upstream identity changed")
                attempt[field] = value[field]
        if value.get("usage") is not None:
            if not isinstance(value["usage"], dict):
                raise ValueError("invalid usage object")
            attempt["usage"] = value["usage"]

    def finish(self, name, complete=False):
        with self.lock:
            attempt = self.attempts[name]
            if attempt["state"] != "pending":
                return attempt["state"] == "complete"
            usage = attempt["usage"] or {}
            tokens, cost = usage.get("total_tokens"), usage.get("cost")
            valid = (
                complete
                and attempt["dispatches"] == 1
                and attempt["provider"] == "OpenAI"
                and attempt["model"]
                in {MODEL, CANONICAL, CANONICAL.removeprefix("openai/")}
                and type(tokens) is int
                and 0 <= tokens <= 2048
                and type(cost) in {int, float}
                and math.isfinite(cost)
                and 0 <= cost <= attempt["reserved_usd"]
            )
            attempt["state"] = "complete" if valid else "unknown"
            self._append({"event": "finished", **attempt})
            return valid

    def summary(self):
        values = list(self.attempts.values())
        return {
            "prior_reserved_usd": self.prior_reserved_usd,
            "prior_consumed_cases": sorted(self.blocked_cases),
            "attempts": values,
            "dispatch_claims": sum(a["dispatches"] for a in values),
            "sdk_retries": 0,
            "provider_internal_retries": "unobservable",
            "unknown_liability_usd": sum(
                a["reserved_usd"] for a in values if a["state"] != "complete"
            ),
            "reported_cost_usd": sum(
                a["usage"]["cost"] for a in values if a["state"] == "complete"
            ),
        }
