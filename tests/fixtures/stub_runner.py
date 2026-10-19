#!/usr/bin/env python3
"""Fake 'agent' for failup.py tests. Zero network, zero model calls.

Reads STUB_PLAN (comma-separated: ok|capability|availability) and walks one
entry per invocation, tracked by STUB_COUNTER_FILE (clamps to the last entry
if called more times than the plan has). Mirrors what a real runner's outcome
looks like from failup.py's point of view: an "availability" call never
touches the repo and prints a marker failup.py's runner_availability_failure()
must catch; "capability"/"ok" calls write marker.txt for tests/fixtures/
check_marker.py to grade.
"""

import os
import pathlib
import sys


def main():
    counter_path = pathlib.Path(os.environ["STUB_COUNTER_FILE"])
    plan = os.environ.get("STUB_PLAN", "ok").split(",")
    n = int(counter_path.read_text()) if counter_path.is_file() else 0
    counter_path.write_text(str(n + 1))
    mode = plan[min(n, len(plan) - 1)]

    if mode == "availability":
        sys.stderr.write("APIConnectionError: 503 Service Unavailable (stub)\n")
        sys.exit(1)

    marker = pathlib.Path("marker.txt")
    marker.write_text("FAIL" if mode == "capability" else "PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
