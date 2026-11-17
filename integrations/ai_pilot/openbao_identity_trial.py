# SPDX-License-Identifier: Apache-2.0
"""Bounded real-server identity/custody controls; never calls an LLM provider."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from gateway import open_once  # noqa: F401
from openbao_credentials import OpenBaoCredential
from openbao_identity import (
    OPERATOR,
    ROLE_PATH,
    SECRET_ID_PATH,
    checked,
    enroll,
    prepare_binding,
    provision,
    read_private_json,
)
from openbao_local import SECRET_PATH, LocalBao, private


def run(binary, output, custody):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {
        "passed": [],
        "failed": [],
        "paid_requests": 0,
        "cleanup": False,
        "custody_import_confirmed": False,
    }
    bao = None
    try:
        bao = LocalBao(binary, output / "bao")
        bao.start()
        bao.initialize()
        bao.put("synthetic-provider-v1")
        provision(bao, custody)
        assert bao.root_token is None and bao.unseal is None
        report["passed"].append("bootstrap-root-revoked-and-unseal-forgotten")
        record = read_private_json(custody)
        bad = dict(record, ca_sha256="0" * 64)
        wrong = custody.parent / "wrong-binding.json"
        private(wrong, json.dumps(bad))
        try:
            prepare_binding(wrong, output / "not-created")
        except ValueError:
            report["passed"].append("custody-cannot-target-different-ca")
        else:
            raise AssertionError("CA mismatch accepted")
        binding = output / "binding.json"
        prepare_binding(custody, binding)
        saved = binding.read_text()
        report["identity"] = enroll(bao, binding)
        assert not binding.exists()
        report["passed"].append("wrapped-approle-login-and-delivery-removal")
        source = OpenBaoCredential(bao.address, bao.ca, bao.token_file)
        assert source() == "synthetic-provider-v1"
        service = bao.token_file.read_text()
        private(binding, saved)
        try:
            enroll(bao, binding)
        except RuntimeError:
            report["passed"].append("wrapping-token-replay-refused")
        else:
            raise AssertionError("wrapping replay accepted")
        binding.unlink()
        for label, method, path, body in (
            (
                "service-cannot-write-key",
                "POST",
                SECRET_PATH,
                {"data": {"api_key": "tamper"}},
            ),
            (
                "service-cannot-read-other-component",
                "GET",
                "secret/data/cairn/signing",
                None,
            ),
            ("service-cannot-enumerate-secrets", "LIST", "secret/metadata", None),
            ("service-cannot-mint-identity", "POST", SECRET_ID_PATH, {}),
            (
                "service-cannot-change-policy",
                "PUT",
                "sys/policies/acl/portage-reader",
                {"policy": 'path "*" { capabilities=["sudo"] }'},
            ),
            ("service-cannot-renew-itself", "POST", "auth/token/renew-self", {}),
        ):
            assert bao.request(method, path, body, service)[0] == 403
            report["passed"].append(label)
        operator = checked(
            bao,
            "POST",
            "auth/userpass/login/" + OPERATOR,
            {"password": record["operator_password"]},
        )["auth"]["client_token"]
        assert (
            bao.request(
                "PUT", "sys/policies/acl/portage-reader", {"policy": "bad"}, operator
            )[0]
            == 403
        )
        report["passed"].append("operator-cannot-change-policy")
        checked(
            bao,
            "POST",
            SECRET_PATH,
            {"data": {"api_key": "synthetic-provider-v2"}},
            operator,
        )
        assert source() == "synthetic-provider-v2"
        report["passed"].append("operator-rotation-observed-without-gateway-restart")
        # Directly inspect one-use SecretID consumption independently of wrapping.
        role = checked(bao, "GET", ROLE_PATH + "/role-id", token=operator)["data"][
            "role_id"
        ]
        sid = checked(bao, "POST", SECRET_ID_PATH, {}, operator)["data"]["secret_id"]
        assert (
            bao.request(
                "POST", "auth/approle/login", {"role_id": role, "secret_id": sid}
            )[0]
            == 200
        )
        assert bao.request(
            "POST", "auth/approle/login", {"role_id": role, "secret_id": sid}
        )[0] in (400, 403)
        report["passed"].append("secret-id-single-use-enforced-by-server")
        # A wrapper from the wrong origin must never be consumed as an identity.
        status, wrongwrap = bao.request(
            "GET", SECRET_PATH, token=operator, wrap_ttl="60s"
        )
        assert status == 200
        private(
            binding,
            json.dumps(
                {
                    "version": 1,
                    "role_id": role,
                    "wrapped_token": wrongwrap["wrap_info"]["token"],
                }
            ),
        )
        try:
            enroll(bao, binding)
        except ValueError:
            report["passed"].append("wrong-wrapping-origin-refused")
        else:
            raise AssertionError("wrong wrapper accepted")
        binding.unlink()
        expired = checked(bao, "POST", SECRET_ID_PATH, {}, operator, wrap_ttl="1s")[
            "wrap_info"
        ]["token"]
        private(
            binding, json.dumps({"version": 1, "role_id": role, "wrapped_token": expired})
        )
        time.sleep(1.2)
        try:
            enroll(bao, binding)
        except RuntimeError:
            report["passed"].append("expired-wrapping-token-refused")
        else:
            raise AssertionError("expired wrapper accepted")
        binding.unlink()
        # Keep an unused ID in the backup, demonstrating restoration invalidates it.
        pending = checked(bao, "POST", SECRET_ID_PATH, {}, operator)["data"]["secret_id"]
        checked(bao, "POST", "auth/token/revoke-self", token=operator)
        ledger = output / "independent-ledger.json"
        private(ledger, json.dumps({"unresolved": 1, "reserved": 25}))
        ledger_before = ledger.read_bytes()
        bao.stop()
        backup = bao.backup()
        bao.restore(backup)
        bao.start()
        assert bao.request("GET", "sys/health")[1]["sealed"]
        report["passed"].append("restored-server-stays-sealed-before-operator-recovery")
        # Fresh process has no bootstrap root or memory-only unseal share.
        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("openbao_identity.py")),
                "--custody-file",
                str(custody),
                "--binding-file",
                str(binding),
                "--recover",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env={"PATH": os.environ["PATH"], "LANG": "C"},
        )
        private(output / "operator-recovery.log", child.stdout + child.stderr)
        assert child.returncode == 0, "fresh-process recovery failed; inspect private log"
        assert bao.request("GET", SECRET_PATH, token=service)[0] == 403
        report["passed"].append("restored-service-token-revoked-before-reenrollment")
        assert bao.request(
            "POST", "auth/approle/login", {"role_id": role, "secret_id": pending}
        )[0] in (400, 403)
        report["passed"].append("restored-unused-secret-id-destroyed")
        enroll(bao, binding)
        assert source() == "synthetic-provider-v2"
        assert ledger.read_bytes() == ledger_before
        report["passed"].append(
            "fresh-process-custody-recovery-preserves-independent-ledger"
        )
        sensitive = [record["unseal_key"].encode(), record["operator_password"].encode()]
        for f in output.rglob("*"):
            if f.is_file():
                assert not any(secret in f.read_bytes() for secret in sensitive)
        report["passed"].append("no-operator-recovery-material-in-runtime-or-backup")
    except BaseException as exc:
        report["failed"].append(type(exc).__name__)
        raise
    finally:
        if bao:
            bao.close()
            report["cleanup"] = bao.proc is None and not bao.token_file.exists()
        private(output / "result.json", json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bao", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--custody-file", type=Path, required=True)
    parser.add_argument("--execute-local", action="store_true", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    run(args.bao, args.output.resolve(), args.custody_file.resolve())
