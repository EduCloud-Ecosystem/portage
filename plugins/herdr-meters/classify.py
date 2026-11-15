#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
classify — free local triage and routing for herdr-meters.

Three jobs, in this order, cheapest first:

  1. TRIAGE   is this task specified well enough to dispatch at all?
  2. ROUTE    which target: provider + model + effort.
  3. SHAPE    normalize the prompt to the target's conventions.

Triage is first on purpose. The tokens a hybrid stack actually wastes are mostly
NOT misrouting — they're an expensive agent burning a turn to ask "which file?"
or building the wrong thing from an ambiguous ask. Catching that HERE, on a free
local model, is worth more than any model-selection gain.

Design rules that keep a 7B classifier from becoming the problem:

  * DETERMINISTIC RULES RUN FIRST, and they win. Sensitive-data pins and explicit
    user overrides never touch the model. A small model must never be the thing
    deciding whether PHI leaves the machine.
  * IT ASKS, IT DOESN'T REWRITE. The classifier may flag what's missing and
    propose ONE clarifying question. It does not silently rewrite your intent —
    a small model reworking a task it half-understands is worse than no rewriting.
    `shaped` is a normalization (whitespace, target conventions), not a reinterpretation.
  * UNCERTAINTY ESCALATES. Low confidence routes to a HIGHER ceiling, never lower.
    Fail-up is cheap; a too-weak model failing a hard task costs two attempts.
  * IT IS ADVISORY. dispatch shows the decision and can be overridden. The
    fail-up guard remains the real correctness mechanism.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / "models.json").read_text())["targets"]
CLASSIFIER_MODEL = os.environ.get("METERS_CLASSIFIER", "qwen2.5-coder:7b")

# --- deterministic layer: no model call, always wins -------------------------

SENSITIVE = re.compile(
    r"\b(clinical|patient|phi|hipaa|irb|student record|ferpa|identifiable|"
    r"medical record|protected health)\b",
    re.I,
)

OVERRIDE = re.compile(r"@(local|codex|claude|perplexity)\b", re.I)

RESEARCH = re.compile(
    r"\b(literature review|prior art|state of the art|survey of|"
    r"competitive scan|who (?:else )?(?:has|is) (?:built|doing))\b",
    re.I,
)

# Signals that a coding task is underspecified enough to waste a real turn.
VAGUE = re.compile(
    r"\b(fix (?:it|this|the bug)|make it (?:work|better|faster)|"
    r"clean (?:it|this) up|improve|refactor (?:it|this))\b",
    re.I,
)
HAS_TARGET = re.compile(
    r"[\w/]+\.(py|ts|tsx|js|rs|go|md|json|toml|ya?ml)|"
    r"\b(function|class|module|endpoint|test)\b",
    re.I,
)


def by_id(tid: str) -> dict:
    return next((t for t in CATALOG if t["id"] == tid), CATALOG[0])


def deterministic(task: str) -> dict | None:
    """Rules that must never be delegated to a model."""
    if SENSITIVE.search(task):
        return {
            "target": "local.big",
            "confidence": 1.0,
            "why": "sensitive-data pin",
            "pinned": True,
            "missing": [],
            "clarify": None,
        }
    m = OVERRIDE.search(task)
    if m:
        prov = m.group(1).lower()
        tid = {
            "local": "local.big",
            "codex": "codex.default",
            "claude": "claude.default",
            "perplexity": "perplexity.research",
        }[prov]
        return {
            "target": tid,
            "confidence": 1.0,
            "why": f"explicit @{prov} override",
            "pinned": True,
            "missing": [],
            "clarify": None,
        }
    if RESEARCH.search(task):
        return {
            "target": "perplexity.research",
            "confidence": 0.9,
            "why": "research phrasing — Opus-grade off the Claude wallet",
            "pinned": False,
            "missing": [],
            "clarify": None,
        }
    return None


def cheap_triage(task: str) -> list[str]:
    """Free, no model: obvious underspecification."""
    missing = []
    if VAGUE.search(task) and not HAS_TARGET.search(task):
        missing.append("no file, function, or symbol named")
    if len(task.split()) < 4:
        missing.append("too short to act on")
    return missing


# --- local model layer: the ambiguous remainder ------------------------------

PROMPT = """You route coding tasks. Reply with ONLY a JSON object, no prose.

Targets:
{catalog}

Task: {task}

JSON keys:
  target      one target id from the list
  confidence  0.0-1.0
  why         under 12 words
  missing     array of specifics the task lacks to be actionable (empty if fine)
  clarify     ONE short question to ask the user, or null

Rules: pick the cheapest target whose ceiling clearly covers the task. If unsure
between two, pick the HIGHER ceiling. Do not invent target ids."""


def ask_local(task: str) -> dict | None:
    lines = "\n".join(
        f"  {t['id']}  ceiling={t['ceiling']} cost={t['cost']} "
        f"good_for={','.join(t['good_for'][:3])}"
        for t in CATALOG
    )
    try:
        r = subprocess.run(
            ["ollama", "run", CLASSIFIER_MODEL, PROMPT.format(catalog=lines, task=task)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return None
    out = r.stdout.strip()
    i, j = out.find("{"), out.rfind("}")
    if not (0 <= i < j):
        return None
    try:
        d = json.loads(out[i : j + 1])
    except json.JSONDecodeError:
        return None
    if not any(t["id"] == d.get("target") for t in CATALOG):
        return None
    return d


def escalate(tid: str) -> str:
    """Uncertainty goes UP the ceiling ladder, never down."""
    order = ["low", "medium", "high", "frontier"]
    cur = by_id(tid)
    if cur.get("scarce"):
        return tid
    want = order[min(order.index(cur["ceiling"]) + 1, len(order) - 1)]
    nxt = next(
        (
            t
            for t in CATALOG
            if t["ceiling"] == want
            and not t.get("scarce")
            and t["provider"] != "perplexity"
        ),
        None,
    )
    return nxt["id"] if nxt else tid


def _with_clarify(d: dict) -> dict:
    """Triage must fire even when the model layer is unavailable — an
    unanswerable task wastes a real turn regardless of who routed it."""
    if d["missing"] and not d.get("clarify"):
        d["clarify"] = f"Be specific before dispatching: {'; '.join(d['missing'])}."
    return d


def classify(task: str) -> dict:
    det = deterministic(task)
    missing = cheap_triage(task)

    if det:
        det["missing"] = det["missing"] or missing
        return _with_clarify(det) | {"source": "rules"}

    guess = ask_local(task)
    if not guess:
        # classifier unavailable or unusable -> safe middle, flagged
        return _with_clarify(
            {
                "target": "claude.default",
                "confidence": 0.0,
                "why": "classifier unavailable; safe default",
                "missing": missing,
                "clarify": None,
                "pinned": False,
            }
        ) | {"source": "fallback"}

    guess["missing"] = guess.get("missing") or missing
    if guess.get("confidence", 0) < 0.6:
        guess["target"] = escalate(guess["target"])
        guess["why"] = (guess.get("why", "") + " (low confidence -> escalated)").strip()
    guess["pinned"] = False
    return _with_clarify(guess) | {"source": "local-model"}


def shape(task: str, target: dict) -> dict:
    """Delegate to adapt.py — the canonical target-conditioned adapter.

    adapt.py does template SELECTION + slot filling: the template is a
    deterministic lookup keyed on (lane, model class), so every adaptation
    emits a `template_id` and verified-success-rate can be attributed per
    template. That makes prompt engineering an A/B test against the verifier
    instead of a matter of taste — which is why this function is a thin shim
    and not a second set of rules.

    Fallback (adapt.py unavailable): pass the task through unchanged. Never
    invent scaffolding here; a silent second implementation would break the
    per-template attribution that makes adaptation measurable.
    """
    original = " ".join(task.split())
    core = OVERRIDE.sub("", original).strip()
    lane = {"perplexity": "science"}.get(target["provider"], "code")
    try:
        r = subprocess.run(
            [
                sys.executable,
                str(ROOT / "adapt.py"),
                "--task",
                core,
                "--target",
                target["id"],
                "--lane",
                lane,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        d = json.loads(r.stdout)
        return {
            "original": original,
            "prompt": d.get("prompt", core),
            "template_id": d.get("template_id"),
        }
    except Exception:
        return {"original": original, "prompt": core, "template_id": None}


def main():
    task = " ".join(sys.argv[1:]).strip()
    if not task:
        task = sys.stdin.read().strip()
    d = classify(task)
    t = by_id(d["target"])
    sh = shape(task, t)
    print(
        json.dumps(
            {
                **d,
                "provider": t["provider"],
                "model": t["model"],
                "effort": t["effort"],
                "cost": t["cost"],
                "meter": t["meter"],
                "scarce": bool(t.get("scarce")),
                "original": sh["original"],  # verbatim; downstream must keep this
                "shaped": sh["prompt"],
                "template_id": sh["template_id"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
