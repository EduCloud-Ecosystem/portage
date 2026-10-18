# SPDX-License-Identifier: Apache-2.0
"""Local qualification grants. Operator registration is explicit and offline.

No transport, secret lookup, implicit store creation, or hosted eligibility.
The protected launch configuration owns registry pins; a same-privilege operator
can defeat local file/host pins. This is not a rollback-proof distributed ledger.
"""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from pilot_ledger import Denied, Ledger, opaque

TASKS = (
    ("arithmetic", "What is 6 times 7? Reply with only the integer.", "42"),
    ("extraction", "From 'red, blue, green', return only the second color.", "blue"),
)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def profile_digest(manifest):
    return digest(encoded(manifest).encode())


def runtime_digest():
    root = Path(__file__).resolve().parents[2]
    paths = (
        "src/portage/qualification_guard.py",
        "src/portage/pilot_ledger.py",
        "integrations/ai_pilot/gateway.py",
        "integrations/ai_pilot/qualify.py",
    )
    return profile_digest({name: digest((root / name).read_bytes()) for name in paths})


def local_origin(url):
    try:
        value = urlsplit(url)
        valid = (
            value.scheme == "http"
            and ipaddress.ip_address(value.hostname).is_loopback
            and value.path in {"", "/"}
            and not value.username
            and not value.password
            and not value.query
            and not value.fragment
            and value.port is not None
            and 0 < value.port <= 65535
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise Denied("local_origin_required")


def validate_profile(manifest):
    try:
        if (
            manifest["mode"] != "qualification"
            or set(manifest["models"]) != {"code_small"}
            or type(manifest["concurrency"]) is not int
            or manifest["concurrency"] != 2
        ):
            raise ValueError
        model = manifest["models"]["code_small"]
        local_origin(model["endpoint"])
        for key in ("revision", "template_sha256"):
            if type(model[key]) is not str or not re.fullmatch(
                "[a-f0-9]{64}", model[key]
            ):
                raise ValueError
        for key, maximum in (("max_output_tokens", 128), ("max_request_tokens", 4096)):
            if type(model[key]) is not int or not 0 < model[key] <= maximum:
                raise ValueError
        for key in ("project_allowance", "participant_allowance"):
            if type(manifest[key]) is not int or not 0 < manifest[key] <= 65536:
                raise ValueError
        if (
            model["operation"] != "chat/completions"
            or model["synthetic"] is not False
            or model["institutional_only"] is not True
        ):
            raise ValueError
        if not all(
            manifest["approved_capacity"][key] is True
            for key in ("local_only", "egress_blocked", "existing_installed_model")
        ):
            raise ValueError
        if (
            type(model["context_tokens"]) is not int
            or model["context_tokens"] < model["max_request_tokens"]
        ):
            raise ValueError
        for value, maximum in (
            (model["request_timeout_seconds"], 120),
            (model["resource_limits"]["cpus"], 1e9),
            (model["resource_limits"]["memory_mb"], 1e15),
        ):
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not 0 < value <= maximum
            ):
                raise ValueError
        if not all(
            type(model[key]) is str and model[key].strip()
            for key in ("upstream_model", "quantization", "provenance")
        ):
            raise ValueError
        encoded(manifest)
    except (KeyError, ValueError, TypeError):
        raise Denied("qualification_profile_required") from None


def protocol():
    inference, metadata, batches = {}, {}, []
    for op in ("version", "tags", "show"):
        metadata[f"initial.{op}"] = {"op": op, "batch": None}
    for concurrency in (1, 2):
        for repetition in range(2):
            jobs = [(task, stream) for task in TASKS for stream in (False, True)]
            for offset in range(0, len(jobs), concurrency):
                batch = f"batch{len(batches):02d}"
                slots = []
                for task, stream in jobs[offset : offset + concurrency]:
                    slot = f"{batch}.{task[0]}.{'stream' if stream else 'json'}"
                    inference[slot] = {
                        "task": task,
                        "stream": stream,
                        "concurrency": concurrency,
                        "repetition": repetition,
                        "batch": batch,
                    }
                    slots.append(slot)
                for op in ("version", "tags", "show", "ps"):
                    metadata[f"{batch}.{op}"] = {"op": op, "batch": batch}
                batches.append((batch, slots))
    return inference, metadata, batches


INFERENCE, METADATA, BATCHES = protocol()
PLAN_SHA256 = profile_digest({"inference": INFERENCE, "metadata": METADATA})
LIMITS = {"inference": 16, "metadata": 51, "authority": 83}
STICKY = {
    "approval_expired",
    "clock_continuity_lost",
    "approval_identity_changed",
    "approval_binding_changed",
    "unknown_work",
    "unbound_work",
    "abandoned_work",
    "membership_changed",
    "lease_lost",
    "store_identity_changed",
    "ledger_identity_changed",
    "protected_file_required",
    "qualification_profile_required",
}


def system_identity():
    """Linux identity only; an unsupported platform must obtain explicit revalidation."""
    try:
        host = Path("/etc/machine-id").read_text().strip()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        raise Denied("clock_continuity_lost") from None
    if not host or not boot:
        raise Denied("clock_continuity_lost")
    return digest(host.encode()), digest(boot.encode())


def protected_file(path):
    path = Path(path)
    try:
        info = path.lstat()
        if (
            not path.is_absolute()
            or path.resolve(strict=True) != path
            or not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o022
            or info.st_uid not in {0, os.geteuid()}
        ):
            raise Denied("protected_file_required")
        for ancestor in path.parents:
            parent = ancestor.stat()
            # A root-owned sticky temporary directory protects entries owned
            # by this operator. Other writable or foreign-owned ancestors do not.
            sticky_root = parent.st_uid == 0 and parent.st_mode & stat.S_ISVTX
            if parent.st_uid not in {0, os.geteuid()} or (
                parent.st_mode & 0o022 and not sticky_root
            ):
                raise Denied("protected_file_required")
    except OSError:
        raise Denied("protected_file_required") from None
    return [info.st_dev, info.st_ino]


def unique_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out

    def constant(_value):
        raise ValueError("nonfinite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def observe_usage(previous, result):
    """Reject ambiguity instead of allowing a later observation to refund work."""
    if "usage" not in result or result["usage"] is None:
        return previous
    usage = result["usage"]
    if type(usage) is not dict or type(usage.get("total_tokens")) is not int:
        raise ValueError("invalid usage")
    value = usage["total_tokens"]
    if not 0 <= value <= 65536 or (previous is not None and previous != value):
        raise ValueError("ambiguous usage")
    return value


def create_file(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


@contextmanager
def file_lock(path, *, nonblocking=False):
    expected = protected_file(path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if [opened.st_dev, opened.st_ino] != expected:
            raise Denied("store_identity_changed")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        except BlockingIOError:
            raise Denied("approval_busy", 409) from None
        yield fd
    finally:
        os.close(fd)


def migrate(path, authority_id, epoch):
    """Explicit OFFLINE operation on an existing ledger; never called at startup."""
    opaque(authority_id)
    opaque(epoch)
    protected_file(path)
    ledger = Ledger.open_existing(path)
    fence = str(path) + ".qualification-fence"
    if not Path(fence).exists():
        create_file(fence, b"")
    with file_lock(fence), ledger.transaction() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS qualification_store "
            "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
            "authority TEXT NOT NULL, epoch TEXT NOT NULL)"
        )
        row = db.execute("SELECT * FROM qualification_store").fetchone()
        if row and (row["authority"], row["epoch"]) != (authority_id, epoch):
            raise Denied("store_identity_changed")
        db.execute(
            "INSERT OR IGNORE INTO qualification_store VALUES(1,?,?)",
            (authority_id, epoch),
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS qualification_grants "
            "(id TEXT PRIMARY KEY, budget TEXT UNIQUE NOT NULL, binding TEXT NOT NULL, "
            "state TEXT NOT NULL, lease TEXT, wall REAL NOT NULL, mono REAL NOT NULL)"
        )
        if db.execute(
            "SELECT 1 FROM qualification_grants WHERE lease IS NOT NULL"
        ).fetchone():
            raise Denied("approval_busy", 409)
        db.execute(
            "CREATE TABLE IF NOT EXISTS qualification_attempts "
            "(id TEXT PRIMARY KEY, budget TEXT NOT NULL, kind TEXT NOT NULL, "
            "slot TEXT NOT NULL, state TEXT NOT NULL, lease TEXT NOT NULL, "
            "request TEXT UNIQUE, UNIQUE(budget,kind,slot))"
        )
    return ledger


def register(
    registry_path,
    ledger_path,
    manifest,
    *,
    grant_id,
    capacity_budget_id,
    token,
    subject,
    authority_url,
    identity=None,
    clock=time,
):
    """Explicit OFFLINE registration; project/member/credential must already exist."""
    validate_profile(manifest)
    local_origin(authority_url)
    opaque(grant_id)
    opaque(capacity_budget_id)
    opaque(subject)
    registry_path = Path(registry_path)
    if registry_path.exists():
        raise Denied("registry_exists")
    file_identity = protected_file(ledger_path)
    ledger = Ledger.open_existing(ledger_path, identity=file_identity)
    if manifest.get("mode") != "qualification":
        raise Denied("qualification_required")
    capacity = manifest["approved_capacity"]
    if capacity["ledger_path"] != str(ledger_path):
        raise Denied("approval_binding_changed")
    deadline = datetime.fromisoformat(capacity["deadline_utc"])
    if deadline.tzinfo is None:
        raise Denied("approval_expired")
    remaining = deadline.timestamp() - clock.time()
    if not math.isfinite(remaining) or not 0 < remaining <= 1800:
        raise Denied("approval_expired")
    host, boot = (identity or system_identity)()
    lease_path = str(registry_path) + ".lease"
    fence_path = str(ledger_path) + ".qualification-fence"
    create_file(lease_path, b"")
    with file_lock(fence_path), ledger.transaction() as db:
        project, member = ledger._authenticate(db, token)
        if project["id"] != manifest["project"] or member["subject"] != subject:
            raise Denied("membership_changed")
        if db.execute(
            "SELECT 1 FROM requests r LEFT JOIN qualification_attempts a "
            "ON a.request=r.id WHERE r.project=? "
            "AND (a.id IS NULL OR r.state IN ('pending','unknown')) LIMIT 1",
            (project["id"],),
        ).fetchone():
            raise Denied("unbound_work")
        store = dict(db.execute("SELECT * FROM qualification_store").fetchone())
        binding = {
            "version": 1,
            "grant_id": grant_id,
            "capacity_budget_id": capacity_budget_id,
            "ledger_path": str(ledger_path),
            "ledger_identity": file_identity,
            "registry_path": str(registry_path),
            "lease_path": lease_path,
            "lease_identity": protected_file(lease_path),
            "fence_path": fence_path,
            "fence_identity": protected_file(fence_path),
            "authority_id": store["authority"],
            "store_epoch": store["epoch"],
            "host": host,
            "boot": boot,
            "profile_sha256": profile_digest(manifest),
            "plan_sha256": PLAN_SHA256,
            "runtime_sha256": runtime_digest(),
            "subject": subject,
            "generation": member["generation"],
            "project": project["id"],
            "authority_url": authority_url,
            "deadline": deadline.timestamp(),
            "monotonic_deadline": clock.monotonic() + remaining,
            "project_allowance": manifest["project_allowance"],
            "participant_allowance": manifest["participant_allowance"],
            "concurrency": 2,
        }
        if (
            project["allowance"] != binding["project_allowance"]
            or member["allowance"] != binding["participant_allowance"]
            or project["concurrency"] != 2
            or member["concurrency"] != 2
        ):
            raise Denied("approval_binding_changed")
        db.execute(
            "INSERT INTO qualification_grants VALUES(?,?,?,'active',NULL,?,?)",
            (
                grant_id,
                capacity_budget_id,
                encoded(binding),
                clock.time(),
                clock.monotonic(),
            ),
        )
    # A failed file publication leaves an unusable grant, never an implicit retry/reset.
    raw = encoded(binding).encode()
    create_file(registry_path, raw)
    return digest(raw)


class QualificationGuard:
    def __init__(self, registry, expected_sha256, manifest, *, identity=None, clock=time):
        self.registry = str(registry)
        self.pin, self.manifest = expected_sha256, manifest
        self.identity, self.clock = identity or system_identity, clock
        self.mutex = threading.RLock()
        self.lease_id = None
        self.lease_fd = None
        self.owner_pid = os.getpid()
        self.binding = self._registry()
        self._files()
        self._static_binding()
        self._preflight()
        self.ledger = Ledger.open_existing(
            self.binding["ledger_path"], identity=self.binding["ledger_identity"]
        )

    def _preflight(self):
        """Read-only store/grant resolution before constructing a Ledger wrapper."""
        b = self.binding
        try:
            db = sqlite3.connect(Path(b["ledger_path"]).as_uri() + "?mode=ro", uri=True)
            try:
                store = db.execute(
                    "SELECT authority,epoch FROM qualification_store"
                ).fetchall()
                grants = db.execute(
                    "SELECT budget,binding FROM qualification_grants WHERE id=?",
                    (b["grant_id"],),
                ).fetchall()
            finally:
                db.close()
            self._files()
            if store != [(b["authority_id"], b["store_epoch"])]:
                raise Denied("store_identity_changed")
            if grants != [(b["capacity_budget_id"], encoded(b))]:
                raise Denied("approval_binding_changed")
        except sqlite3.Error:
            raise Denied("registered_store_required") from None

    def _registry(self):
        protected_file(self.registry)
        raw = Path(self.registry).read_bytes()
        if len(raw) > 65536 or digest(raw) != self.pin:
            raise Denied("approval_binding_changed")
        try:
            result = unique_json(raw)
            if result["registry_path"] != self.registry or result["version"] != 1:
                raise ValueError
            return result
        except (ValueError, KeyError, TypeError):
            raise Denied("approval_binding_changed") from None

    def _files(self):
        b = self.binding
        for path, ident in (
            (b["ledger_path"], b["ledger_identity"]),
            (b["lease_path"], b["lease_identity"]),
            (b["fence_path"], b["fence_identity"]),
        ):
            if protected_file(path) != ident:
                raise Denied("store_identity_changed")

    def _static_binding(self):
        b = self.binding
        validate_profile(self.manifest)
        local_origin(b["authority_url"])
        if (
            self._registry() != b
            or profile_digest(self.manifest) != b["profile_sha256"]
            or b["plan_sha256"] != PLAN_SHA256
            or b["runtime_sha256"] != runtime_digest()
        ):
            raise Denied("approval_binding_changed")
        if tuple(self.identity()) != (b["host"], b["boot"]):
            raise Denied("approval_identity_changed")

    def _validate(self, db, *, lease=True, inspect=False):
        if getattr(self, "poisoned", False):
            raise Denied("approval_held")
        self._files()
        self._static_binding()
        b = self.binding
        store = db.execute("SELECT * FROM qualification_store").fetchone()
        if not store or (store["authority"], store["epoch"]) != (
            b["authority_id"],
            b["store_epoch"],
        ):
            raise Denied("store_identity_changed")
        grant = db.execute(
            "SELECT * FROM qualification_grants WHERE id=?", (b["grant_id"],)
        ).fetchone()
        if not grant or grant["binding"] != encoded(b):
            raise Denied("approval_binding_changed")
        if grant["state"] != "active":
            raise Denied("approval_" + grant["state"])
        wall, mono = self.clock.time(), self.clock.monotonic()
        if not all(math.isfinite(n) for n in (wall, mono)) or (
            wall < grant["wall"] or mono < grant["mono"]
        ):
            raise Denied("clock_continuity_lost")
        if wall >= b["deadline"] or mono >= b["monotonic_deadline"]:
            raise Denied("approval_expired")
        if lease and (
            not self.lease_id
            or self.owner_pid != os.getpid()
            or grant["lease"] != self.lease_id
        ):
            raise Denied("lease_lost")
        member = self.ledger._member(db, b["project"], b["subject"])
        project = db.execute(
            "SELECT * FROM projects WHERE id=?", (b["project"],)
        ).fetchone()
        if (
            not project
            or not project["active"]
            or member["generation"] != b["generation"]
            or project["allowance"] != b["project_allowance"]
            or member["allowance"] != b["participant_allowance"]
            or project["concurrency"] != 2
            or member["concurrency"] != 2
        ):
            raise Denied("membership_changed")
        if db.in_transaction:
            db.execute(
                "UPDATE qualification_grants SET wall=?,mono=? WHERE id=?",
                (wall, mono, b["grant_id"]),
            )
        if inspect:
            return grant
        for row in db.execute(
            "SELECT r.state,a.lease FROM requests r LEFT JOIN qualification_attempts a "
            "ON a.request=r.id WHERE r.project=?",
            (b["project"],),
        ):
            if row["lease"] is None:
                raise Denied("unbound_work")
            if row["state"] == "unknown":
                raise Denied("unknown_work")
            if row["state"] == "pending" and row["lease"] != self.lease_id:
                raise Denied("abandoned_work")
        for row in db.execute(
            "SELECT state,lease FROM qualification_attempts WHERE budget=?",
            (b["capacity_budget_id"],),
        ):
            if row["state"] == "unknown":
                raise Denied("unknown_work")
            if row["state"] in {"admitted", "claimed"} and row["lease"] != self.lease_id:
                raise Denied("abandoned_work")
        return grant

    @contextmanager
    def _write(self):
        try:
            with self.ledger.transaction() as db:
                yield db
        except Denied as error:
            if error.code in STICKY:
                self.hold()
            raise
        except BaseException:
            # Commit may have succeeded without its acknowledgement. Block this
            # object even if the follow-up durable hold cannot be written. A new
            # process must also reject the persisted lease as abandoned.
            self.poisoned = True
            try:
                self.hold()
            except (OSError, sqlite3.Error):
                pass
            raise

    def hold(self):
        self.poisoned = True
        with self.ledger.transaction() as db:
            db.execute(
                "UPDATE qualification_grants SET state='held' WHERE id=? "
                "AND state='active'",
                (self.binding["grant_id"],),
            )
            db.execute(
                "UPDATE requests SET state='unknown' WHERE state='pending' AND id IN "
                "(SELECT request FROM qualification_attempts WHERE budget=?)",
                (self.binding["capacity_budget_id"],),
            )

    def remaining(self):
        b = self.binding
        return max(
            0,
            min(
                b["deadline"] - self.clock.time(),
                b["monotonic_deadline"] - self.clock.monotonic(),
            ),
        )

    @property
    def deadline(self):
        return self.binding["deadline"]

    def check(self):
        with self._write() as db:
            self._validate(db)

    def acquire(self, token):
        if self.lease_fd is not None:
            raise Denied("approval_busy", 409)
        self._files()
        fd = os.open(self.binding["lease_path"], os.O_RDWR | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if [opened.st_dev, opened.st_ino] != self.binding["lease_identity"]:
                raise Denied("store_identity_changed")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Denied("approval_busy", 409) from None
            with self._write() as db:
                grant = self._validate(db, lease=False)
                self._credential(db, token)
                used = db.execute(
                    "SELECT 1 FROM qualification_attempts WHERE budget=?",
                    (self.binding["capacity_budget_id"],),
                ).fetchone()
                if grant["lease"] or used:
                    raise Denied("abandoned_work")
                self.lease_id = secrets.token_hex(16)
                db.execute(
                    "UPDATE qualification_grants SET lease=? WHERE id=?",
                    (self.lease_id, self.binding["grant_id"]),
                )
            self.lease_fd = fd
            self.token = token
        except BaseException:
            self.lease_id = None
            os.close(fd)
            raise
        return self

    def close(self):
        if self.lease_fd is None:
            return
        try:
            with self.ledger.transaction() as db:
                pending = db.execute(
                    "SELECT 1 FROM qualification_attempts WHERE budget=? "
                    "AND state!='complete'",
                    (self.binding["capacity_budget_id"],),
                ).fetchone()
                db.execute(
                    "UPDATE qualification_grants SET state=?,lease=NULL WHERE id=? "
                    "AND state='active' AND lease=?",
                    (
                        "held" if pending else "closed",
                        self.binding["grant_id"],
                        self.lease_id,
                    ),
                )
                db.execute(
                    "UPDATE requests SET state='unknown' WHERE state='pending' AND "
                    "id IN (SELECT request FROM qualification_attempts WHERE lease=?)",
                    (self.lease_id,),
                )
        finally:
            os.close(self.lease_fd)
            self.lease_fd = self.lease_id = None

    def authenticate(self, token):
        with self._write() as db:
            self._validate(db)
            return self._credential(db, token)

    def check_body(self, slot, body):
        item = self._slot("inference", slot)
        expected = {
            "model": "code_small",
            "messages": [{"role": "user", "content": item["task"][1]}],
            "stream": item["stream"],
        }
        if type(body) is not dict or encoded(body) != encoded(expected):
            raise Denied("workload_changed")

    def _credential(self, db, token):
        project, member = self.ledger._authenticate(db, token)
        if (project["id"], member["subject"], member["generation"]) != (
            self.binding["project"],
            self.binding["subject"],
            self.binding["generation"],
        ):
            raise Denied("membership_changed")
        return project, member

    def _slot(self, kind, slot):
        plan = (
            INFERENCE if kind == "inference" else METADATA if kind == "metadata" else {}
        )
        if type(slot) is not str or slot not in plan:
            raise Denied("slot_not_allowed")
        return plan[slot]

    def _completed(self, db, kind, slot):
        return db.execute(
            "SELECT 1 FROM qualification_attempts WHERE budget=? AND kind=? "
            "AND slot=? AND state='complete'",
            (self.binding["capacity_budget_id"], kind, slot),
        ).fetchone()

    def _available(self, db, kind, slot):
        if db.execute(
            "SELECT 1 FROM qualification_attempts WHERE budget=? AND kind=? AND slot=?",
            (self.binding["capacity_budget_id"], kind, slot),
        ).fetchone():
            raise Denied("slot_consumed", 409)
        count = db.execute(
            "SELECT count(*) FROM qualification_attempts WHERE budget=? AND kind=?",
            (self.binding["capacity_budget_id"], kind),
        ).fetchone()[0]
        if count >= LIMITS[kind]:
            raise Denied("attempts_exhausted", 429)

    def _prerequisites(self, db, kind, slot):
        item = self._slot(kind, slot)
        required = []
        if kind == "inference":
            required = [
                ("metadata", f"{prefix}.{op}")
                for prefix in ("initial", item["batch"])
                for op in ("version", "tags", "show")
            ]
        else:
            prefix, op = slot.rsplit(".", 1)
            if prefix != "initial":
                required.extend(
                    ("metadata", f"initial.{part}")
                    for part in ("version", "tags", "show")
                )
            if op == "version" and prefix != "initial":
                index = [name for name, _ in BATCHES].index(prefix)
                if index:
                    required.append(("metadata", BATCHES[index - 1][0] + ".ps"))
            if op == "tags":
                required.append(("metadata", prefix + ".version"))
            if op == "show":
                required.append(("metadata", prefix + ".tags"))
            if op == "ps":
                required.extend(("inference", name) for name in dict(BATCHES)[prefix])
        if any(not self._completed(db, k, s) for k, s in required):
            raise Denied("slot_prerequisite")

    def _insert(self, db, kind, slot, request=None):
        self._validate(db, inspect=True)
        attempt = secrets.token_hex(16)
        db.execute(
            "INSERT INTO qualification_attempts VALUES(?,?,?,?,?,?,?)",
            (
                attempt,
                self.binding["capacity_budget_id"],
                kind,
                slot,
                "admitted",
                self.lease_id,
                request,
            ),
        )
        return attempt

    def authority(self, kind, slot, phase):
        self._slot(kind, slot)
        if phase not in (("pre", "post") if kind == "inference" else ("pre",)):
            raise Denied("slot_not_allowed")
        lookup = f"{kind}:{slot}:{phase}"
        with self._write() as db:
            self._validate(db)
            self._credential(db, self.token)
            self._prerequisites(db, kind, slot)
            self._available(db, kind, slot)
            self._available(db, "authority", lookup)
            if phase == "post" and not self._completed(
                db, "authority", f"{kind}:{slot}:pre"
            ):
                raise Denied("slot_prerequisite")
            return self._insert(db, "authority", lookup)

    def admit(self, kind, slot, *, token=None, body=None):
        item = self._slot(kind, slot)
        with self._write() as db:
            self._validate(db)
            self._credential(db, self.token if token is None else token)
            self._available(db, kind, slot)
            self._prerequisites(db, kind, slot)
            phases = ("pre", "post") if kind == "inference" else ("pre",)
            if any(
                not self._completed(db, "authority", f"{kind}:{slot}:{phase}")
                for phase in phases
            ):
                raise Denied("authority_required")
            request = None
            if kind == "inference":
                expected = {
                    "model": "code_small",
                    "messages": [{"role": "user", "content": item["task"][1]}],
                    "stream": item["stream"],
                }
                if type(body) is not dict or encoded(body) != encoded(expected):
                    raise Denied("workload_changed")
                from pilot_ledger import prepare_request

                _, reserved = prepare_request(
                    body, self.manifest["models"], "chat/completions"
                )
                request = self.ledger._admit(
                    db,
                    self.token if token is None else token,
                    "code_small",
                    reserved,
                    admission_check=lambda: self._validate(db),
                )
            attempt = self._insert(db, kind, slot, request)
            return attempt, request

    def claim(self, attempt):
        # Local revocation cutoff is committed claim issuance, not remote receipt.
        with self.mutex, file_lock(self.binding["fence_path"]), self._write() as db:
            self._validate(db)
            self._credential(db, self.token)
            self._validate(db)
            result = db.execute(
                "UPDATE qualification_attempts SET state='claimed' "
                "WHERE id=? AND budget=? AND lease=? AND state='admitted'",
                (attempt, self.binding["capacity_budget_id"], self.lease_id),
            )
            if result.rowcount != 1:
                raise Denied("dispatch_claim_consumed", 409)

    def finish(self, attempt, *, known, usage=None):
        with self._write() as db:
            row = db.execute(
                "SELECT * FROM qualification_attempts WHERE id=? AND budget=? "
                "AND lease=?",
                (attempt, self.binding["capacity_budget_id"], self.lease_id),
            ).fetchone()
            if not row or row["state"] not in {"admitted", "claimed"}:
                return
            known = known and row["state"] == "claimed"
            if row["kind"] == "inference":
                known = known and type(usage) is int and 0 <= usage <= 65536
                db.execute(
                    "UPDATE requests SET actual=?,state=? WHERE id=? AND state='pending'",
                    (
                        usage if known else None,
                        "complete" if known else "unknown",
                        row["request"],
                    ),
                )
            db.execute(
                "UPDATE qualification_attempts SET state=? WHERE id=?",
                ("complete" if known else "unknown", attempt),
            )
            if not known:
                db.execute(
                    "UPDATE qualification_grants SET state='held' "
                    "WHERE id=? AND state='active'",
                    (self.binding["grant_id"],),
                )

    def validate_gateway(self, ledger, manifest, authority_url):
        if (
            ledger is not self.ledger
            or profile_digest(manifest) != self.binding["profile_sha256"]
            or authority_url != self.binding["authority_url"]
        ):
            raise Denied("approval_binding_changed")
        self.check()


def revoke(registry, pin, manifest, *, identity=None, clock=time):
    """Explicit local operator revocation, serialized with final claim permission."""
    guard = QualificationGuard(registry, pin, manifest, identity=identity, clock=clock)
    with file_lock(guard.binding["fence_path"]), guard.ledger.transaction() as db:
        db.execute(
            "UPDATE qualification_grants SET state='revoked' WHERE id=?",
            (guard.binding["grant_id"],),
        )
