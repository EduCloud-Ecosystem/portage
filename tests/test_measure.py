"""HB-2: per-class failure priors and per-tier recall in measure.py::summarize().

No test_measure.py existed before HB-2 — these cover only the new fields;
they don't re-test win_tier_distribution/floor_pass_rate/etc., which have no
dedicated tests either but are exercised indirectly by every prior consumer
of failup-log.jsonl. Writing log entries by hand (not through failup.py)
keeps this file independent of the guard's own tests.
"""

import json


def _write_log(project, entries):
    d = project / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "failup-log.jsonl").open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _attempt(
    run_id,
    tier,
    model,
    ok,
    reason,
    category,
    attempt_in_tier=0,
    cost_usd=None,
    tokens_in=None,
    tokens_out=None,
    cache_read_tokens=None,
):
    return {
        "ts": "2026-08-06T00:00:00+00:00",
        "run_id": run_id,
        "task": "t",
        "tier": tier,
        "model": model,
        "effort": None,
        "attempt_in_tier": attempt_in_tier,
        "ok": ok,
        "reason": reason,
        "reason_code": None,
        "category": category,
        "seconds": 0.1,
        "cost_usd": cost_usd,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_read_tokens": cache_read_tokens,
    }


def test_per_class_failures_counts_failed_attempts_by_class(measure, tmp_path):
    project = tmp_path
    _write_log(
        project,
        [
            _attempt("r1", 0, "m0", False, "lint-failed", "capability"),
            _attempt(
                "r1", 0, "m0", False, "lint-failed", "capability", attempt_in_tier=1
            ),
            _attempt("r1", 1, "m1", True, "ok", "ok"),
            _attempt("r2", 0, "m0", False, "tests-failed", "capability"),
            _attempt("r2", 1, "m1", True, "ok", "ok"),
        ],
    )

    s = measure.summarize(str(project), None, None)

    assert s["per_class_failures"] == {"lint-failed": 2, "tests-failed": 1}


def test_per_class_failures_excludes_availability(measure, tmp_path):
    project = tmp_path
    _write_log(
        project,
        [
            _attempt("r1", 0, "m0", False, "unavailable:503", "availability"),
            _attempt("r1", 0, "m0", True, "ok", "ok"),
        ],
    )

    s = measure.summarize(str(project), None, None)

    # The tier-0 attempt that never reached the verifier contributes no class.
    assert s["per_class_failures"] == {}


def test_per_tier_recall_is_pass_share_of_attempts_that_reached_the_tier(
    measure, tmp_path
):
    project = tmp_path
    _write_log(
        project,
        [
            _attempt("r1", 0, "m0", False, "lint-failed", "capability"),
            _attempt("r1", 1, "m1", True, "ok", "ok"),
            _attempt("r2", 0, "m0", True, "ok", "ok"),
            _attempt("r3", 0, "m0", False, "lint-failed", "capability"),
            _attempt("r3", 1, "m1", True, "ok", "ok"),
        ],
    )

    s = measure.summarize(str(project), None, None)

    # tier 0: 3 attempts reached it (r1, r2, r3), 1 passed (r2) -> 33.3%
    # tier 1: 2 attempts reached it (r1, r3), 2 passed -> 100%
    assert s["per_tier_recall"] == {0: 33.3, 1: 100.0}


# ------------------------------------------------- HB-2b: three-price / CNA --


def test_runner_reported_cost_sums_by_tier(measure, tmp_path):
    project = tmp_path
    _write_log(
        project,
        [
            _attempt(
                "r1", 0, "sonnet", False, "lint-failed", "capability", cost_usd=0.01
            ),
            _attempt("r1", 1, "opus", True, "ok", "ok", cost_usd=0.05),
            _attempt("r2", 0, "sonnet", True, "ok", "ok", cost_usd=0.02),
        ],
    )

    s = measure.summarize(str(project), None, None)

    assert s["cost_by_tier_usd"] == {0: 0.03, 1: 0.05}


def test_success_per_dollar_is_recall_over_cost_per_tier(measure, tmp_path):
    project = tmp_path
    _write_log(
        project,
        [
            # tier 0: 2 attempts, 1 passed -> recall 50%, cost 0.10 -> 0.5/0.10=5.0
            _attempt(
                "r1", 0, "sonnet", False, "lint-failed", "capability", cost_usd=0.05
            ),
            _attempt("r2", 0, "sonnet", True, "ok", "ok", cost_usd=0.05),
        ],
    )

    s = measure.summarize(str(project), None, None)

    assert s["success_per_dollar_by_tier"] == {0: 5.0}


def test_cna_is_solved_at_start_tier_over_solvable_at_all(measure, tmp_path):
    # HB-0 rev 3: real Ceiling-Normalized Accuracy from the Herdr reference —
    # (share routed to a tier that it solves) / (share solvable by ANY tier).
    project = tmp_path
    _write_log(
        project,
        [
            # r1: routed to tier 0, tier 0 solves it directly.
            _attempt("r1", 0, "m0", True, "ok", "ok"),
            # r2: routed to tier 0, tier 0 fails, escalates, tier 1 solves it —
            # solvable, but NOT solved by the tier it was routed to.
            _attempt("r2", 0, "m0", False, "lint-failed", "capability"),
            _attempt("r2", 1, "m1", True, "ok", "ok"),
            # r3: routed to tier 0, never solved by anyone — stalled, excluded
            # from both numerator and denominator (not "solvable at all").
            _attempt("r3", 0, "m0", False, "lint-failed", "capability"),
            _attempt("r3", 1, "m1", False, "lint-failed", "capability"),
        ],
    )

    s = measure.summarize(str(project), None, None)

    # tier 0 was routed to for r1/r2/r3; r3 is stalled (excluded); of the
    # remaining 2 solvable, only r1 was solved BY tier 0 itself -> 1/2.
    assert s["cna_by_tier"] == {0: 0.5}


def test_cna_grouped_by_start_tier_not_every_tier_touched(measure, tmp_path):
    # A run that starts above the floor (--start-tier) groups under ITS
    # start tier for CNA, distinct from per_tier_recall's tier_seen grouping.
    project = tmp_path
    _write_log(
        project,
        [
            _attempt("r1", 1, "m1", True, "ok", "ok"),  # started AT tier 1, solved there
        ],
    )

    s = measure.summarize(str(project), None, None)

    assert s["cna_by_tier"] == {1: 1.0}
    assert 0 not in s["cna_by_tier"]


def test_unpriceable_rung_counted_not_dropped(measure, tmp_path):
    project = tmp_path
    _write_log(
        project,
        [
            _attempt("r1", 0, "some-future-rung", True, "ok", "ok"),  # no cost_usd,
            # not a mapped rung
        ],
    )

    s = measure.summarize(str(project), None, None)

    assert s["cost_by_tier_usd"] == {}
    assert s["cost_unknown_by_basis"] == {"unmapped-rung": 1}
    # the run itself is still counted normally elsewhere — not dropped
    assert s["tasks"] == 1
    assert s["floor_pass_rate"] == 100.0
