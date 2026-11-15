"""Tests for src/portage/render_config.py and validate_env.py (HB-0 Gate 1).

Hermetic: no network, no model calls, no live Ollama/Postgres needed — this
tests the renderer's own logic against small in-memory registries. The engine
repo's real Gate-1 evidence (against the checked-in sanitized example) is the
`--check` invocation wired into CI; see .github/workflows/portage-ci.yml.
"""

import json

import pytest
import yaml
from conftest import SCRIPTS, _load

render_config = pytest.fixture(
    lambda: _load("render_config_under_test", SCRIPTS / "render_config.py")
)
validate_env = pytest.fixture(
    lambda: _load("validate_env_under_test", SCRIPTS / "validate_env.py")
)


@pytest.fixture
def schema():
    schema_path = SCRIPTS.parent.parent / "schema" / "registry.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _entry(**overrides):
    base = {
        "alias": "embedding",
        "provider_route": "ollama_chat",
        "model_id": "nomic-embed-text",
        "endpoint": "os.environ/NODE_A",
        "open_weight": True,
        "license": "Apache-2.0",
        "license_family": "permissive",
        "max_context": 8192,
        "supports_tools": False,
        "supports_json": False,
        "data_classification": "public",
        "benchmark_version": None,
        "bfclv3": None,
        "ifeval": None,
        "enabled": True,
    }
    base.update(overrides)
    return base


class TestSchemaValidation:
    def test_valid_registry_passes(self, render_config, schema):
        registry = {"models": [_entry()]}
        assert render_config.validate_schema(registry, schema) == []

    def test_unknown_alias_rejected(self, render_config, schema):
        registry = {"models": [_entry(alias="made_up_alias")]}
        errors = render_config.validate_schema(registry, schema)
        assert any("made_up_alias" in e for e in errors)

    def test_ollama_chat_without_endpoint_rejected(self, render_config, schema):
        entry = _entry()
        del entry["endpoint"]
        registry = {"models": [entry]}
        errors = render_config.validate_schema(registry, schema)
        assert any("endpoint" in e for e in errors)

    def test_missing_required_field_rejected(self, render_config, schema):
        entry = _entry()
        del entry["license"]
        registry = {"models": [entry]}
        errors = render_config.validate_schema(registry, schema)
        assert any("license" in e for e in errors)


class TestLicenseFamily:
    """CW-04 §2.5 / C6. `open_weight_only` tests THIS field, not `open_weight`
    — Kimi K3 ships public weights under a grant with a revenue-triggered
    separate-agreement clause, which is the falsification that made the field
    necessary. A gate only some rows populate is not a gate, so it is
    required, not optional."""

    ALLOWED = (
        "permissive",
        "weak_copyleft",
        "strong_copyleft",
        "non_permissive",
        "proprietary",
        "unverified",
    )

    def test_unlisted_value_rejected(self, render_config, schema):
        registry = {"models": [_entry(license_family="mostly-fine-probably")]}
        errors = render_config.validate_schema(registry, schema)
        assert any("license_family" in e for e in errors)

    def test_every_allowlisted_value_accepted(self, render_config, schema):
        for fam in self.ALLOWED:
            registry = {"models": [_entry(license_family=fam)]}
            assert render_config.validate_schema(registry, schema) == [], fam

    def test_field_is_required_not_optional(self, render_config, schema):
        entry = _entry()
        del entry["license_family"]
        registry = {"models": [entry]}
        errors = render_config.validate_schema(registry, schema)
        assert any("license_family" in e for e in errors)

    def test_open_weight_true_does_not_imply_an_allowlisted_family(
        self, render_config, schema
    ):
        # The Kimi K3 case, stated as a test: weights published, licence not
        # acceptable. Both fields must be readable independently downstream.
        entry = _entry(
            open_weight=True,
            license="Kimi-K3-Custom",
            license_family="non_permissive",
        )
        assert render_config.validate_schema({"models": [entry]}, schema) == []
        info = render_config.render_model_list([entry])["model_list"][0]["model_info"]
        assert info["open_weight"] is True
        assert info["license_family"] == "non_permissive"


class TestEffortField:
    """CC-P6 §3: one checkpoint occupying two rungs at different reasoning
    budgets. Registry calls it `effort` (matching models.json on Lane A);
    LiteLLM calls it `reasoning_effort`."""

    def test_max_effort_accepted(self, render_config, schema):
        registry = {"models": [_entry(effort="max")]}
        assert render_config.validate_schema(registry, schema) == []

    def test_null_effort_accepted(self, render_config, schema):
        registry = {"models": [_entry(effort=None)]}
        assert render_config.validate_schema(registry, schema) == []

    def test_unlisted_effort_rejected(self, render_config, schema):
        registry = {"models": [_entry(effort="maximum")]}
        errors = render_config.validate_schema(registry, schema)
        assert any("effort" in e for e in errors)

    def test_effort_renders_to_reasoning_effort_and_model_info(self, render_config):
        doc = render_config.render_model_list([_entry(effort="max")])
        entry = doc["model_list"][0]
        assert entry["litellm_params"]["reasoning_effort"] == "max"
        assert entry["model_info"]["effort"] == "max"

    def test_absent_or_null_effort_omits_the_param_entirely(self, render_config):
        # A rung wanting default effort must not carry the flag at all — the
        # same rule failup.py's tiers file states ("default" is not a valid
        # effort). Sending a default would flatten the ladder silently.
        for entry in (_entry(), _entry(effort=None)):
            rendered = render_config.render_model_list([entry])["model_list"][0]
            assert "reasoning_effort" not in rendered["litellm_params"]
            assert "effort" not in rendered["model_info"]

    def test_same_checkpoint_at_two_efforts_is_two_valid_rungs(self, render_config):
        models = [
            _entry(
                alias="code_large",
                provider_route="deepseek",
                model_id="deepseek-v4-flash",
                endpoint=None,
                order=1,
            ),
            _entry(
                alias="code_large",
                provider_route="deepseek",
                model_id="deepseek-v4-flash",
                endpoint=None,
                order=3,
                effort="max",
            ),
        ]
        assert render_config.validate_cross_entry(models) == []
        params = [
            m["litellm_params"]
            for m in render_config.render_model_list(models)["model_list"]
        ]
        assert params[0]["model"] == params[1]["model"] == "deepseek/deepseek-v4-flash"
        assert "reasoning_effort" not in params[0]
        assert params[1]["reasoning_effort"] == "max"


class TestFableTierGate:
    """CC-P6 §2. The gate is DECLARATIVE, matching CW-02's T6 gate as it
    actually exists in this repo — policy plus `enabled: false`, not code. See
    the CC-P6 report §1: there is no confirm-prompt mechanism anywhere in
    portage, and failup.py escalates through .claude/tiers.json without ever
    opening the registry, so there is no runtime selector here to gate.

    What these tests lock in is the contract a selector must honour: a
    `fable_tier` row is excluded from ordinary selection on its own flag, so
    that flipping `enabled` later does not silently promote it to a rung.
    """

    @staticmethod
    def _fable(**kw):
        base = dict(
            alias="code_large",
            provider_route="moonshot",
            model_id="kimi-k3",
            endpoint=None,
            order=5,
            open_weight=True,
            license="Kimi-K3-Custom",
            license_family="non_permissive",
            max_context=262144,
            fable_tier=True,
            enabled=False,
        )
        base.update(kw)
        return _entry(**base)

    @staticmethod
    def _ordinary_rungs(model_list):
        """What ordinary escalation may select. `enabled` is the flag HB-0
        documents downstream tooling filtering on; `fable_tier` is the second,
        independent veto CC-P6 adds."""
        return [
            m["model_name"]
            for m in model_list
            if m["model_info"]["enabled"] and not m["model_info"].get("fable_tier")
        ]

    def test_fable_row_still_renders_into_the_routing_table(self, render_config):
        # It must appear: HB-0 Gate 2 requires /v1/models to list every alias
        # the deployment declares, and the renderer carries `enabled` into
        # model_info rather than dropping the row.
        doc = render_config.render_model_list([self._fable()])
        entry = doc["model_list"][0]
        assert entry["model_name"] == "code_large"
        assert entry["litellm_params"]["model"] == "moonshot/kimi-k3"
        assert entry["model_info"]["enabled"] is False
        assert entry["model_info"]["fable_tier"] is True

    def test_ordinary_escalation_never_selects_a_fable_row(self, render_config):
        models = [
            _entry(
                alias="code_large",
                provider_route="deepseek",
                model_id="deepseek-v4-flash",
                endpoint=None,
                order=1,
            ),
            self._fable(),
        ]
        doc = render_config.render_model_list(models)
        assert self._ordinary_rungs(doc["model_list"]) == ["code_large"]
        assert len(doc["model_list"]) == 2  # present, but not a rung

    def test_fable_row_stays_invisible_even_if_enabled_is_flipped_true(
        self, render_config
    ):
        # The whole point of a second flag. `enabled: true` provisions the
        # route; it must not, on its own, make K3 an escalation target.
        doc = render_config.render_model_list([self._fable(enabled=True)])
        assert self._ordinary_rungs(doc["model_list"]) == []
        assert doc["model_list"][0]["model_info"]["enabled"] is True

    def test_explicit_path_can_reach_the_row_ordinary_escalation_cannot(
        self, render_config
    ):
        # The only path that should exist: a caller that asks for the fable
        # tier by name, which is what gets logged as a human decision.
        doc = render_config.render_model_list([self._fable(enabled=True)])
        explicit = [
            m["model_name"]
            for m in doc["model_list"]
            if m["model_info"].get("fable_tier")
        ]
        assert explicit == ["code_large"]

    def test_ordinary_row_carries_no_fable_key_at_all(self, render_config):
        info = render_config.render_model_list([_entry()])["model_list"][0]["model_info"]
        assert "fable_tier" not in info
        assert "failover_only" not in info

    def test_failover_only_is_a_separate_marker(self, render_config, schema):
        # CW-04 §2.2's OpenRouter demotion. No live row sets it yet; the field
        # exists so HB-2's health-check-gated path has somewhere to land.
        entry = _entry(
            alias="code_large",
            provider_route="openrouter",
            model_id="example-org/x",
            endpoint=None,
            failover_only=True,
            license_family="unverified",
        )
        assert render_config.validate_schema({"models": [entry]}, schema) == []
        info = render_config.render_model_list([entry])["model_list"][0]["model_info"]
        assert info["failover_only"] is True


class TestCrossEntryValidation:
    def test_duplicate_alias_without_order_rejected(self, render_config):
        models = [
            _entry(alias="code_small"),
            _entry(alias="code_small", model_id="other"),
        ]
        problems = render_config.validate_cross_entry(models)
        assert any("no `order`" in p for p in problems)

    def test_duplicate_alias_with_orders_ok(self, render_config):
        models = [
            _entry(alias="code_small", order=1),
            _entry(alias="code_small", model_id="other", order=2),
        ]
        assert render_config.validate_cross_entry(models) == []

    def test_duplicate_order_values_rejected(self, render_config):
        models = [
            _entry(alias="code_small", order=1),
            _entry(alias="code_small", model_id="other", order=1),
        ]
        problems = render_config.validate_cross_entry(models)
        assert any("duplicate `order`" in p for p in problems)

    def test_disabled_duplicate_does_not_require_order(self, render_config):
        # A disabled sibling shouldn't force the enabled entry to carry `order`.
        models = [
            _entry(alias="code_small"),
            _entry(alias="code_small", model_id="other", enabled=False),
        ]
        assert render_config.validate_cross_entry(models) == []


class TestRenderModelList:
    def test_disabled_entries_still_rendered_but_flagged(self, render_config):
        # Gate 2 requires /v1/models to list exactly the seven aliases, so a
        # disabled alias (e.g. proprietary_code before HB-2) must still show
        # up there — `enabled: false` is carried into model_info instead of
        # excluding the entry from model_list.
        models = [
            _entry(),
            _entry(
                alias="proprietary_code",
                provider_route="anthropic",
                model_id="claude-sonnet-5",
                endpoint=None,
                enabled=False,
            ),
        ]
        doc = render_config.render_model_list(models)
        names = [m["model_name"] for m in doc["model_list"]]
        assert names == ["embedding", "proprietary_code"]
        by_name = {m["model_name"]: m for m in doc["model_list"]}
        assert by_name["proprietary_code"]["model_info"]["enabled"] is False
        assert by_name["embedding"]["model_info"]["enabled"] is True

    def test_ollama_chat_route(self, render_config):
        doc = render_config.render_model_list([_entry()])
        params = doc["model_list"][0]["litellm_params"]
        assert params["model"] == "ollama_chat/nomic-embed-text"
        assert params["api_base"] == "os.environ/NODE_A"

    def test_first_party_routes_use_their_own_keys(self, render_config):
        # CW-04 §2.2 moved the hosted rungs off aggregators onto first-party
        # endpoints. All three are native LiteLLM providers in the pinned
        # v1.93.0, so no api_base is rendered — the provider supplies it.
        expected = {
            "deepseek": ("deepseek/deepseek-v4-flash", "os.environ/DEEPSEEK_API_KEY"),
            "morph": ("morph/minimax-m3", "os.environ/MORPH_API_KEY"),
            "moonshot": ("moonshot/kimi-k3", "os.environ/MOONSHOT_API_KEY"),
        }
        ids = {
            "deepseek": "deepseek-v4-flash",
            "morph": "minimax-m3",
            "moonshot": "kimi-k3",
        }
        for route, (model, key) in expected.items():
            entry = _entry(
                alias="code_large",
                provider_route=route,
                model_id=ids[route],
                endpoint=None,
                order=1,
            )
            params = render_config.render_model_list([entry])["model_list"][0][
                "litellm_params"
            ]
            assert params["model"] == model
            assert params["api_key"] == key
            assert "api_base" not in params

    def test_openai_direct_is_not_the_sovereign_openai_route(self, render_config):
        # These two must never collapse into one enum value. `openai` is Scale
        # 2's institution-hosted vLLM; `openai_direct` is api.openai.com.
        # Rendering GPT-5.6 Sol under `openai` would point it at Jetstream2 and
        # sign it with the sovereign token.
        sovereign = _entry(
            alias="code_large",
            provider_route="openai",
            model_id="portage-code-large",
            endpoint="os.environ/SOVEREIGN_BASE_URL",
        )
        direct = _entry(
            alias="proprietary_research",
            provider_route="openai_direct",
            model_id="gpt-5.6-sol",
            endpoint=None,
            enabled=False,
        )
        s = render_config.render_model_list([sovereign])["model_list"][0][
            "litellm_params"
        ]
        d = render_config.render_model_list([direct])["model_list"][0]["litellm_params"]
        assert s["api_base"] == "os.environ/SOVEREIGN_BASE_URL"
        assert s["api_key"] == "os.environ/SOVEREIGN_TOKEN"
        assert d["model"] == "openai/gpt-5.6-sol"
        assert d["api_key"] == "os.environ/OPENAI_API_KEY"
        assert "api_base" not in d

    def test_openrouter_route_uses_env_key(self, render_config):
        entry = _entry(
            alias="code_large",
            provider_route="openrouter",
            model_id="z-ai/glm-5.2",
            endpoint=None,
            order=1,
        )
        doc = render_config.render_model_list([entry])
        params = doc["model_list"][0]["litellm_params"]
        assert params["model"] == "openrouter/z-ai/glm-5.2"
        assert params["api_key"] == "os.environ/OPENROUTER_API_KEY"


class TestValidateEnv:
    def test_missing_vars_reported(self, validate_env, tmp_path, monkeypatch):
        config = tmp_path / "config.yaml"
        model_list = tmp_path / "model_list.generated.yaml"
        model_list.write_text(
            yaml.safe_dump(
                {"model_list": [{"litellm_params": {"api_key": "os.environ/NEEDS_ME"}}]}
            )
        )
        config.write_text(
            yaml.safe_dump(
                {
                    "include": ["model_list.generated.yaml"],
                    "general_settings": {"master_key": "os.environ/ALSO_NEEDED"},
                }
            )
        )
        monkeypatch.delenv("NEEDS_ME", raising=False)
        monkeypatch.delenv("ALSO_NEEDED", raising=False)
        doc = validate_env.load_with_includes(config)
        refs = validate_env.collect_env_refs(doc)
        assert refs == {"NEEDS_ME", "ALSO_NEEDED"}

    def test_all_vars_present(self, validate_env, tmp_path, monkeypatch):
        config = tmp_path / "config.yaml"
        model_list = tmp_path / "model_list.generated.yaml"
        model_list.write_text(yaml.safe_dump({"model_list": []}))
        config.write_text(
            yaml.safe_dump(
                {
                    "include": ["model_list.generated.yaml"],
                    "general_settings": {"master_key": "os.environ/PRESENT_VAR"},
                }
            )
        )
        monkeypatch.setenv("PRESENT_VAR", "x")
        doc = validate_env.load_with_includes(config)
        refs = validate_env.collect_env_refs(doc)
        assert refs == {"PRESENT_VAR"}
        assert all(v in __import__("os").environ for v in refs)
