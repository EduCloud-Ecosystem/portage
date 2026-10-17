# Direct local inference qualification — October 17, 2026

**Decision: DEFER actual model qualification.** The synthetic Portage controls
pass; no approved running engine/model was available. This record authorizes
neither deployment nor a default-route change.

## Revision and ownership

- Remote main inspected: `2ec86ad0447d71a90ab545206b44fe41dbb69ee0`.
- Existing local pilot source preserved: `9e2a877ef414413a402093d7ca06bb7ff60c5200`.
- Isolated prerequisite: `73b7b31602707ee4f9618723b9171c5524162ffc`, including
  the exact pilot cherry-pick and a guard excluding paid review on draft PRs.
- Qualification code: `e78a6b6e3952d02fb52c041a1efcada7243f8212`.
- Work tracking: [Portage #9](https://github.com/EduCloud-Ecosystem/portage/issues/9).
- Prerequisite review: [Portage #10](https://github.com/EduCloud-Ecosystem/portage/pull/10),
  draft; deterministic CI passed, paid model reviewer skipped.
- Qualification review: [Portage #11](https://github.com/EduCloud-Ecosystem/portage/pull/11),
  stacked draft; [Linux synthetic CI passed](https://github.com/EduCloud-Ecosystem/portage/actions/runs/39075295809)
  at `1f9197c`. The CI record preserves actual runtime criteria as NOT RUN.

Only the isolated Portage worktree changed. The original Portage checkout is
still clean on `codex/ai-pilot` at `9e2a877`. Belay, portage-local, Waypoint,
Outfitter and PAIR were not modified. No existing service or real inference engine was started or restarted,
weights downloaded, subscription purchased, capacity provisioned or real data used.

## Capacity and model identity

Read-only discovery found an Ollama executable at `/usr/local/bin/ollama`, no
listener at `http://127.0.0.1:11434` (connection refused), and no manifests in
the default local Ollama model inventory. This is not a claim that every machine
or alternate model-storage location is empty. No other approved capacity
manifest was provided.

| Property | Observed value |
| --- | --- |
| Selected installed model / revision | Unknown; NOT RUN |
| Engine runtime version | Unknown; NOT RUN |
| Template / SHA256 | Unknown; NOT RUN |
| Quantization / effective context | Unknown; NOT RUN |
| Candidate engine origin | `http://127.0.0.1:11434`, unavailable at discovery |
| Prepared request type | Text-only `POST /v1/chat/completions`, streaming and non-streaming |
| Proposed protocol limits | 16 total calls; concurrency 1 and 2; template output cap 32 tokens, per-request reservation cap 1,024, aggregate allowance 32,768; these are not model measurements |
| Actual latency / supported engine concurrency / memory | NOT RUN; no values inferred from fake services |
| Embeddings | NOT RUN; not required for this selected chat-only path |

## Acceptance matrix

| Criterion | Synthetic control result | Actual engine result / remaining consequence |
| --- | --- | --- |
| Streaming/non-streaming identity and attribution | PASS | NOT RUN; real engine compatibility pending |
| Participant/application scope and spoofed attribution | PASS | NOT RUN; institutional identity acceptance remains separate |
| Forbidden models/destinations; redirects/proxy overrides | PASS | NOT RUN; operator must verify engine egress/local-only controls |
| Revocation, expiry, unavailable authority; recheck before dispatch | PASS | NOT RUN against institutional membership service |
| Project/member exhaustion and bounded concurrency | PASS | NOT RUN for selected capacity/cohort load |
| Every explicit retry/background call individually admitted | PASS | NOT RUN for hidden engine attempts; independent trace required |
| Cancellation, engine failure, header/stream deadlines | PASS | NOT RUN for actual engine termination behavior |
| Missing/invalid usage and interrupted/error streams | PASS | NOT RUN; unknown rows retain reservations and concurrency slots |
| Restart, reconciliation and a fresh evidence directory | PASS | NOT RUN for operator engine restart; durable ledger prevents a fresh folder resetting debt |
| Model digest, template, quantization pin checks | PASS against deliberately mismatched fixtures | NOT RUN for actual artifacts |
| Bounded workload, latency, availability and task quality | Runner exercised with synthetic engine only | NOT RUN; no model quality or speed claim |
| Resident memory / effective context | Instrumentation exercised with fake metadata only | NOT RUN; independent OS/GPU peak memory also required |
| Conservative token reservation bound | NOT RUN against a tokenizer | Must prove framing/tokenizer bound before hosted use |
| Institutional data, retention, recovery, accessibility, support | NOT RUN | Remain closed admission gates |

Machine-readable per-control results and exact file hashes are in
[`2026-10-17-direct-local-controls.json`](2026-10-17-direct-local-controls.json).
The [operator protocol](../specs/direct-inference-qualification.md) contains
reproduction commands, finite live manifest, instrumentation, cancellation and
restart/reconciliation steps. The fixture run uses no weights or provider calls.

Final local validation at `e78a6b6` on macOS 26.5 arm64, Python 3.12.13:
**65/65 qualification controls PASS; full suite 195 passed, 6 skipped**
(74.03 seconds). Ruff and diff whitespace checks pass. All three generated
routing profiles match their sources, and the profile/schema/package files
are unchanged from the remote baseline. Raw local logs and JUnit results are
retained under `.qualification/2026-10-17-durable-final/` and
`.qualification/durable-final-suite.{log,xml}` in the isolated worktree.

## Review and retained failed evidence

Implementation review focused on dispatch/accounting consistency and the bounds
of the measurements. It found and addressed redirects to unapproved destinations,
premature release of unknown concurrency, missing stream terminal markers,
revocation during body receipt, and reuse of a fresh ledger on a repeat run.

A full-suite run at `47d67d8` had **1 failed, 194 passed, 6 skipped**: the header
deadline control occasionally received a closed connection instead of HTTP 503.
`RemoteDisconnected` also inherits `ConnectionResetError`; the handler mistook
the upstream failure for client cancellation. The finalizer retained unknown
liability throughout. Commit `e703374` distinguishes failure before response
headers and returns a visible 503. A later full suite passed 195 tests with the
same six skips. The earlier dedicated 65-control run passed at `47d67d8`; both
observations are retained because timing selected different exception paths.

The six full-suite skips are preexisting verifier-contract integration checks:
the sibling `verifier-contract` checkout is absent from this isolated worktree.
They are not passing evidence. Human institutional/service acceptance and
independent real-capacity reproduction have not occurred.

## Concrete next decision

Assign one existing approved host, one already installed permitted model and a
named operator for a maximum 30-minute window. Complete the manifest with exact
artifact/template/version/context/quantization, enforced resource limits,
local-only/egress evidence, and an absolute durable local ledger path. Reuse that
ledger across runs; unresolved work blocks further dispatch. No paid subscription
is required by the prepared software path; local operating cost is unmeasured.

If that capacity cannot be assigned, retain **NOT RUN**. No hardware sizing,
provider price, allocation entitlement, purchase request or paid fallback is
invented. Any future spending needs its own concrete quote, budget ceiling,
owner and explicit decision before acquisition. The non-AI Python/R workflow
continues independently of this pending gate.
