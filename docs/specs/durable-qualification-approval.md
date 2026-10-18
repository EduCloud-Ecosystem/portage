# Durable local qualification approval

This corrective implementation binds the fixed local qualification protocol to one operator-provisioned grant and authoritative ledger on one protected host. It does not approve live inference, capacity, hosted transport, deployment or routing changes. All twelve runtime gates remain NOT RUN.

## Confirmed failure and approved correction

At source `b2ba332ff5f81ff15c7ada67d5fc2a79b65cde94`, two fresh processes using the same fixture approval, configuration and temporary ledger dispatched 16 inference calls each and 51 engine metadata calls each. Both reports claimed accounting PASS. Unknown inference retained its 176-unit reservation and slot, but a repeated invocation performed three metadata calls before refusing. The historical local proposal/reproduction and the frozen 95/17/147 evidence remain unchanged. The separate [durable approval record](../qualifications/2026-10-17-durable-approval-controls.json) retains this failing baseline and corrected results.

## Trust and startup

A trusted launch configuration supplies the protected registry path and its expected SHA256, never values taken from a client request. The registry pins the exact canonical existing ledger path and device/inode, authority/store epoch, grant and capacity-budget IDs, host and boot identity, profile/plan digest, member generation, existing authority endpoint, and original absolute and same-boot monotonic deadlines. Linux machine and boot IDs provide the runtime identity; tests supply explicitly fictional identities and clocks. Unsupported identity/clock continuity fails closed.

Registry and store files must be regular, non-symlink files in a protected directory, with no group/world write permissions; the operator must keep the trust pin outside runner-editable manifests. Runtime resolves and validates all bindings before `Ledger.open_existing`. That path uses SQLite `mode=rw`, performs no DDL, and cannot create missing state. Each later connection and admission rechecks file identity and store epoch. Qualification startup performs no migration, grant registration, project/member upsert, reactivation or credential issuance. It uses an explicitly supplied existing participant credential. Missing or legacy grants refuse before contact.

This is a protected local trust boundary. Permissions and hashes do not stop the same privileged operator from replacing the trust pin, rolling a store back in place, or copying registry plus database and host identifiers elsewhere. No global or hostile-administrator prevention is claimed. Automatic restore activation and cross-host authority remain deferred.

## Persistent protocol

One canonical approval exists per capacity-budget ID. Replacement grant wrappers and historical attribution are deferred. Permanent uniqueness on `(capacity_budget_id, kind, slot)` and inference request identity prevents a credential, output directory, label or restart from creating another attempt.

The plan is fixed: 16 inference slots for two tasks, JSON/stream transport, concurrency cells one/two and two repetitions. Metadata has 51 slots: an initial version/tags/show pin, twelve batch pins with those three operations, and twelve post-batch residency samples. Ceilings are per kind: after inference 16 the final predefined residency sample remains permitted; inference 17 and metadata 52 refuse. Slots carry exact task/body/mode and prerequisite metadata/batch identities. No warmup, fallback, polling or automatic retry exists.

Membership-authority traffic has 83 permanent slots: two lookups for each inference slot and one for each metadata slot. There is no extra startup lookup. Local binding, credential, lease, prior-work and slot checks precede every lookup; repeated/rejected invocations cannot generate fresh authority traffic. Each authority request has one bounded transport attempt and a single-use claim. Inactive membership revokes/holds the grant; unavailable or ambiguous authority replies hold it.

## Lease and transactions

A nonblocking OS file lock allows one runner process per approval. The runner may dispatch its two approved inference calls concurrently. A second runner refuses busy before any authority or engine traffic. A persisted lease ID and attempt states distinguish normal in-flight work from abandonment after process death. The runtime never resumes a partially used protocol automatically. Completed, stopped or abandoned invocations remain status-only; an unfinished attempt becomes a conservative hold.

In one `BEGIN IMMEDIATE`, admission checks the immutable binding, current membership generation, both original deadlines, lease ownership, grant state, prior unknown/unbound work, fixed slot/prerequisites, permanent count, tokens and concurrency; it then inserts the attempt and inference reservation atomically. Metadata and authority consume their slots before contact, without inventing token charges. Normal pending inference owned by the current lease permits the planned second concurrent call. Unknown or abandoned work blocks new operations.

A durable dispatch claim commits after connection setup and expiry recheck, immediately before the transport sends. The final local permission check and explicit local revocation share a short cross-process fence lock. No database transaction or fence lock is held during network I/O. Claim commitment is the local revocation cutoff; revocation cannot retract an already issued permission or prove cancellation. Lost acknowledgement, duplicate claim, crash or uncertain send never grants another dispatch. Clock, state and authority validity are checked again after lock waits.

Known supported usage is recorded fully, including usage over a reservation. Missing, invalid, unsupported or ambiguous usage retains the full unknown reservation and slot. Settlement and evidence-backed reconciliation never return attempt slots. Metadata ambiguity holds the approval without a fabricated token charge. A completion/hash alone is not proof of termination or valid reconciliation.

## Explicit offline operations and compatibility

The operator API is `qualification_guard.migrate(existing_path, authority_id, epoch)`, followed by `register(registry_path, existing_path, manifest, grant_id=..., capacity_budget_id=..., token=..., subject=..., authority_url=...)`. These calls perform local registration only. The project, participant and credential must already exist through the institution's separately approved provisioning process. Registration returns the registry SHA256 for the protected launch configuration. `revoke(registry_path, pin, manifest)` explicitly closes future dispatch permission under the shared fence. None of these functions contacts an engine or membership service. No operator operation was performed on a real ledger during this change.

Runtime uses `QualificationGuard(registry_path, expected_sha256, manifest)`, then acquires the existing credential's runner lease. The CLI additionally requires `--registry`, `--registry-sha256` and `--credential-file` alongside its existing approved-execution flags. The credential JSON has `participant_token` and `authority_token` fields and must be private to its owner (0600); credentials never go into the registry or evidence. The existing authority endpoint must also be a literal loopback HTTP origin. This implementation does not install or launch that authority.

The registry binds hashes of the four runtime source files as well as the profile and fixed plan. Files and all ancestors must be owned by the operator or root and protected from group/world writes; a root-owned sticky temporary ancestor is allowed for fixture stores. Opened lease/fence descriptors are checked against their pinned device/inode. Directory protections exclude an unrelated local user's rename/swap attack; they do not add protection against a privileged operator. The runtime does not verify an external deployment's operating-system policy.

Registration is deliberately not a recovery API. If publication fails after the grant commits, the grant remains unusable; orphaned lock files, stale leases and failed registrations need explicit operator inspection. Migration refuses a persisted runner lease. Replacement grants, automatic cleanup, lease stealing, restore activation and budget transfer remain deferred. Historical unknown work cannot be assigned to a new budget by changing a label.

Migration is a separate offline operator function on an existing ledger, performed while admission is fenced. It adds store/grant/attempt tables and pre-created lock files without altering historical requests, usage, unknown holds, reconciliations, generic ledger APIs or positional request inserts. Registration requires an existing active project/member, a matching pre-issued participant credential, exact profile and platform identity, and no unbound historical work in that scope. It never guesses ownership. Registration and revocation are explicit operator operations, not runner side effects.

Expired, revoked, held, exhausted and interrupted states persist. Original absolute and monotonic deadlines are stored at registration; a new process does not calculate a new window. Boot change, detected clock rollback, missing continuity, store/registry epoch mismatch or replaced state refuses and requires explicit revalidation. Restores do not activate approvals automatically.

Generic synthetic/hosted gateway defaults remain unchanged. Every direct construction of qualification mode requires a real guard bound to the same ledger, manifest and authority. Qualification control routes cannot perform generic provisioning. Qualification execution uses the guarded fixed plan; hosted runtime remains absent.

## Verification and release

New controls exercise actual guard, ledger, runner and qualification Handler code with in-memory transport. Child-process fixtures exercise OS lease exclusion, process death and permanent state. They do not demonstrate real model performance, host resource enforcement, cancellation, network timing or provider entitlement. Existing generic adapter/expiry controls retain their synthetic loopback fixtures. The 147 hosted-contract fixtures and all historical evidence remain unchanged.

Use deterministic in-memory transport and temporary stores for new controls: repeat/unknown repeats with zero engine and authority traffic; fixed final residency after inference 16; process lease/last-slot races; zero/tiny/large/unknown usage; duplicate claims, failed commit, lost acknowledgements and crash windows; expiry/revocation after waits/connect; all binding/path/store changes; and explicit migration preserving every historical liability. Run existing generic controls and the full suite, lint and generated-profile checks. Preserve the historical packets and frozen evidence hashes. Require independent read-only review, fixes and final-revision CI before merge. No live qualification is part of verification.
