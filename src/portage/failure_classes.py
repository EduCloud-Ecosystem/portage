#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
The five-class failure taxonomy, named once.

Before this module, "the five classes" existed only as a fact you could derive
by reading two files: the `code` profile's four active reason codes
(`verifier-contract/schema/reason_codes.json` — `code.empty_diff`,
`code.lint_failed`, `code.typecheck_failed`, `code.tests_failed`) plus
`failup.py`'s own `unavailable:<marker>` category, which the contract
deliberately does not know about (SPEC.md section 2.1). Nothing imported both,
so nothing could add a sixth class to one side without silently omitting it
from the other.

`failup.py` imports this for `MAX_ATTEMPTS_PER_TIER` and `classify()`;
`measure.py` imports it for `CLASSES`, so a per-class breakdown always covers
exactly this set. Neither file's own reason-string vocabulary changes — this
module maps into it, not the other way around, so a month-old
`failup-log.jsonl` entry classifies exactly the same today as it always would
have.
"""

from __future__ import annotations

# Legacy `reason` strings failup.py has written since before the verifier
# contract existed (see failup.py::_LEGACY_REASON). The fifth class,
# `unavailable`, is not a literal member of this set — it's every string that
# starts with `unavailable:`, checked by `classify()` below rather than listed,
# because the marker suffix (`unavailable:503`, `unavailable:timeout`, ...) is
# diagnostic detail that stays in the raw log, not a taxonomy member of its own.
CAPABILITY_CLASSES = frozenset(
    {
        "empty-diff",
        "lint-failed",
        "typecheck-failed",
        "tests-failed",
    }
)

UNAVAILABLE_CLASS = "unavailable"

CLASSES = CAPABILITY_CLASSES | {UNAVAILABLE_CLASS}

# Same-tier retries before a tier's failure escalates the ladder (HB-2). One
# retry, so "hard two-retry cap per class" reads as "two attempts, then move
# on" rather than "retry until the cap is proven wrong" — a class that fails
# twice in a row at one tier is treated as that tier's answer, not noise.
MAX_ATTEMPTS_PER_TIER = 2


def classify(reason: str) -> str:
    """Map a failup-log `reason` string onto one of the five classes.

    Raises on anything else, on purpose: a new reason string that isn't one of
    the four legacy capability strings and doesn't start with `unavailable:` is
    either a bug (a typo in a caller) or a genuine sixth class that has to be
    added here deliberately, not absorbed silently into a per-class count that
    would then undercount it.
    """
    if reason in CAPABILITY_CLASSES:
        return reason
    if reason.startswith("unavailable:"):
        return UNAVAILABLE_CLASS
    raise ValueError(
        f"unrecognized failure reason, not in the five-class taxonomy: {reason!r}"
    )
