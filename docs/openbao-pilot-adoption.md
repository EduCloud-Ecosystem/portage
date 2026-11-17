# OpenBao pilot adoption review

Greg authorized review, service identity and recovery custody, integration when
ready, and a fresh full classroom run on 2026-11-16. This continues the approved
local trial; no additional planner/model run is required. Work stays sequential.

Base Portage: 2ac908615a6d306f7862622cf5fd8ff1eed0c1a1 on codex/openbao-local-trial.
Base companion Waypoint: 8894ca79cb82074636309580fb2de1741bb290e5 on
codex/waypoint-openbao-local-trial. Existing static-key pilot remains the rollback.
Do not change other components, provision hosts, admit students, or rotate the
real vendor key. Prior evidence and private outputs remain preserved.

## Ordered scope and checks

1. Review credential and orchestration boundaries; fix unsafe private-file writes.
2. Add an exact-path Portage AppRole with short-lived tokens, single-use expiring
   SecretIDs, response-wrapped delivery, and validation of the wrapping origin.
   Revoke bootstrap root before classroom runtime starts. No default policies,
   automatic renewal, cached provider key, new membership authority or retries.
3. Greg selected an institutional password manager plus a separately held backup.
   Prepare an owner-only import record outside Git and runtime output containing
   unseal material and a narrowly scoped recovery-operator login. The record is
   plaintext staging for import, not an encrypted vault or completed custody.
   Exercise fresh-process unseal/restore without bootstrap memory; keep actual
   password-manager import and separate backup confirmation explicitly pending.
4. Verify denial/replay/expiry controls and restored-token invalidation with actual
   OpenBao; retain failures and the independent accounting ledger. Run component
   regression controls and verify source pins before the full browser rerun.
5. Integrate the reviewed optional credential path into the local instructor
   workflow, preserving static-key rollback. One fresh live run may use the same
   source-fixed synthetic question and seven-request/$0.175 maximum. Failed or
   unknown paid work is not automatically replayed. Preserve actual transport,
   SDK retry, cost, liability and cleanup records.

Permitted edits: Portage openbao credential/runtime modules, focused tests and
handoff docs; companion Waypoint evaluator binding/pins/tests and handoff docs.
No shared production secret store is selected. Hosted adoption additionally needs
real service-user isolation, custodian-held recovery material and verified restore
on the selected host. Current local notebook evaluator runs under the operator OS
account and does not establish an adversarial student isolation boundary.

Official references checked: https://openbao.org/docs/auth/approle/ and
https://openbao.org/docs/concepts/response-wrapping/ . Use actual server responses
for acceptance. API-level identity is separate from OS process isolation.

## Decisions implemented

The service identity is `portage-classroom` in a dedicated AppRole mount. It reads
one provider-key path with no default policy. SecretID and delivery wrapper expire
in 60 seconds and are single-use. Tokens expire after at most 20 minutes and have
no self-renew permission. Both login and token use are bound to loopback. Operator
re-enrollment is explicit; key rotation does not extend a course grant or budget.
The wrapping origin is checked before unwrapping, as recommended by OpenBao.

Bootstrap root is revoked before the classroom child starts. The separate
`pilot-recovery` operator login has a five-minute token and can change the provider
key, deliver that service's SecretID, invalidate that mount's tokens and pending
SecretIDs. It cannot modify policies or create another role. These application
identities do not replace separate OS accounts on a hosted multi-user deployment.

Greg selected institutional password-manager custody with a separate backup.
The tool exports a new owner-only JSON import file in an owner-only directory
outside both source and runtime output. It contains the unseal share and recovery
operator password, never root. **This staging file is plaintext, not an encrypted
vault.** Do not attach it to a PR, log, classroom workspace or public report. Import
it into the restricted institutional vault, make the independently held backup,
verify both can be retrieved, then remove the staging copy. No tool currently
connected here can confirm those vault/offline-backup operations. Until that is
confirmed, persistent/default pilot adoption remains closed.

Local demonstration uses one unseal share and a one-day test TLS certificate.
Neither quorum custody nor certificate renewal nor a selected hosted service-user
boundary is qualified. Those are hosted-release requirements; they do not prevent
the bounded local instructor workflow and recovery test. Original static-key
launchers remain the rollback and no real learner records are used.

Recovery: stop admission; stop Bao; retain pre-restore storage; restore the cold
Raft copy without restoring the independent Portage ledger; start sealed; run the
operator recovery tool with `--recover`; invalidate all restored AppRole tokens
and unused SecretIDs; create a fresh wrapped handoff; verify credentials without
model inference; only then resume a finite session. A sealed instance refuses
ordinary enrollment without explicit recovery. Cold restore must use the same
pinned instance/CA; relocation and TLS renewal require a separate reviewed update.

Fresh-process controls run via `integrations/ai_pilot/openbao_identity_trial.py`.
Full classroom integration is `integrations/ai_pilot/openbao_classroom.py`, now
requiring `--custody-export` in addition to the earlier exact-pinned arguments.
It exercises recovery of the actual post-classroom store without another model
call and verifies the accounting database stays byte-identical. Its credential
read accounting separates classroom requests from recovery checks.

Retained development failures: identity-01 expected a generic wrapping permission
that the narrow operator correctly lacked; the negative control now wraps a
permitted read from the wrong origin instead. Identity-02 used a retired revocation
route and stopped with HTTP 404. The documented `sys/leases/revoke-prefix` route
with synchronous revocation passes in identity-03. No permission was broadened
for either failure. These runs made no paid calls and cleaned up their servers.
Source: https://openbao.org/docs/internals/token/ .
