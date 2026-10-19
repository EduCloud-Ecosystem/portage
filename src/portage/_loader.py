#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared "load a sibling module by path" helper for the single-file scripts.

measure.py, distill.py and failup.py are `uv run --script` utilities, not
package members, and tests load them by path too (tests/conftest.py) — so a
plain `import runlog` would resolve only when sys.path happens to contain
src/portage. Loading by path works in every mode and adds no dependency:
runlog.py, tier_pricing.py, failure_classes.py and code_profile.py are
stdlib-only, like everything else in this repo's core.

Each script bootstraps THIS module by path once, then asks it for every
sibling it needs — replacing the load-by-path boilerplate those scripts used
to copy from each other per module.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_cache: dict[str, object] = {}


def load_by_path(module_name: str, path: Path):
    """Executes the module at `path` and returns it.

    Cached by `module_name`: failup.py's lazy `failure_classes()` /
    `code_profile()` may be called repeatedly, and a module body must never
    re-execute — harmless for today's stateless siblings, but a cache makes
    that a rule instead of an accident.
    """
    if module_name in _cache:
        return _cache[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _cache[module_name] = module
    return module
