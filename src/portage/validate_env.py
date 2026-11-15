#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""validate_env.py — asserts every `os.environ/VAR` reference in a rendered
LiteLLM config actually resolves (HB-0 Step 1, Gate 1).

Walks the rendered config.yaml AND its included model_list file (LiteLLM's
`include:` directive), collects every `os.environ/VARNAME` string anywhere in
the YAML tree, and checks `os.environ`. Exits non-zero listing every missing
variable if any are absent; exits 0 with a summary otherwise. Wired to run
before the proxy starts (docker-compose.yaml's litellm service command, or a
pre-boot Makefile/script target).

    python src/portage/validate_env.py --config ../portage-local/litellm/config.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

PREFIX = "os.environ/"


def _walk_strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)
    elif isinstance(node, str):
        yield node


def collect_env_refs(doc: dict) -> set[str]:
    refs = set()
    for s in _walk_strings(doc):
        if s.startswith(PREFIX):
            refs.add(s[len(PREFIX) :])
    return refs


def load_with_includes(config_path: Path) -> dict:
    doc = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    merged = dict(doc)
    includes = merged.pop("include", [])
    for inc in includes:
        inc_path = config_path.parent / inc
        inc_doc = yaml.safe_load(inc_path.read_text(encoding="utf-8")) or {}
        merged.update(inc_doc)
    return merged


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", required=True, type=Path)
    args = p.parse_args(argv)

    try:
        doc = load_with_includes(args.config)
    except (OSError, yaml.YAMLError) as e:
        print(f"validate_env: could not load {args.config}: {e}", file=sys.stderr)
        return 1

    refs = collect_env_refs(doc)
    missing = sorted(v for v in refs if v not in os.environ)

    if missing:
        print(
            f"validate_env: {len(missing)} of {len(refs)} referenced variable(s) "
            "MISSING:",
            file=sys.stderr,
        )
        for v in missing:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print(f"validate_env: all {len(refs)} referenced variable(s) resolve. OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
