# SPDX-License-Identifier: Apache-2.0
"""Launch the pinned NHANES evaluator with a disposable OpenBao credential service.

Only the already-authorized source-fixed instructor question can reach the real
provider, under the existing seven-transport/$0.175 reservation cap. No raw key
is passed to the child. Bootstrap, server and tokens are removed/stopped on exit.
"""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from gateway import open_once  # noqa: F401 -- initializes Portage source import path
from openbao_local import LocalBao, private
from openrouter_adapter import load_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "bao",
        "provider-key-file",
        "waypoint",
        "driver",
        "cairn",
        "belay",
        "kernel-python",
        "kernel-lock",
        "output",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("grader-image", "checkout-image", "waypoint-pin"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--execute-approved", action="store_true", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    portage = Path(__file__).resolve().parents[2]
    report = {
        "synthetic_inputs_only": True,
        "live_provider": True,
        "cleanup": False,
        "failed": [],
        "secret_leak_scan": "not_run",
    }
    bao = None
    try:
        for repo, pin in ((args.waypoint, args.waypoint_pin), (portage, None)):
            head = subprocess.check_output(
                ["git", "-C", repo, "rev-parse", "HEAD"], text=True
            ).strip()
            dirty = subprocess.check_output(
                ["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"],
                text=True,
            ).strip()
            if dirty or (pin is not None and head != pin):
                raise ValueError("source checkout differs from frozen trial")
            report["waypoint_source" if pin else "portage_source"] = head
        key = load_key(args.provider_key_file)
        bao = LocalBao(args.bao, output / "bao")
        bao.start()
        bao.initialize()
        bao.put(key)
        command = [
            str(args.driver),
            str(args.waypoint / "course-workspace/rehearsal/nhanes_desktop.py"),
            "--cairn",
            str(args.cairn),
            "--belay",
            str(args.belay),
            "--kernel-python",
            str(args.kernel_python),
            "--kernel-lock",
            str(args.kernel_lock),
            "--grader-image",
            args.grader_image,
            "--checkout-image",
            args.checkout_image,
            "--output",
            str(output / "workflow"),
            "--execute-synthetic",
            "--tutor-mode",
            "live",
            "--live-portage",
            str(portage),
            "--execute-approved",
            "--openbao-address",
            bao.address,
            "--openbao-ca",
            str(bao.ca),
            "--openbao-token-file",
            str(bao.token_file),
        ]
        # Preserve only execution prerequisites; never inherit unrelated provider secrets.
        env = {
            name: os.environ[name]
            for name in (
                "PATH",
                "HOME",
                "LANG",
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "GOTOOLCHAIN",
            )
            if name in os.environ
        }
        with (output / "workflow.log").open("w") as log:
            child = subprocess.run(
                command,
                cwd=args.waypoint,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=660,
            )
        report["workflow_exit_code"] = child.returncode
        workflow = json.loads((output / "workflow/result.json").read_text())
        report["workflow"] = workflow
        if child.returncode or workflow["failed"] or not workflow["cleanup"]:
            raise RuntimeError("classroom acceptance failed; do not repeat unknown work")
        audits = [json.loads(line) for line in bao.audit.read_text().splitlines()]
        reads = [
            row
            for row in audits
            if row.get("type") == "request"
            and row.get("request", {}).get("path") == "secret/data/portage/provider"
            and row["request"].get("operation") == "read"
        ]
        assert len(reads) == workflow["model_transports"]
        report["bao_credential_reads"] = len(reads)
        report["openbao_binary_sha256"] = bao.binary_sha256
        report["audit_sha256"] = hashlib.sha256(bao.audit.read_bytes()).hexdigest()
        # Evidence lives in a private output tree. Check every regular file, not
        # just stdout, before permitting any sanitized report to be published.
        sensitive = (key.encode(), bao.token_file.read_bytes(), bao.root_token.encode())
        leaks = []
        for path in output.rglob("*"):
            if path.is_file() and path != bao.token_file:
                raw = path.read_bytes()
                if any(value in raw for value in sensitive):
                    leaks.append(str(path.relative_to(output)))
        report["secret_leak_scan"] = "passed" if not leaks else "failed"
        if leaks:
            raise RuntimeError("private artifact leak; withhold all artifact publication")
    except BaseException as exc:
        report["failed"].append(type(exc).__name__)
        raise
    finally:
        if bao:
            bao.close()
            report["cleanup"] = bao.proc is None and not bao.token_file.exists()
        private(output / "result.json", json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {key: value for key, value in report.items() if key != "workflow"},
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
