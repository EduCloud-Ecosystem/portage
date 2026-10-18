# SPDX-License-Identifier: Apache-2.0
"""Pure fixture contract. No transport, credential access, or execution eligibility.

Request plans are internal planning data, not logs. Only evidence() exports are
sanitized for sharing. Classifications never settle or reconcile a ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

ORIGIN = "https://llm.jetstream-cloud.org"
CHAT_PATH = "/api/chat/completions"
CATALOG_PATH = "/api/models"
MAX_BODY_BYTES = 262144
MAX_USAGE_TOKENS = 65536
RESERVATION = 1024
TASKS = (
    ("arithmetic", "What is 6 times 7? Reply with only the integer.", "42"),
    ("extraction", "From 'red, blue, green', return only the second color.", "blue"),
)
UNVERIFIED = (
    "individual_entitlement",
    "model_compatibility",
    "service_terms",
    "resource_bounds",
    "tls_and_dns",
    "persistent_attempt_limit",
    "persistent_catalog_limit",
    "provider_termination",
    "runtime_approval",
)


class ContractError(ValueError):
    """Only fixed, non-payload error codes may leave validation."""


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_hash(value):
    return value if type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) else None


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _require(condition, code):
    if not condition:
        raise ContractError(code)


def _integer(value, ceiling=MAX_USAGE_TOKENS):
    return type(value) is int and 0 <= value <= ceiling


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", value)


@dataclass(frozen=True)
class Profile:
    _encoded: bytes = field(repr=False)


def validate_profile(profile: dict) -> Profile:
    required = {
        "profile_id",
        "credential_owner_ref",
        "origin",
        "chat_path",
        "catalog_path",
        "model_id",
        "returned_model_ids",
    }
    _require(type(profile) is dict and set(profile) == required, "profile_fields")
    _require(
        profile["origin"] == ORIGIN
        and profile["chat_path"] == CHAT_PATH
        and profile["catalog_path"] == CATALOG_PATH,
        "destination_not_allowed",
    )
    for key in ("profile_id", "credential_owner_ref", "model_id"):
        _require(bool(_identifier(profile[key])), "profile_identifier")
    models = profile["returned_model_ids"]
    _require(
        type(models) is list
        and 1 <= len(models) <= 4
        and all(_identifier(model) for model in models)
        and len(set(models)) == len(models),
        "model_mapping",
    )
    return Profile(_json(profile))


def _profile(profile):
    _require(type(profile) is Profile, "validated_profile_required")
    # Even a manually constructed Profile cannot bypass validation.
    try:
        data = json.loads(profile._encoded)
    except (ValueError, TypeError, RecursionError):
        raise ContractError("profile_fields") from None
    return json.loads(validate_profile(data)._encoded)


def _task(task_id):
    _require(type(task_id) is str, "task_not_allowed")
    for task in TASKS:
        if task[0] == task_id:
            return task
    raise ContractError("task_not_allowed")


@dataclass(frozen=True)
class RequestPlan:
    method: str
    url: str = field(repr=False)
    body: bytes = field(repr=False)
    profile_sha256: str

    def evidence(self):
        return {
            "evidence_class": "synthetic_fixture_request_plan",
            "profile_sha256": _safe_hash(self.profile_sha256),
            "request_sha256": (
                _hash(self.body)
                if type(self.body) is bytes and len(self.body) <= MAX_BODY_BYTES
                else None
            ),
            "execution_authorized": False,
        }


def build_chat_plan(profile: Profile, task_id: str) -> RequestPlan:
    data = _profile(profile)
    _, prompt, _ = _task(task_id)
    body = {
        "model": data["model_id"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32,
        "stream": False,
        "n": 1,
    }
    return RequestPlan("POST", ORIGIN + CHAT_PATH, _json(body), _hash(_json(data)))


def assess_readiness(_evidence=None):
    # Populating every fictional approval field cannot make this module live.
    return {
        "execution_authorized": False,
        "status": "FIXTURE_ONLY",
        "provider_observations": "NOT RUN",
        "unverified": list(UNVERIFIED),
    }


@dataclass(frozen=True)
class Classification:
    code: str
    transport: str = "FAIL"
    task: str = "NOT RUN"
    usage_status: str = "UNKNOWN"
    provider_reported_usage: int | None = field(default=None, repr=False)
    accounting_action: str = "retain_unknown"
    bound: str = "UNVERIFIED"
    stop: bool = True
    body_sha256: str | None = None
    profile_sha256: str | None = None

    def evidence(self):
        # Fixed classifications/hashes only: no raw data, IDs, headers or amounts.
        allowed = {
            "code": {
                "body_invalid_or_oversized",
                "disconnected",
                "http_rejected",
                "content_type_rejected",
                "duplicate_json_key",
                "unsupported_json_number",
                "response_schema",
                "model_mismatch",
                "terminal_reason",
                "malformed_response",
                "usage_missing_or_invalid",
                "usage_inconsistent",
                "reservation_exceeded",
                "provider_reported_completion",
                "invalid_classification",
            },
            "transport": {"FAIL", "PASS"},
            "task": {"NOT RUN", "FAIL", "PASS"},
            "usage_status": {"UNKNOWN", "PROVIDER_REPORTED"},
            "accounting_action": {
                "retain_unknown",
                "record_provider_reported_usage",
                "record_provider_reported_usage_and_stop",
            },
            "bound": {"UNVERIFIED", "FAIL"},
        }
        if type(self.stop) is not bool or any(
            type(getattr(self, key)) is not str or getattr(self, key) not in values
            for key, values in allowed.items()
        ):
            return Classification("invalid_classification").evidence()
        return {
            "evidence_class": "synthetic_fixture_response",
            "code": self.code,
            "transport": self.transport,
            "task": self.task,
            "usage_status": self.usage_status,
            "accounting_action": self.accounting_action,
            "bound": self.bound,
            "stop": self.stop,
            "body_sha256": _safe_hash(self.body_sha256),
            "profile_sha256": _safe_hash(self.profile_sha256),
            "provider_termination": "UNVERIFIED",
            "execution_authorized": False,
        }


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate_json_key")
        value[key] = item
    return value


def _reject_number(_):
    raise ContractError("unsupported_json_number")


def _response(raw, models):
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_constant=_reject_number,
        parse_float=_reject_number,
    )
    _require(type(value) is dict, "response_schema")
    _require(
        {"model", "choices"}
        <= set(value)
        <= {"model", "choices", "usage", "id", "object", "created", "system_fingerprint"},
        "response_schema",
    )
    _require(value["model"] in models, "model_mismatch")
    if "id" in value:
        _require(type(value["id"]) is str and len(value["id"]) <= 256, "response_schema")
    if "object" in value:
        _require(value["object"] == "chat.completion", "response_schema")
    if "created" in value:
        _require(_integer(value["created"], (1 << 63) - 1), "response_schema")
    if "system_fingerprint" in value:
        fingerprint = value["system_fingerprint"]
        _require(
            fingerprint is None or type(fingerprint) is str and len(fingerprint) <= 128,
            "response_schema",
        )
    choices = value["choices"]
    _require(type(choices) is list and len(choices) == 1, "response_schema")
    choice = choices[0]
    _require(
        type(choice) is dict and set(choice) == {"index", "message", "finish_reason"},
        "response_schema",
    )
    _require(type(choice["index"]) is int and choice["index"] == 0, "response_schema")
    _require(choice["finish_reason"] in ("stop", "length"), "terminal_reason")
    message = choice["message"]
    _require(
        type(message) is dict
        and set(message) == {"role", "content"}
        and message["role"] == "assistant"
        and type(message["content"]) is str
        and len(message["content"]) <= 8192,
        "response_schema",
    )
    return value, message["content"], choice["finish_reason"]


def _usage(value):
    _require(type(value) is dict, "usage_missing_or_invalid")
    keys = set(value)
    _require(
        keys in ({"total_tokens"}, {"total_tokens", "prompt_tokens", "completion_tokens"})
        and all(_integer(count) for count in value.values()),
        "usage_missing_or_invalid",
    )
    total = value["total_tokens"]
    if "prompt_tokens" in value:
        _require(
            value["prompt_tokens"] + value["completion_tokens"] == total,
            "usage_inconsistent",
        )
    return total


def classify_response(
    profile: Profile,
    task_id: str,
    status: int | None,
    content_type: str | None,
    body: bytes,
) -> Classification:
    data = _profile(profile)
    _, _, expected = _task(task_id)
    profile_hash = _hash(_json(data))
    body_hash = None
    if type(body) is not bytes or len(body) > MAX_BODY_BYTES:
        return Classification("body_invalid_or_oversized", profile_sha256=profile_hash)
    body_hash = _hash(body)

    def rejected(code, **kwargs):
        return Classification(
            code, body_sha256=body_hash, profile_sha256=profile_hash, **kwargs
        )

    if status is None:
        return rejected("disconnected")
    if type(status) is not int or not 200 <= status < 300:
        return rejected("http_rejected")
    if content_type not in ("application/json", "application/json; charset=utf-8"):
        return rejected("content_type_rejected")
    try:
        value, text, reason = _response(body, data["returned_model_ids"])
    except ContractError as error:
        return rejected(str(error))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return rejected("malformed_response")
    task = "PASS" if reason == "stop" and text.strip() == expected else "FAIL"
    try:
        usage = _usage(value.get("usage"))
    except ContractError as error:
        return rejected(str(error), transport="PASS", task=task)
    exceeded = usage > RESERVATION
    return Classification(
        "reservation_exceeded" if exceeded else "provider_reported_completion",
        transport="PASS",
        task=task,
        usage_status="PROVIDER_REPORTED",
        provider_reported_usage=usage,
        accounting_action=(
            "record_provider_reported_usage_and_stop"
            if exceeded
            else "record_provider_reported_usage"
        ),
        # Within-reservation usage is not proof of the tokenizer/resource bound.
        bound="FAIL" if exceeded else "UNVERIFIED",
        stop=exceeded or task == "FAIL",
        body_sha256=body_hash,
        profile_sha256=profile_hash,
    )
