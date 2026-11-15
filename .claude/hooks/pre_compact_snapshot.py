#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
PreCompact hook — Lane A.

Fires before Claude Code compacts context. Deterministic only: no model calls,
so it draws zero quota. It backs up the transcript and writes a short, factual
state file that the SessionStart hook re-injects after a compact or on resume.

The point is to stop you (and the agent) re-deriving where the repo is after a
compact — re-derivation is re-sent context, which is pure quota burn.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
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

    project = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    )
    state_dir = project / ".claude" / "state"
    backups = state_dir / "transcripts"
    state_dir.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    trigger = payload.get("trigger", "unknown")  # "manual" | "auto"

    # Back up the transcript so a bad compact is never lossy.
    transcript = payload.get("transcript_path")
    backup_ref = "none"
    if transcript and Path(transcript).is_file():
        dest = backups / f"{stamp}.jsonl"
        try:
            shutil.copy2(transcript, dest)
            backup_ref = str(dest.relative_to(project))
        except Exception:
            backup_ref = "copy-failed"

    branch = sh("git", "-C", str(project), "rev-parse", "--abbrev-ref", "HEAD")
    status = sh("git", "-C", str(project), "status", "--short")
    log = sh("git", "-C", str(project), "log", "-5", "--oneline")

    state = f"""# Project state snapshot
_Written by pre_compact_snapshot.py at {stamp} (trigger: {trigger})._
_Deterministic; no model was called._

## Git
- branch: `{branch or "unknown"}`
- last commits:
```
{log or "(none)"}
```
- working tree:
```
{status or "(clean)"}
```

## Recovery
- transcript backup: `{backup_ref}`
- If context feels thin after this compact, read the backup above before re-exploring.
"""
    (state_dir / "project-state.md").write_text(state, encoding="utf-8")

    # PreCompact cannot block; stderr is informational only.
    print(
        f"[pre_compact] snapshot written (trigger={trigger}, backup={backup_ref})",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
