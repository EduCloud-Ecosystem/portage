# Proposed Jetstream2 hosted qualification contract

**Status: fixture-only implementation; review and final checks pending.** This
spec defines a pure, fixture-only module for an optional hosted qualification
lane. It authorizes no provider selection, credential access, network request,
inference, deployment, spending, or default-route change.

The candidate covers one explicitly selected model and two fixed synthetic text
tasks. It keeps hosted API evidence separate from local Ollama qualification and
from hosted deployment acceptance. The existing [95-control record](../qualifications/2026-10-17-direct-local-review-controls.json),
[17 expiry controls](../qualifications/2026-10-17-expiry-controls.json), and twelve
actual-runtime NOT RUN gates remain unchanged.

## Module boundary

The implementation adds only these code and test paths:

- `integrations/ai_pilot/hosted_contract.py`: pure validation, request planning,
  and response classification.
- `tests/test_hosted_contract.py`: deterministic tests with fabricated data.
- `tests/fixtures/hosted_contract/`: synthetic request and response fixtures.

The module must not import or instantiate a network client, read environment
variables or files for credentials, start a service, mutate the ledger, register
a gateway mode, or offer an execution entry point. Production and test callers
receive data structures, never a dispatch capability. Approval evidence and
responses are supplied as test inputs; the module does not obtain them or enforce
a live clock/window.

An offline implementation can be reviewed independently of account access or
model selection. Live transport, approval persistence, and runtime admission
remain later work requiring their own reviewed contract and authorization.

## Proposed interface

These functions implement only the offline contract.

| Function | Inputs | Result and responsibility |
| --- | --- | --- |
| `validate_profile` | A draft profile containing exact endpoint/path policy, a model identifier, and opaque owner/profile references | Validated immutable profile or structured validation errors. Null or placeholder runtime requirements remain unresolved; validation never grants execution permission. |
| `build_chat_plan` | A validated fixture profile and one of two fixed task IDs | An internal request plan containing the exact method, URL and fixed body. No secret or usable authorization header is accepted or returned. The plan is not an evidence/log object. |
| `classify_response` | Fabricated HTTP status, content type, bounded body bytes, and the approved model mapping | Separate transport, task, terminal-response, and provider-reported usage observations, plus a proposed accounting action. No ledger update. |
| `assess_readiness` | Explicitly supplied evidence/approval fields | Unresolved requirements and a disabled result. This first module has no path that returns runtime execution permission. |

All outputs are deterministic for supplied inputs. Use structured error codes
without echoing raw error bodies, credentials, personal identifiers, or
unrestricted provider metadata. Fixture owner/model IDs are fabricated values
such as `fixture_owner_01` and `fixture_model_01`; they imply no existing account.
The request plan retains the fixed synthetic prompt for planning only and hides
it from its representation. Exported evidence contains only hashes and bounded
classifications; it excludes the request plan, model/owner IDs, response text,
headers, raw errors, and usage amounts. Reported usage is a separate typed
classification field, never an instruction to call the existing ledger.

## Destination and model contract

Jetstream2 documents an authenticated Open WebUI proxy and separately restricted
direct backends. This candidate targets only the proxy origin
`https://llm.jetstream-cloud.org`, with completion path `/api/chat/completions`.
Its API key must not be shared. [Jetstream2 API documentation](https://docs.jetstream-cloud.org/inference-service/api/)

The proposed catalog path is `/api/models`, based on upstream Open WebUI
documentation. Deployment-specific support remains unverified. Upstream
documentation also describes configurable defaults, filters, tools, streaming,
and usage reporting; those behaviors require service-specific confirmation.
[Open WebUI API reference](https://docs.openwebui.com/reference/api-endpoints/)

The profile owns the destination, HTTPS port 443, operation paths, exact model
ID, approved returned-model mapping, and credential-owner reference. No current
service model is selected. A fixture model does not qualify a service model.
Reject user-supplied base URLs, paths, credentials, alternate providers, fallback
models, URL credentials, or unapproved ports. No redirect, proxy override, custom
DNS, tunnel, direct-backend switch, or model fallback is part of this contract.

The existing gateway joins its configured endpoint to `/v1/chat/completions`;
changing only the endpoint value is not the proposed integration. Do not weaken
the local qualification mode's loopback checks or hosted mode's acceptance gates.
The separate module plans the exact proxy path without modifying either mode.

## Request and response contract

The proposed first request is non-streaming, text-only chat with one choice and
a requested completion limit of 32 tokens. The emitted fields are `model`,
`messages`, `max_tokens`, `stream=false`, and `n=1`. Exact field support and
whether the completion limit includes hidden reasoning need confirmation before
any later live use. A rejected limit cannot be silently removed or retried.

Only the fixed arithmetic and color-selection prompts from the direct qualifier
are in scope. Reject unsupported fields rather than forwarding them. Exclude
tools/functions/tool IDs, search, files, images, URLs, retrieval sources,
embeddings, saved-chat IDs, conversation history, and follow-up completion calls.
Omitting those fields does not independently prove that service defaults or
filters perform no additional work.

A fixture response is eligible for reported-usage classification only when it has:

- A successful status and the expected JSON content type, within a 262,144-byte
  body limit.
- Exactly one textual choice, an approved returned model ID or preapproved
  canonical mapping, an assistant message, and terminal reason `stop` or `length`.
- A nonnegative integer `usage.total_tokens`; booleans, fractions, missing values,
  and contradictory usage observations are invalid. The supported integer range
  is 0 through 65,536, inclusive. Larger values are unsupported/unknown; they are
  never clamped or passed through as SQLite charges.

The exact top-level fields are `model`, `choices`, optional `usage`, and optional
`id`, `object`, `created`, and `system_fingerprint`. `object`, when present, must
be `chat.completion`; `created` is a nonnegative signed-64-bit integer; optional
IDs/fingerprints are bounded strings (fingerprint may be null). Each response has
one choice with exactly `index=0`, `message`, and `finish_reason`. The message
contains exactly `role=assistant` and a string `content` of at most 8,192
characters. Usage contains `total_tokens` and optionally both `prompt_tokens`
and `completion_tokens`; all use the supported integer range and the two
components must sum exactly to the total. Partial component pairs and additional
usage/detail fields are unsupported. Missing usage remains unknown even when the
text answers the task correctly.

Reject duplicate JSON keys, any floating-point/nonfinite JSON number, unknown
fields, error objects, tool/function calls, task IDs, streaming or incomplete
responses. Accept only UTF-8 JSON and the declared bounded schema. No provider
compatibility is inferred from this deliberately small supported subset.

Unexpected streaming, incomplete JSON, model substitution, unsupported tool
work, or ambiguous termination produces a stop/retain-unknown recommendation.
A terminal length-limited reply may report usage while failing the exact-output
task check. `length` always fails the exact-output task check, even if the visible
text matches. Valid supported usage above the reservation is retained in full
with a stop/bound-failure classification. A valid response is labelled
**provider reported**, never independent
proof of model identity, resource consumption, or hidden engine attempts.

## Accounting and approval contract for later runtime work

The module only describes accounting actions. A future runtime integration must
preserve these boundaries using Portage's existing ledger and expiry controls:

| Event | Required behavior |
| --- | --- |
| Rejection before admission | No reservation or inference dispatch |
| Any uncertainty after admission | Retain the full reservation and active slot as pending/unknown |
| Valid terminal response with valid reported usage | Record the full reported usage with its provenance; do not infer independent engine measurements |
| Usage exceeds reservation | Record the full amount, stop the run, and fail the reservation-bound assessment |
| Timeout, disconnect, expiry, provider error, or missing usage | No automatic retry, refund, fallback, or cancellation claim |
| Restart or new output directory | Preserve approval identity, attempts, reservations, and unknown liabilities |
| Reconciliation | Require independently validated termination/completion and usage evidence; a supplied evidence hash alone proves neither. Unknown work stays held when evidence is unavailable. |

The proposed initial live envelope is two serial inference attempts and at most
two catalog reads in a maximum 15-minute approved window, with request timeout at
most 60 seconds. These are unapproved design ceilings. Proposed reservations of
1,024 units per attempt and 2,048 total are provisional Portage accounting units;
they are not proven provider token, GPU, memory, or monetary bounds. Live work
stays disabled if an acceptable finite resource bound cannot be established.

A future implementation must persist an immutable approval/profile identity and
the attempt ceiling in the same transaction as admission. Current per-invocation
loop limits and token allowances alone cannot enforce a lifetime attempt cap.
Completed attempts count toward it; relabeling a run or changing credentials
cannot reset it. Catalog reads have a separate durable count and no polling.

Keep membership checks and expiry checks after metadata and queue/authority
waits, under the ledger write lock, and after connect immediately before dispatch.
Test remote DNS/TLS delays separately: socket timeouts do not prove a hard bound
on DNS resolution, and socket shutdown does not prove provider cancellation.

## Evidence separation

New fixture evidence uses `hosted_service_qualification` as a separate namespace.
Fixture results may pass only synthetic controls. All provider observations
start NOT RUN; cancellation evidence starts UNVERIFIED. No API response can make
any of the twelve existing local runtime gates pass.

| Hosted observation | Claim it cannot replace |
| --- | --- |
| Requested/returned model ID and metadata hash | Installed weight digest, template, quantization, immutable deployment identity |
| Two client-visible outcomes and durations | Service availability/SLA, representative workload quality, engine latency |
| Serial admissions and reported usage | Concurrency-two behavior, hidden attempts, independently measured consumption |
| Catalog context value | Tested effective context or tokenizer/hidden-reasoning reservation bound |
| Published hardware description | Resident or peak memory measurements |
| Client disconnect or Portage restart | Provider cancellation, engine termination, or provider-engine restart |

Keep actual memory, engine internals, model digests, and provider restart
unavailable when the service cannot expose the needed evidence. Do not convert
unavailable evidence to PASS or weaken hosted deployment acceptance.

## Runtime decisions that remain open

A later runtime proposal needs a named credential owner and confirmed individual
access; exact model/destination and license approval; service defaults, filters,
external destinations, usage/output-limit semantics, and change policy; API data
retention/deletion and administrator-access terms; acceptable finite limits; and
a recovery path for uncertain remote work. An initial probe acts only for its
credential owner. Multi-user use of a personal credential needs separate provider
and institutional permission.

Provider descriptions remain source statements, not verified deployment or
institutional acceptance. See the [service overview](https://docs.jetstream-cloud.org/inference-service/overview/)
and [usage policies](https://docs.jetstream-cloud.org/general/policies/). This
proposal contains no account identifiers, credentials, private approval records,
local filesystem paths, or allocation selection.

## Proposed controls and acceptance

[The fixture-control plan](jetstream2-hosted-controls.json) separates passing
pure-module assertions from later runtime integration tests. The focused local
suite has 147 passing tests. Runtime requirements remain NOT RUN; describing or
classifying them in fixtures does not establish live enforcement.

For the authorized offline implementation, require deterministic tests with
network and secret access prohibited, sanitization checks, and independent
review. Then run the existing 95 controls, 17 expiry controls, full suite, lint,
and generated-profile checks. Record new evidence separately at the reviewed
source revision. An offline implementation PASS is not execution authorization,
provider qualification, deployment acceptance, or route promotion.
