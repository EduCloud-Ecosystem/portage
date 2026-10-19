"""CC-P11 — prove residency survives failover, before `failover_only` gets a row.

Construction test, not a runtime/network test. The claim from specs/13 §4.3:
a `sovereign`-mode request cannot be failed over to an endpoint absent from
that mode's config — and since config absence is the enforcement, the machine
check is that the renderer REFUSES to express a config where a `failover_only`
row lands on a sovereign-classified alias. If the config can't express the
violation, there is nothing for LiteLLM's retry/fallback/cooldown machinery
(`allowed_fails`, `cooldown_time`, model-group fallback) to find.

This lands before any row sets `failover_only` (the schema field exists,
unused, per CW04-HB0-drift.md). The rule mirrors
`test_off_institution_rows_are_public_only` in test_scale2_profile.py: a
`failover_only` row is only ever legal on an alias whose `data_classification`
is `public` — an off-institution endpoint may only ever be cleared for
`public`, and a failover path on a sensitive/regulated alias would let a
sovereign request silently leave the institution.

Fail-closed posture, chosen to match the renderer's existing behaviour for
every other cross-entry violation: refuse to render (`validate_cross_entry`
returns the problem; `main()` then prints and exits nonzero with no output
written) rather than silently dropping the row — a silently dropped row would
hide the violation instead of forcing the author to fix it.
"""

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
from conftest import SCRIPTS, _load  # noqa: E402

render_config = pytest.fixture(  # noqa: E402
    lambda: _load("render_config_under_test", SCRIPTS / "render_config.py")
)

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "config" / "profiles"
STUDENT = PROFILES / "scale2.educloud.student.registry.yaml"
STAFF = PROFILES / "scale2.educloud.staff.registry.yaml"

# Same off-institution set test_scale2_profile.py uses.
OFF_INSTITUTION_ROUTES = {"openrouter", "anthropic", "perplexity"}


@pytest.fixture
def schema():
    schema_path = REPO / "schema" / "registry.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _entry(**overrides):
    base = {
        "alias": "code_large",
        "provider_route": "openrouter",
        "model_id": "example-org/example-large-coder",
        "endpoint": None,
        "open_weight": True,
        "license": "UNVERIFIED",
        "license_family": "unverified",
        "max_context": 131072,
        "supports_tools": True,
        "supports_json": True,
        "data_classification": "public",
        "benchmark_version": None,
        "bfclv3": None,
        "ifeval": None,
        "enabled": True,
    }
    base.update(overrides)
    return base


def _models(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["models"]


class TestFailoverOnlyRequiresPublicClassification:
    """The rule itself, stated as a row-level unit test."""

    def test_sensitive_failover_row_refused(self, render_config):
        models = [
            _entry(
                data_classification="personal_sensitive",
                failover_only=True,
            )
        ]
        problems = render_config.validate_cross_entry(models)
        assert any("failover_only" in p for p in problems), (
            "a failover_only row classified personal_sensitive rendered without "
            "refusal — a sovereign request could be failed over off-institution"
        )

    def test_regulated_failover_row_refused(self, render_config):
        models = [_entry(data_classification="regulated", failover_only=True)]
        problems = render_config.validate_cross_entry(models)
        assert any("failover_only" in p for p in problems)

    def test_public_failover_row_still_renders(self, render_config):
        # The field stays usable for its intended case (CW-04 §2.2's OpenRouter
        # insurance for PUBLIC work). Refusing only the non-public classification
        # is the rule; refusing everything would delete the affordance.
        models = [_entry(data_classification="public", failover_only=True)]
        assert render_config.validate_cross_entry(models) == []
        info = render_config.render_model_list(models)["model_list"][0]["model_info"]
        assert info["failover_only"] is True


class TestSovereignConfigCannotExpressTheViolation:
    """The CC-P11 construction: the actual sovereign lane, plus a hypothetical
    off-institution `failover_only` row that someone has added to it. The
    renderer must refuse, so no combination of router_settings or model-group
    fallback can build a path — there is no row to fail over to."""

    def test_student_lane_with_hypothetical_failover_row_refused(
        self, render_config, schema
    ):
        models = _models(STUDENT)
        # The lane is entirely sovereign (`openai`) and personal_sensitive.
        assert {m["provider_route"] for m in models} == {"openai"}
        assert all(m["data_classification"] == "personal_sensitive" for m in models)
        # Hypothetical: an off-institution failover_only row added to a
        # sovereign alias, carrying the lane's own classification.
        models.append(
            _entry(
                alias="code_large",
                provider_route="openrouter",
                model_id="example-org/example-large-coder",
                data_classification="personal_sensitive",
                failover_only=True,
                order=9,
            )
        )
        # Schema-level: the row is legal JSON Schema today (nothing in the
        # schema stops it) — this is exactly why a cross-entry check is needed.
        assert render_config.validate_schema({"models": models}, schema) == []
        problems = render_config.validate_cross_entry(models)
        assert any("failover_only" in p for p in problems), (
            "the sovereign student lane rendered a hypothetical off-institution "
            "failover_only row without refusal — a student request could reach "
            "an endpoint absent from the lane's config via LiteLLM retry/fallback"
        )

    def test_staff_shared_alias_sensitive_failover_refused(self, render_config):
        # The staff `code_large` alias legitimately mixes a sovereign
        # (personal_sensitive) row with an off-institution (public) row. The
        # dangerous hypothetical is a failover_only row carrying the SENSITIVE
        # classification onto that shared alias: refused.
        models = _models(STAFF)
        assert any(
            m["alias"] == "code_large"
            and m["provider_route"] in OFF_INSTITUTION_ROUTES
            and m["data_classification"] == "public"
            for m in models
        ), "staff code_large should already mix sovereign + public off-institution rows"
        models.append(
            _entry(
                alias="code_large",
                provider_route="perplexity",
                model_id="example-org/example-research-model",
                data_classification="personal_sensitive",
                failover_only=True,
                order=9,
            )
        )
        problems = render_config.validate_cross_entry(models)
        assert any("failover_only" in p for p in problems)

    def test_checked_in_profiles_do_not_trip_the_rule(self, render_config):
        # No regression from the new rule on the real profiles: no checked-in
        # row sets failover_only, and every off-institution row is already
        # public, so the rule must not add a single problem. (The staff profile
        # already carries one PRE-EXISTING, unrelated problem — its placeholder
        # `proprietary_code` row names the alias CC-P6 deleted, which the
        # renderer's six-alias check rejects. Scale-2 placeholder content is
        # out of scope here; the guard is that this rule adds nothing to it.)
        for path in (STUDENT, STAFF):
            problems = render_config.validate_cross_entry(_models(path))
            assert all(
                "failover_only" not in p for p in problems
            ), f"{path.name} trips the failover_only/public rule: {problems}"
        assert render_config.validate_cross_entry(_models(STUDENT)) == []

    def test_router_settings_cannot_recreate_the_path(self, render_config, schema):
        # The "no combination of allowed_fails / cooldown_time / model-group
        # fallback" clause: fallback knobs live in the settings document the
        # renderer merges verbatim, so they are never consulted for a row that
        # fails cross-entry validation. Aggressive fallback settings cannot
        # resurrect a path the config cannot express.
        models = [_entry(data_classification="personal_sensitive", failover_only=True)]
        registry = {"models": models}
        assert render_config.validate_schema(registry, schema) == []
        problems = render_config.validate_cross_entry(models)
        assert any("failover_only" in p for p in problems)
        # And the settings knobs themselves are inert here: nothing about
        # allowed_fails or cooldown_time appears in any refusal path — the
        # refusal happens at validation, before rendering, unconditionally.
        for knob in ("allowed_fails", "cooldown_time", "fallbacks"):
            assert all(knob not in p for p in problems)
