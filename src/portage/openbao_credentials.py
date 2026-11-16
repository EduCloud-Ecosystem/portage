# SPDX-License-Identifier: Apache-2.0
"""Opt-in local TLS OpenBao KV reader; no caching, retries or secret logging."""

import http.client
import json
import os
import re
import socket
import ssl
import stat
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from pilot_ledger import Denied


def private_token(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise ValueError("private token file required")
        token = stream.read(4097).strip()
    if (
        not token
        or len(token) > 4096
        or not token.isascii()
        or any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in token)
    ):
        raise ValueError("invalid token file")
    return token


class OpenBaoCredential:
    """One exact KV-v2 path, TLS loopback only. Auth is service-owned, not learner-owned.

    The caller must recheck its authority/deadline after this bounded I/O and
    before admission. Removing a KV value does not revoke a vendor API key.
    """

    def __init__(self, address, ca_file, token_file, path="secret/data/portage/provider"):
        parsed = urlsplit(address)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "127.0.0.1"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or not parsed.port
        ):
            raise ValueError("local OpenBao requires an explicit TLS loopback port")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+/data/[a-zA-Z0-9_/-]+", path) or "//" in path:
            raise ValueError("exact KV-v2 path required")
        self.port = parsed.port
        self.path = "/v1/" + path
        self.token_file = Path(token_file)
        self.context = ssl.create_default_context(cafile=str(ca_file))
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2

    def __call__(self):
        connection = None
        timer = None
        try:
            token = private_token(self.token_file)
            deadline = time.monotonic() + 2
            connection = http.client.HTTPSConnection(
                "127.0.0.1", self.port, timeout=2, context=self.context
            )
            connection.connect()
            transport = connection.sock

            def interrupt():
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("secret deadline expired")
            transport.settimeout(remaining)
            timer = threading.Timer(remaining, interrupt)
            timer.daemon = True
            timer.start()
            connection.request("GET", self.path, headers={"X-Vault-Token": token})
            response = connection.getresponse()
            # Refuse redirects, access denial, seal and any server error alike.
            if response.status != 200:
                raise ValueError("secret unavailable")
            raw = response.read(16385)
            if len(raw) > 16384 or time.monotonic() >= deadline:
                raise ValueError("secret response too large")
            value = json.loads(raw)["data"]["data"]["api_key"]
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 4096
                or not value.isascii()
                or any(not 33 <= ord(c) <= 126 for c in value)
            ):
                raise ValueError("invalid credential")
            return value
        except Exception:
            # Do not expose URLs, tokens, response bodies or configuration in errors.
            raise Denied("credential_unavailable", 503) from None
        finally:
            if timer is not None:
                timer.cancel()
            if connection is not None:
                connection.close()
