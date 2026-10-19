#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
One reconstruction of the fail-up guard's attempt log, shared by every consumer.

`failup.py` writes one record per ATTEMPT. Every consumer wants RUNS: the
escalation attempts for a single task, grouped by `run_id`, ordered by tier,
with "which tier won" derived from them. Before this module, `measure.py`'s
`summarize()`, `measure.py`'s `tasks_in()` and `distill.py`'s `tasks()` each did
that grouping independently — three copies of one reconstruction — and all three
carried the same defect, which is how it survived: the guard records whether an
attempt failed because the tier LACKED THE CAPABILITY or because the tier WAS
NEVER REACHED (`category: "availability"`, rate limits / refused connections /
timeouts, detected before the verifier runs), and not one consumer read the
field. An unreachable tier 0 read as a tier 0 that tried and failed.

That inflated `escalation_rate`, deflated `floor_pass_rate`, shifted
`win_tier_distribution` upward, produced false `proven` verdicts in the
downscale counterfactual that gates cancelling paid lanes, and taught the router
to over-route. Note the direction of the bias: it makes the cheap local tiers
look LESS capable than they are, which is the opposite of what this project
claims. It does not flatter the result; it damages it.

WHY FILTERING THE RECORDS IS NOT THE FIX. Dropping the availability attempts
before reconstructing removes the false escalation and the false `proven`. It
also makes the run indistinguishable from a task that genuinely started at the
higher tier — so it still lands in `win_tier_distribution` as a task that needed
that tier, and still becomes a routing label pointing at a tier whose cheaper
alternative was never tested. That trades a visible bias for a quiet one of the
same sign. Admissibility is a judgement about the RUN, not a filter on records,
which is why the availability attempts stay in `attempts` below: they are real
events and every report needs to be able to count them.
"""

# `failup.py` writes exactly these three. "ok" and "capability" are verdicts a
# verifier reached about the tier; "availability" means no verifier ever ran.
CAT_OK = "ok"
CAT_CAPABILITY = "capability"
CAT_AVAILABILITY = "availability"


def attempt_category(attempt: dict) -> str:
    """The attempt's category, tolerating a record written before the field.

    Records predating the `category` field carry only `ok`. Defaulting those to
    a capability verdict preserves exactly what such a record used to mean, so
    reading an old log through this module changes no number. Defaulting the
    other way would silently declare all history inadmissible — a much louder
    lie than the one being fixed.
    """
    cat = attempt.get("category")
    if cat:
        return cat
    return CAT_OK if attempt.get("ok") else CAT_CAPABILITY


def reconstruct(attempts: list[dict]) -> list[dict]:
    """Group attempts into runs and mark each admissible or not.

    A run is admissible capability evidence only when every tier below its
    winning tier produced a capability verdict. A tier that was never reached
    (category == "availability") proves nothing about that tier.

    Stated the other way round, and this is the whole rule:

      * An availability failure BELOW the winning tier makes the run
        inadmissible. The run cannot say whether a cheaper tier could have done
        the task, because a cheaper tier was never tested — so it must not
        contribute to any capability statistic or training label.
      * An availability failure AT OR ABOVE the winning tier leaves the run
        admissible. Every cheaper tier was tested; the unreachable one is above
        the answer and changes nothing about it.
      * A STALLED run (nothing passed) with any availability failure at all is
        inadmissible. With no winner, every attempted tier is "below" it, and a
        stall attributed to capability when a tier was never reached is the same
        misfiling in the quality guardrail rather than the efficiency numbers.

    Each returned run is a dict with:

      run_id              the grouping key (the attempt's `ts` if absent)
      attempts            every attempt, availability ones included, tier-ordered
      start_tier          the lowest tier actually attempted
      win_tier            the lowest tier that passed, or None
      win_model           the model at `win_tier`, or None
      stalled             True when nothing passed
      admissible          the rule above
      inadmissible_reason None, or "availability_below_winner:<tiers>" /
                          "availability_in_stalled_run:<tiers>"

    ONE THING THIS RULE DELIBERATELY DOES NOT DO. A run started above the floor
    (`--start-tier 2`) has untried tiers below its winner too, and by a strict
    reading of "every tier below the winner produced a capability verdict" it
    would be inadmissible as well. It is not treated so here: `start_tier` is
    already carried on every run, and the two existing consumers of that fact
    (`proven` in measure.py, which requires `start_tier < win_tier`, and the
    escalation count, which compares the winner against the lowest tier
    attempted) already decline to claim anything about tiers that were never
    entered. Availability is the case where the ladder BELIEVED it tested a tier
    and did not; a deliberate `--start-tier` is a caller saying it never
    intended to. Conflating them would silently reclassify every budget-capped
    run, which is a separate decision and not this one.
    """
    by_run: dict = {}
    for a in attempts:
        by_run.setdefault(a.get("run_id", a["ts"]), []).append(a)

    runs = []
    for run_id, run in by_run.items():
        run = sorted(run, key=lambda a: a["tier"])
        passed = [a for a in run if a["ok"]]
        win_tier = min((a["tier"] for a in passed), default=None)

        if win_tier is None:
            unreached = [
                a["tier"] for a in run if attempt_category(a) == CAT_AVAILABILITY
            ]
            marker = "availability_in_stalled_run"
        else:
            unreached = [
                a["tier"]
                for a in run
                if a["tier"] < win_tier and attempt_category(a) == CAT_AVAILABILITY
            ]
            marker = "availability_below_winner"

        runs.append(
            {
                "run_id": run_id,
                "attempts": run,
                "start_tier": run[0]["tier"],
                "win_tier": win_tier,
                "win_model": next(
                    (a["model"] for a in run if a["tier"] == win_tier), None
                ),
                "stalled": win_tier is None,
                "admissible": not unreached,
                "inadmissible_reason": (
                    None
                    if not unreached
                    else f"{marker}:{','.join(str(t) for t in sorted(unreached))}"
                ),
            }
        )
    return runs


def partition(runs: list[dict]) -> tuple[list[dict], int]:
    """Split reconstructed runs into (admissible, count-excluded).

    A convenience so that no caller can take the admissible half without also
    holding the number it dropped. NO SILENT EXCLUSION: every surface that
    excludes a run has to say how many it excluded, because a capability
    statistic computed over a filtered population without saying so is a worse
    defect than the one this module exists to fix.
    """
    admissible = [r for r in runs if r["admissible"]]
    return admissible, len(runs) - len(admissible)
