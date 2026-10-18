# SPDX-License-Identifier: Apache-2.0
"""Durable admission ledger for the optional course/research gateway.

No prompts, responses, names or email addresses belong here. Allowances are
finite token ceilings, not prices. Unknown usage retains its full reservation.
SQLite transactions serialize admission across processes on one host; this is
not a distributed ledger and must not be placed on a network filesystem.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Denied(Exception):
    def __init__(self, code: str, status: int = 403):
        self.code, self.status = code, status
        super().__init__(code)


def opaque(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,128}", value):
        raise ValueError("expected opaque identifier")
    return value


def positive(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("expected positive integer")
    return value


class Ledger:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self.db() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, allowance INTEGER NOT NULL,
                concurrency INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS members (
                project TEXT NOT NULL, subject TEXT NOT NULL,
                allowance INTEGER NOT NULL, concurrency INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, generation INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(project,subject));
            CREATE TABLE IF NOT EXISTS credentials (
                digest TEXT PRIMARY KEY, project TEXT NOT NULL, subject TEXT,
                kind TEXT NOT NULL, generation INTEGER, expires REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, subject TEXT NOT NULL,
                model TEXT NOT NULL, reserved INTEGER NOT NULL, actual INTEGER,
                state TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS usage_scope ON requests(project,subject,state);
            CREATE TABLE IF NOT EXISTS reconciliations (
                request TEXT PRIMARY KEY, evidence TEXT NOT NULL, recorded REAL NOT NULL);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def project(self, project: str, allowance: int, concurrency: int):
        with self.transaction() as db:
            db.execute(
                "INSERT INTO projects(id,allowance,concurrency) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET allowance=excluded.allowance, "
                "concurrency=excluded.concurrency",
                (opaque(project), positive(allowance), positive(concurrency)),
            )

    def member(self, project: str, subject: str, allowance: int, concurrency: int = 2):
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project,)).fetchone():
                raise Denied("unknown_project")
            # Re-enrollment never restores old credentials or erases prior usage.
            db.execute(
                "INSERT INTO members(project,subject,allowance,concurrency) "
                "VALUES(?,?,?,?) ON CONFLICT(project,subject) DO UPDATE SET "
                "allowance=excluded.allowance, concurrency=excluded.concurrency, "
                "active=1",
                (project, opaque(subject), positive(allowance), positive(concurrency)),
            )

    def revoke(self, project: str, subject: str):
        with self.transaction() as db:
            db.execute(
                "UPDATE members SET active=0,generation=generation+1 "
                "WHERE project=? AND subject=?",
                (project, subject),
            )
            db.execute(
                "UPDATE credentials SET active=0 WHERE project=? AND subject=?",
                (project, subject),
            )

    def retire(self, project: str):
        with self.transaction() as db:
            db.execute("UPDATE projects SET active=0 WHERE id=?", (project,))
            db.execute("UPDATE credentials SET active=0 WHERE project=?", (project,))

    def issue(
        self,
        project: str,
        *,
        subject: str | None = None,
        lifetime: int = 3600,
        kind: str = "participant",
    ) -> str:
        if kind not in {"participant", "application"} or not 0 < lifetime <= 86400 * 30:
            raise ValueError("invalid credential scope or lifetime")
        if (kind == "participant") != (subject is not None):
            raise ValueError("participant credentials require a subject")
        token = "ptg_" + secrets.token_urlsafe(32)
        with self.transaction() as db:
            project_row = db.execute(
                "SELECT * FROM projects WHERE id=?", (project,)
            ).fetchone()
            if not project_row or not project_row["active"]:
                raise Denied("project_inactive")
            generation = None
            if subject:
                generation = self._member(db, project, subject)["generation"]
            db.execute(
                "INSERT INTO credentials(digest,project,subject,kind,generation,expires) "
                "VALUES(?,?,?,?,?,?)",
                (
                    self.digest(token),
                    project,
                    subject,
                    kind,
                    generation,
                    time.time() + lifetime,
                ),
            )
        return token

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def disable_credential(self, token: str):
        with self.transaction() as db:
            db.execute(
                "UPDATE credentials SET active=0 WHERE digest=?", (self.digest(token),)
            )

    def install_application(self, project: str, token: str):
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise ValueError("application secret must be 32 random bytes in hex")
        with self.transaction() as db:
            if not db.execute(
                "SELECT 1 FROM projects WHERE id=? AND active=1", (project,)
            ).fetchone():
                raise Denied("project_inactive")
            db.execute(
                "INSERT OR IGNORE INTO credentials"
                "(digest,project,subject,kind,generation,expires) "
                "VALUES(?,?,NULL,'application',NULL,?)",
                (self.digest(token), project, time.time() + 86400 * 30),
            )

    @staticmethod
    def _member(db, project, subject):
        row = db.execute(
            "SELECT * FROM members WHERE project=? AND subject=?", (project, subject)
        ).fetchone()
        if not row or not row["active"]:
            raise Denied("membership_required")
        return row

    def _authenticate(self, db, token, asserted_subject=None):
        credential = db.execute(
            "SELECT * FROM credentials WHERE digest=?", (self.digest(token),)
        ).fetchone()
        if (
            not credential
            or not credential["active"]
            or credential["expires"] <= time.time()
        ):
            raise Denied("invalid_credential", 401)
        project = db.execute(
            "SELECT * FROM projects WHERE id=?", (credential["project"],)
        ).fetchone()
        if not project or not project["active"]:
            raise Denied("project_inactive")
        # Only an application credential can assert a user. Participant headers
        # and payload fields can never select someone else's budget.
        subject = (
            asserted_subject
            if credential["kind"] == "application"
            else credential["subject"]
        )
        if not subject:
            raise Denied("trusted_subject_required")
        member = self._member(db, project["id"], subject)
        if credential["kind"] == "participant" and (
            member["generation"] != credential["generation"]
        ):
            raise Denied("invalid_credential", 401)
        return dict(project), dict(member)

    def authenticate(self, token, asserted_subject=None):
        with self.db() as db:
            return self._authenticate(db, token, asserted_subject)

    @staticmethod
    def _usage(db, project, subject=None):
        where = "project=?" + (" AND subject=?" if subject is not None else "")
        values = (project, subject) if subject is not None else (project,)
        row = db.execute(
            "SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) AS committed, "
            # Unknown completion may still be running in the engine. Keep its
            # concurrency slot until an operator supplies reconciliation evidence.
            "COALESCE(SUM(state IN ('pending','unknown')),0) AS active, "
            "COALESCE(SUM(state='unknown'),0) AS unresolved "
            "FROM requests WHERE " + where,
            values,
        ).fetchone()
        return dict(row)

    def usage(self, project, subject=None):
        with self.db() as db:
            return self._usage(db, project, subject)

    def admit(
        self, token, model, reserved, asserted_subject=None, *, admission_check=None
    ):
        positive(reserved)
        with self.transaction() as db:
            project, member = self._authenticate(db, token, asserted_subject)
            for scope, subject in ((project, None), (member, member["subject"])):
                usage = self._usage(db, project["id"], subject)
                if usage["committed"] + reserved > scope["allowance"]:
                    raise Denied("allowance_exhausted", 429)
                if usage["active"] >= scope["concurrency"]:
                    raise Denied("concurrency_exhausted", 429)
            request = secrets.token_hex(16)
            # BEGIN IMMEDIATE may wait for another writer. Recheck a finite
            # approval under that lock, immediately before creating liability.
            if admission_check is not None:
                admission_check()
            db.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?)",
                (
                    request,
                    project["id"],
                    member["subject"],
                    model,
                    reserved,
                    None,
                    "pending",
                    time.time(),
                ),
            )
            return request

    def settle(self, request: str, usage: int | None):
        if usage is not None and (type(usage) is not int or usage < 0):
            usage = None
        with self.transaction() as db:
            db.execute(
                "UPDATE requests SET actual=?,state=? WHERE id=? AND state='pending'",
                (usage, "complete" if usage is not None else "unknown", request),
            )

    def reconcile(self, request: str, usage: int, evidence: str):
        if (
            type(usage) is not int
            or usage < 0
            or not re.fullmatch(r"[a-f0-9]{64}", evidence)
        ):
            raise ValueError("reconciliation needs measured usage and evidence SHA256")
        with self.transaction() as db:
            row = db.execute(
                "SELECT state FROM requests WHERE id=?", (request,)
            ).fetchone()
            if not row or row["state"] not in {"unknown", "pending"}:
                raise Denied("not_unresolved", 409)
            db.execute(
                "INSERT INTO reconciliations VALUES(?,?,?)",
                (request, evidence, time.time()),
            )
            db.execute(
                "UPDATE requests SET actual=?,state='reconciled' WHERE id=?",
                (usage, request),
            )


def prepare_request(body: dict, models: dict, operation: str) -> tuple[dict, int]:
    """Strict text-only OpenAI subset; reject provider overrides and tool execution."""
    alias = body.get("model")
    if alias not in models or models[alias]["operation"] != operation:
        raise Denied("model_not_allowed")
    spec = models[alias]
    if operation == "embeddings":
        value = body.get("input")
        if isinstance(value, str):
            value = [value]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(x, str) for x in value)
        ):
            raise Denied("text_input_required", 400)
        outgoing = {"model": alias, "input": value, "encoding_format": "float"}
        reserved = sum(len(x.encode()) + 16 for x in value)
    else:
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise Denied("messages_required", 400)
        clean = []
        for message in messages:
            if (
                not isinstance(message, dict)
                or message.get("role") not in {"system", "user", "assistant", "developer"}
                or not isinstance(message.get("content"), str)
            ):
                raise Denied("text_messages_required", 400)
            clean.append({"role": message["role"], "content": message["content"]})
        maximum = body.get(
            "max_completion_tokens", body.get("max_tokens", spec["max_output_tokens"])
        )
        if type(maximum) is not int or not 1 <= maximum <= spec["max_output_tokens"]:
            raise Denied("output_limit_exceeded", 400)
        if body.get("n", 1) != 1 or body.get("tools") or body.get("functions"):
            raise Denied("unsupported_generation", 400)
        outgoing = {
            "model": alias,
            "messages": clean,
            "max_tokens": maximum,
            "stream": body.get("stream") is True,
        }
        if outgoing["stream"]:
            outgoing["stream_options"] = {"include_usage": True}
        # Use a deliberately conservative byte ceiling plus message framing.
        # Qualification must prove the bound for each admitted tokenizer.
        reserved = (
            len(json.dumps(clean, ensure_ascii=False).encode())
            + 64 * len(clean)
            + maximum
        )
    if reserved > spec["max_request_tokens"]:
        raise Denied("request_limit_exceeded", 413)
    return outgoing, reserved
