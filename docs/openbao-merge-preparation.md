# OpenBao merge preparation

Greg authorized CI and merge preparation on 2026-11-16, while keeping default
activation gated on custody. No new live model calls or deployed-host changes.

The review branch incorporates current main's shared protocol; existing live
classroom evidence remains pinned to its original application revisions. New CI
runs deterministic regression/render/qualification checks and a real OpenBao
2.7.2 Linux synthetic transport/identity/restore job. It has no provider secret,
uses a checksum-pinned binary and pinned actions, a ten-minute timeout, read-only
repository permission and bounded result artifacts. It never uploads custody,
TLS private keys, service tokens or storage. Paid-review CI is disabled for the
draft PR; no paid-review repository setting is changed.

The inherited protocol checker failed Portage's repository-wide Ruff check.
Formatting/import order and explicit exception chaining were corrected without
changing policy decisions or the shared protocol digest.

Default launchers and their static-key rollback remain unchanged. Source merge
is distinct from activation; the target instance's actual vault import, separate
backup and recovery verification must be recorded before default activation.
The current local rehearsal record is not a future deployment's custody record.

Public recovery instructions: the coordinated EduCloud
`docs/pilot/OPENBAO_CUSTODY_CHECKLIST.md`. Private values are never placed in a PR.

The managed worktree helper stalled without returning a path/operation ID for the
umbrella review. After verifying no new worktree was registered, a separate Git
worktree at `/Users/gregchism/dev/.educloud-worktrees/educloud-openbao-merge` was
created from `e56b6e1`. Only the OpenBao documentation/evidence commit was copied;
unrelated Studio status work and the other chat's `docs/audits/` stay in place.
