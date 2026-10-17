# Course and research pilot gateway

The approved EduCloud AI pilot adds a finite, revocable admission boundary in
front of the existing LiteLLM routing spine. The dependency-free ledger lives
in `src/portage/pilot_ledger.py`; HTTP and LiteLLM dependencies belong to the
optional `integrations/ai_pilot` deployment, outside the core.

Credentials bind a project and participant, or a trusted application connection
that may assert an opaque participant within its own project. Every admitted
request rechecks current Waypoint membership and the ledger. Caller-supplied
owner, project, policy, provider URLs and metadata cannot select attribution.
No content is persisted in the ledger. Linkable usage metadata can still be a
protected record and follows EduCloud's destination register.

Admission reserves a conservative input-byte ceiling plus the bounded output
allowance in one SQLite write transaction. Participant and project ceilings
and concurrency apply together. The HTTP adapter admits each retry, title,
summary and embedding call. LiteLLM automatic retries and fallbacks are disabled
in this pilot. Missing usage retains the reservation as unknown; a crash leaves
pending liability. Only reconciliation with a measured amount and an evidence
digest can resolve it. No automatic reset or timeout erases liabilities.

One local filesystem and one gateway deployment own each ledger. Scaling across
hosts requires a different transactional store and acceptance tests. Token
ceilings are not currency ceilings. Overreported or underestimated actual usage
is recorded as debt and blocks subsequent admission; qualification must verify
the conservative bound for the selected model tokenizer before hosted use.

The manifest must name actual model revisions, provenance, endpoints, finite
resources and allowances. Synthetic mock manifests cannot start in hosted mode.
Model availability and quality are separate qualification outcomes. No
institutional model is qualified by the synthetic harness.

The [direct inference qualification protocol](direct-inference-qualification.md)
adds an opt-in single-model local path. Unknown requests retain concurrency
slots as well as token reservations until reconciliation; a timed-out or
disconnected client does not prove the engine stopped. Default routes and
hosted qualification requirements remain unchanged.
