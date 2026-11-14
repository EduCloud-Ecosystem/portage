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

## Run the working software pilot

From a clean checkout of this branch, Python 3.11+ is sufficient for the demo:

```sh
python3 integrations/ai_pilot/decision_demo.py
```

Expected: `passed: true`, seven passing controls, HTTP statuses
`[200, 200, 200, 403]`, three actual loopback inference requests, zero external
model requests and SDK retries, and cleanup of owned servers/temporary state.
The rules baseline recommends `code_large` for one fixture while the gateway
still forwards the originally requested `code_small`. Unknown input abstains.
Output contains labels, uncalibrated scores, backend/source identity and measured
decision latency; never input text, credentials or exception messages.

For the existing synthetic gateway launcher only, set
`PILOT_DECISIONS=rules-shadow-v1`; default is `off`. Hosted and qualification
modes refuse this hook. No browser or caller can enable it. It adds no public
endpoint or response fields. Operator evidence lives in the existing ledger's
`shadow_decisions` table, keyed to admitted `requests.id`. These are synthetic
pilot records; a real-data retention/export policy remains required.

Full software checks use the existing `uv.lock`:

```sh
uv run --locked pytest
uv run --locked ruff check .
```

Use the three render-check commands in `.github/workflows/portage-ci.yml` too.
No dependency or model package was added. The initial validation used CPython
3.12.13 and uv 0.11.16, installing dependencies from the local cache with
`--offline`. The standalone demo also ran on Python 3.14.5.

The score adapter is a **trusted bounded local-code interface**, not a sandbox
for arbitrary Python plugins. Its fixed input cap is 4096 UTF-8 bytes; one call
answers all three questions. The initial score-margin threshold of 0.5 is a
reference operating point, not calibrated confidence. A trained backend must
qualify its execution time, artifact and scale before use. The production
launcher exposes only the rules baseline, and only in synthetic mode.

This delivery provides working software integration, not a learned System One
model, routing savings, scientific acceptance or classroom deployment. The
original failed numeric-validation and refusal-accounting controls and initial
lint failure are retained in `.qualification/system-one-v1/`; the umbrella
coordination record carries reviewed counts and hashes. A draft PR is not
opened automatically because this repository's PR workflow invokes a paid
model reviewer; no such invocation is authorized by this slice.
