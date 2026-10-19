#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
SessionStart hook — Lane A.

Fires on startup / resume / clear / compact. Reads the state file written by
pre_compact_snapshot.py and feeds it back as additionalContext, plus a fresh
git status so the agent resumes grounded instead of re-exploring the repo.

Deterministic: no model calls, zero quota.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def sh(*args: str) -> str:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return ""


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    source = payload.get("source", "startup")  # startup | resume | clear | compact
    project = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    )

    parts: list[str] = []
    snapshot = project / ".claude" / "state" / "project-state.md"
    if snapshot.is_file():
        parts.append(snapshot.read_text(encoding="utf-8").strip())

    branch = sh("git", "-C", str(project), "rev-parse", "--abbrev-ref", "HEAD")
    status = sh("git", "-C", str(project), "status", "--short")
    if branch:
        parts.append(
            f"## Live git ({source})\n- branch: `{branch}`\n- working tree:\n"
            f"```\n{status or '(clean)'}\n```"
        )

    context = "\n\n".join(parts).strip()
    if context:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": context,
                    }
                }
            )
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
