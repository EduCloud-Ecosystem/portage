#!/usr/bin/env python3
"""Stand-in test gate for failup.py tests: pass iff marker.txt reads PASS."""

import pathlib
import sys

marker = pathlib.Path("marker.txt")
sys.exit(0 if marker.is_file() and marker.read_text().strip() == "PASS" else 1)
