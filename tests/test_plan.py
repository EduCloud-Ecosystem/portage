"""Phase 2: harden plan.py's extract/validate/toposort/MANUAL-stop path, and
the guard/acceptance/integration control flow in do_run. Zero network, zero
model calls: the FAILUP guard call is stubbed; acceptance/integration checks
are real subprocess calls to the `true`/`false` shell builtins, not a network
call.
"""

import json

import pytest

GOOD_PLAN = {
    "task": "add a feature",
    "subtasks": [
        {
            "id": "a",
            "goal": "do a",
            "depends_on": [],
            "acceptance_check": 'python -c "import sys; sys.exit(0)"',
        },
    ],
    "integration_check": 'python -c "import sys; sys.exit(0)"',
    "risky_seams": [],
}


# --------------------------------------------------------------- extract_plan --


def test_extract_plan_clean_json(plan_mod):
    raw = json.dumps(GOOD_PLAN)
    assert plan_mod.extract_plan(raw) == GOOD_PLAN


def test_extract_plan_brace_sliced_from_prose(plan_mod):
    raw = f"Sure, here is the plan:\n{json.dumps(GOOD_PLAN)}\nLet me know!"
    assert plan_mod.extract_plan(raw) == GOOD_PLAN


def test_extract_plan_raises_when_no_json_present(plan_mod):
    with pytest.raises(ValueError):
        plan_mod.extract_plan("no braces here at all")


# -------------------------------------------------------------- validate_plan --


def test_validate_plan_accepts_a_good_plan(plan_mod):
    plan_mod.validate_plan(GOOD_PLAN)  # must not raise


def test_validate_plan_rejects_missing_top_level_key(plan_mod):
    bad = {k: v for k, v in GOOD_PLAN.items() if k != "integration_check"}
    with pytest.raises(ValueError, match="integration_check"):
        plan_mod.validate_plan(bad)


def test_validate_plan_rejects_subtask_missing_required_field(plan_mod):
    bad = json.loads(json.dumps(GOOD_PLAN))
    del bad["subtasks"][0]["goal"]
    with pytest.raises(ValueError, match="goal"):
        plan_mod.validate_plan(bad)


# ------------------------------------------------------------------ toposort --


def test_toposort_orders_by_dependency(plan_mod):
    subtasks = [
        {"id": "c", "goal": "c", "depends_on": ["b"]},
        {"id": "a", "goal": "a", "depends_on": []},
        {"id": "b", "goal": "b", "depends_on": ["a"]},
    ]
    ordered = [s["id"] for s in plan_mod.toposort(subtasks)]
    assert ordered.index("a") < ordered.index("b") < ordered.index("c")


def test_toposort_allows_independent_branches_either_order(plan_mod):
    subtasks = [
        {"id": "a", "goal": "a", "depends_on": []},
        {"id": "b", "goal": "b", "depends_on": []},
        {"id": "c", "goal": "c", "depends_on": ["a", "b"]},
    ]
    ordered = [s["id"] for s in plan_mod.toposort(subtasks)]
    assert ordered.index("c") == 2
    assert set(ordered[:2]) == {"a", "b"}


def test_toposort_raises_on_dependency_cycle(plan_mod):
    subtasks = [
        {"id": "a", "goal": "a", "depends_on": ["b"]},
        {"id": "b", "goal": "b", "depends_on": ["a"]},
    ]
    with pytest.raises(SystemExit):
        plan_mod.toposort(subtasks)


def test_toposort_raises_on_missing_dependency_id(plan_mod):
    subtasks = [{"id": "a", "goal": "a", "depends_on": ["ghost"]}]
    with pytest.raises(SystemExit):
        plan_mod.toposort(subtasks)


# -------------------------------------------------------------------- do_run --


def _write_plan(tmp_path, plan):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan))
    return str(p)


def _patch_guard(monkeypatch, plan_mod, rc):
    """Stub only the FAILUP subprocess call (`uv run failup.py ...`); real
    acceptance/integration shell commands still run for real (they're just
    `true`/`false`, no network)."""
    original_run = plan_mod.run

    def fake_run(cmd, cwd=None, timeout=1800, shell=False):
        if isinstance(cmd, list) and cmd[:2] == ["uv", "run"]:

            class FakeProc:
                returncode = rc

            return FakeProc()
        return original_run(cmd, cwd=cwd, timeout=timeout, shell=shell)

    monkeypatch.setattr(plan_mod, "run", fake_run)


def test_do_run_manual_stop_never_invokes_the_guard(plan_mod, tmp_path, monkeypatch):
    def exploding_run(*a, **k):
        raise AssertionError("MANUAL: subtasks must stop before any run() call")

    monkeypatch.setattr(plan_mod, "run", exploding_run)

    plan = json.loads(json.dumps(GOOD_PLAN))
    plan["subtasks"][0]["acceptance_check"] = "MANUAL: needs a human to eyeball this"
    plan_path = _write_plan(tmp_path, plan)

    with pytest.raises(SystemExit) as exc:
        plan_mod.do_run(plan_path, str(tmp_path))
    assert exc.value.code == 3


def test_do_run_succeeds_when_guard_and_checks_pass(
    plan_mod, tmp_path, monkeypatch, capsys
):
    _patch_guard(monkeypatch, plan_mod, rc=0)
    plan_path = _write_plan(tmp_path, GOOD_PLAN)

    plan_mod.do_run(plan_path, str(tmp_path))  # must not raise

    assert "integration check green" in capsys.readouterr().out
    log = tmp_path / ".claude" / "state" / "decomp-log.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert entries[0]["guard_ok"] is True
    assert entries[0]["accept_ok"] is True


def test_do_run_stops_when_guard_fails(plan_mod, tmp_path, monkeypatch):
    _patch_guard(monkeypatch, plan_mod, rc=1)
    plan_path = _write_plan(tmp_path, GOOD_PLAN)
    with pytest.raises(SystemExit) as exc:
        plan_mod.do_run(plan_path, str(tmp_path))
    assert exc.value.code == 1


def test_do_run_stops_when_acceptance_check_fails(plan_mod, tmp_path, monkeypatch):
    _patch_guard(monkeypatch, plan_mod, rc=0)
    plan = json.loads(json.dumps(GOOD_PLAN))
    plan["subtasks"][0]["acceptance_check"] = "false"
    plan_path = _write_plan(tmp_path, plan)
    with pytest.raises(SystemExit) as exc:
        plan_mod.do_run(plan_path, str(tmp_path))
    assert exc.value.code == 1


def test_do_run_stops_when_integration_check_fails(plan_mod, tmp_path, monkeypatch):
    _patch_guard(monkeypatch, plan_mod, rc=0)
    plan = json.loads(json.dumps(GOOD_PLAN))
    plan["integration_check"] = "false"
    plan_path = _write_plan(tmp_path, plan)
    with pytest.raises(SystemExit) as exc:
        plan_mod.do_run(plan_path, str(tmp_path))
    assert exc.value.code == 2
