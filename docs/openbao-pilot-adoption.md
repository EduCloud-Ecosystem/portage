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
3. Add an operator-only encrypted recovery envelope (unseal material plus a
   narrowly scoped recovery-operator login), addressed to an external certificate.
   No private recipient key enters server storage, backups or classroom runtime.
   A synthetic recipient exercises fresh-process unseal and restore. Real custody
   destination requires Greg's selection; synthetic custody cannot satisfy it.
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
