#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: AGPL-3.0-only
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
distill — turn the platform's own verifier logs into training data.

STATUS (CW02 §2.4, 2026-07-28): PARKED until HB-4 / S4. This exists ahead of
its phase — the herdr-build-plan lists distill.py as unwritten; it is written,
but it must gain the collapse guards (class-weighted labels, exploration
fraction, per-tier recall + CNA tracking) before any training run consumes
its output.

The key property (docs/specs/09 §4): this platform LABELS ITSELF. No hand annotation.

  routing (R2)   the CHEAPEST TIER THAT PASSED is the correct route, by
                 construction. The fail-up guard produces perfect labels as a
                 side effect of doing its job.
  triage  (R1)   tasks that needed a clarification vs. tasks that one-shot at
                 the floor = a natural specified/underspecified split.
  adapt   (R3)   template_id x verified outcome = which template wins per
                 (lane, model class).

Emits JSONL ready for LoRA SFT (messages format) plus a report on whether there
is enough signal to bother training yet.

  distill.py --project . --role routing --out data/routing.jsonl
  distill.py --project . --report

HONEST LIMIT (docs/specs/09 §6): these labels come from your own ladder, so a model
trained on them learns YOUR ladder, not the optimal one. Keep a held-out,
human-judged slice as an anchor, and gate every adapter on the platform's
non-inferiority rule before it ships.
"""

import argparse
import importlib.util
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

MIN_PER_ROLE = 300  # below this, prompted roles beat a weak adapter


def _load_runlog():
    """The shared run reconstruction (`runlog.py`), loaded by path.

    distill.py is a single-file `uv run --script` utility rather than a package
    member, and tests load it by path too, so a plain `import runlog` would
    resolve only when sys.path happens to contain src/portage. Same idiom, and
    same reason, as measure.py::_load_runlog() and failup.py::code_profile().
    """
    path = Path(__file__).resolve().parent / "runlog.py"
    spec = importlib.util.spec_from_file_location("portage_runlog", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runlog = _load_runlog()


def state(project: str) -> Path:
    return Path(project) / ".claude" / "state"


def read_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def tasks(project: str) -> list[dict]:
    """Reconstruct per-task outcomes from the guard's attempt log.

    Reconstruction is `runlog.reconstruct` — the same one measure.py uses, so
    the two cannot drift and a fifth reader cannot reintroduce the defect by
    grouping by `run_id` for itself. Every run is returned, admissible or not,
    each carrying `admissible` and `inadmissible_reason`; deciding what to do
    with an inadmissible run belongs to each builder, because they do not all
    depend on the tier ladder (see `build_triage` and `build_adapt`).
    """
    out = []
    for r in runlog.reconstruct(read_jsonl(state(project) / "failup-log.jsonl")):
        out.append(
            {
                "run_id": r["run_id"],
                # guard logs task text if present
                "task": r["attempts"][0].get("task", ""),
                "start_tier": r["start_tier"],
                "win_tier": r["win_tier"],
                "win_model": r["win_model"],
                "attempts": len(r["attempts"]),
                "stalled": r["stalled"],
                "admissible": r["admissible"],
                "inadmissible_reason": r["inadmissible_reason"],
            }
        )
    return out


# ---------------------------------------------------------------- builders --


def build_routing(project: str) -> list[dict]:
    """Label = the cheapest tier that passed. Ground truth, for free.

    Ground truth only where the ladder actually walked. If a cheaper tier was
    never reached (rate limit, refused connection, timeout) then "the cheapest
    tier that passed" is not the cheapest tier that COULD have passed, and the
    label teaches the router to over-route to a tier it never needed. Those runs
    are skipped, and `report()` prints how many so the exclusion is never
    silent.
    """
    rows = []
    for t in tasks(project):
        if not t["admissible"]:
            continue
        if t["stalled"] or not t["task"] or t["win_model"] is None:
            continue
        rows.append(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "Route this coding task. Reply with only the target model string.",
                    },
                    {"role": "user", "content": t["task"]},
                    {"role": "assistant", "content": t["win_model"]},
                ],
                "meta": {"run_id": t["run_id"], "win_tier": t["win_tier"]},
            }
        )
    return rows


def build_triage(project: str) -> list[dict]:
    """Positive = one-shot at the floor. Negative = needed clarification."""
    clarified = {
        r.get("run_id")
        for r in read_jsonl(state(project) / "triage-log.jsonl")
        if r.get("clarify")
    }
    rows = []
    for t in tasks(project):
        if not t["task"]:
            continue
        under = t["run_id"] in clarified
        rows.append(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "Is this task specified well enough to dispatch? Reply SPECIFIED "
                        "or UNDERSPECIFIED.",
                    },
                    {"role": "user", "content": t["task"]},
                    {
                        "role": "assistant",
                        "content": "UNDERSPECIFIED" if under else "SPECIFIED",
                    },
                ],
                "meta": {"run_id": t["run_id"]},
            }
        )
    return rows


def build_adapt(project: str) -> list[dict]:
    """Preference pairs: for a (lane, class), which template verified better."""
    log = read_jsonl(state(project) / "adapt-log.jsonl")
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # key -> tpl -> [ok, n]
    for r in log:
        key = (r.get("lane"), r.get("model_class"))
        cell = agg[key][r.get("template_id")]
        cell[1] += 1
        cell[0] += 1 if r.get("verified") else 0
    rows = []
    for key, tpls in agg.items():
        scored = sorted(
            ((ok / n, t, n) for t, (ok, n) in tpls.items() if n >= 5), reverse=True
        )
        if len(scored) >= 2:
            rows.append(
                {
                    "lane": key[0],
                    "model_class": key[1],
                    "winner": scored[0][1],
                    "winner_rate": round(scored[0][0], 3),
                    "loser": scored[-1][1],
                    "loser_rate": round(scored[-1][0], 3),
                    "n": sum(s[2] for s in scored),
                }
            )
    return rows


BUILDERS = {"routing": build_routing, "triage": build_triage, "adapt": build_adapt}


# ------------------------------------------------------------------ report --


def report(project: str) -> None:
    ts = tasks(project)
    inadmissible = sum(1 for t in ts if not t["admissible"])
    print(
        f"tasks with outcomes: {len(ts)}   stalled: {sum(t['stalled'] for t in ts)}"
        f"   inadmissible: {inadmissible}"
    )
    if inadmissible:
        print(
            f"  ! {inadmissible} run(s) had a tier below the winner that was never"
            "\n    reached (rate limit / refused connection / timeout). They are"
            "\n    excluded from the routing labels: 'the cheapest tier that passed'"
            "\n    is not ground truth when a cheaper tier was never tried. They are"
            "\n    still counted in triage, whose label comes from the clarify log"
            "\n    rather than from tiers."
        )
    missing_text = sum(1 for t in ts if not t["task"])
    if missing_text:
        print(
            f"  ! {missing_text} tasks have no task text logged — they are "
            "unusable for training. Ensure the guard logs the task string."
        )
    print(f"\n{'role':<10}{'examples':>10}{'ready?':>10}")
    print("-" * 30)
    for role, fn in BUILDERS.items():
        n = len(fn(project))
        ready = "yes" if n >= MIN_PER_ROLE else f"no (<{MIN_PER_ROLE})"
        print(f"{role:<10}{n:>10}{ready:>10}")

    # Admissible only, because this is billed as "the routing label
    # distribution" and build_routing now emits labels for admissible runs only.
    # A distribution that disagreed with the labels it claims to describe would
    # be a new version of the defect this line is being fixed for.
    dist = Counter(t["win_tier"] for t in ts if not t["stalled"] and t["admissible"])
    if dist:
        print(
            "\nwin-tier distribution (the routing label distribution,"
            " admissible runs only):"
        )
        for tier, c in sorted(dist.items()):
            print(f"  tier {tier}: {c}")
        if len(dist) == 1:
            print(
                "  ! only one tier ever wins — a router trained on this learns"
                "\n    a constant. Vary the workload before training."
            )

    print(
        "\nUntil a role reads 'yes', prompted roles outperform a weak adapter."
        "\nGate any adapter on non-inferiority vs. the prompted baseline."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--role", choices=list(BUILDERS))
    ap.add_argument("--out")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    if a.report or not a.role:
        report(a.project)
        return
    rows = BUILDERS[a.role](a.project)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"[distill] wrote {len(rows)} examples -> {a.out}")
    else:
        for r in rows:
            print(json.dumps(r))


if __name__ == "__main__":
    main()
