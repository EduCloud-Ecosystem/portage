# SPDX-License-Identifier: Apache-2.0
"""Disposable real OpenBao server for explicit local trials, never production."""

import hashlib
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import time
from pathlib import Path

VERSION = "2.7.2"
ARCHIVE_SHA256 = "2b4fc131910f4b075b2e1c9a9de67c461489491a8f03fbdc73387294d67d9547"
SECRET_PATH = "secret/data/portage/provider"


def private(path, content):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(content)


class LocalBao:
    """Finite single-node Raft rehearsal with TLS and audit, no dev-mode server."""

    def __init__(self, binary, directory):
        self.binary = Path(binary).resolve()
        self.directory = Path(directory).resolve()
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.proc = None
        self.log = None
        self.root_token = None
        self.unseal = None
        self.version = subprocess.check_output(
            [self.binary, "version"], text=True
        ).strip()
        if not self.version.startswith("OpenBao v" + VERSION + " "):
            raise ValueError("unexpected OpenBao version")
        self.binary_sha256 = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.address = f"https://127.0.0.1:{self.port}"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cluster_port = sock.getsockname()[1]
        self.ca = self.directory / "tls.crt"
        self.token_file = self.directory / "service.token"
        self.config = self.directory / "server.hcl"
        self.storage = self.directory / "storage"
        self.audit = self.directory / "audit.jsonl"
        private(
            self.directory / "tls.cnf",
            """[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=portage-openbao-local
[ext]
subjectAltName=IP:127.0.0.1
basicConstraints=critical,CA:TRUE
keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign
""",
        )
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-config",
                str(self.directory / "tls.cnf"),
                "-keyout",
                str(self.directory / "tls.key"),
                "-out",
                str(self.ca),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (self.directory / "tls.key").chmod(0o600)
        private(
            self.config,
            f'''ui = false
api_addr = "{self.address}"
cluster_addr = "https://127.0.0.1:{cluster_port}"
storage "raft" {{
  path = "{self.storage}"
  node_id = "portage-local-trial"
}}
listener "tcp" {{
  address = "127.0.0.1:{self.port}"
  cluster_address = "127.0.0.1:{cluster_port}"
  tls_cert_file = "{self.ca}"
  tls_key_file = "{self.directory / "tls.key"}"
}}
audit "file" "local-trial" {{
  options {{ file_path = "{self.audit}" }}
}}
''',
        )
        self.context = ssl.create_default_context(cafile=str(self.ca))

    def request(self, method, path, body=None, token=None):
        conn = http.client.HTTPSConnection(
            "127.0.0.1", self.port, context=self.context, timeout=30
        )
        try:
            conn.request(
                method,
                "/v1/" + path,
                body=json.dumps(body) if body is not None else None,
                headers={
                    "Content-Type": "application/json",
                    "X-Vault-Token": token or "",
                },
            )
            response = conn.getresponse()
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("bounded response exceeded")
            return response.status, json.loads(raw) if raw else {}
        finally:
            conn.close()

    def admin(self, method, path, body=None):
        status, result = self.request(method, path, body, self.root_token)
        if status not in (200, 204):
            raise RuntimeError(f"OpenBao setup refused: status {status}, path {path}")
        return result

    def start(self):
        if self.proc is not None:
            raise ValueError("already started")
        self.log = open(self.directory / "server.log", "ab")
        self.proc = subprocess.Popen(
            [self.binary, "server", "-config", self.config],
            stdout=self.log,
            stderr=self.log,
            cwd=self.directory,
            env={"PATH": os.defpath, "LANG": "C"},
            start_new_session=True,
        )
        for _ in range(100):
            if self.proc.poll() is not None:
                raise RuntimeError("OpenBao exited; inspect private server.log")
            try:
                self.request("GET", "sys/health")
                return
            except (OSError, http.client.HTTPException):
                time.sleep(0.1)
        raise TimeoutError("OpenBao startup exceeded ten seconds")

    def initialize(self):
        result = self.admin(
            "POST", "sys/init", {"secret_shares": 1, "secret_threshold": 1}
        )
        self.unseal, self.root_token = result["keys_base64"][0], result["root_token"]
        # Bootstrap values remain memory-only; trial backups cannot be recovered
        # after process exit. Production key custody is explicitly not qualified.
        self.unseal_server()
        self.admin(
            "POST", "sys/mounts/secret", {"type": "kv", "options": {"version": "2"}}
        )
        policy = f'path "{SECRET_PATH}" {{ capabilities = ["read"] }}'
        self.admin("PUT", "sys/policies/acl/portage-reader", {"policy": policy})
        self.admin(
            "PUT",
            "sys/policies/acl/no-provider",
            {"policy": 'path "secret/data/unrelated" { capabilities = ["read"] }'},
        )
        self.install_token()

    def unseal_server(self):
        self.admin("POST", "sys/unseal", {"key": self.unseal})
        for _ in range(150):
            status, state = self.request("GET", "sys/health")
            if status == 200 and not state["sealed"] and not state["standby"]:
                return
            time.sleep(0.1)
        raise TimeoutError("OpenBao active-node readiness exceeded fifteen seconds")

    def issue(self, policy="portage-reader", ttl="20m"):
        return self.admin(
            "POST",
            "auth/token/create-orphan",
            {
                "policies": [policy],
                "no_default_policy": True,
                "renewable": False,
                "ttl": ttl,
                "explicit_max_ttl": ttl,
            },
        )["auth"]["client_token"]

    def install_token(self, **kwargs):
        token = self.issue(**kwargs)
        private(self.token_file, token)
        return token

    def put(self, value):
        self.admin("POST", SECRET_PATH, {"data": {"api_key": value}})

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
            self.proc = None
        if self.log:
            self.log.close()
            self.log = None

    def backup(self):
        if self.proc is not None:
            raise ValueError("file backend backup requires a stopped server")
        target = self.directory / "backup"
        shutil.copytree(self.storage, target)
        return target

    def restore(self, backup):
        if self.proc is not None:
            raise ValueError("restore requires a stopped server")
        # Retain failed state; never overwrite the evidence or any Portage ledger.
        self.storage.rename(self.directory / "storage-before-restore")
        shutil.copytree(backup, self.storage)

    def close(self):
        self.stop()
        self.token_file.unlink(missing_ok=True)
        self.root_token = self.unseal = None
