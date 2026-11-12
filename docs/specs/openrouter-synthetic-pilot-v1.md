# OpenRouter synthetic pilot v1

## Scope and ownership

User supplied a local key and instructed proceeding on 2026-11-12. One bounded
engineering outcome: Portage's authenticated HTTP gateway reaches OpenRouter
with synthetic inputs, retaining reservations and no implicit retries.
Base: 709f5aba85dd2e56f87e9f5c32a2ac7438268ee5.
Checkout: /Users/gregchism/dev/.educloud-worktrees/portage-system-one-shadow-pilot-v1.
Branch: codex/openrouter-synthetic-pilot-v1. Prior branch/checkpoint preserved.
No other agents dispatched; no original Belay, research or other owner edits.

Reuse the existing gateway, finite request transport, membership and usage ledger.
Extend with an explicitly external, synthetic-input-only smoke mode, not hosted
institutional acceptance or the existing Ollama qualification protocol. No
fictional CPU/memory/model precision evidence. System One remains off.

## Finite execution and controls

- Four fixed text cases maximum; one external transport per case; no retries,
  warmup, automatic model/provider fallback, tools, downloads or learner data.
- One provider (OpenAI) and model (openai/gpt-4.1-mini), canonical catalog identity
  openai/gpt-4.1-mini-2025-04-14; unknown weights/precision stay unknown.
- At most 128 output tokens, 2048 reserved tokens/request, concurrency one,
  60 seconds/request, 10 minute run deadline, five-cent application budget.
- Require freshly observed public endpoint prices below explicit request price
  caps. Record vendor-reported cost separately from local request accounting.
- Credential metadata checked: valid, no key credit limit configured. Do not
  change account settings. Application price/request caps are not account caps.
- Durable one-shot run state, no replay/resume on a used directory; interrupted
  requests remain unknown and preserve original holds. No replacement run just
  to discard a failure. Raw synthetic outputs retained locally, secrets excluded.
- Pre-admission invalid credentials/revoked membership must make zero external
  requests. Exercise nonstream JSON and SSE, invalid route/override controls,
  unknown usage and transport failures offline before any paid requests.
- Inspect exact response provider/model, terminal stream marker, usage and
  deterministic synthetic outcomes; do not infer teaching quality or deployment.

Permitted source: integrations/ai_pilot/gateway.py, a bounded OpenRouter adapter/
runner in that directory, focused tests, this record. Existing deployment modes
and authority contracts keep their existing acceptance requirements.

## Verification and handoff

Focused hermetic tests, gateway/qualification regression tests, lint/format and
full suite. Live four-case check only after those pass. Preserve failed checks.
No merge, deployment, live student traffic or colony experiments. Hosted-model
internal retries and hardware are not independently visible. Classroom quality,
hosting, institutional acceptance, embeddings and trained System One remain
separate gates. Required final checkpoint: exact revision, tests, raw evidence,
actual external request count, cost/unknowns, limitations and next action.

## Implementation checkpoint before live execution

The bounded adapter is src/portage/openrouter_adapter.py, imported by the existing
HTTP gateway. integrations/ai_pilot/openrouter_pilot.py owns the one-shot runner.
The first three cases exercise Portage HTTP JSON/SSE. The fourth uses the actual
Belay-classroom PortageProvider and its enforced local ledger at unchanged source
c5a27073e74b9eeb7ab697190915378b50132883, with a fixed synthetic subject and local
synthetic membership authority. This is not an institutional enrollment exercise.
Only code_small is exposed; code_large, embedding and arbitrary prompts are not
silently enabled. Known JSON-format behavior in other modes is unchanged.

Preliminary focused checks: 82 passed across new controls/gateway/System One;
actual Belay provider and both ledgers separately passed against the offline
adapter fixture. Retained initial failures: seven-character synthetic project ID
rejected by the existing opaque-ID validator (fixed to eight characters), fixture
threads required interruption after setup errors, initial lint formatting, and
one unavailable interpreter path corrected to the existing root .venv. No paid
request occurred during these failures. Raw logs remain under ignored
.qualification/openrouter/evidence/; this includes skipped/unavailable attempts.

Reproduction (from this checkout; explicit paid execution, do not rerun an
existing evidence directory):

```sh
/Users/gregchism/dev/.educloud-worktrees/belay-classroom-system-one-consumer-v1/.venv/bin/python \
  integrations/ai_pilot/openrouter_pilot.py \
  --env-file .qualification/openrouter/.env \
  --output .qualification/openrouter/evidence/live-01 \
  --belay-source /Users/gregchism/dev/.educloud-worktrees/belay-classroom-system-one-consumer-v1 \
  --execute-approved
```

Python 3.12.13 for the Belay caller, its existing installed dependency capture
SHA256 5f9eb3e6a5d2a22fea347c386415ba483f25aa2b1681d0c4a4847150c0d2d3d2
(.qualification/openrouter/evidence/belay-environment.txt). Portage retains its
existing uv.lock; the adapter itself uses only the standard library. The capture
is an installed-environment identity, not a newly generated dependency lock.
Vendor API reference: https://openrouter.ai/docs/guides/routing/provider-selection
and https://openrouter.ai/docs/cookbook/administration/usage-accounting. Public
endpoint metadata is reacquired before the finite run; weights, exact precision,
provider internal attempts and billing correctness remain provider-reported or
unobservable, never independently attested by this probe.

## Retained live failure and bounded adaptation

At source 5a71874d4856bfb1cd63163a148c463364c44a5a, live-01 admitted
arithmetic_json, made one dispatch, returned local 503 and preserved 259 reserved
tokens plus a $0.0125 unknown monetary hold. It stopped without replay. Its
invalid-key and revoked-member controls both passed. The provider error body
was not available through the existing generic gateway error translation.

A separately recorded diagnostic used the next originally planned, previously
unexecuted extraction_json case, one direct provider request, within the same
four-request/$0.05/10-minute envelope. OpenRouter returned 404:
"No endpoints found matching your data policy (Zero data retention)."
The account credit check succeeded; lack of funds is not the observed blocker.
The diagnostic reserves another $0.0125; neither earlier hold is cleared by an
unchanged account-usage observation or the provider's refusal message.

For the remaining two unattempted cases only, external-smoke now explicitly
sets zdr=false while preserving data_collection=deny, one model/provider,
price caps, fixed synthetic prompts and no learner/private data. This changes
only the synthetic probe's provider requirement; no student deployment policy
is relaxed. The original artifacts are sealed. --continue-from reads their
pointers and carries forward the original deadline, consumed case identities
and $0.025 prior reservation. It cannot replay either attempted case, and uses
a new evidence directory for stream_terminal and the real Belay hint_json call.
A successful continuation will not turn the original failed run into a pass.

This is a product integration diagnostic, not a comparative colony experiment.
The original ZDR requirement was a conservative probe choice; its failure and
this explicit synthetic-only amendment must remain visible in any handoff.
