#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: AGPL-3.0-only
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Decomposition driver (Lane B) — plan-first execution for large tasks.

Two phases, so an unapproved plan cannot run (the human gate is structural):

  plan.py plan --task "<large task>"     -> Opus emits a structured plan, saved.
  # you review + approve by passing the plan file to:
  plan.py run  --plan <plan.json>        -> executes each subtask under failup.py,
                                            then runs the integration check.

Opus is spent ONCE, on the plan. Stages run cheap under the fail-up guard, so a
stage harder than planned self-corrects upward. Accuracy is verified at the seams
(per-stage acceptance via the guard + the final integration check), because
nothing unit-tests a plan.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILUP = HERE / "failup.py"
PLAN_MODEL = "claude-opus-4-8"  # planning is a T2 judgment task; never downshifted

PLAN_PROMPT = """You are decomposing a large task for this repo. Explore as
needed, then output ONLY a JSON object (no prose, no code fences) with keys:
task, subtasks[], integration_check, risky_seams[]. Each subtask has:
id, goal, depends_on[], files_touched[], parallelizable (bool), acceptance_check.

CRITICAL: `acceptance_check` and `integration_check` must each be a RUNNABLE SHELL
COMMAND that exits 0 iff the work is complete — e.g.
"uv run pytest tests/test_x.py::test_y -q"
or "uv run python -c 'import mod; assert mod.f()'". Not prose. If a subtask cannot
be reduced to a runnable check, say so in its acceptance_check as the literal
string "MANUAL:" followed by why — the driver will stop and require a human.

Make each subtask independently checkable; keep stages small and ordered;
mark parallelizable true only when genuinely file-disjoint. Task:\n\n{task}"""

REQUIRED_KEYS = {"task", "subtasks", "integration_check"}


def _brace_slice(s: str):
    i, j = s.find("{"), s.rfind("}")
    return s[i : j + 1] if 0 <= i < j else None


def extract_plan(raw: str) -> dict:
    """Robust: try a clean parse, then a first-brace..last-brace slice. No greedy
    regex (which mis-slices on nested/adjacent braces). Prefer a runner
    `--output-format json` upstream if your CLI supports it."""
    for candidate in (raw, _brace_slice(raw)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no valid JSON object found in planner output")


def validate_plan(plan: dict) -> None:
    missing = REQUIRED_KEYS - plan.keys()
    if missing:
        raise ValueError(f"plan missing keys: {sorted(missing)}")
    for s in plan["subtasks"]:
        for k in ("id", "goal", "acceptance_check"):
            if k not in s:
                raise ValueError(f"subtask missing '{k}': {s.get('id', s)}")


def run(cmd, cwd=None, timeout=1800, shell=False):
    # VERIFIED (Phase 2, tests/test_plan.py): do_run calls this with shell=True
    # for acceptance_check/integration_check (they're shell command strings, not
    # argv lists). The wrapper never forwarded `shell` to subprocess.run, so
    # every such call raised TypeError — never caught because nothing had
    # exercised do_run's non-MANUAL path until these tests did.
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=shell
    )


def state_dir(project: str) -> Path:
    d = Path(project) / ".claude" / "state"
    (d / "plans").mkdir(parents=True, exist_ok=True)
    return d


def do_plan(task: str, project: str) -> None:
    # Native `claude -p`, not a gateway: Phase 1 verified Claude Code accepts a
    # bare model name/alias directly (docs/phase-1-findings.md). claude-code-router
    # is gone. This draws the interactive Max wallet, same as `failup.py`'s
    # default runner — planning and execution share one meter unless overridden.
    proc = run(
        ["claude", "-p", PLAN_PROMPT.format(task=task), "--model", PLAN_MODEL],
        cwd=project,
    )
    raw = proc.stdout.strip()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        plan = extract_plan(raw)
        validate_plan(plan)
    except ValueError as err:
        dump = state_dir(project) / "plans" / f"{stamp}.raw.txt"
        dump.write_text(raw, encoding="utf-8")
        print(
            f"[plan] {err}. Raw planner output saved to {dump.relative_to(project)}",
            file=sys.stderr,
        )
        sys.exit(1)
    out = state_dir(project) / "plans" / f"{stamp}.json"
    out.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"[plan] saved {out.relative_to(project)}\n")
    print(json.dumps(plan, indent=2))
    print(
        "\n[plan] REVIEW this plan. To execute an approved plan:\n"
        f"    src/portage/plan.py run --plan {out.relative_to(project)}"
    )


def toposort(subtasks: list[dict]) -> list[dict]:
    done, order = set(), []
    while len(order) < len(subtasks):
        progressed = False
        for s in subtasks:
            if s["id"] in done:
                continue
            if all(d in done for d in s.get("depends_on", [])):
                order.append(s)
                done.add(s["id"])
                progressed = True
        if not progressed:
            raise SystemExit("[run] dependency cycle or missing id in plan")
    return order


def do_run(plan_path: str, project: str) -> None:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    log = state_dir(project) / "decomp-log.jsonl"

    for st in toposort(plan["subtasks"]):
        goal = st["goal"]
        check = st["acceptance_check"]
        print(f"[run] subtask {st['id']}: {goal}")

        if check.strip().startswith("MANUAL:"):
            print(
                f"[run] subtask {st['id']} has no runnable check ({check}). "
                "Stopping for a human — the driver will not auto-pass an "
                "unverifiable stage.",
                file=sys.stderr,
            )
            sys.exit(3)

        t0 = time.time()
        # Stage runs under the generic guard (agent changed something + coherent +
        # repo tests). Sequential by default; parallel only for file-disjoint
        # `parallelizable` stages (batch runner + Herdr `wait` — kept sequential).
        guard_ok = (
            run(
                ["uv", "run", str(FAILUP), "--task", goal, "--project", project],
                cwd=project,
                timeout=3600,
            ).returncode
            == 0
        )

        # THE per-subtask acceptance gate — deterministic, outside the model. The
        # planner proposed this command; you vetted it at the approval gate; a
        # runner (not the model's self-report) decides pass/fail.
        accept_ok = guard_ok and run(check, cwd=project, shell=True).returncode == 0

        with log.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(),
                        "id": st["id"],
                        "guard_ok": guard_ok,
                        "accept_ok": accept_ok,
                        "seconds": round(time.time() - t0, 1),
                    }
                )
                + "\n"
            )

        if not accept_ok:
            why = "failed its acceptance_check" if guard_ok else "failed the guard"
            print(
                f"[run] subtask {st['id']} {why}. Stopping; inspect before "
                "continuing.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Seam verification — the plan's own integration_check, not a hardcoded suite.
    print("[run] all stages passed their acceptance checks. Running integration check.")
    if run(plan["integration_check"], cwd=project, shell=True).returncode != 0:
        print(
            "[run] INTEGRATION CHECK FAILED. Stages passed individually but "
            "disagree at a seam. Identify the implicated stage and re-run it, "
            "or re-plan (which re-enters the human gate).",
            file=sys.stderr,
        )
        sys.exit(2)
    print("[run] integration check green. Large task complete.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--task", required=True)
    r = sub.add_parser("run")
    r.add_argument("--plan", required=True)
    ap.add_argument("--project", default=os.getcwd())
    args = ap.parse_args()
    if args.cmd == "plan":
        do_plan(args.task, args.project)
    else:
        do_run(args.plan, args.project)


if __name__ == "__main__":
    main()
