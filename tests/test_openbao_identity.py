# SPDX-License-Identifier: Apache-2.0
"""Regression controls for operator-only custody and safe runtime file writes."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "integrations/ai_pilot"))
from openbao_identity import enroll, provision, read_private_json  # noqa: E402
from openbao_local import private  # noqa: E402


def test_atomic_private_write_rejects_links_permissions_and_preserves_old(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "token"
    private(path, "original")
    assert path.stat().st_mode & 0o777 == 0o600
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        private(link, "changed")
    link.unlink()
    link.hardlink_to(path)
    with pytest.raises(ValueError):
        private(path, "changed")
    link.unlink()
    path.chmod(0o644)
    with pytest.raises(ValueError):
        private(path, "changed")
    assert path.read_text() == "original"
    path.chmod(0o600)
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError):
        private(path, "changed")


def test_custody_rejects_oversized_or_shared_records(tmp_path):
    tmp_path.chmod(0o700)
    p = tmp_path / "record"
    private(p, json.dumps({"secret": "x" * 16385}))
    with pytest.raises(ValueError):
        read_private_json(p)
    private(p, "{}")
    p.chmod(0o644)
    with pytest.raises(ValueError):
        read_private_json(p)


def test_custody_cannot_be_written_to_runtime_tree(tmp_path):
    tmp_path.chmod(0o700)
    state = tmp_path / "runtime"
    state.mkdir(mode=0o700)
    bao = SimpleNamespace(directory=state / "bao")
    with pytest.raises(ValueError, match="outside"):
        provision(bao, state / "recovery.json")


def test_enrollment_rejects_unexpected_wrapper_without_unwrapping(tmp_path):
    tmp_path.chmod(0o700)
    binding = tmp_path / "binding"
    private(
        binding, json.dumps({"version": 1, "role_id": "role", "wrapped_token": "wrapped"})
    )
    calls = []

    def request(method, path, body=None, token=None):
        calls.append(path)
        return 200, {"data": {"creation_path": "sys/wrapping/wrap", "creation_ttl": 60}}

    with pytest.raises(ValueError):
        enroll(SimpleNamespace(request=request), binding)
    assert calls == ["sys/wrapping/lookup"]
