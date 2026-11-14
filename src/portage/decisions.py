# SPDX-License-Identifier: Apache-2.0
"""Typed, advisory decisions. No generation, network, training, or route authority.

Backends are trusted in-process, bounded local code, not user-supplied plugins.
The included backend is a rules baseline, NOT a learned decision model. A future
model adapter must separately qualify its artifact, latency and data handling.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SCHEMA = "educloud.system-one.shadow.v1"
MAX_INPUT_BYTES = 4096


@dataclass(frozen=True)
class Question:
    id: str
    labels: tuple[str, ...]


QUESTIONS = (
    Question("task_class", ("explanation", "debugging", "research")),
    Question("recommended_tier", ("code_small", "code_large")),
    Question("needs_retrieval", ("false", "true")),
)


class ScoreBackend(Protocol):
    """One bounded local invocation for the entire question set.

    Output is exactly one finite score per declared label. No generated prose,
    probabilities, credentials, permissions, or backend-selected question IDs.
    """

    backend_id: str
    artifact_sha256: str
    kind: str

    def score(self, text: str, questions: tuple[Question, ...]) -> dict: ...


class RulesBaseline:
    backend_id = "rules-baseline-v1"
    kind = "rules"

    def __init__(self):
        self.artifact_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def score(self, text, questions):
        words = set(re.findall(r"[a-z]+", text.lower()))
        hits = {
            "explanation": bool(words & {"explain", "meaning", "define"}),
            "debugging": bool(words & {"debug", "traceback", "exception", "error"}),
            "research": bool(words & {"evidence", "hypothesis", "literature", "study"}),
        }
        selected = [label for label, hit in hits.items() if hit]
        certain = len(selected) == 1
        small = certain and selected[0] in {"explanation", "debugging"}
        large = certain and selected[0] == "research"
        retrieval = bool(
            words & {"source", "sources", "cite", "documentation", "evidence"}
        )
        return {
            "task_class": [float(hits[label]) for label in questions[0].labels],
            "recommended_tier": [float(small), float(large)],
            "needs_retrieval": [float(not retrieval and certain), float(retrieval)],
        }


class ShadowDecider:
    """Validate scores and abstain; never modify the requested inference route."""

    def __init__(self, backend: ScoreBackend | None = None):
        self.backend = backend if backend is not None else RulesBaseline()
        if (
            not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", self.backend.backend_id)
            or not re.fullmatch(r"[a-f0-9]{64}", self.backend.artifact_sha256)
            or self.backend.kind not in {"rules", "synthetic_model", "local_model"}
        ):
            raise ValueError("pinned local backend identity required")

    def decide(self, messages: list[dict]) -> dict:
        started = time.perf_counter_ns()
        report = {
            "schema": SCHEMA,
            "mode": "shadow",
            "backend_id": self.backend.backend_id,
            "artifact_sha256": self.backend.artifact_sha256,
            "backend_kind": self.backend.kind,
            "score_semantics": "uncalibrated",
            "status": "abstained",
            "reason": "missing_input",
            "backend_calls": 0,
            "model_forward_calls": 0,
            "elapsed_ns": 0,
            "decisions": {},
        }
        # Only the latest user message; prompts/history are not persisted or used
        # as authority. Empty/large input abstains rather than silently truncating.
        text = next(
            (
                message["content"]
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        try:
            if not isinstance(text, str) or not text.strip():
                return report
            if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
                report["reason"] = "input_limit"
                return report
            report["backend_calls"] = 1
            report["model_forward_calls"] = int(self.backend.kind != "rules")
            try:
                raw = self.backend.score(text, QUESTIONS)
            except Exception:
                # Exception strings can contain input or credentials.
                report.update(status="failed", reason="backend_failure")
                return report
            if type(raw) is not dict or set(raw) != {q.id for q in QUESTIONS}:
                report["reason"] = "invalid_scores"
                return report
            answers = {}
            for question in QUESTIONS:
                scores = raw[question.id]
                if (
                    type(scores) not in {list, tuple}
                    or len(scores) != len(question.labels)
                    or any(
                        type(s) not in {float, int}
                        or not -1000 <= s <= 1000
                        or not math.isfinite(s)
                        for s in scores
                    )
                ):
                    report["reason"] = "invalid_scores"
                    return report
                ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
                # Reference threshold, not calibrated uncertainty. A qualified
                # model must be evaluated at this fixed operating point first.
                ambiguous = scores[ranked[0]] - scores[ranked[1]] < 0.5
                value = None if ambiguous else question.labels[ranked[0]]
                if question.id == "needs_retrieval" and value is not None:
                    value = value == "true"
                answers[question.id] = {
                    "value": value,
                    "abstain": ambiguous,
                    "scores": dict(zip(question.labels, scores, strict=True)),
                }
            abstained = any(answer["abstain"] for answer in answers.values())
            report.update(
                decisions=answers,
                status="abstained" if abstained else "answered",
                reason="ambiguous_scores" if abstained else "scored",
            )
            return report
        finally:
            report["elapsed_ns"] = time.perf_counter_ns() - started
