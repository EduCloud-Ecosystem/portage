#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
herdr-meters — cross-vendor meter awareness for Herdr.

Herdr is already the interface: real PTYs per agent, semantic blocked/working/done,
persistence, remote attach, and integrations for Claude Code, Codex, OpenCode and
friends. It also surfaces Claude's 5h/Week bars on a Claude pane.

What it does NOT do is reason ACROSS vendors: which of your meters has headroom
right now, and where should this task go. That's all this plugin adds.

  board      one table: every meter, its pane, its state
  picker     popup: pick a meter, jump to (or create) its pane
  dispatch   send a task to the best AVAILABLE meter, not a fixed one
  mark       flag a meter as rate-limited (starts a cooldown)
  research   open the Perplexity Pro lane (app-only; cannot be a pane)

Everything talks to Herdr through $HERDR_BIN_PATH, which keeps it portable across
Unix sockets and Windows pipes. State lives in $HERDR_PLUGIN_STATE_DIR, config in
$HERDR_PLUGIN_CONFIG_DIR — per the plugin contract.

HONEST LIMIT: no vendor exposes remaining quota via API. Availability here is
OBSERVATIONAL — parsed from pane output and from what you mark by hand. It is a
good-enough signal for "stop typing into the exhausted lane," not an accounting
system.
"""

import json
import os
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
STATE = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR", ".")) / "meters-state.json"
CONFIG = Path(os.environ.get("HERDR_PLUGIN_CONFIG_DIR", ".")) / "meters.json"
COOLDOWN_S = 3 * 3600  # assume ~a window; you can re-mark sooner

# Shipped defaults; copy to $HERDR_PLUGIN_CONFIG_DIR/meters.json to customize.
DEFAULT_METERS = [
    {
        "name": "local",
        "kind": "pane",
        "cmd": "ollama run qwen2.5-coder:32b",
        "cost": "free",
        "classes": ["bulk", "private", "offline"],
        "priority": 1,
    },
    {
        "name": "codex",
        "kind": "pane",
        "cmd": "codex",
        "cost": "subscription",
        "classes": ["code", "quick"],
        "priority": 2,
    },
    {
        "name": "claude",
        "kind": "pane",
        "cmd": "claude",
        "cost": "subscription",
        "classes": ["code", "deep", "judgment"],
        "priority": 3,
        "scarce": True,
    },
    {
        "name": "perplexity",
        "kind": "app",
        "url": "https://www.perplexity.ai/search?q={q}",
        "cost": "subscription",
        "classes": ["research"],
        "priority": 1,
    },
]

# Substrings that suggest a lane is spent. Cheap, and deliberately conservative.
EXHAUSTED_HINTS = (
    "rate limit",
    "usage limit",
    "limit reached",
    "try again at",
    "resets at",
    "out of credit",
    "quota exceeded",
    "429",
)


# ---------- herdr plumbing ----------


def herdr(*args, check=False):
    return subprocess.run([HERDR, *args], capture_output=True, text=True, check=check)


def panes() -> list[dict]:
    """Best-effort pane inventory. Herdr's CLI shape varies by version, so we
    try JSON first and degrade to an empty list rather than guessing."""
    for args in (("pane", "list", "--json"), ("pane", "list")):
        r = herdr(*args)
        if r.returncode == 0 and r.stdout.strip():
            try:
                data = json.loads(r.stdout)
                return data if isinstance(data, list) else data.get("panes", [])
            except json.JSONDecodeError:
                return []
    return []


def pane_text(pane_id: str) -> str:
    r = herdr("pane", "read", pane_id, "--source", "recent-unwrapped")
    return r.stdout if r.returncode == 0 else ""


def find_pane(meter: dict, inv: list[dict]) -> str | None:
    """Match a meter to a live pane by the command running in it."""
    needle = meter.get("cmd", "").split()[0] if meter.get("cmd") else None
    if not needle:
        return None
    for p in inv:
        blob = json.dumps(p).lower()
        if needle in blob:
            return str(p.get("id") or p.get("pane_id") or "")
    return None


# ---------- state ----------


def meters() -> list[dict]:
    if CONFIG.is_file():
        try:
            return json.loads(CONFIG.read_text())["meters"]
        except Exception:
            pass
    return DEFAULT_METERS


def state() -> dict:
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def cooling(name: str, s: dict) -> int:
    left = int(s.get(name, {}).get("cooldown_until", 0) - time.time())
    return max(0, left)


def survey() -> list[dict]:
    """Meter + pane + availability, merged."""
    inv, s, out = panes(), state(), []
    for m in meters():
        row = dict(m)
        row["pane"] = find_pane(m, inv) if m["kind"] == "pane" else None
        row["cooldown"] = cooling(m["name"], s)
        auto = False
        if row["pane"]:
            tail = pane_text(row["pane"]).lower()[-4000:]
            auto = any(h in tail for h in EXHAUSTED_HINTS)
        row["looks_spent"] = auto
        row["available"] = (
            row["cooldown"] == 0
            and not auto
            and (row["pane"] is not None or m["kind"] == "app")
        )
        out.append(row)
    return out


# ---------- commands ----------


def board(_=None):
    rows = survey()
    print(f"{'meter':<12}{'cost':<14}{'pane':<8}{'state':<22}classes")
    print("-" * 78)
    for r in rows:
        if r["cooldown"]:
            st = f"cooling {r['cooldown'] // 60}m"
        elif r["looks_spent"]:
            st = "looks rate-limited"
        elif r["kind"] == "app":
            st = "app (no pane)"
        elif not r["pane"]:
            st = "no pane yet"
        else:
            st = "available"
        star = "*" if r.get("scarce") else " "
        print(
            f"{star}{r['name']:<11}{r['cost']:<14}{str(r['pane'] or '-'):<8}"
            f"{st:<22}{','.join(r['classes'])}"
        )
    print(
        "\n* scarce — spend deliberately."
        "\nAvailability is observational (pane output + your marks), not an API."
    )


def picker(_=None):
    rows = survey()
    board()
    print("\npick a meter to focus (enter = cancel):")
    for i, r in enumerate(rows, 1):
        flag = "" if r["available"] else "   [unavailable]"
        print(f"  {i}. {r['name']}{flag}")
    try:
        choice = input("> ").strip()
    except EOFError:
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(rows)):
        return
    r = rows[int(choice) - 1]
    if r["kind"] == "app":
        research()
        return
    if r["pane"]:
        herdr("pane", "focus", r["pane"])
    else:
        herdr("pane", "run", "1-1", r["cmd"])
        print(f"[meters] started {r['name']}")


def best_for(cls: str) -> dict | None:
    cands = [
        r
        for r in survey()
        if cls in r["classes"] and r["available"] and r["kind"] == "pane"
    ]
    # free before metered; scarce last
    cands.sort(
        key=lambda r: (
            0 if r["cost"] == "free" else 1,
            1 if r.get("scarce") else 0,
            r["priority"],
        )
    )
    return cands[0] if cands else None


def classify_task(task: str) -> dict | None:
    """Free local triage + routing. Advisory: the guard is still the real check."""
    root = Path(os.environ.get("HERDR_PLUGIN_ROOT", Path(__file__).parent))
    try:
        r = subprocess.run(
            [sys.executable, str(root / "classify.py"), task],
            capture_output=True,
            text=True,
            timeout=90,
        )
        return json.loads(r.stdout)
    except Exception:
        return None


def dispatch(_=None):
    ctx = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    task = (ctx.get("selected_text") or "").strip()
    if not task:
        print("Task (from selection, or type it):")
        try:
            task = input("> ").strip()
        except EOFError:
            return
    if not task:
        return

    d = classify_task(task)
    if not d:
        print("[meters] classifier unavailable — falling back to the picker.")
        picker()
        return

    # 1. TRIAGE — stop before spending a real turn on an unanswerable task.
    if d.get("clarify"):
        print(f"[meters] {d['clarify']}")
        try:
            more = input("add detail (enter = send anyway): ").strip()
        except EOFError:
            more = ""
        if more:
            task = f"{task} — {more}"
            d = classify_task(task) or d

    # 2. ROUTE — show the decision; never route silently.
    scarce = "  ** SCARCE" if d.get("scarce") else ""
    effort = f" effort={d['effort']}" if d.get("effort") else ""
    print(
        f"[meters] {d['provider']}/{d['model']}{effort}{scarce}\n"
        f"         {d['why']}  (conf {d['confidence']}, via {d['source']})"
    )

    if d["provider"] == "perplexity":
        research_query(d["shaped"])
        return

    rows = survey()
    target = next((r for r in rows if r["name"] == d["provider"]), None)
    if not target or not target["available"]:
        alt = best_for("code")
        if not alt:
            print("[meters] target unavailable and no fallback has headroom.")
            return
        print(f"[meters] {d['provider']} unavailable -> {alt['name']}")
        target = alt

    if d.get("scarce") or d.get("pinned"):
        try:
            if input("send? [Y/n] ").strip().lower() in ("n", "no"):
                return
        except EOFError:
            pass

    log_use(target["name"], "dispatch", d["shaped"])
    herdr("pane", "run", target["pane"], d["shaped"])
    print(f"[meters] sent to {target['name']} (pane {target['pane']})")


def mark(_=None):
    pane = os.environ.get("HERDR_PANE_ID", "")
    rows = survey()
    hit = next((r for r in rows if r["pane"] and r["pane"] == pane), None)
    if not hit:
        print("[meters] focused pane isn't a known meter; nothing marked.")
        return
    s = state()
    s.setdefault(hit["name"], {})["cooldown_until"] = time.time() + COOLDOWN_S
    save_state(s)
    print(
        f"[meters] {hit['name']} marked rate-limited for {COOLDOWN_S // 3600}h. "
        "Dispatch will route around it."
    )


def log_use(meter: str, kind: str, task: str = "") -> None:
    """Record that a lane was used. Without this, `measure.py downscale` only
    sees automated (Lane B) traffic and will undercount every lane you drive by
    hand — which is exactly how you'd talk yourself into cutting a lane you
    actually depend on."""
    p = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR", ".")) / "use-log.jsonl"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "meter": meter,
                        "kind": kind,
                        "chars": len(task),
                    }
                )
                + "\n"
            )
    except Exception:
        pass  # logging must never break dispatch


def loguse(_=None):
    """Manual entry for lanes with no CLI (app-only work done in a browser)."""
    try:
        meter = input("which lane did you use? (perplexity/claude/codex/local): ").strip()
    except EOFError:
        return
    if meter:
        log_use(meter, "manual")
        print(f"[meters] logged manual use of {meter}")


def research_query(q: str):
    m = next(x for x in meters() if x["name"] == "perplexity")
    log_use("perplexity", "research", q)
    webbrowser.open(m["url"].format(q=urllib.parse.quote(q)))
    print(
        "[meters] opened Perplexity. Switch to Deep Research — it's the "
        "Opus-powered path and costs no Claude quota."
    )


def research(_=None):
    ctx = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    q = (ctx.get("selected_text") or "").strip()
    if not q:
        try:
            q = input("Research query: ").strip()
        except EOFError:
            return
    research_query(q)


CMDS = {
    "board": board,
    "picker": picker,
    "dispatch": dispatch,
    "mark": mark,
    "research": research,
    "loguse": loguse,
}

if __name__ == "__main__":
    CMDS.get(sys.argv[1] if len(sys.argv) > 1 else "board", board)()
