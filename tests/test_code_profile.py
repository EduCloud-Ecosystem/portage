"""Gate 3/5: the deterministic gate through the verifier-contract boundary.

Zero network, zero model calls — every gate command here is a `python3 -c`
one-liner that exits with a fixed status.

What is asserted, and each is a way the port could have gone wrong:

1. The PREDICATE is unchanged: non-empty change set, then lint, then typecheck,
   then tests, short-circuiting at the first failure, with `checks_pass`'s three
   reasons arriving as their registered reason codes.
2. The verdict says which checks NEVER RAN, so a `fail` documents its own
   coverage instead of leaving it ambiguous whether tests passed or were
   skipped.
3. EVIDENCE DOES NOT REPRODUCE THE CANDIDATE (SPEC.md §6) — for this profile
   that means no command output, because lint and test output quotes source.
4. The verifier-error / failed-verdict distinction survives at the executable
   boundary (SPEC.md §1.1).
5. `failup.py` still logs the exact legacy reason strings that months of
   `.claude/state/failup-log.jsonl` already carry.

The request/verdict documents validate against the schemas in the sibling
`verifier-contract` checkout when it is present.
"""

import json
import os
import pathlib
import re
import subprocess
import sys

import pytest
from conftest import SCRIPTS

EXIT_0 = [sys.executable, "-c", "import sys; sys.exit(0)"]
EXIT_1 = [sys.executable, "-c", "import sys; sys.exit(1)"]
# A command that prints the sort of thing a linter prints — source lines. If any
# of it reached the verdict, the evidence would be reproducing the candidate.
NOISY_FAIL = [
    sys.executable,
    "-c",
    "import sys; print('src/portage/failup.py:118:1: E501 line too long'); sys.exit(1)",
]

DIFF = (
    " M src/portage/failup.py\n"
    " M src/portage/code_profile.py\n"
    "?? tests/test_code_profile.py\n"
)


def _req(code_profile, diff=DIFF, **cmds):
    return code_profile.build_request(diff=diff, working_dir=str(SCRIPTS), **cmds)


# ── 1. the predicate is unchanged ────────────────────────────────────────────


def test_empty_change_set_is_empty_diff(code_profile):
    verdict = code_profile.verify(_req(code_profile, diff="", lint=EXIT_0, test=EXIT_0))
    assert verdict["verdict"] == "fail"
    assert verdict["reason_code"] == "code.empty_diff"


def test_whitespace_only_change_set_is_also_empty(code_profile):
    """`checks_pass` used `.strip()` on the porcelain output; so does this."""
    verdict = code_profile.verify(
        _req(code_profile, diff="  \n\n", lint=EXIT_0, test=EXIT_0)
    )
    assert verdict["reason_code"] == "code.empty_diff"


def test_lint_failure_beats_tests(code_profile):
    verdict = code_profile.verify(_req(code_profile, lint=EXIT_1, test=EXIT_1))
    assert verdict["reason_code"] == "code.lint_failed"


def test_tests_failure(code_profile):
    verdict = code_profile.verify(_req(code_profile, lint=EXIT_0, test=EXIT_1))
    assert verdict["reason_code"] == "code.tests_failed"


def test_optional_typecheck_is_a_fourth_check_between_lint_and_tests(code_profile):
    verdict = code_profile.verify(
        _req(code_profile, lint=EXIT_0, typecheck=EXIT_1, test=EXIT_1)
    )
    assert verdict["reason_code"] == "code.typecheck_failed"


def test_clean_run_passes(code_profile):
    verdict = code_profile.verify(_req(code_profile, lint=EXIT_0, test=EXIT_0))
    assert verdict["verdict"] == "pass"
    assert "reason_code" not in verdict


# ── 2. the verdict documents its own coverage ────────────────────────────────


def _by_check(verdict):
    return {e["check"]: e["status"] for e in verdict["evidence"]}


def test_empty_diff_reports_that_no_command_ran(code_profile):
    verdict = code_profile.verify(_req(code_profile, diff="", lint=EXIT_0, test=EXIT_0))
    assert _by_check(verdict) == {
        "diff": "failed",
        "lint": "not_run",
        "typecheck": "not_configured",
        "test": "not_run",
    }


def test_lint_failure_reports_tests_as_not_run_not_as_passed(code_profile):
    verdict = code_profile.verify(_req(code_profile, lint=EXIT_1, test=EXIT_0))
    assert _by_check(verdict) == {
        "diff": "passed",
        "lint": "failed",
        "typecheck": "not_configured",
        "test": "not_run",
    }


def test_absent_command_is_not_configured_not_passed(code_profile):
    """A check nobody configured is not a check that passed. A `pass` that
    claimed otherwise would report coverage it does not have (SPEC.md §4)."""
    verdict = code_profile.verify(_req(code_profile))
    assert verdict["verdict"] == "pass"
    assert _by_check(verdict) == {
        "diff": "passed",
        "lint": "not_configured",
        "typecheck": "not_configured",
        "test": "not_configured",
    }


def test_evidence_order_is_fixed(code_profile):
    cases = ({"lint": EXIT_0, "test": EXIT_0}, {"lint": EXIT_1, "test": EXIT_0}, {})
    for kwargs in cases:
        verdict = code_profile.verify(_req(code_profile, **kwargs))
        assert [e["check"] for e in verdict["evidence"]] == [
            "diff",
            "lint",
            "typecheck",
            "test",
        ]


# ── 3. evidence does not reproduce the candidate ─────────────────────────────


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _shares_long_run(a, b, n=40):
    """SPEC.md §6: a contiguous run of >= n chars shared with the candidate,
    case-insensitive, whitespace normalised."""
    norm = lambda s: re.sub(r"\s+", " ", s).lower()  # noqa: E731
    a, b = norm(a), norm(b)
    if len(a) < n or len(b) < n:
        return False
    windows = {a[i : i + n] for i in range(len(a) - n + 1)}
    return any(b[i : i + n] in windows for i in range(len(b) - n + 1))


def test_evidence_never_reproduces_the_change_set(code_profile):
    long_diff = "".join(
        f" M src/portage/generated_module_{i:03d}.py\n" for i in range(40)
    )
    verdict = code_profile.verify(_req(code_profile, diff=long_diff, lint=EXIT_1))
    for s in _strings(verdict["evidence"]):
        assert not _shares_long_run(long_diff, s)


def test_evidence_carries_no_command_output(code_profile):
    """Lint output quotes source lines, and source lines are candidate content."""
    verdict = code_profile.verify(_req(code_profile, lint=NOISY_FAIL, test=EXIT_0))
    blob = json.dumps(verdict)
    assert "E501" not in blob
    assert "line too long" not in blob
    assert verdict["evidence"][1] == {"check": "lint", "status": "failed", "exit_code": 1}


def test_changed_files_is_a_count_not_a_listing(code_profile):
    verdict = code_profile.verify(_req(code_profile, lint=EXIT_0, test=EXIT_0))
    assert verdict["evidence"][0]["changed_files"] == 3
    assert "src/portage" not in json.dumps(verdict["evidence"])


# ── 4. determinism and the executable boundary ───────────────────────────────


def test_determinism(code_profile):
    for kwargs in ({"lint": EXIT_0, "test": EXIT_1}, {"lint": EXIT_0, "test": EXIT_0}):
        request = _req(code_profile, **kwargs)
        first = json.dumps(code_profile.verify(request))
        second = json.dumps(code_profile.verify(request))
        assert first == second


def test_executable_form_round_trips_on_stdin_stdout(code_profile):
    request = _req(code_profile, lint=EXIT_0, test=EXIT_1)
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "code_profile.py")],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == code_profile.verify(request)


@pytest.mark.parametrize(
    "payload",
    [
        "{ not json",
        json.dumps({"profile": "code", "task": "", "candidate": "x", "context": {}}),
    ],
    ids=["unparseable-request", "context-missing-working-dir"],
)
def test_a_broken_verifier_exits_non_zero_and_emits_no_verdict(payload):
    """SPEC.md §1.1/§2.2: a judge that cannot decide must NOT emit a `fail`.
    Reading it as one would escalate every task at the first crash."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "code_profile.py")],
        input=payload,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode != 0
    assert proc.stdout.strip() == ""


def test_request_carries_no_model_handle_credential_or_endpoint(code_profile):
    """The structural invariant (SPEC.md §5) is the closed request shape."""
    request = _req(code_profile, lint=EXIT_0, test=EXIT_0)
    assert set(request) == {"profile", "task", "candidate", "context"}
    assert set(request["context"]) == {"working_dir", "commands"}
    blob = json.dumps(request).lower()
    forbidden_fields = ("api_key", "api-key", "base_url", "endpoint", "model", "token")
    for forbidden in forbidden_fields:
        assert forbidden not in blob


# ── 5. failup still reads the same predicate, and logs the same strings ──────


def test_failup_calls_the_profile_and_maps_back_to_legacy_reasons(failup, git_repo):
    """The guard's log strings are longitudinal: measure.py and distill.py read
    records months old. The boundary moved; the strings did not."""
    (git_repo / "marker.txt").write_text("CHANGED")
    verdict = failup.code_verdict(str(git_repo), gate_cmds=(EXIT_0, EXIT_1))
    assert verdict["verdict"] == "fail"
    assert failup._LEGACY_REASON[verdict["reason_code"]] == "tests-failed"


def test_failup_empty_tree_is_empty_diff_through_the_boundary(failup, git_repo):
    verdict = failup.code_verdict(str(git_repo), gate_cmds=(EXIT_0, EXIT_0))
    assert failup._LEGACY_REASON[verdict["reason_code"]] == "empty-diff"


def test_availability_check_stays_upstream_of_the_verifier(failup):
    """SPEC.md §2: two failure kinds, two sites, on purpose. The contract must
    not have grown an availability mechanism, and failup must not have lost one."""
    assert callable(failup.runner_availability_failure)
    assert "429" in failup.AVAILABILITY_MARKERS
    source = (SCRIPTS / "code_profile.py").read_text()
    for forbidden in ("AVAILABILITY_MARKERS", "unavailable", "429", "rate limit"):
        assert forbidden not in source.split('"""', 2)[2], forbidden


def test_every_registered_code_reason_has_a_legacy_string(failup):
    """Cross-repo invariant: if the registry grows a `code.` code, the guard
    must learn to log it rather than KeyError in production."""
    registry = _contract_dir()
    if registry is None:
        pytest.skip("verifier-contract sibling checkout not present")
    codes = json.loads((registry / "schema" / "reason_codes.json").read_text())["codes"]
    for code, spec in codes.items():
        if spec["profile"] == "code":
            assert code in failup._LEGACY_REASON, code


# ── contract schemas (sibling checkout) ──────────────────────────────────────


def _contract_dir():
    env = os.environ.get("VERIFIER_CONTRACT_DIR")
    if env:
        return pathlib.Path(env)
    sibling = pathlib.Path(__file__).resolve().parents[2] / "verifier-contract"
    return sibling if (sibling / "schema").is_dir() else None


@pytest.mark.parametrize(
    "kwargs,diff",
    [
        ({"lint": EXIT_0, "test": EXIT_0}, DIFF),
        ({"lint": EXIT_1, "test": EXIT_0}, DIFF),
        ({"lint": EXIT_0, "test": EXIT_1}, DIFF),
        ({"lint": EXIT_0, "test": EXIT_0}, ""),
        ({}, DIFF),
    ],
)
def test_documents_validate_against_the_contract_schemas(code_profile, kwargs, diff):
    contract = _contract_dir()
    if contract is None:
        pytest.skip("verifier-contract sibling checkout not present")
    jsonschema = pytest.importorskip("jsonschema")
    schema = contract / "schema"
    request_v = jsonschema.Draft202012Validator(
        json.loads((schema / "request.schema.json").read_text())
    )
    verdict_v = jsonschema.Draft202012Validator(
        json.loads((schema / "verdict.schema.json").read_text())
    )
    context_v = jsonschema.Draft202012Validator(
        json.loads((schema / "context" / "code.context.schema.json").read_text())
    )
    registered = json.loads((schema / "reason_codes.json").read_text())["codes"]

    request = _req(code_profile, diff=diff, **kwargs)
    request_v.validate(request)
    context_v.validate(request["context"])
    verdict = code_profile.verify(request)
    verdict_v.validate(verdict)
    assert verdict["profile"] == request["profile"]
    if verdict["verdict"] == "fail":
        assert verdict["reason_code"] in registered
        assert verdict["reason_code"].split(".", 1)[0] == verdict["profile"]
