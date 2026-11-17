# SPDX-License-Identifier: Apache-2.0
"""Offline regressions for secret denial, input isolation and accounting seams."""

import sys
from pathlib import Path

import pytest
from test_pilot_gateway import Fixture, server  # noqa: F401

sys.path.insert(0, str(Path(__file__).parents[1] / "src/portage"))
from openbao_credentials import OpenBaoCredential, private_token  # noqa: E402
from pilot_ledger import Denied  # noqa: E402


@pytest.mark.parametrize(
    "address",
    [
        "http://127.0.0.1:8200",
        "https://example.com:8200",
        "https://127.0.0.1",
        "https://user:pass@127.0.0.1:8200",
        "https://127.0.0.1:8200/other",
        "https://127.0.0.1:8200?redirect=1",
    ],
)
def test_only_explicit_local_tls_address(address):
    with pytest.raises(ValueError):
        OpenBaoCredential(address, "/missing", "/missing")


@pytest.mark.parametrize(
    "path", ["secret/data/../admin", "secret/data/a?x=1", "secret//data/a"]
)
def test_exact_secret_path(path):
    with pytest.raises(ValueError):
        OpenBaoCredential("https://127.0.0.1:8200", "/missing", "/missing", path)


def test_private_token_permissions_links_and_header_injection(tmp_path):
    path = tmp_path / "token"
    path.write_text("test-token")
    path.chmod(0o600)
    assert private_token(path) == "test-token"
    link = tmp_path / "symlink"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_token(link)
    hardlink = tmp_path / "hardlink"
    hardlink.hardlink_to(path)
    with pytest.raises(ValueError):
        private_token(path)
    hardlink.unlink()
    path.chmod(0o644)
    with pytest.raises(ValueError):
        private_token(path)
    path.chmod(0o600)
    for value in ("", "one\r\nInjected: secret", "x" * 4097, "a\x00b"):
        path.write_text(value)
        with pytest.raises(ValueError):
            private_token(path)


BODY = {"model": "code_small", "messages": [{"role": "user", "content": "test"}]}


def test_secret_failure_is_before_reservation(server):  # noqa: F811
    service, request = server

    def unavailable():
        raise Denied("credential_unavailable", 503)

    service.credential_source = unavailable
    before = service.ledger.usage("course01", "learner1")
    assert request("/v1/chat/completions", BODY)[0] == 503
    assert service.ledger.usage("course01", "learner1") == before
    assert Fixture.calls == []


def test_membership_is_rechecked_after_secret_fetch(server):  # noqa: F811
    service, request = server

    def expired_during_fetch():
        Fixture.active = False
        return "unused-key"

    service.credential_source = expired_during_fetch
    before = service.ledger.usage("course01", "learner1")
    assert request("/v1/chat/completions", BODY)[0] == 403
    assert service.ledger.usage("course01", "learner1") == before
    assert Fixture.calls == []
