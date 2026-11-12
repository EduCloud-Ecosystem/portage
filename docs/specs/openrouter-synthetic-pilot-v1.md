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
