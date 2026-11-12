# System One shadow decision pilot

User-authorized implementation, 2026-11-12. Base:
`79742746b10ace18e498111dd5a8f3227edd995c` (current remote main and the
classroom integration pin). Worktree: `portage-system-one-shadow-pilot-v1`,
branch: `codex/system-one-shadow-pilot-v1`. The primary `codex/ai-pilot`
checkout diverges and lacks qualification controls; it is preserved.

## Outcome and reuse

An admitted synthetic classroom request produces a bounded, typed advisory
decision alongside its existing inference accounting. The requested model,
permissions, deadlines and grading authority do not change. Reuse the actual
gateway, current-membership checks, ledger and classroom `code_small` /
`code_large` aliases. No new service, model download, learned router, public
endpoint, or secondary reservation authority.

System One means input plus a fixed set of typed questions to decisions, not
fast text generation. Provide an in-process score-backend interface, strict
validation and abstention, and an ordinary rules baseline. The baseline is
explicitly NOT a trained System One model. A synthetic score backend exercises
the single-forward-call contract in tests. Actual model quality and calibration
remain unqualified; scores are never labeled probabilities.

## Bounded implementation

1. Add `src/portage/decisions.py`: versioned fixed questions, finite input,
   typed labels/scores, abstention, one backend invocation, content-free results.
2. Extend only `pilot_ledger.py` and `integrations/ai_pilot/gateway.py` with an
   opt-in synthetic-only shadow hook, after admission and before inference.
   Retain failures, latency, backend identity and work counts in the existing
   ledger. Recheck current membership after the hook. No automatic route change.
3. Add focused negative controls and a standalone finite loopback demo using
   actual gateway/ledger code and fabricated data. No external model transport.
4. Run focused checks, full existing suite and all three profile render checks.
   Retain failed check outputs under ignored `.qualification/system-one-v1/`.

Scope excludes other component source, existing qualification artifacts,
pedagogical/affective classification, production configuration, paid calls,
training, deployment, merges and colony experiments. Local CPU rules and
synthetic fixture tests are software verification, not scientific acceptance.

## Acceptance

- Disabled default produces no decision events and preserves the wire response.
- Enabled shadow emits exactly one decision event per admitted chat attempt;
  forbidden aliases, malformed input, inactive membership and exhausted budgets
  do not invoke the backend. Embeddings are unchanged.
- Unknown, ambiguous, malformed and non-finite backend scores abstain; exception
  text and original input never enter durable events. Scores are uncalibrated.
- One batched backend invocation answers the fixed questions; failures count.
- Shadow cannot promote a route, bypass refusal, erase unknown usage, or alter
  qualification/hosted mode. Actual inference transports remain separately counted.
- Decision-step revocation is rechecked before inference; original liability is
  retained conservatively on failure. Streaming retains ordinary behavior.
- Clean-checkout demo is finite, loopback-only, self-cleaning and labels all
  model responses synthetic. No successful software control implies model quality.

## Next qualification

Freeze a separately reviewed decision-model artifact and evaluation set, compare
against these rules and the existing LLM approach, and measure correctness,
abstention, latency, costs and downstream quality. Do not enable route-changing
behavior or student-data processing from this synthetic milestone.
