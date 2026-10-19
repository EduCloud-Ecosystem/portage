"""Phase 2: harden failup.py with a stub runner. Zero network, zero model calls.

Covers HANDOFF Phase 2 acceptance: the ladder walks tiers in order; --max-tier
stops below the ceiling with the correct message; stash/reset recovery
restores a clean tree between attempts; an availability failure and a
capability failure produce distinguishable log records.
"""

import json

from conftest import CHECK_MARKER, NOOP_LINT, STUB_RUNNER


def _log_entries(project):
    p = project / ".claude" / "state" / "failup-log.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _tiers(tmp_path, names):
    p = tmp_path / "tiers.json"
    p.write_text(json.dumps(names))
    return p


# ---------------------------------------------------------------- load_tiers --


def test_load_tiers_accepts_bare_array(failup, tmp_path):
    p = _tiers(tmp_path, ["sonnet", {"model": "opus", "effort": "high"}])
    tiers = failup.load_tiers(str(tmp_path), str(p))
    assert tiers == [
        {"model": "sonnet", "effort": None},
        {"model": "opus", "effort": "high"},
    ]


def test_load_tiers_accepts_object_with_tiers_key(failup, tmp_path):
    p = tmp_path / "tiers.json"
    p.write_text(json.dumps({"_comment": "docs", "tiers": ["local-small", "opus"]}))
    tiers = failup.load_tiers(str(tmp_path), str(p))
    assert tiers == [
        {"model": "local-small", "effort": None},
        {"model": "opus", "effort": None},
    ]


# ----------------------------------------------------- availability detection --


def test_runner_availability_failure_detects_markers(failup):
    class P:
        stdout, stderr = "", "APIConnectionError: 503 Service Unavailable"

    assert failup.runner_availability_failure(P()) == "unavailable:503"


def test_runner_availability_failure_clean_on_normal_output(failup):
    class P:
        stdout, stderr = "some ordinary output", ""

    assert failup.runner_availability_failure(P()) is None


# -------------------------------------------------------------- _runner_usage --


def test_runner_usage_parses_claude_code_json_result(failup):
    class P:
        stdout = (
            '{"type":"result","total_cost_usd":0.042,'
            '"usage":{"input_tokens":1000,"output_tokens":200,'
            '"cache_read_input_tokens":300}}'
        )

    assert failup._runner_usage(P()) == {
        "tokens_in": 1000,
        "tokens_out": 200,
        "cache_read_tokens": 300,
        "cost_usd": 0.042,
    }


def test_runner_usage_empty_on_non_json_stdout(failup):
    class P:
        stdout = "not json, e.g. the stub runner's empty output"

    assert failup._runner_usage(P()) == failup._EMPTY_USAGE


def test_runner_usage_empty_when_usage_key_absent(failup):
    class P:
        stdout = '{"type":"result","total_cost_usd":0.01}'

    u = failup._runner_usage(P())
    assert u == {
        "tokens_in": None,
        "tokens_out": None,
        "cache_read_tokens": None,
        "cost_usd": 0.01,
    }


# --------------------------------------------------------------- run_ladder --


def test_ladder_walks_tiers_in_order(failup, git_repo, tmp_path, monkeypatch):
    # Counter lives OUTSIDE the repo: `git stash -u` sweeps any untracked,
    # non-ignored file inside it (the same reason the log needs .gitignore —
    # see the git_repo fixture), which would reset the stub's call count to 0
    # on every escalation and repeat tier 0 forever instead of progressing.
    # HB-2: each tier gets up to two attempts before escalating, so a tier
    # that's really incapable exhausts both before the ladder moves on.
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "capability,capability,capability,capability,ok")
    tiers = _tiers(git_repo, ["r0", "r1", "r2"])

    rc = failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    assert rc == 0
    entries = _log_entries(git_repo)
    assert [e["tier"] for e in entries] == [0, 0, 1, 1, 2]
    assert [e["model"] for e in entries] == ["r0", "r0", "r1", "r1", "r2"]
    assert [e["ok"] for e in entries] == [False, False, False, False, True]


def test_max_tier_stops_below_ceiling_with_correct_message(
    failup, git_repo, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "capability")  # never passes, at any tier
    tiers = _tiers(git_repo, ["r0", "r1", "r2", "r3"])

    rc = failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        max_tier=1,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    assert rc == 1
    entries = _log_entries(git_repo)
    # HB-2: two attempts per tier before escalating, so r0 and r1 each log twice.
    assert [e["tier"] for e in entries] == [0, 0, 1, 1]  # never reached r2/r3
    assert [e["attempt_in_tier"] for e in entries] == [0, 1, 0, 1]
    err = capsys.readouterr().err
    assert "budget ceiling reached (quota-capped below the top tier)" in err
    assert "did not spend scarce Opus quota" in err


def test_retry_same_tier_once_before_escalating(failup, git_repo, tmp_path, monkeypatch):
    # HB-2: tier 0 fails twice (exhausting its retry) before the ladder moves
    # to tier 1, rather than escalating on the very first miss.
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "capability,capability,ok")
    tiers = _tiers(git_repo, ["r0", "r1"])

    rc = failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    assert rc == 0
    entries = _log_entries(git_repo)
    assert [e["tier"] for e in entries] == [0, 0, 1]
    assert [e["attempt_in_tier"] for e in entries] == [0, 1, 0]
    assert [e["ok"] for e in entries] == [False, False, True]


def test_retry_prompt_carries_the_prior_verdict(failup, git_repo, tmp_path, monkeypatch):
    # The stub runner ignores its argv task text, so this checks the ARGV the
    # ladder builds for the retry attempt directly rather than the outcome.
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "capability,ok")
    tiers = _tiers(git_repo, ["r0"])

    seen_tasks = []
    real_run = failup.run

    def spy(cmd, cwd=None, timeout=1800):
        if cmd[0] != "git":
            seen_tasks.append(cmd[2])  # [python, stub_runner.py, task, "--model", ...]
        return real_run(cmd, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(failup, "run", spy)
    failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    assert seen_tasks[0] == "do the thing"
    assert seen_tasks[1].startswith("do the thing\n\n[failup retry]")
    assert "tests-failed" not in seen_tasks[1]  # the legacy string, not the detail
    assert "the previous attempt failed" in seen_tasks[1]


def test_stash_reset_recovery_restores_clean_tree_between_attempts(
    failup, git_repo, tmp_path, monkeypatch
):
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "capability,ok")
    tiers = _tiers(git_repo, ["r0", "r1"])

    rc = failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    assert rc == 0
    # r0 wrote FAIL and was reset; r1 wrote PASS and was left in the tree. If
    # reset hadn't run, this would still read FAIL (r1 wouldn't overwrite a
    # dirty tree the same way) or the working tree would carry stray state.
    assert (git_repo / "marker.txt").read_text() == "PASS"
    status = failup.git(str(git_repo), "status", "--porcelain").stdout
    assert status.strip().splitlines() == ["M marker.txt"]


def test_log_entries_carry_usage_fields_null_for_a_non_json_runner(
    failup, git_repo, tmp_path, monkeypatch
):
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "ok")
    tiers = _tiers(git_repo, ["r0"])

    failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    entry = _log_entries(git_repo)[0]
    assert entry["tokens_in"] is None
    assert entry["tokens_out"] is None
    assert entry["cache_read_tokens"] is None
    assert entry["cost_usd"] is None


def test_output_format_json_is_always_requested(failup, git_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "ok")
    tiers = _tiers(git_repo, ["r0"])

    seen_cmds = []
    real_run = failup.run

    def spy(cmd, cwd=None, timeout=1800):
        seen_cmds.append(cmd)
        return real_run(cmd, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(failup, "run", spy)
    failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    runner_cmd = next(c for c in seen_cmds if c[0] != "git")
    assert "--output-format" in runner_cmd
    assert runner_cmd[runner_cmd.index("--output-format") + 1] == "json"


def test_availability_and_capability_failures_are_distinguishable(
    failup, git_repo, tmp_path, monkeypatch
):
    monkeypatch.setenv("STUB_COUNTER_FILE", str(tmp_path / ".stub-counter"))
    monkeypatch.setenv("STUB_PLAN", "availability,capability,ok")
    tiers = _tiers(git_repo, ["r0", "r1", "r2"])

    rc = failup.run_ladder(
        "do the thing",
        str(git_repo),
        str(tiers),
        STUB_RUNNER,
        gate_cmds=(NOOP_LINT, CHECK_MARKER),
    )

    assert rc == 0
    entries = _log_entries(git_repo)
    assert [e["category"] for e in entries] == ["availability", "capability", "ok"]
    assert entries[0]["reason"].startswith("unavailable:")
    assert entries[1]["reason"] == "tests-failed"
    # The availability attempt must never have reached the deterministic gate,
    # so it left no trace in the tree for the reset to even need to undo.
    assert entries[0]["reason"] != "empty-diff"


# ------------------------------------------- CC-P6: the fable tier is not here --
# The gate CC-P6 §2 asks about does not belong in this file, and these two tests
# exist to record WHY rather than to leave the absence looking like an omission.
#
# The guard's ladder is FILE-DRIVEN from .claude/tiers.json. It never opens
# registry.yaml, and the two vocabularies do not overlap: the tiers files ship
# rungs like `local-small` / `sovereign-work` / `sonnet` / `opus`, while the
# registry ships the seven capability aliases. A `fable_tier: true` flag on a
# registry row is therefore invisible to this module by construction — ordinary
# escalation here cannot select a registry row in the first place, so there is
# nothing in the guard to gate. The fable-tier gate is declarative, in the
# registry and its rendered model_info, and is tested in test_render_config.py
# (TestFableTierGate). See the CC-P6 report §1.

REGISTRY_ALIASES = frozenset(
    {
        "classifier",
        "code_small",
        "code_large",
        "research_synthesis",
        "embedding",
        "proprietary_code",
        "proprietary_research",
    }
)


def test_escalation_ladder_is_tiers_driven_not_registry_driven(failup, tmp_path):
    # The shipped ladders, verbatim. If a future change makes a registry alias a
    # rung, this fails and the fable-tier gate has to move into the guard.
    for rungs in (
        ["local-small", "local-big", "sonnet", {"model": "opus", "effort": "high"}],
        ["local-small", "sovereign-work", "sonnet", {"model": "opus", "effort": "high"}],
    ):
        p = tmp_path / "tiers.json"
        p.write_text(json.dumps({"_comment": "as shipped", "tiers": rungs}))
        models = {t["model"] for t in failup.load_tiers(str(tmp_path), str(p))}
        assert models & REGISTRY_ALIASES == set()


def test_a_missing_tiers_file_falls_back_to_models_not_aliases(failup, tmp_path):
    # Even the no-config path names models, never registry aliases — so there is
    # no route by which a fable_tier row becomes reachable from this module.
    tiers = failup.load_tiers(str(tmp_path), "does-not-exist.json")
    assert {t["model"] for t in tiers} & REGISTRY_ALIASES == set()
