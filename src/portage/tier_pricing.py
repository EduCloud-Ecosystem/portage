#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
HB-2b: the explicit, honest mapping between `.claude/tiers.json` rung names
and `registry.yaml` aliases — the gap HB0-report.md §4 item 1 named as
"explicit HB-2 scope" and HB-2/HB-2b's own reports left open rather than
guess at.

WHY THIS IS A SMALL STATIC TABLE AND NOT A FULL RECONCILIATION. The two
vocabularies were never going to unify cleanly: `sonnet`/`opus` are Lane A,
subscription-billed through the native Max wallet, and CC-P6 deleted
`proprietary_code` from the registry OUTRIGHT — there is no row for them and
there should not be one (see that deletion's own comment in registry.yaml).
`local-big` and `sovereign-work` named a local-big-model tier and a Scale-2
sovereign-HPC tier that CW-04 §2.4 and the Scale-1 registry never built —
mapping them to something would be inventing a row, not recording one.

So this module maps ONLY where a real, unambiguous correspondence exists, and
says so explicitly for every rung that has no honest answer. `measure.py`
reads `RUNG_TO_ALIAS` and `price_for_rung()` reads `runner-reported cost`
first (from `failup.py`'s `--output-format json` capture) BEFORE ever
consulting the registry — for `sonnet`/`opus` that is the ONLY correct price
source, since it's what the Max wallet actually billed, and registry price
fields for those rungs would just be null anyway.
"""

from __future__ import annotations

# rung model string -> registry alias, or None with a reason if there isn't
# an honest one. Only rungs that actually appear in the shipped tiers files
# (.claude/tiers.local.json, tiers.educloud.json) are listed; an unlisted rung
# is a genuine gap, not an oversight — see NO_REGISTRY_EQUIVALENT.
RUNG_TO_ALIAS = {
    # Both code_small occupants (gemma4:12b, gemma4:e4b) are local and $0 —
    # the alias resolves to an exact price regardless of which one served a
    # given call, which is the one case here where "which occupant" doesn't
    # matter to the answer.
    "local-small": "code_small",
}

# Rungs with NO honest registry mapping, and why — read before adding one.
NO_REGISTRY_EQUIVALENT = {
    "local-big": "retired: CW-04 §2.4 dropped the larger local-model tier; "
    "no alias in the Scale-1 registry occupies this role.",
    "sovereign-work": "Scale-2 concept (sovereign HPC/vLLM); the Scale-1 "
    "registry has no row for it.",
    "sonnet": "Lane A, subscription-billed through the native Max wallet — "
    "registry.yaml's proprietary_code row was DELETED by CC-P6, not "
    "disabled, and should not be resurrected just for pricing. Use "
    "the runner's own reported total_cost_usd instead.",
    "opus": "same as sonnet.",
}


def price_for_rung(
    model: str,
    *,
    cost_usd: float | None,
    tokens_in: int | None,
    tokens_out: int | None,
    cache_read_tokens: int | None,
    price_table: dict,
) -> tuple[float | None, str]:
    """(price_usd, basis). `basis` is always present, even when price is None,
    so a caller can report WHY a number is missing instead of just that it is.

    Precedence, in order:
      1. `cost_usd` — the runner's own reported spend (HB-2b's
         `--output-format json` capture). Authoritative when present: it is
         what actually got billed, not an estimate from a price table.
      2. A registry lookup, only when every enabled occupant of the alias
         `model` maps to prices IDENTICALLY (not "there's only one occupant"
         — `code_small`'s two local occupants both cost $0, so which one
         served this call doesn't change the answer). A multi-occupant alias
         whose occupants differ (e.g. `code_large`: $0.14 vs $0.30 vs $3.00)
         can't be priced from the rung name alone, because which occupant
         actually served this call isn't recoverable from a
         `.claude/tiers.json` rung name, and guessing with the cheapest
         occupant would understate cost for exactly the calls that escalated
         past it.
      3. None, with a basis explaining which of the above didn't apply.
    """
    if cost_usd is not None:
        return cost_usd, "runner-reported"

    if model in NO_REGISTRY_EQUIVALENT:
        return None, f"no-registry-equivalent: {NO_REGISTRY_EQUIVALENT[model]}"

    alias = RUNG_TO_ALIAS.get(model)
    if alias is None:
        return None, "unmapped-rung"

    rows = [r for r in price_table.get(alias, []) if r.get("enabled")]
    price_keys = (
        "price_input_per_million",
        "price_output_per_million",
        "price_cache_hit_per_million",
    )
    distinct_prices = {tuple(r.get(k) for k in price_keys) for r in rows}
    # Ambiguity only matters when it changes the ANSWER. code_small has two
    # enabled occupants (gemma4:12b, gemma4:e4b) and both are $0 local — which
    # one served a given call is genuinely unrecoverable from the rung name,
    # but the price is the same either way, so this is not the case
    # `price_for_rung`'s docstring warns about (code_large's occupants differ
    # by an order of magnitude and DO need to be told apart).
    if not rows or len(distinct_prices) != 1:
        return None, f"ambiguous-occupant: {len(rows)} enabled rows for {alias!r}"

    row = rows[0]
    if tokens_in is None or tokens_out is None:
        return None, "no-token-counts"

    price_in = row.get("price_input_per_million")
    price_out = row.get("price_output_per_million")
    if price_in is None or price_out is None:
        return None, "registry-price-unconfirmed"

    cache_hit = row.get("price_cache_hit_per_million")
    cache_read_tokens = cache_read_tokens or 0
    if cache_hit is not None and cache_read_tokens:
        miss_tokens = max(0, tokens_in - cache_read_tokens)
        input_cost = (miss_tokens * price_in + cache_read_tokens * cache_hit) / 1_000_000
    else:
        # No confirmed cache-hit rate for this row (e.g. the Morph/MiniMax M3
        # row — see HB2b-report.md §3), or no cache reads on this attempt:
        # list price, not a discount that was never confirmed.
        input_cost = tokens_in * price_in / 1_000_000

    output_cost = tokens_out * price_out / 1_000_000
    return round(input_cost + output_cost, 6), "registry-exact"
