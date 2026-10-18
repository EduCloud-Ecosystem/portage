# Direct local inference qualification

This is the narrow Portage P2 work item from the approved October 17, 2026
EduCloud handoff. It preserves the public `/v1` API and credential, membership,
allowance and reconciliation boundary. An explicitly selected `qualification`
mode routes one `code_small` alias to one existing local Ollama engine. It does
not change default routes, qualify hosted service, or require inference for
Python/R. Belay, portage-local, Waypoint, Outfitter and PAIR are outside this change.

## Existing implementation and narrow changes

The prerequisite gateway and ledger already existed at local Portage commit
`9e2a877ef414413a402093d7ca06bb7ff60c5200`. They provide participant/application
credentials, current membership checks, aliases, atomic project/participant
allowances, request identities and reconciliation. The isolated worktree starts
from remote `main` `2ec86ad0447d71a90ab545206b44fe41dbb69ee0` and cherry-picks only
that pilot commit. Unrelated local documentation/routing commits are excluded;
the original checkout and branch are preserved.

Qualification adds server-controlled alias-to-engine-model mapping. Other modes
retain their five-alias contract. Qualification requires a literal loopback
HTTP origin and cannot substitute for hosted acceptance. HTTP redirects and
environment proxies are disabled for inference and membership. Membership is
rechecked after body receipt, immediately before atomic ledger admission.

Unknown requests retain both token reservations **and concurrency slots** until
evidence-backed reconciliation. The existing `active` field now counts pending
and unknown requests because either may still be running. This is a conservative
behavior correction with the same response schema. Streams must reach `[DONE]`
without an error before reported usage settles. Cancellation, truncated streams
and failures leave unknown liabilities. An absolute transport deadline bounds
each response attempt; `X-Portage-Request-Id` links dispatch, response and ledger.

## Synthetic controls

From the isolated Portage checkout, with its development dependencies:

```sh
uv run python integrations/ai_pilot/qualify.py --output .qualification/controls-01
```

Choose a fresh directory; existing evidence is never overwritten. The command
runs real loopback HTTP against deterministic fake membership/inference servers.
It writes `record.json`, `controls.xml` and `controls.log`, with source hashes and
per-control PASS/FAIL/NOT RUN. Without a manifest it makes **no real engine
request** and leaves every runtime gate NOT RUN. Tests of the live runner also
use a fake engine; their durations/memory fixtures are not model benchmarks.
Every selected control must pass before the runner can enter the live path;
skipped controls remain NOT RUN and fail the overall control gate.

Controls cover both transports; user/project identity; application scope;
spoofed headers/body fields; forbidden aliases, destinations, redirects and
proxy variables; expired/revoked credentials; unavailable membership; revocation
during body receipt; both allowance scopes; concurrency; separately admitted
retry/background calls; cancellation; deadline; engine failure; invalid/missing
usage; and restart/reconciliation.

## Prepare the capacity manifest

Copy `integrations/ai_pilot/qualification.example.json` to a private evidence
directory and fill every null from operator-reviewed evidence. It is deliberately
not executable. The template's 32-token output, 1,024-token request reservation
and 32,768-token aggregate ceilings are **protocol limits**, not measured model
capabilities. Maximum accepted bounds are 128 output tokens, 4,096 per request,
65,536 aggregate tokens, concurrency two and 120 seconds per attempt.

| Field | Required evidence before generation |
| --- | --- |
| Operator/host/approval/license | Existing capacity assignment and permitted installed model; no acquisition implied |
| Endpoint/request type | Literal loopback origin; text-only `POST /v1/chat/completions`, streaming and non-streaming |
| Engine version | Exact installed version compared with `GET /api/version` |
| Model/revision | Exact installed name and full 64-hex digest from `GET /api/tags` |
| Template | SHA256 of exact UTF-8 template from `POST /api/show` |
| Quantization | Exact installed `details.quantization_level` |
| Context | Approved effective context, checked against `GET /api/ps` during the run |
| Token bounds | Fixed output limit and conservative byte-plus-framing reservation; tokenizer proof is a separate gate |
| CPU/memory | Actual process/container limits and observation procedure; gateway metadata does not enforce engine resources |
| Ledger | Absolute path on local disk outside per-run evidence directories; reuse across retries/runs |
| Local-only/egress | Evidence of disabled cloud routing and blocked external egress; loopback alone does not prove locality |
| Absolute expiry | Timezone-aware deadline within 30 minutes, allowing time for synthetic controls first |

The runner verifies installed version, digest, template and quantization before
generation and each batch, rejects cloud-backed metadata, and never pulls,
copies, warms up through an unaccounted call, stops or restarts an engine.
Freeze the model-name mapping for the run. Operator attestations are inputs,
not programmatically verified operating-system controls.

Ollama documents streaming chat, `stream_options.include_usage` and output
limits in its [OpenAI compatibility reference](https://docs.ollama.com/api/openai-compatibility).
Context must be configured on the model/engine; this API does not set it.
[Installed-model metadata](https://docs.ollama.com/api/tags) and
[running-model metadata](https://docs.ollama.com/api/ps) supply inventory and
resident-size observations. The [FAQ](https://docs.ollama.com/faq) documents
local-only configuration and parallel-request controls. These interface
references are not qualification evidence for any installed engine.

## Frozen bounded workload

After existing capacity/model approval is recorded:

```sh
uv run python integrations/ai_pilot/qualify.py \
  --manifest .qualification/approved-manifest.json \
  --execute-approved --output .qualification/direct-01
```

Keep the manifest outside the new output directory. Only synthetic prompts enter
the engine: integer arithmetic and selecting a color from a fixed list. Two
tasks × two transport modes × concurrency cells 1 and 2 × two repetitions =
**16 maximum inference attempts**, each admitted through Portage. There are no
unmetered warmups/retries. Do not call the first request a cold start without
observing engine residency first. Metadata reads are not inference. Batches stop
before expiry and after unavailable or ambiguously accounted work. A client
disconnect does not prove engine termination; its budget and slot remain held.

The runner rechecks remaining time after each metadata pin and before each
batch. The gateway checks every request after authority verification, inside
the ledger write transaction immediately before reservation, and after connect
immediately before engine dispatch. An elapsed-time deadline prevents a wall
clock rollback from extending the approval. The transport timeout is capped by
the remaining approved window. Expiry before reservation creates no liability;
expiry after reservation retains unknown usage and its concurrency slot, even
when dispatch was refused. Socket interruption does not prove that already
admitted engine work has stopped; reconciliation still requires evidence.

Separate fake-clock and loopback regressions live in
`tests/test_qualification_expiry.py` and CI's `synthetic-expiry-regressions`
artifact. They supplement the frozen 95-control record without changing it or
closing any of the 12 actual-runtime NOT RUN gates. The separate
[expiry regression record](../qualifications/2026-10-17-expiry-controls.json)
retains the failing baseline and fixed-source hashes.

`attempts.json` links request/ledger identity, latency, streaming first-content
time, availability, exact-output quality and output hash. The private SQLite
ledger retains liabilities across runs, even with a new evidence directory.
Pending/unknown work blocks a further run before dispatch. Random credentials are hashed
and disabled on normal exit. `record.json` gives nearest-rank p50/p95 over
successful calls with denominators. This tiny workload tests instrumentation,
not an SLA or research competence. Inspect per-cell rows: two admitted clients
do not prove two engine workers execute simultaneously.

`GET /api/ps` samples resident model/VRAM sizes after batches. These are
engine-reported observations, **not OS/GPU peak memory measurements**. The sample
gate is marked FAIL when returned size fields are missing or invalid. Capture
independent peak measurements and corroborate settings on the approved host.
Retain engine request tracing to prove internal attempts do not bypass Portage.
Prove the reservation bound against the pinned tokenizer/template, including
framing and supported text inputs. Peak memory, internal attempts, tokenizer
bound and operator restart stay NOT RUN in automatic output; evidence-backed
human review closes them. Embeddings, tools, images, Responses API, RAG and
research-task quality are outside this selected path.

## Failure, reconciliation and operator restart

1. Stop new submissions after ambiguity. Retain record, manifest, source hashes,
   ledger and engine evidence. Never create a fresh ledger to bypass liabilities.
2. Fence the test gateway and observe the named engine's active work. A closed
   connection is not cancellation proof. Never stop an unrelated/shared service.
3. If needed, use that host's approved engine restart procedure. Record exact
   command, operator, timing, owned processes and remaining work. This harness
   does not install or manage services.
4. Reopen the same ledger offline and inspect `pending`/`unknown` rows. Reconcile
   current membership/revocations before reopening access. Restart never
   redispatches, refunds or clears work automatically.
5. Reconcile only after independently proving termination/completion and
   measuring usage. Operator-only `/control/reconcile` requires request ID,
   measured usage and SHA256 of retained evidence. The digest is provenance,
   not proof of correctness. If usage is unknowable, keep it unresolved.
6. Recheck model pins, context and limits before further approved work. Carry
   unresolved liabilities forward in the same ledger; this harness cannot resume an
   ambiguous run. Record restart acceptance separately.

## Capacity decision and institutional gates

October 17 discovery found an installed Ollama executable, no listener at
`127.0.0.1:11434`, and an empty default model-manifest inventory. No approved
alternate capacity/model manifest was supplied. No engine was started, model
downloaded, subscription purchased or resource provisioned.

**Defer live qualification; assign an existing approved host and installed
permitted model.** The concrete decision needs a named operator, pinned artifact
and template, available CPU/memory or GPU limits, a maximum 30-minute window,
and the completed manifest. No subscription is required by this software path;
that is not a zero operating cost claim. If existing capacity cannot be assigned,
keep runtime NOT RUN. Any purchase would need a separate quote, ceiling, owner
and explicit decision; none is requested or authorized here.

Institutional identity/current membership, data classes/destinations, access
isolation, recovery/revocation/deletion reconciliation, retention, support,
accessibility, representative task quality and cohort load remain service gates.
Synthetic results do not admit private research or student records. Hosted
launch, adoption and default-route migration require separate approval.

## Offline capacity review packet

`review_packet.py` turns **one existing public record** and a separate capacity
draft into `packet.json` and `packet.md`. It does not run controls, contact an
engine, import the qualifier/gateway, open a ledger, or authorize any action.
The accepted 95-control record stays unchanged, including its original source
revision, file hashes, platform, denominators, and all runtime gates NOT RUN.

Reproduce a review packet from that pinned record without running inference:

```sh
mkdir -p .qualification
uv run python integrations/ai_pilot/review_packet.py \
  --root . \
  --record docs/qualifications/2026-10-17-direct-local-review-controls.json \
  --expected-sha256 7744b3f070cae861d0a06bf547795d89d9f46f00157ea8db9484fa1cb8ec190f \
  --capacity-draft integrations/ai_pilot/capacity-review.example.json \
  --output .qualification/capacity-review-01
```

Supply the expected record SHA256 from a separately trusted review or source
commit. Calculating a hash from an unknown record and immediately treating that
same hash as trusted only proves self-consistency. The packet verifies bytes,
not the truth of an operator statement or the current machine's state.

The capacity draft is deliberately incomplete and has its own schema. It is
**not** the executable `qualification.example.json` manifest and contains no
hosted-readiness booleans. Proposed protocol limits are not resource approvals.
Use public opaque operator/host/ledger references; keep private names, account
credentials and absolute ledger paths in the appropriate protected system.
All `*_evidence_ref` fields must refer to an explicitly pinned artifact:
repeat `--artifact relative/path=SHA256` for each public evidence file. Cost
category `evidence_ref` fields use the same references. File contents are not
copied, interpreted as instructions, or combined into another run's results.

The packet follows the umbrella cost packet's eight categories: need and
alternatives, exact resource, primary-source terms, finite request, full exposure,
controls, operations, and decision. Missing cost amounts, currency, billing
interval, and native-unit ceilings remain null. The builder neither calculates
prices nor converts tokens, native allocation units, or memory measurements
into currency. A complete draft only passes **field completeness**; execution,
promotion and spending authorization are always false.

Source-reported runtime results remain separately labeled unverified claims;
offline review never promotes them to live acceptance. Failed or skipped controls
cannot become a control PASS. Missing usage stays unknown; pending/unknown
attempts remain visible even if the imported aggregate claims zero. Measurements
retain their native units. The packet accepts exactly one source record and
does not pool different model, template, context or platform results.

Use a narrow root containing intended public evidence. Inputs and output paths
must be relative to that root with existing real parent directories. Symlinks,
FIFOs, devices, traversal, duplicate JSON keys/control IDs, nonfinite numbers,
and output collisions are rejected. Limits are 1 MiB per record/artifact,
64 KiB per draft, 16 extra artifacts, 4 MiB total input, 2,048 controls and 16
attempts. The new output directory is private (0700), with 0600 files. Invalid
inputs create no output; an I/O failure while writing may leave an incomplete
new directory for inspection. Nothing is overwritten. Only whitelisted public
fields are emitted; control parameter text is replaced with a case-identity hash.

The resulting decision remains: assign an existing approved host, installed
permitted model and named operator, complete the pinned model/resource/egress/
recovery evidence, and separately approve one bounded window and native-unit
ceiling. If capacity is unavailable, retain **NOT RUN** and continue offline
work. This packet requests no purchase and performs no deployment or route change.
