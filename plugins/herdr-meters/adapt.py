#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
adapt — target-conditioned prompt adaptation (role R3, docs/specs/09).

Runs AFTER routing, BEFORE dispatch. Once the target is known (model class +
lane), the prompt is adapted to that target's conventions.

This is template SELECTION + SLOT FILLING, not rewriting:

  * template choice is a deterministic dict lookup — no inference, no surprises
  * slots are filled from structured facts (task text, repo conventions, the
    subtask's acceptance command, files named in the task)
  * the local model is used ONLY for bounded extraction (pull file paths /
    symbols out of the task). It never rephrases the goal.

Why this is safe when runtime prompt-rewriting was not: nothing generative
touches your intent, it's free (local), and it's MEASURABLE — every adaptation
emits a template_id, so verified-success-rate can be attributed per template.
Prompt engineering becomes an A/B test against the verifier instead of taste.

  adapt.py --task "..." --target claude.deep --lane code \
           [--acceptance "uv run pytest -q"] [--conventions-file CLAUDE.md]
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts"
CATALOG = json.loads((ROOT / "models.json").read_text())["targets"]
EXTRACTOR = os.environ.get("METERS_CLASSIFIER", "qwen2.5-coder:7b")

# Coarse buckets on purpose (docs/specs/09 §6): per-model templates would proliferate
# faster than they could be maintained or measured.
#
# The bucket is keyed on MODEL FAMILY, not on the routing `ceiling` field. The
# two are different questions: `ceiling` says how capable a target is for
# ROUTING; the template says what prompt conventions a model family responds to.
# Commercial frontier families (Claude, GPT/Codex) infer intent well and get
# terser prompts; open-weight families degrade on ambiguity faster, so their
# template spends tokens on explicit scope and a hard output contract. Keying on
# `ceiling` mis-sent Sonnet — a frontier-family model — to the open template.
FRONTIER_PROVIDERS = {"claude", "anthropic", "codex", "openai"}

FILE_RE = re.compile(
    r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|rs|go|java|rb|md|json|toml|ya?ml|sql)\b"
)


def model_class(target_id: str) -> str:
    t = next((x for x in CATALOG if x["id"] == target_id), None)
    if not t:
        return "open"
    return "frontier" if t.get("provider") in FRONTIER_PROVIDERS else "open"


def template_key(lane: str, target_id: str) -> str:
    """Deterministic. No model call. Falls back to the lane's 'any' variant."""
    if lane in ("science", "plan"):
        return f"{lane}.any"
    return f"{lane}.{model_class(target_id)}"


def load_template(key: str) -> tuple[str, str]:
    p = PROMPTS / f"{key}.md"
    if not p.is_file():
        p = PROMPTS / "code.open.md"  # safest default: most scaffolding
        key = "code.open"
    body = re.sub(r"<!--.*?-->\s*", "", p.read_text(), flags=re.DOTALL)
    return key, body.strip()


def extract_files(task: str) -> list[str]:
    """Regex first (free, exact). Only ask the model if regex finds nothing."""
    hits = FILE_RE.findall(task)
    if hits:
        return sorted(set(hits))
    try:
        r = subprocess.run(
            [
                "ollama",
                "run",
                EXTRACTOR,
                "List only file paths or code symbols named in this task, one per "
                "line. If none, output NONE. Do not explain.\n\n" + task,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = [line.strip() for line in r.stdout.splitlines() if line.strip()]
        return [] if not out or out[0].upper().startswith("NONE") else out[:8]
    except Exception:
        return []


def conventions(path: str | None) -> str:
    for cand in ([path] if path else []) + ["CLAUDE.md", "AGENTS.md"]:
        if cand and Path(cand).is_file():
            txt = " ".join(Path(cand).read_text().split())
            return txt[:600] + ("…" if len(txt) > 600 else "")
    return "(none recorded)"


def adapt(
    task: str,
    target_id: str,
    lane: str,
    acceptance: str | None,
    conv_file: str | None,
    rubric: str | None,
) -> dict:
    key, tpl = load_template(template_key(lane, target_id))
    files = extract_files(task)
    slots = {
        "task": task.strip(),
        "files": ", ".join(files) if files else "(not specified — infer from the repo)",
        "conventions": conventions(conv_file),
        "acceptance_check": acceptance or "uv run pytest -q",
        "rubric": rubric or "(none specified)",
    }
    prompt = tpl
    for k, v in slots.items():
        prompt = prompt.replace("{" + k + "}", v)
    return {
        "template_id": key,
        "target": target_id,
        "model_class": model_class(target_id),
        "lane": lane,
        "files_detected": files,
        "prompt": prompt,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--target", required=True, help="target id from models.json")
    ap.add_argument(
        "--lane", default="code", choices=["code", "science", "plan", "design"]
    )
    ap.add_argument("--acceptance")
    ap.add_argument("--conventions-file")
    ap.add_argument("--rubric")
    ap.add_argument("--json", action="store_true", help="emit full record")
    a = ap.parse_args()

    rec = adapt(a.task, a.target, a.lane, a.acceptance, a.conventions_file, a.rubric)
    if a.json:
        print(json.dumps(rec, indent=2))
    else:
        sys.stderr.write(
            f"[adapt] template={rec['template_id']} "
            f"class={rec['model_class']} files={rec['files_detected']}\n"
        )
        print(rec["prompt"])


if __name__ == "__main__":
    main()
