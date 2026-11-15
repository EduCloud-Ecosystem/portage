"""CC-P4: an unreachable tier is not evidence that the tier could not do the task.

Fixtures only — every log record here is written by hand. Zero network, zero
model calls, and no subprocess at all except in the one case that has to
exercise the guard itself (`test_log_record_carries_both_reason_and_reason_code`,
which uses the same stub runner the rest of the suite does).

The rule under test, stated once: a run is admissible capability evidence only
if every tier BELOW its winning tier produced a capability verdict. The tempting
fix — dropping `category == "availability"` records before reconstructing — is
what cases 1 and 3 exist to rule out: it would make case 1's run look like a task
that genuinely started at tier 1, which is the same bias with the volume turned
down.
"""

import json

from conftest import CHECK_MARKER, NOOP_LINT, STUB_RUNNER

# --------------------------------------------------------------- fixtures ----

TS = "2026-08-04T12:00:0{}+00:00"


def attempt(run_id, tier, category, model=None, task="write the thing", n=0):
    """One record in the shape `failup.py` writes."""
    ok = category == "ok"
    return {
        "ts": TS.format(n),
        "run_id": run_id,
        "task": task,
        "tier": tier,
        "model": model or f"m{tier}",
        "effort": None,
        "ok": ok,
        "reason": {
            "ok": "ok",
            "capability": "tests-failed",
            "availability": "unavailable:429",
        }[category],
        "reason_code": None if category != "capability" else "code.tests_failed",
        "category": category,
        "seconds": 1.0,
    }


def write_log(project, attempts):
    d = project / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "failup-log.jsonl").write_text("".join(json.dumps(a) + "\n" for a in attempts))
    return project


def summarize_all(measure, project):
    return measure.summarize(str(project), None, None)


# ------------------------------------------- case 1: availability below win --

CASE1 = [attempt("r1", 0, "availability", n=0), attempt("r1", 1, "ok", n=1)]


def test_availability_below_winner_makes_the_run_inadmissible(runlog):
    (run,) = runlog.reconstruct(CASE1)
    assert run["admissible"] is False
    assert run["inadmissible_reason"] == "availability_below_winner:0"
    assert run["win_tier"] == 1
    # The availability attempt is KEPT. Admissibility is a judgement about the
    # run, not a reason to discard the records it is made of.
    assert [a["tier"] for a in run["attempts"]] == [0, 1]


def test_case1_not_proven_and_escalation_rate_unaffected(measure, tmp_path):
    write_log(tmp_path, CASE1)
    rows, excluded = measure.tasks_in(str(tmp_path), None, None)
    assert rows == []  # the only run was excluded
    assert excluded == 1

    s = summarize_all(measure, tmp_path)
    assert s["tasks"] == 1
    assert s["admissible_tasks"] == 0
    assert s["inadmissible_runs"] == 1
    assert s["inadmissible_rate"] == 100.0
    # No admissible run, so no capability claim in either direction. Before the
    # fix this window reported escalation_rate 100% and floor_pass_rate 0%.
    assert s["escalation_rate"] is None
    assert s["floor_pass_rate"] is None
    assert s["win_tier_distribution"] == {}


def test_case1_emits_no_routing_label(distill, tmp_path):
    write_log(tmp_path, CASE1)
    assert distill.build_routing(str(tmp_path)) == []
    # ...and the run is still visible as a task, with the reason recorded.
    (t,) = distill.tasks(str(tmp_path))
    assert t["admissible"] is False
    assert t["inadmissible_reason"] == "availability_below_winner:0"


# ------------------------- case 2: capability failure below win (REGRESSION) --

CASE2 = [attempt("r2", 0, "capability", n=0), attempt("r2", 1, "ok", n=1)]


def test_capability_failure_below_winner_stays_admissible(runlog):
    """The regression guard: the fix must not discard escalations wholesale."""
    (run,) = runlog.reconstruct(CASE2)
    assert run["admissible"] is True
    assert run["inadmissible_reason"] is None
    assert run["win_tier"] == 1


def test_case2_is_proven_and_counts_as_an_escalation(measure, tmp_path):
    write_log(tmp_path, CASE2)
    rows, excluded = measure.tasks_in(str(tmp_path), None, None)
    assert excluded == 0
    assert len(rows) == 1
    assert rows[0]["proven"] is True  # tier 0 really was tried and failed
    assert rows[0]["win_tier"] == 1

    s = summarize_all(measure, tmp_path)
    assert s["admissible_tasks"] == 1
    assert s["inadmissible_runs"] == 0
    assert s["escalation_rate"] == 100.0
    assert s["floor_pass_rate"] == 0.0
    assert s["win_tier_distribution"] == {1: 1}


def test_case2_routing_label_points_at_tier_1(distill, tmp_path):
    write_log(tmp_path, CASE2)
    (row,) = distill.build_routing(str(tmp_path))
    assert row["meta"]["win_tier"] == 1
    assert row["messages"][-1]["content"] == "m1"


# ------------------------------------------- case 3: availability above win --

CASE3 = [attempt("r3", 0, "ok", n=0), attempt("r3", 1, "availability", n=1)]


def test_availability_at_or_above_the_winner_is_still_admissible(runlog):
    (run,) = runlog.reconstruct(CASE3)
    assert run["admissible"] is True
    assert run["inadmissible_reason"] is None
    assert run["win_tier"] == 0


def test_case3_statistics_are_untouched(measure, distill, tmp_path):
    write_log(tmp_path, CASE3)
    s = summarize_all(measure, tmp_path)
    assert s["admissible_tasks"] == 1
    assert s["inadmissible_runs"] == 0
    assert s["floor_pass_rate"] == 100.0
    assert s["escalation_rate"] == 0.0
    assert s["win_tier_distribution"] == {0: 1}

    rows, excluded = measure.tasks_in(str(tmp_path), None, None)
    assert excluded == 0
    assert rows[0]["proven"] is False  # nothing cheaper than tier 0 exists
    (row,) = distill.build_routing(str(tmp_path))
    assert row["meta"]["win_tier"] == 0


# --------------------------------------------- case 4: every tier unreached --

CASE4 = [
    attempt("r4", 0, "availability", n=0),
    attempt("r4", 1, "availability", n=1),
    attempt("r4", 2, "availability", n=2),
]


def test_all_availability_run_is_both_stalled_and_inadmissible(runlog):
    (run,) = runlog.reconstruct(CASE4)
    assert run["stalled"] is True
    assert run["admissible"] is False
    assert run["inadmissible_reason"] == "availability_in_stalled_run:0,1,2"


def test_case4_stalled_and_inadmissible_are_reported_as_distinct_numbers(
    measure, distill, tmp_path, capsys
):
    write_log(tmp_path, CASE4)
    s = summarize_all(measure, tmp_path)
    # Distinct, not collapsed: the run stalled AND was inadmissible, and the
    # ceiling-stall RATE (the quality guardrail, admissible runs only) must not
    # be charged with a stall caused by the gateway being down.
    assert s["tasks"] == 1
    assert s["stalled"] == 1
    assert s["inadmissible_runs"] == 1
    assert s["admissible_tasks"] == 0
    assert s["ceiling_stall_rate"] is None

    distill.report(str(tmp_path))
    out = capsys.readouterr().out
    assert "stalled: 1" in out
    assert "inadmissible: 1" in out


# ------------------------------------------------ case 5: mixed population ---

# Five runs, hand-computed below. Two inadmissible, three admissible.
CASE5 = [
    # a: tier 0 availability -> tier 1 pass          INADMISSIBLE
    attempt("a", 0, "availability", n=0),
    attempt("a", 1, "ok", n=1),
    # b: tier 0 capability   -> tier 1 pass          admissible, escalated, win 1
    attempt("b", 0, "capability", n=2),
    attempt("b", 1, "ok", n=3),
    # c: tier 0 pass                                 admissible, floor, win 0
    attempt("c", 0, "ok", n=4),
    # d: tier 0 pass, tier 1 availability (above)    admissible, floor, win 0
    attempt("d", 0, "ok", n=5),
    attempt("d", 1, "availability", n=6),
    # e: all three tiers availability                INADMISSIBLE, stalled
    attempt("e", 0, "availability", n=7),
    attempt("e", 1, "availability", n=8),
    attempt("e", 2, "availability", n=9),
]


def test_mixed_population_matches_hand_computed_values(measure, tmp_path):
    write_log(tmp_path, CASE5)
    s = summarize_all(measure, tmp_path)

    assert s["tasks"] == 5
    assert s["admissible_tasks"] == 3  # b, c, d
    assert s["inadmissible_runs"] == 2  # a, e
    assert s["inadmissible_rate"] == 40.0  # 2/5 exactly
    assert s["stalled"] == 1  # e, over the whole population

    # over the three admissible runs: c and d passed at the floor, b escalated
    assert s["floor_pass_rate"] == 66.7  # 2/3
    assert s["escalation_rate"] == 33.3  # 1/3
    assert s["ceiling_stall_rate"] == 0.0  # e is not admissible evidence
    assert s["win_tier_distribution"] == {0: 2, 1: 1}

    rows, excluded = measure.tasks_in(str(tmp_path), None, None)
    assert excluded == 2
    assert sorted(r["win_tier"] for r in rows) == [0, 0, 1]
    assert sum(r["proven"] for r in rows) == 1  # only b


def test_mixed_population_uncorrected_numbers_would_have_been_wrong(measure, tmp_path):
    """What the old reconstruction reported, so the size of the bug is pinned.

    Over all five runs with `category` ignored: a and b both look escalated
    (2/5 = 40%), c and d floor-pass (2/5 = 40%), e stalls (1/5 = 20%). The fix
    moves floor-pass 40 -> 66.7 and escalation 40 -> 33.3. The direction matters:
    the uncorrected numbers understate the cheap tiers.
    """
    write_log(tmp_path, CASE5)
    s = summarize_all(measure, tmp_path)
    assert s["floor_pass_rate"] > 40.0
    assert s["escalation_rate"] < 40.0


def test_mixed_population_routing_labels_exclude_the_inadmissible(distill, tmp_path):
    write_log(tmp_path, CASE5)
    rows = distill.build_routing(str(tmp_path))
    assert {r["meta"]["run_id"] for r in rows} == {"b", "c", "d"}


def test_mixed_population_triage_is_unaffected_by_admissibility(distill, tmp_path):
    """build_triage is deliberately untouched: its label comes from the clarify
    log, not from tiers, so an unreachable tier says nothing about it."""
    write_log(tmp_path, CASE5)
    rows = distill.build_triage(str(tmp_path))
    assert {r["meta"]["run_id"] for r in rows} == {"a", "b", "c", "d", "e"}


def test_downscale_reports_the_excluded_count(measure, tmp_path, capsys):
    write_log(tmp_path, CASE5)
    (tmp_path / ".claude" / "tiers.json").write_text(json.dumps(["local", "opus"]))

    class Args:
        project = str(tmp_path)
        since = until = tiers = use_log = None

    measure.downscale(Args())
    out = capsys.readouterr().out
    assert "automated tasks in window: 3" in out
    assert "excluded as inadmissible:  2" in out


# -------------------------------------- case 6: reason and reason_code both --


def test_log_record_carries_both_reason_and_reason_code(
    failup, git_repo, tmp_path, monkeypatch
):
    """The guard writes the legacy string AND the registry code, unchanged.

    `reason` is pinned to the exact literal `_LEGACY_REASON` produced before
    this change, because `.claude/state/failup-log.jsonl` is longitudinal and a
    reworded reason silently changes what a month-old record says.
    """
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "availability,capability,ok")
    tiers = tmp_path / "tiers.json"
    tiers.write_text(json.dumps(["r0", "r1", "r2"]))

    rc = failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )
    assert rc == 0

    p = git_repo / ".claude" / "state" / "failup-log.jsonl"
    entries = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

    assert all("reason" in e and "reason_code" in e for e in entries)

    # the availability attempt never reached a verifier, so there is no verdict
    # document and therefore no code — SPEC.md §2.1 has no availability namespace
    assert entries[0]["category"] == "availability"
    assert entries[0]["reason"].startswith("unavailable:")
    assert entries[0]["reason_code"] is None

    # the capability failure: legacy string exactly as before, plus the code
    assert entries[1]["reason"] == "tests-failed"
    assert entries[1]["reason_code"] == "code.tests_failed"
    assert failup._LEGACY_REASON["code.tests_failed"] == "tests-failed"

    # a pass carries no reason code (schema/verdict.schema.json requires one
    # only on `fail`), and the legacy reason stays the literal "ok"
    assert entries[2]["reason"] == "ok"
    assert entries[2]["reason_code"] is None


def test_every_legacy_reason_string_is_unchanged(failup):
    """Pins the whole table, not just the case the ladder happened to hit."""
    assert failup._LEGACY_REASON == {
        "code.empty_diff": "empty-diff",
        "code.lint_failed": "lint-failed",
        "code.typecheck_failed": "typecheck-failed",
        "code.tests_failed": "tests-failed",
    }


# ----------------------------------------------------------------- corners --


def test_records_without_a_category_field_read_as_capability(runlog):
    """Pre-`category` records must keep meaning exactly what they meant."""
    old = [
        {"ts": TS.format(0), "run_id": "z", "tier": 0, "model": "m0", "ok": False},
        {"ts": TS.format(1), "run_id": "z", "tier": 1, "model": "m1", "ok": True},
    ]
    (run,) = runlog.reconstruct(old)
    assert run["admissible"] is True
    assert run["win_tier"] == 1


def test_partition_hands_back_the_count_it_dropped(runlog):
    runs = runlog.reconstruct(CASE5)
    admissible, excluded = runlog.partition(runs)
    assert len(admissible) == 3
    assert excluded == 2
    assert len(runs) == len(admissible) + excluded
