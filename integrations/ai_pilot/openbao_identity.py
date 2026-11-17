# SPDX-License-Identifier: Apache-2.0
"""Operator-mediated local pilot identity; no runtime root or unseal credentials.

The private export is a staging artifact for an institutional password manager,
not proof of completed custody. Never mount it in a classroom workspace.
"""

import argparse
import hashlib
import json
import os
import secrets
import ssl
import stat
from pathlib import Path

from openbao_local import SECRET_PATH, LocalBao, private

ROLE = "portage-classroom"
ROLE_PATH = "auth/approle/role/" + ROLE
SECRET_ID_PATH = ROLE_PATH + "/secret-id"
OPERATOR = "pilot-recovery"
OPERATOR_POLICY = "portage-pilot-operator"


def read_private_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as src:
        info = os.fstat(src.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise ValueError("owned private regular file required")
        data = src.read(16385)
    if len(data) > 16384:
        raise ValueError("private record exceeds limit")
    return json.loads(data)


def checked(bao, method, path, body=None, token=None, **kwargs):
    status, data = bao.request(method, path, body, token, **kwargs)
    if status not in (200, 204):
        raise RuntimeError(f"OpenBao identity request refused ({status})")
    return data


def provision(bao, custody_file):
    """Called once after initialize/put; revoke root before returning."""
    custody_file = Path(custody_file).absolute()
    # The actual local deployment contract keeps operator recovery out of both
    # the repo and the entire runtime/evidence tree. Tests use distinct roots.
    if custody_file.exists() or custody_file.is_symlink():
        raise ValueError("custody export must be a new file")
    for forbidden in (Path(__file__).resolve().parents[2], bao.directory.parent):
        if custody_file.resolve().is_relative_to(forbidden):
            raise ValueError("custody belongs outside source and runtime output")
    if custody_file.parent.resolve() != custody_file.parent:
        raise ValueError("custody parent may not contain symlinks")
    info = custody_file.parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("private operator custody directory required")
    original = bao.token_file.read_text()
    bao.admin("POST", "auth/token/revoke", {"token": original})
    bao.token_file.unlink()
    bao.admin("POST", "sys/auth/approle", {"type": "approle"})
    bao.admin("POST", "sys/auth/userpass", {"type": "userpass"})
    bao.admin(
        "POST",
        ROLE_PATH,
        {
            "bind_secret_id": True,
            "secret_id_num_uses": 1,
            "secret_id_ttl": "60s",
            "secret_id_bound_cidrs": ["127.0.0.1/32"],
            "token_policies": ["portage-reader"],
            "token_no_default_policy": True,
            "token_ttl": "20m",
            "token_max_ttl": "20m",
            "token_explicit_max_ttl": "20m",
            "token_bound_cidrs": ["127.0.0.1/32"],
            "token_type": "service",
        },
    )
    policy = f'''
path "{SECRET_PATH}" {{ capabilities = ["read", "create", "update"] }}
path "{ROLE_PATH}/role-id" {{ capabilities = ["read"] }}
path "{SECRET_ID_PATH}" {{ capabilities = ["update", "list"] }}
path "{ROLE_PATH}/secret-id-accessor/destroy" {{ capabilities = ["update"] }}
path "sys/leases/revoke-prefix/auth/approle/login" {{ capabilities = ["update", "sudo"] }}
path "auth/token/revoke-self" {{ capabilities = ["update"] }}
'''
    bao.admin("PUT", "sys/policies/acl/" + OPERATOR_POLICY, {"policy": policy})
    password = secrets.token_urlsafe(48)
    bao.admin(
        "POST",
        "auth/userpass/users/" + OPERATOR,
        {
            "password": password,
            "token_policies": [OPERATOR_POLICY],
            "token_no_default_policy": True,
            "token_ttl": "5m",
            "token_max_ttl": "5m",
            "token_explicit_max_ttl": "5m",
            "token_bound_cidrs": ["127.0.0.1/32"],
        },
    )
    record = {
        "version": 1,
        "purpose": "operator-only-password-manager-import",
        "instance": str(bao.directory),
        "address": bao.address,
        "ca_sha256": hashlib.sha256(bao.ca.read_bytes()).hexdigest(),
        "unseal_key": bao.unseal,
        "operator": OPERATOR,
        "operator_password": password,
    }
    private(custody_file, json.dumps(record) + "\n")
    # Durable export must succeed before destroying the only bootstrap reference.
    assert read_private_json(custody_file) == record
    root = bao.root_token
    bao.admin("POST", "auth/token/revoke-self")
    assert bao.request("GET", "auth/token/lookup-self", token=root)[0] == 403
    bao.root_token = bao.unseal = None


def connect(record):
    from urllib.parse import urlsplit

    parsed = urlsplit(record["address"])
    if (
        record.get("version") != 1
        or parsed.scheme != "https"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or record.get("operator") != OPERATOR
    ):
        raise ValueError("invalid local recovery binding")
    bao = object.__new__(LocalBao)
    bao.directory = Path(record["instance"])
    bao.address, bao.port = record["address"], parsed.port
    bao.ca, bao.token_file = bao.directory / "tls.crt", bao.directory / "service.token"
    if hashlib.sha256(bao.ca.read_bytes()).hexdigest() != record["ca_sha256"]:
        raise ValueError("recovery CA binding mismatch")
    bao.context = ssl.create_default_context(cafile=str(bao.ca))
    bao.root_token = bao.unseal = None
    return bao


def prepare_binding(custody_file, binding_file, *, recover=False):
    """Operator process. Restores need fresh credentials before admission resumes."""
    record = read_private_json(custody_file)
    bao = connect(record)
    status, health = bao.request("GET", "sys/health")
    if health.get("sealed"):
        if not recover:
            raise ValueError("sealed instance requires explicit recovery invalidation")
        checked(bao, "POST", "sys/unseal", {"key": record["unseal_key"]})
        # Readiness is bounded; unsealing does not make the node immediately active.
        import time

        for _ in range(150):
            if bao.request("GET", "sys/health")[0] == 200:
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("unsealed server did not become ready")
    operator = checked(
        bao,
        "POST",
        "auth/userpass/login/" + OPERATOR,
        {"password": record["operator_password"]},
    )["auth"]["client_token"]
    try:
        if recover:
            # Auth tokens can be resurrected by restore. Invalidate every token
            # issued via this dedicated mount and all pending SecretIDs first.
            checked(
                bao,
                "POST",
                "sys/leases/revoke-prefix/auth/approle/login",
                {"sync": True},
                token=operator,
            )
            status, ids = bao.request("LIST", SECRET_ID_PATH, token=operator)
            if status not in (200, 404):
                raise RuntimeError("cannot enumerate restored SecretIDs")
            for accessor in ids.get("data", {}).get("keys", []):
                checked(
                    bao,
                    "POST",
                    ROLE_PATH + "/secret-id-accessor/destroy",
                    {"secret_id_accessor": accessor},
                    operator,
                )
        role_id = checked(bao, "GET", ROLE_PATH + "/role-id", token=operator)["data"][
            "role_id"
        ]
        wrapped = checked(bao, "POST", SECRET_ID_PATH, {}, operator, wrap_ttl="60s")[
            "wrap_info"
        ]
        private(
            binding_file,
            json.dumps(
                {"version": 1, "role_id": role_id, "wrapped_token": wrapped["token"]}
            )
            + "\n",
        )
    finally:
        checked(bao, "POST", "auth/token/revoke-self", token=operator)
    return bao


def enroll(bao, binding_file):
    """Service process: only a wrapped, single-use SecretID is delivered."""
    binding = read_private_json(binding_file)
    if set(binding) != {"version", "role_id", "wrapped_token"} or binding["version"] != 1:
        raise ValueError("invalid service binding")
    wrapped = binding["wrapped_token"]
    info = checked(bao, "POST", "sys/wrapping/lookup", token=wrapped)["data"]
    if info["creation_path"] != SECRET_ID_PATH or not 0 < info["creation_ttl"] <= 60:
        raise ValueError("wrong wrapping origin or lifetime")
    data = checked(bao, "POST", "sys/wrapping/unwrap", token=wrapped)["data"]
    auth = checked(
        bao,
        "POST",
        "auth/approle/login",
        {"role_id": binding["role_id"], "secret_id": data["secret_id"]},
    )["auth"]
    if (
        set(auth["policies"]) != {"portage-reader"}
        or not 0 < auth["lease_duration"] <= 1200
    ):
        raise ValueError("unexpected service authority")
    private(bao.token_file, auth["client_token"])
    Path(binding_file).unlink()
    return {
        "identity": ROLE,
        "ttl_seconds": auth["lease_duration"],
        "policies": auth["policies"],
        "wrapped_delivery": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--custody-file", type=Path, required=True)
    parser.add_argument("--binding-file", type=Path, required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    # This operator entrypoint never prints recovery material, tokens or passwords.
    prepare_binding(args.custody_file, args.binding_file, recover=args.recover)
    print(json.dumps({"operator_handoff_prepared": True, "recovery": args.recover}))


if __name__ == "__main__":
    main()
