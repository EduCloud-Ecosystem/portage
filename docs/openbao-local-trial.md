# Local OpenBao credential trial

Status: preparation, isolated; not merged or deployed. Greg authorized this
bounded trial and the classroom rerun on 2026-11-16. The earlier proposal is
the approved scope; no model planner, extra approval or paid planning is needed.

## Ownership and starting points

- Portage: `codex/openbao-local-trial`, managed worktree
  `/Users/gregchism/.codex/worktrees/portage-openbao-trial/portage`, base
  `b72881f009e61e1311b6e46b92b42841991fd163`.
- Working Portage pilot: `codex/nhanes-live-tutoring-v1`, unchanged.
- Waypoint classroom evaluator: `de701887e06c3ae19292b05639a6c9e83ba53d3c`.
- Cairn: `533c16a414b9fef1979d0de783b3436f31dd03a7`.
- Belay-classroom: `c5a27073e74b9eeb7ab697190915378b50132883`.

## Ordered implementation and acceptance

1. Pin a local OpenBao binary, create a disposable TLS-protected loopback server
   with encrypted persistent storage, audit logging and an exact-path read role.
   Keep bootstrap material private; never read or change production credentials.
2. Add an opt-in Portage credential source and gateway injection point. Fetch
   fresh credentials before admission; recheck membership after retrieval. No
   cached-key fallback, redirects, implicit retries or provider calls on refusal.
   Existing fixed-key behavior stays unchanged when the option is absent.
3. Exercise the real OpenBao server and actual Portage HTTP gateway against a
   synthetic upstream. Verify rotation, wrong-role/path/write denial, expired
   and revoked tokens, sealed/unreachable server, restart and backup restoration.
   Inspect actual upstream authorization and ledger state, including unknown
   usage after an admitted failed transport. Persist failures and sanitized
   results; never reset a ledger to make recovery pass.
4. Run Portage's required offline suite and rendered-config checks. Then run the
   existing full NHANES browser workflow with an isolated trial bridge. Preserve
   source pins and ordinary acceptance controls. A bounded live rerun may use the
   previously authorized synthetic question and existing 7-request/$0.175 cap;
   never treat it as student admission or repeat unknown paid work.

## Deliberate design choice

The first adapter reads KV over a pinned TLS connection for each admitted-call
candidate, rather than trusting an asynchronously rendered file after token
revocation or server failure. This tests running-process rotation directly and
keeps the integration stdlib-only. It adds a bounded secret-service request per
candidate. This local-only adapter is not production deployment configuration.

KV storage does not rotate/revoke the upstream provider key. Credential expiry
does not terminate cloud resources, renew course authority, or clear liabilities.
No AWS plugin, cloud resources, real learner data, shared pilot change or merge.
Production decisions still need workload identity, operational ownership, HA,
backup custody, provider-side key rotation and independent deployment acceptance.

Sources: https://openbao.org/docs/install/ ;
https://openbao.org/docs/secrets/kv/ ; https://openbao.org/docs/audit/ .
