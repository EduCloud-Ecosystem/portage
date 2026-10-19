"""HB-2b: tier_pricing.py's rung-to-alias mapping and price_for_rung()."""

import pytest


@pytest.fixture
def tier_pricing():
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "src" / "portage" / "tier_pricing.py"
    spec = importlib.util.spec_from_file_location("tier_pricing_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tier_pricing_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


CODE_SMALL_TABLE = {
    "code_small": [
        {
            "model_id": "gemma4:12b",
            "enabled": True,
            "price_input_per_million": 0,
            "price_output_per_million": 0,
            "price_cache_hit_per_million": 0,
        },
    ],
}

CODE_LARGE_TABLE = {
    "code_large": [
        {
            "model_id": "deepseek-v4-flash",
            "enabled": True,
            "price_input_per_million": 0.14,
            "price_output_per_million": 0.28,
            "price_cache_hit_per_million": 0.0028,
        },
        {
            "model_id": "minimax-m3",
            "enabled": True,
            "price_input_per_million": 0.30,
            "price_output_per_million": 1.20,
            "price_cache_hit_per_million": None,
        },
    ],
}


def test_runner_reported_cost_wins_regardless_of_rung(tier_pricing):
    price, basis = tier_pricing.price_for_rung(
        "sonnet",
        cost_usd=0.0123,
        tokens_in=1000,
        tokens_out=200,
        cache_read_tokens=None,
        price_table={},
    )
    assert (price, basis) == (0.0123, "runner-reported")


def test_sonnet_and_opus_have_no_registry_equivalent(tier_pricing):
    for rung in ("sonnet", "opus"):
        price, basis = tier_pricing.price_for_rung(
            rung,
            cost_usd=None,
            tokens_in=1000,
            tokens_out=200,
            cache_read_tokens=None,
            price_table={},
        )
        assert price is None
        assert basis.startswith("no-registry-equivalent:")


def test_local_big_and_sovereign_work_have_no_registry_equivalent(tier_pricing):
    for rung in ("local-big", "sovereign-work"):
        price, basis = tier_pricing.price_for_rung(
            rung,
            cost_usd=None,
            tokens_in=1000,
            tokens_out=200,
            cache_read_tokens=None,
            price_table={},
        )
        assert price is None
        assert basis.startswith("no-registry-equivalent:")


def test_unmapped_rung(tier_pricing):
    price, basis = tier_pricing.price_for_rung(
        "some-future-rung",
        cost_usd=None,
        tokens_in=1000,
        tokens_out=200,
        cache_read_tokens=None,
        price_table={},
    )
    assert (price, basis) == (None, "unmapped-rung")


def test_local_small_single_occupant_prices_exactly(tier_pricing):
    price, basis = tier_pricing.price_for_rung(
        "local-small",
        cost_usd=None,
        tokens_in=1_000_000,
        tokens_out=500_000,
        cache_read_tokens=None,
        price_table=CODE_SMALL_TABLE,
    )
    assert (price, basis) == (0.0, "registry-exact")


def test_two_occupants_same_price_still_prices_exactly(tier_pricing):
    # The real registry: code_small has TWO enabled occupants (gemma4:12b,
    # gemma4:e4b), both $0 local. Which one served the call is unrecoverable
    # from the rung name, but the price doesn't depend on the answer.
    two_free_occupants = {
        "code_small": [
            {
                "model_id": "gemma4:12b",
                "enabled": True,
                "price_input_per_million": 0,
                "price_output_per_million": 0,
                "price_cache_hit_per_million": 0,
            },
            {
                "model_id": "gemma4:e4b",
                "enabled": True,
                "price_input_per_million": 0,
                "price_output_per_million": 0,
                "price_cache_hit_per_million": 0,
            },
        ],
    }
    price, basis = tier_pricing.price_for_rung(
        "local-small",
        cost_usd=None,
        tokens_in=1_000_000,
        tokens_out=500_000,
        cache_read_tokens=None,
        price_table=two_free_occupants,
    )
    assert (price, basis) == (0.0, "registry-exact")


def test_ambiguous_occupant_when_alias_has_multiple_enabled_rows(tier_pricing):
    # code_large isn't in RUNG_TO_ALIAS at all today, so exercise the branch
    # directly the way a future rung mapped to it would hit it.
    tier_pricing.RUNG_TO_ALIAS["_test_code_large"] = "code_large"
    try:
        price, basis = tier_pricing.price_for_rung(
            "_test_code_large",
            cost_usd=None,
            tokens_in=1000,
            tokens_out=200,
            cache_read_tokens=None,
            price_table=CODE_LARGE_TABLE,
        )
    finally:
        del tier_pricing.RUNG_TO_ALIAS["_test_code_large"]
    assert price is None
    assert "ambiguous-occupant: 2 enabled rows" in basis


def test_cache_hit_rate_applied_when_confirmed_and_present(tier_pricing):
    tier_pricing.RUNG_TO_ALIAS["_test_flash"] = "code_large"
    single_occupant = {"code_large": [CODE_LARGE_TABLE["code_large"][0]]}
    try:
        price, basis = tier_pricing.price_for_rung(
            "_test_flash",
            cost_usd=None,
            tokens_in=1_000_000,
            tokens_out=1_000_000,
            cache_read_tokens=500_000,
            price_table=single_occupant,
        )
    finally:
        del tier_pricing.RUNG_TO_ALIAS["_test_flash"]
    # 500k miss @ 0.14/M + 500k cache-hit @ 0.0028/M + 1M out @ 0.28/M
    expected = round((500_000 * 0.14 + 500_000 * 0.0028) / 1_000_000 + 0.28, 6)
    assert (price, basis) == (expected, "registry-exact")


def test_no_cache_hit_rate_falls_back_to_list_price(tier_pricing):
    tier_pricing.RUNG_TO_ALIAS["_test_minimax"] = "code_large"
    single_occupant = {"code_large": [CODE_LARGE_TABLE["code_large"][1]]}
    try:
        price, basis = tier_pricing.price_for_rung(
            "_test_minimax",
            cost_usd=None,
            tokens_in=1_000_000,
            tokens_out=1_000_000,
            cache_read_tokens=500_000,  # present, but no confirmed cache rate
            price_table=single_occupant,
        )
    finally:
        del tier_pricing.RUNG_TO_ALIAS["_test_minimax"]
    # list price only: 1M in @ 0.30/M + 1M out @ 1.20/M, cache ignored
    assert (price, basis) == (1.50, "registry-exact")
