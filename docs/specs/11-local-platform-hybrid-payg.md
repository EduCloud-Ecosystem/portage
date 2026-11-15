# Local Platform — Hybrid Open-First with Proprietary PAYG Ceiling

> **Ladder rewritten 2026-08-05** per CW-04 and CC-P6; decision record in `portage-local/docs/reports/`.

*Recommended Scale 1 transition architecture: open-weight models receive the workload first; proprietary APIs remain
available only as metered, evidence-based escalation.*

> **Revised 2026-07-28 per CW02-decisions.md §3 (dormant-slot synthesis) —
> HISTORICAL, superseded in part by the note below.** local_burst is no longer a
> tier (this part stands) — the MacBook is a second health-checked deployment of
> `local_fast`, and the freed T2 slot holds `local_large` (dormant, enabled:
> auto). *Superseded:* this revision put Groq at T3 (`remote_open_fast`) and
> Together at a defined-but-dormant T5. Neither holds — see below. Capability
> aliases are the seven-cell set in CW02 §3.

> **Revised again 2026-08-05 per `CW04-model-roster.md` §2.1–2.5 and CC-P6.**
> Groq vacates T3 into the dormant reserve — its self-serve catalog serves none
> of the models this roster selects. **OpenRouter leaves the ladder entirely**:
> removed, not demoted in place, because serving precision is now the deciding
> constraint. T3 is `remote_open_direct` (DeepSeek first-party); T4 is
> `remote_open_broad` (Morph, bf16 unquantized) plus the "Flash Max" re-run; T5
> is `remote_open_reserve`, dormant, absorbing Groq and Together. **The
> proprietary ceiling collapses to one occupant**: `proprietary_research` =
> GPT-5.6 Sol, `enabled: false`. Anthropic's `proprietary_code` row is deleted
> outright — not capped, not gated — so the deployment declares six aliases, not
> seven, and Perplexity is gated behind the science-lane citation verifier
> rather than occupying a rung. The Kimi K3 **Fable tier** is added off the
> chain: not a T-number, not rung 7, entered only by a logged human declaration.
> The old §6 `proprietary_specialist` / §7 `proprietary_ceiling` split is gone
> with the multi-vendor ceiling it described; T6 is one line and T7 is the
> terminal stall.

## Purpose

This is the recommended **production transition mode** while the platform measures whether open-weight models have
reached sufficient parity for the user's real workloads.

The architecture preserves the existing Herdr + LiteLLM routing spine, deterministic triage, `adapt.py`, `failup.py`,
plan-first decomposition, and `measure.py`.

The major change from the original subscription ladder is:

> **Remove fixed Claude Max/Codex-style subscription rungs.**

Use local open-weight inference first, then hosted open-weight inference, and only then use proprietary APIs when the
open ladder has genuinely failed or a specialist capability requires them.

---

## Core principle

> **Open-weight by default; proprietary only when it produces a verified outcome that the open ladder could not.**

The target is to eliminate recurring model subscriptions immediately while preserving a measured frontier safety valve.

---

## Scale 1 footprint

### Existing hardware

- **iMac** — always-on LiteLLM + local inference
- **MacBook Pro** — Herdr surface plus opportunistic local inference worker
- **2 TB NVMe** — active AI workspace
- **8 TB Seagate** — bulk/archive/backup tier

### Future hardware

- **High-memory local AI node** — target roughly 128 GB model-accessible memory
- Added when telemetry shows it will materially replace hosted or proprietary inference

---

## Recommended topology

```text
                         HERDR
                           |
                 classify / adapt
                           |
                        LiteLLM
                           |
        +------------------+------------------+
        |                  |                  |
   local-fast                           local-large
   iMac + MacBook Pro                 future 128GB node
   Gemma 4 E4B (warm) + 12B Q4        (dormant, enabled: auto)
   (two deployments, one rung)
        |                  |                  |
        +------------------+------------------+
                           |
                   remote-open-direct          T3
              DeepSeek, first-party API
              v4-flash (cheap first attempt)
                    ->  v4-pro
                           |
                   remote-open-broad           T4
                 Morph — MiniMax M3
                   (bf16, unquantized)
                           |
              "Flash Max" — same rung, same
              checkpoint as v4-flash above,
              re-run at `effort: max`
                           |
                  remote-open-reserve          T5
           [DORMANT — Groq (latency trigger) /
            Together (Morph-outage trigger)]
                           |
                      proprietary              T6
              GPT-5.6 Sol, and nothing else
                 (enabled: false)
                           |
                      CEILING_STALL            T7


  ── not rungs, at any T-number ────────────────────────────────────────

  FABLE TIER — Kimi K3  (moonshot/kimi-k3)
      Reached ONLY by an explicit human declaration that a specific task
      warrants it, with the reason logged. Never by a stall, a verifier
      failure, or any other escalation. It is NOT rung 7 — T7 is the
      terminal stall — and it is not the step after T6. It is off the
      escalation graph, which is why it is drawn outside the chain
      rather than below it. Carried as `fable_tier: true` +
      `enabled: false`. Public weights, `license_family:
      non_permissive`, so `open_weight_only` excludes it too.

  OpenRouter
      OFF THE LADDER entirely (CW-04 §2.2) — not a rung at any
      T-number. Its defined role is a non-routable failover path tagged
      `unbenched`, reachable only when a first-party endpoint
      health-checks down. THAT PATH IS UNBUILT: the schema carries a
      `failover_only` field for it and NO row sets it. Nothing routes
      through OpenRouter today; the mechanism is HB-2 work.

  Anthropic / Claude
      NOT PRESENT. `proprietary_code` was deleted from the registry by
      CC-P6, not disabled and not capped — its budget line is gone, and
      a T6 gate over a line with no cap protects nothing. Lane A's
      Claude Code usage is subscription-based and never touched this
      row. Six aliases are declared now, not seven.
```

---

## Inference ladder

### 0. `deterministic`

Runs before any inference.

Responsibilities:

- sensitive-content handling
- explicit overrides
- task-shape rules
- triage
- acceptance-command discovery
- policy checks
- budget checks
- provider/model availability checks

---

### 1. `local_fast`

**Primary host:** iMac.

Use for:

- classifier
- routine coding
- bounded edits
- summarization
- extraction
- R/Python/SQL assistance
- embeddings
- low-cost agent work

Always preferred when likely to succeed.

**Current occupants** (CW-04 §2.4; live in `registry.yaml`): `classifier` =
`gemma4:e4b` on the iMac, sole occupant, kept warm at `OLLAMA_KEEP_ALIVE=-1`;
`code_small` = `gemma4:12b` Q4 on the MacBook (`order: 1`) with `gemma4:e4b` on the iMac as `order: 2`; `embedding` =
`nomic-embed-text` on the iMac, single deployment. Qwen3-Coder 7B is retired from the documented roster entirely and
appears nowhere in the live registry.

All three Gemma rows carry `license_family: unverified` — the Gemma terms carry use restrictions, so `permissive` would
be wrong and `non_permissive` would be a guess about a grant nobody here has read. `unverified` fails closed by design.
That matters less in `hybrid` than it will at the flip to `open_weight_only`, where these rows would not clear the gate
as currently labelled.

---

### 2. `local_fast`, second deployment (formerly `local_burst`)

No longer a tier (CW02 §2.1): tiers are capability rungs, machines are deployments. LiteLLM load-balances the MacBook
inside `local_fast` with health checks; it buys availability, not capability.

**Host:** MacBook Pro when available.

Use for:

- parallel subtasks
- second-agent review
- test generation
- specialist models
- background indexing
- medium local models

A sleeping or absent MacBook is logged as:

```text
unavailable
```

not as a model failure.

---

### 3. `local_large`

**Future host:** roughly 128 GB high-memory AI node.

Use for:

- larger coding models
- larger reasoning models
- long-context local tasks
- large open-weight MoE models
- local research synthesis
- workloads currently requiring hosted open-weight compute

Expose capability aliases rather than permanent model names:

```text
code_large
research_synthesis
```

Parity Bench determines the model assigned to each alias. The alias vocabulary is the seven-cell set in CW02-decisions
§3; the former `local/*`
namespace is retired — where a capability runs is a deployment property, not part of the alias.

---

### 4. `remote_open_direct` (T3)

**Provider: DeepSeek, first-party** — `api.deepseek.com`, via LiteLLM's native
`deepseek/` route.

Herdr chooses the model *and* the surface serving it. There is no delegated infrastructure choice at this rung, which is
the design rather than a gap.

**Why direct rather than aggregated.** DeepSeek's first-party API does automatic prefix caching, billing a repeated
prefix at roughly 2% of the miss rate. That cache is the reason this rung's economics work, and it is a first-party
behaviour that routing through an intermediary forfeits. It is the whole reason T3 exists separately from T4 (CW-04
§2.2). If Morph turns out to carry an equivalent cache, CW-04 §4 item 1 keeps collapsing T3 into T4 open as a live
option — that verification is not done.

**Occupants:**

| Model               | Where                                              | `license_family`                                                         | Role                                                                        |
|---------------------|----------------------------------------------------|--------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| `deepseek-v4-flash` | `code_large` order 1, `research_synthesis` order 1 | `permissive` (MIT, confirmed 2026-08-05, weights public on Hugging Face) | the **cheap first attempt**, ahead of the primary occupant — not a fallback |
| `deepseek-v4-pro`   | `research_synthesis` order 2                       | `unverified`                                                             | the primary occupant for research synthesis                                 |

Order numbers ascend by cost, so they *are* the escalation order — and Flash sits **before** the primary occupant, not
after.

Controls that apply: the allowlist is expressed as which rows exist in
`registry.yaml` (a model that is not a row is not a deployment); every row carries `license_family`, checked at T0, with
`unverified` failing closed; there is no model fallback outside the registry; and benchmarking is per endpoint, not per
model name. Serving precision needs no filter here because there is no intermediary that could change it.

Both model IDs are the vendor's **documented** names, not confirmed against a live `/v1/models` on DeepSeek's own API —
each carries a `TODO(native)` in
`registry.yaml`, and the B7 gate governs.

---

### 5. `remote_open_broad` (T4)

**Provider: Morph** — bf16 activations, no quantization, one key, via LiteLLM's native `morph/` route.

**Why Morph and not an aggregator.** Every alias is a benchmark cell, and reproducibility is one of the six inclusion
criteria. An aggregator free to change quantization under a stable model ID makes that cell irreproducible — the same
model name silently becomes a different measurement. Morph serves open models at 16-bit activations without quantization
*and says so*. That one test removed six providers from consideration (CW-04 §2.2, §3), and it is why this rung names a
vendor instead of describing a routing policy.

**Occupant:** MiniMax M3 (`morph/minimax-m3`), `code_large` order 2,
`license_family: unverified` — MiniMax M2 shipped MIT, but M3's grant is not confirmed. GLM-5.2 and Qwen sit in-slot
behind the same key if wanted, with no new account and no fresh inclusion review.

**"Flash Max" — a second rung on the same checkpoint.** After the Morph occupant comes `deepseek/deepseek-v4-flash`
again at `effort: max` (order 3 on both ladders). **The same checkpoint as order 1, not a separate model.**
Buying more thinking on a model that already passed the cheap attempt is a cheaper escalation than onboarding a new
vendor.

> **Caveat, unresolved.** `litellm_settings.yaml` sets `drop_params: true`. If
> DeepSeek's API rejects the literal `reasoning_effort: max`, LiteLLM drops the
> parameter **silently** and this rung collapses into a duplicate of order 1 —
> no error, just quietly not a rung. Confirm at HB-0 Gate 2.

---

### 6. `remote_open_reserve` (T5) — DORMANT

Defined, disabled, holding two unrelated re-enable triggers, per the CW-02 §2.1 dormant-slot idiom.

> **Naming hazard.** This slot was called `remote_open_direct` under CW-02, and
> CW-04 reassigned that name to **T3** (DeepSeek). Two tiers have held the same
> name at different times — when reading anything dated before 2026-08-02, check
> which is meant.

**Trigger (a) — a latency-sensitive alias no local rung can serve.** Occupant would be **Groq GPT-OSS 120B** (~$0.15/$
0.60, ~500 tok/s), entering **benched as its own capability cell, never as a route to an existing roster model**. Groq
held T3 and vacated it: its self-serve catalog (Llama 3.1 8B / 3.3 70B, GPT-OSS 20B / Safeguard 20B / 120B, Qwen 3.6
27B, MiniMax M2.7 enterprise-only) offers no path to DeepSeek, Kimi, GLM or Mistral, so it cannot serve the models this
roster selects — and it offers no prompt-caching discount, removing the mechanism that makes direct-provider economics
work (CW-04 §2.1).

**Trigger (b) — sustained Morph unavailability.** Occupant would be **Together AI**: serverless per-token inference, no
GPU provisioning, broad open-model catalog, OpenAI-compatible. Together's original CW-02 trigger referenced OpenRouter
unavailability and is superseded by this one. It is also the standing mitigation for the open half of Morph's
inclusion-test assessment, vendor durability (CW-04 §4 item 4).

**Neither is wired.** No Groq or Together rows exist in `registry.yaml`, no keys in `.env.example`, nothing routes to
either. Re-enabling means adding rows and running the inclusion test, not flipping a flag.

DeepInfra, Fireworks, Novita, Atlas and GMICloud are **rejected, not dormant** — serving precision undocumented per
endpoint, which breaks a benchmark cell (CW-04 §3). Recorded there with reasons so a later pass does not reopen them
silently.

---

## Proprietary escalation boundary

No proprietary API should be invoked simply because it is “better.”

It must satisfy at least one of these conditions:

1. **Verified open failure** — applicable open-weight rungs were tried and failed objective acceptance criteria.
2. **Documented specialist requirement** — the capability is not yet reasonably reproduced by the open stack.
3. **Explicit user override** — the user intentionally requests the proprietary provider.

This is the policy boundary that prevents the hybrid system from quietly becoming a proprietary-first system again.

**But be precise about what enforces it.** In this repo the T6 boundary gate is **a policy sentence plus
`enabled: false` on the row** — not code. `P6-report.md`
§1 established this by reading the source: grepping `src/` for `T6`,
`confirm_gate`, `confirm gate` or `logged.reason` returns nothing, no
`failup-log.jsonl` has ever existed on disk, and `failup.py` never opens
`registry.yaml` at all — its ladder is file-driven from `.claude/tiers.*.json`, whose rung names (`local-small`,
`sovereign-work`, `sonnet`, `opus`) do not intersect the registry's capability aliases. There is no confirm-prompt to
point at and no logged-reason mechanism to extend. Do not write as though either exists; building them is HB-2 work.

---

## 7. `proprietary` (T6) — one occupant

The earlier form of this document split the ceiling into a
`proprietary_specialist` tier routed by capability profile (Anthropic for code, Perplexity for research, a general
reasoning ceiling above both) and a
`proprietary_ceiling` above it. **That structure is gone**, because the thing it organised is gone. There is one
proprietary line:

| Alias                  | Occupant                                                                                                                                                         | State            |
|------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------|
| `proprietary_research` | GPT-5.6 Sol — registry `provider_route: openai_direct`, rendering to `model: openai/gpt-5.6-sol` with `api_key: os.environ/OPENAI_API_KEY` and **no** `api_base` | `enabled: false` |

And two absences that matter more than the occupant:

- **`proprietary_code` (Anthropic) does not exist.** CC-P6 deleted the row outright — not disabled, not capped, not
  gated. Its budget line was removed entirely, and a T6 gate over a line with no cap protects nothing. Lane A's Claude
  Code usage is subscription-based and never went through this row. As a result the deployment declares **six** of the
  seven fixed aliases; the seventh is absent from the declaration, not hidden from the listing, so HB-0 Gate 2's
  invariant still holds in the form it is stated.
- **Perplexity is not a rung.** CW-04 §3 gates the Perplexity API behind the science-lane citation verifier — "do not
  open before that ships" — so it should never have occupied `proprietary_research`. GPT-5.6 Sol replaces it there
  (CW-04 §2.3).

The `openai_direct` route is deliberately distinct from the `openai` route. Both render the same `openai/<model_id>`
LiteLLM prefix, which is exactly why the distinction has to live at the registry level: `openai` additionally emits
`api_base: SOVEREIGN_BASE_URL` and `api_key: SOVEREIGN_TOKEN` — Scale 2's institution-hosted vLLM path — while
`openai_direct` emits `OPENAI_API_KEY` and no `api_base`, reaching `api.openai.com`. Rendering GPT-5.6 Sol under
`openai`
would point a commercial OpenAI call at Jetstream2 and sign it with the sovereign token. The two must never collapse,
and a test asserts they don't.

`max_context: 400000` on this row is a **placeholder**, not a confirmed limit — the schema requires an integer, so a
disabled row cannot carry `null`. Treat it as unverified until the row is enabled.

Whatever reaches this rung should be:

- rare
- PAYG
- budget bounded
- logged separately
- followed by deterministic verification
- measured for whether the expense actually changed failure into success

A model call is not justified merely because it produced a plausible response.

`failup.py` remains authoritative.

---

## The Fable tier — off the ladder entirely

Not §8, and not a T-number: numbering it at all would misrepresent it. **Kimi K3 (`moonshot/kimi-k3`) is not the rung
above T6 and not the rung after CEILING_STALL.** It is off the escalation graph.

**How it is reached:** by an explicit human declaration that a specific task warrants it, with the reason logged. That
is the only path. Repeated stalls, verifier failures, ladder exhaustion — none of them reach it, by design.

**Why it exists at all.** CW-04 §2.5 *rejected* K3 for the routine roster on cost and license together ($3.00/$15.00 per
Mtok; a bespoke grant with a revenue-triggered separate-agreement clause for MaaS operators and a UI attribution mandate
above 100M MAU). This row is the narrow exception that rejection leaves room for — not a reversal of it.

**How it is gated:** `fable_tier: true` **and** `enabled: false`, two independent vetoes. `enabled: false` is CW-02's T6
mechanism as it actually exists here; `fable_tier: true` is the second, keeping the row out of ordinary selection *even
if someone later flips `enabled`*, which is the part `enabled`
alone cannot express. Two tests in `tests/test_failup.py` assert that the escalation ladder stays tiers-driven rather
than registry-driven, so if a future change ever makes a registry alias a rung, the suite fails and the gate has to move
into the guard rather than silently becoming reachable.

> **The honest limit, stated rather than glossed.** LiteLLM itself does not read
> `model_info.enabled`. Any row inside an alias's model group is reachable by
> the proxy's own retry/fallback machinery (`num_retries: 2`,
> `allowed_fails: 2`) whatever `model_info` says. Downstream tooling filters on
> the flag; the proxy does not. So a sustained outage of `code_large` orders 1–3
> could in principle have the proxy exhaust its retry budget and reach K3 — the
> exact case this gate says must never happen. This is not fixable inside the
> current model: the schema pins `model_name` to the alias and the seven aliases
> are closed, so a fable row cannot be given its own model group. Genuine
> enforcement is HB-2 work. `enabled: false` narrows the exposure; it does not
> close it. **Recorded as open, not solved** (`P6-report.md` §1).

`max_context: 262144` on both K3 rows is **carried forward from the Kimi K2.6 row this supersedes** and is not confirmed
for K3. The rows are disabled, so the number is inert until someone flips the flag — confirm it as part of that flip.

Under `open_weight_only` (docs/specs/10) the Fable tier is absent, and it is absent on **license**, not on hosting: the
weights are public, and
`license_family: non_permissive` fails the allowlist. That is precisely the distinction the field was added to make.

---

## Recommended proprietary budget model

Before dispatch, Herdr assigns a proprietary budget.

Example:

```yaml
routine_task:
  proprietary_budget: 0

high_value_code_task:
  proprietary_budget: bounded

research_task:
  proprietary_budget: bounded

explicit_override:
  proprietary_budget: user_selected
```

The important metric is not raw API spend.

It is:

```text
proprietary dollars that changed verified failure -> success
-------------------------------------------------------------
total proprietary dollars spent
```

That tells you whether the proprietary ceiling is actually earning its place.

Two corrections to how this is written above. First, the denominator should include the **Fable tier** if it is ever
declared — K3's $3.00/$15.00 is the most expensive call on this ladder and it is not a T6 call, so measuring only
"proprietary dollars" would miss it. Second, the per-task-class budget model sketched here is a design, not a mechanism:
as with the T6 confirm gate, nothing in `src/` implements it.

**The actual budget envelope**, which is two layers and neither is set today:

| Line      | Console cap | Change                                                                                                           |
|-----------|-------------|------------------------------------------------------------------------------------------------------------------|
| DeepSeek  | $5 / 30d    | unchanged — but `CW04-HB0-drift.md` §2 records these caps as *never set*, so "unchanged" may mean "still absent" |
| Morph     | $5 / 30d    | same caveat                                                                                                      |
| OpenAI    | $20 / 30d   | raised from $10                                                                                                  |
| Moonshot  | $10 / 30d   | new — set it **before** provisioning `MOONSHOT_API_KEY`, not after                                               |
| Anthropic | —           | **retired.** Remove or zero the cap; the row is deleted                                                          |

Total ceiling **$40 / 30d**, up from CW-04 §2.7's $30 — entirely the OpenAI increase plus the new Moonshot line, net of
Anthropic's removal. Worth a conscious nod rather than discovering it on a statement.

Both layers are required. The LiteLLM layer is the one code can misconfigure; the console layer is what survives that
misconfiguration, and a runaway agent loop can exhaust a month in an hour. The LiteLLM half lives in **runtime database
state** reached through the admin API or UI against a running proxy — not version-controlled config, so it has no home
in this repo (`P6-report.md`
§4 confirmed `litellm_settings.yaml` carries no budget keys of any kind, and a grep for `max_budget|budget_duration|30d`
across `portage-local` returns nothing). The 429/budget enforcement gap CW-02 opened remains open and remains HB-2 work;
console-side caps are the interim mitigation.

---

## Recommended transition ladder

### Phase A — immediately

```text
local open
  -> hosted open (DeepSeek -> Morph -> Flash Max)
    -> GPT-5.6 Sol PAYG, disabled by default
```

Cancel fixed high-cost model subscriptions once the PAYG escape hatch is tested and working.

### Phase B — after adding high-memory local compute

```text
local-fast (both machines)
  -> local-large
    -> hosted open (DeepSeek -> Morph -> Flash Max)
      -> proprietary PAYG
```

### Phase C — target state

```text
local-fast (both machines)
  -> local-large
    -> hosted open (DeepSeek -> Morph -> Flash Max)
      -> proprietary calls approaching zero
```

At this point, the same architecture can be switched to `open_weight_only` without redesigning Herdr — with one caveat
this document did not previously carry: the flip also removes the Fable tier, and it removes several rows currently
labelled `license_family: unverified`. Both Gemma rows and MiniMax M3 sit in that state today, so the flip is gated on
reading those grants, not only on the displacement number.

---

## Provider recommendations

### DeepSeek — the direct hosted-open rung (T3)

Recommended role:

```text
Herdr selects the model AND the endpoint
       |
     LiteLLM  (deepseek/ — native route, api.deepseek.com/beta)
       |
  api.deepseek.com
```

There is no provider-selection layer to configure here, and that is the change from the aggregator design this section
used to describe. What replaces those routing controls:

- **prefix caching** — the first-party reason this rung is direct
- **`license_family` on every row**, checked at T0, `unverified` failing closed
- **allowlist as row existence** — a model with no row is not a deployment
- **per-endpoint benchmarking**, not per model name

Key name: `DEEPSEEK_API_KEY` (LiteLLM's own).

---

### Morph — the broad hosted-open rung (T4)

Serving precision is the reason this vendor is named rather than a routing policy described. Morph serves open models at
bf16 without quantization and states it, which is what keeps an alias's benchmark cell reproducible. MiniMax M3 is the
occupant; GLM-5.2 and Qwen sit behind the same key in-slot.

Vendor durability is the open half of Morph's inclusion-test assessment (CW-04 §4 item 4). The mitigation is T5 trigger
(b), not a second live aggregator.

Key name: `MORPH_API_KEY`.

---

### Groq and Together — dormant reserve (T5), not live backups

Neither has a row, a key, or any traffic. Groq is trigger (a)'s occupant if a latency-sensitive alias appears that no
local rung can serve; Together is trigger (b)'s if Morph becomes sustainedly unavailable. Together's serverless
per-token billing, absence of provisioning minimums, and OpenAI-compatible integration remain the reasons it is the
trigger- (b) choice — they are just not reasons to wire it today.

---

### OpenRouter — not a rung, and not a working failover either

CW-04 §2.2 removed OpenRouter from the ladder. Its defined role is a non-routable failover path tagged `unbenched`,
reachable only when a first-party endpoint health-checks down.

**That path does not exist.** The schema gained a `failover_only` field for it and **no row sets it**, deliberately: any
row rendered into an alias's model group is routable by LiteLLM's own retry/fallback regardless of `model_info`, so a
`failover_only: true` row inside `code_large` would be exactly the routable rung the demotion removed — the tag would be
a comment, not a control. The
`unbenched` tag and the health-check-gated call path are HB-2 work (CW-04 §8 item 6). Until then, nothing routes through
OpenRouter at all.

---

### Anthropic — removed, not capped

**There is no Anthropic row.** CC-P6 deleted `proprietary_code` from the registry outright and removed its budget line;
`ANTHROPIC_API_KEY` is no longer among the variables the rendered config references, and `validate_env.py` (which has no
hardcoded variable list — it walks the rendered config) no longer demands it. Lane A's Claude Code usage is
subscription-based and reaches the Max wallet through the native binary, so it never went through this row.

One consequence belongs on someone's list: `.claude/tiers.*.json` still escalate to `sonnet` and `opus`, and that is
**correct, not a leftover** — those two rungs resolve through the native `claude -p` binary against the subscription, a
different lane with a different wallet. But anyone who pointed
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` at LiteLLM expecting those rungs to resolve *through the proxy* will now
find no Anthropic deployment behind it. That configuration fails at the proxy; it does not fall back. The native path is
unaffected.

---

### OpenAI — the entire proprietary ceiling (T6)

GPT-5.6 Sol is the only proprietary occupant, behind LiteLLM budgets, at
`enabled: false`. Use the capability alias — `proprietary_research` — rather than embedding the model name through the
codebase, so the concrete model can evolve without touching routing.

Route through `openai_direct`, never `openai`: the latter is Scale 2's institution-hosted vLLM path
(`SOVEREIGN_BASE_URL` / `SOVEREIGN_TOKEN`), and collapsing the two would point a commercial call at Jetstream2 signed
with the sovereign token. Key name: `OPENAI_API_KEY`.

---

### Perplexity — gated, not a rung

Sonar / Deep Research is **not** the `proprietary_research` occupant and should not be described as one. CW-04 §3 gates
the Perplexity API behind the science-lane citation verifier: "do not open before that ships." Until it does, the open
research stack is the research path, full stop:

```text
retrieval
  -> source normalization
    -> open-weight synthesis
      -> citation verification
```

Perplexity survives in this platform only as a **Parity Bench baseline arm**, human-executed against the consumer app,
which is a measurement surface rather than a routing target.

---

## Open research path

Even in Hybrid mode, build the self-hosted research stack.

Recommended shape:

```text
query decomposition
       |
web + scholarly retrieval
       |
source normalization
       |
open-weight synthesis
       |
citation-resolution verifier
       |
verified result
```

Only then should a research task escalate to the T6 ceiling when the open path is insufficient — and the ceiling is
GPT-5.6 Sol, not Perplexity, whose API stays gated behind the citation verifier this stack is building.

That is necessary if the long-term goal is to make proprietary research calls disappear as well.

---

## Model strategy

Use capability aliases:

The seven-cell alias set is fixed and closed. The deployment currently declares **six** of them:

```text
classifier              T1   gemma4:e4b (iMac, warm)
code_small              T1   gemma4:12b (MacBook) + gemma4:e4b (iMac)
embedding               T1   nomic-embed-text (iMac)
code_large              T3 -> T4   deepseek-v4-flash -> minimax-m3 -> Flash Max
                                   [+ the off-ladder Fable row, disabled]
research_synthesis      T3 -> T4   deepseek-v4-flash -> deepseek-v4-pro
                                   -> Flash Max
                                   [+ the off-ladder Fable row, disabled]
proprietary_research    T6   gpt-5.6-sol (disabled)

proprietary_code        — NOT DECLARED. Deleted by CC-P6, not disabled.
```

The seventh is **absent from the declaration, not hidden from the listing**, so HB-0 Gate 2 ("every alias the deployment
declares appears at `/v1/models`")
still holds — but Gate 2 will now see six aliases, and anything asserting seven needs updating before that gate is run.

Note also that a capability alias is one LiteLLM model group whose rungs are
`order` values inside it. The tier headings in this document are documentation over a flat ordered list — `code_large`
alone spans T3, T4, the Flash Max re-run, and the Fable row. `failup.py` does not read any of it: the guard's ladder
comes from `.claude/tiers.*.json`, whose rung names and these alias names do not intersect.

Avoid permanent provider/model coupling. `code_medium`, `vision`, `reranker`
earn cells when telemetry shows a routing decision that needs them (scale-mapping §4.3).

The platform should be able to replace a model without changing business logic.

---

## Storage layout

### Fast NVMe

```text
/Volumes/AI/
├── projects/
├── models/active/
├── vectorstores/
├── environments/
├── datasets-working/
├── embeddings/
└── scratch/
```

### Existing 8 TB Seagate

```text
/Volumes/AI-Archive/
├── models/archive/
├── datasets/archive/
├── snapshots/
├── completed-experiments/
└── backups/
```

---

## Recommended policy configuration

The provider-block form this section used to carry (`groq:`, `openrouter:`,
`together:`, `deepinfra:`, each with an `open_weight_only_for_open_rungs`
toggle) never existed in the built system and does not exist now. Two corrections at once: those four are not the roster
any more, and **there is no per-provider policy toggle at all**. Policy is expressed as which rows exist in
`registry.yaml` and what each carries. This is the real shape, rendered by
`src/portage/render_config.py` into `litellm/config.yaml` and
`litellm/model_list.generated.yaml` — both gitignored build artifacts, never hand-edited:

```yaml
# registry.yaml — the hand-edited source of truth. Endpoints and keys are
# `os.environ/` references, never literals, so the file stays portable.

models:
  # ---- T1 local ----------------------------------------------------------
  - alias: classifier
    provider_route: ollama_chat
    model_id: gemma4:e4b
    endpoint: os.environ/PORTAGE_IMAC_HOST
    open_weight: true
    license: UNVERIFIED
    license_family: unverified      # fails closed — the Gemma grant is unread
    max_context: 131072
    supports_tools: true
    supports_json: true
    thinking_disabled_for_structured: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    enabled: true

  # ---- T3: DeepSeek first-party, the cheap first attempt -----------------
  - alias: code_large
    provider_route: deepseek
    model_id: deepseek-v4-flash     # TODO(native): first-party name, not an
    order: 1                        # aggregator's `deepseek/deepseek-v4-flash`
    open_weight: true
    license: MIT
    license_family: permissive
    max_context: 1048576
    supports_tools: true
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    enabled: true

  # ---- T4: Morph, the primary open-weight ceiling ------------------------
  - alias: code_large
    provider_route: morph
    model_id: minimax-m3
    order: 2
    open_weight: true
    license: UNVERIFIED             # M2 shipped MIT; M3's grant is unconfirmed
    license_family: unverified
    max_context: 1048576
    supports_tools: true
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    enabled: true

  # ---- T4: "Flash Max" — the SAME checkpoint as order 1, more thinking ---
  - alias: code_large
    provider_route: deepseek
    model_id: deepseek-v4-flash
    order: 3
    effort: max                     # renders as litellm reasoning_effort: max
    open_weight: true
    license: MIT
    license_family: permissive
    max_context: 1048576
    supports_tools: true
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    enabled: true

  # ---- FABLE TIER: off the ladder. order 4 is deliberately vacant. -------
  - alias: code_large
    provider_route: moonshot
    model_id: kimi-k3
    order: 5
    open_weight: true               # public weights, and still ineligible for
    license: Kimi-K3-Custom         # open_weight_only — see license_family
    license_family: non_permissive
    max_context: 262144             # TODO(native): carried forward from K2.6
    supports_tools: true
    supports_json: true
    data_classification: public
    fable_tier: true                # never selected by ordinary escalation
    enabled: false                  # and disabled on top of that
    benchmark_version: null
    bfclv3: null
    ifeval: null

  # ---- T6: the entire proprietary ceiling, one line ----------------------
  - alias: proprietary_research
    provider_route: openai_direct   # api.openai.com — NOT `openai`, which is
    model_id: gpt-5.6-sol           # Scale 2's sovereign vLLM path
    open_weight: false
    license: Proprietary
    license_family: proprietary
    max_context: 400000             # PLACEHOLDER, unverified; the schema needs
    supports_tools: true            # an integer, so a disabled row can't be null
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    enabled: false                  # T6 rescue only

# NOT PRESENT, and each for a different reason:
#   proprietary_code (Anthropic)  deleted outright by CC-P6, budget line gone
#   openrouter                    off the ladder; `failover_only` exists in the
#                                 schema and no row sets it
#   groq, together                dormant T5 triggers — no rows, no keys
#   deepinfra, fireworks, ...     rejected: serving precision undocumented

on_total_failure:
  action: ceiling_stall
```

Which renders (`model_list.generated.yaml`) to entries of this shape — the
`order` and `reasoning_effort` land in `litellm_params`, the governance metadata in `model_info`:

```yaml
- model_name: code_large
  litellm_params:
    model: deepseek/deepseek-v4-flash
    api_key: os.environ/DEEPSEEK_API_KEY
    order: 3
    reasoning_effort: max
  model_info:
    portage_alias: code_large
    enabled: true
    open_weight: true
    license: MIT
    license_family: permissive
    max_context: 1048576
    supports_tools: true
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    effort: max
```

Note that **disabled rows still render into `model_list`**, carrying
`enabled: false` into `model_info` — HB-0 Gate 2 requires every declared alias to appear at `/v1/models`. So the route
is carried while the row stays out of every downstream selector that filters on the flag. LiteLLM itself does not read
that flag; see the honest-limit note under the Fable tier.

---

## `measure.py` additions

Track:

```text
local success rate
hosted-open success rate            (split T3 / T4 / Flash Max — the
                                     three are separate rungs and a
                                     merged number hides which earned it)
proprietary success rate            (T6 = gpt-5.6-sol only)
fable-tier success rate             (declared K3 calls, counted apart:
                                     not a rung, so not a rung's rate)

proprietary-required tasks
proprietary-avoidable tasks

open failure -> proprietary success
open failure -> proprietary failure

API dollars per verified rescue
```

Splitting T3 from T4 is not bookkeeping fussiness: "Flash Max" is the same checkpoint as the T3 first attempt at a
higher reasoning budget, so if the two report as one number there is no way to tell whether the extra thinking bought
anything — and if `drop_params` silently ate `reasoning_effort: max`, the metric is the only place that would ever show
it.

Add a report:

```text
proprietary_displacement
```

It should answer:

> If the platform were switched to `open_weight_only` today, what percentage of currently successful tasks would become
> ceiling stalls?

That is the most useful transition metric. Two things must be removed to answer it honestly, not one: **T6 and the Fable
tier**. K3 is open-weight but
`license_family: non_permissive`, so it is equally absent under
`open_weight_only`, and a displacement figure that counts only T6 overstates readiness for the flip.

---

## Downscale rule

Evaluate proprietary providers independently.

A provider becomes removable when:

- few tasks require it after genuine open-model failures;
- open-weight models now pass the same task categories;
- another provider provides equivalent verified outcomes more economically.

The progression this section used to describe (Anthropic + OpenAI + Perplexity, shedding one vendor at a time) is
largely already spent, and not by telemetry:

```text
Anthropic + OpenAI + Perplexity
              |
              |  Anthropic deleted (CC-P6), Perplexity gated behind the
              |  citation verifier (CW-04 §3) — neither on evidence of
              |  displacement, both on policy
              v
         OpenAI only  (gpt-5.6-sol, enabled: false)   <- HERE
              |
              |  + the off-ladder Fable tier must also go, and it goes
              |  on license rather than on cost
              v
        open-weight only
```

That last step is the one telemetry actually decides. The exact order of any future shedding should still be determined
by Herdr telemetry rather than assumed in advance — but record which steps were policy calls, because a displacement
number that quietly includes them will overstate what the open ladder earned.

---

## Hardware-purchase rule

The future 128 GB node should be purchased when the logs demonstrate that larger locally runnable open-weight models
would displace enough:

- hosted-open calls, and/or
- proprietary rescue calls

to make the hardware worthwhile.

The question is not:

> “Can a 128 GB machine run larger models?”

It can.

The useful question is:

> “How many of my verified failures disappear when a larger open-weight model becomes local?”

Parity Bench + Herdr telemetry provide that answer.

---

## Recommended operating mode

This Hybrid architecture is the recommended **transition deployment**.

It allows immediate cancellation of expensive fixed subscriptions while retaining a PAYG frontier escape hatch.

At the same time, every successful open-model substitution is measured, making it possible to move deliberately toward
the Open-Weight Only configuration.

The architecture never needs to be rewritten to make that transition.

Only the policy changes:

```yaml
policy_mode: hybrid
```

becomes:

```yaml
policy_mode: open_weight_only
```

---

## End state

Open-weight models receive every task they can reasonably handle.

Local hardware handles the economically sensible share.

Hosted open-weight inference provides access to models too large to justify owning locally.

Proprietary APIs remain metered, rare, profile-specific rescue paths until the data shows they can be removed.

No fixed proprietary LLM subscription is required.

---

## Current provider references

Provider capabilities change, so these should be revalidated periodically.

**Live rungs:**

- DeepSeek API (T3): https://api-docs.deepseek.com/ — model list, and the automatic prefix-caching behaviour this rung's
  economics depend on
- Morph (T4): https://docs.morphllm.com/ — the bf16 / no-quantization serving commitment is the inclusion criterion, so
  revalidate it specifically
- OpenAI Models API (T6): https://platform.openai.com/docs/api-reference/models
- LiteLLM provider routes: `deepseek`, `morph`, `moonshot` are native in the pinned v1.93.0, resolving to
  `api.deepseek.com/beta`, `api.morphllm.com/v1`
  and `api.moonshot.ai/v1`; key names `DEEPSEEK_API_KEY`, `MORPH_API_KEY`,
  `MOONSHOT_API_KEY` come from LiteLLM's own transformation modules

**Off-ladder / dormant — listed so the triggers can be evaluated without re-researching, not because anything routes
there:**

- Moonshot (Fable tier, disabled): https://platform.moonshot.ai/docs
- Groq (T5 trigger (a)): https://console.groq.com/docs/models
- Together AI (T5 trigger (b)): https://docs.together.ai/docs/inference/overview

OpenRouter and Perplexity are intentionally not listed. Neither is a rung — OpenRouter's failover path is unbuilt and
Perplexity is gated behind the citation verifier — and a link here would imply otherwise. Anthropic's LLM gateway
documentation is likewise dropped: there is no Anthropic row to point it at.
