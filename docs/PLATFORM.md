# PLATFORM.md — final definition: **Portage**

> **Ladder rewritten 2026-08-05** per CW-04 and CC-P6; decision record in `portage-local/docs/reports/`.

A self-hostable, verifier-driven, sovereignty-aware agent control plane for
Code, Science, Design, and Cowork — open-weight by default, benchmarked honestly
against the subscription products it replaces (Claude, ChatGPT/Codex,
Perplexity). This document is the capstone: it synthesizes the landscape survey
(`routing-layer-landscape-2026.md` — an external uploaded document, not in this
repo), the platform overview received from
Perplexity, and everything in `docs/specs/00–09`, and it supersedes them where they
conflict. The name is settled: **Portage** (EduCloud umbrella `SYSTEM.md` §1;
prior working name Commons). The ethos it carries is public-infrastructure
Open Access.

---

## 1. What was adopted, corrected, and kept from the survey overview

**Adopted** (the overview got these right):
- **OpenHands** as the agent-execution and Cowork substrate (fleets, sandboxes,
  least-privilege, workflow-level usage tracking). Our thin core stays portable;
  OpenHands is the *execution* layer, not the identity of the platform.
- **LiteLLM Auto Routing + Adaptive Router** as the online routing spine, with
  **Postgres** as routing/outcome memory and **RouteLLM-style offline
  retraining** as the learning loop. This upgrades our static ladder into a
  router that *learns from verifier outcomes* — the natural completion of the
  measurement layer we already had.
- The **policy → router → verifier → learner** ordering, and the 3-mode framing
  (full-open / hybrid / sovereign) as policy configurations of one platform.

**Corrected** (where the overview was missing things we'd already solved):
- It has an eligibility filter but **no triage**: nothing catches an
  underspecified task before dispatch. Our clarify-before-dispatch classifier
  (deterministic pins first, local model second, uncertainty escalates upward)
  is reinstated as a mandatory stage between policy and router.
- It has no **plan-first decomposition with runnable per-subtask acceptance
  checks** and no human plan gate. Reinstated (docs/specs/01; OpenSpec schema per
  docs/specs/08).
- It logs "ceiling-stall" but lacks the **honesty gate** — the rule that an
  efficiency win is void if the stall rate rose. Reinstated as a platform-wide
  invariant, and generalized in the benchmark suite (§5) as non-inferiority.
- Its tier ladder is open-source-only; for the *benchmark* the subscription
  lanes must exist as first-class arms, so the meters layer (herdr-meters,
  quota accounting) is kept — not as product, as **instrumented baseline**.

**Kept from our build, unchanged:** the deterministic fail-up guard (verdict:
still novel), the sensitive-data pin by config absence, and the maintenance
rails (pinning, stub-LLM CI tests, nightly canary, Renovate custom datasource).
The off-hours scheduler was retired with the subscription premise (CW02 §2.4).

**Naming (2026-07-28, CW02):** *Herdr* names the policy brain — classify,
adapt, budget, capability selection, verification state — sitting above LiteLLM
(transport spine) per the Scale-1 pilot hierarchy. `plugins/herdr-meters/` is its seed
implementation; the terminal multiplexer is one surface it drives. LiteLLM
never owns policy; Herdr never owns provider-infrastructure routing.

## 2. Architecture (merged)

```
                     ┌──────────── policy (eligibility, mode, data pins) ────────────┐
 task ─▶ TRIAGE ────▶│ clarify-or-dispatch; deterministic pins run first, always win │
                     └──────────────┬────────────────────────────────────────────────┘
                                    ▼
                       LiteLLM proxy (auto + adaptive routing, cooldowns, groups)
                        T0 deterministic (pins/overrides/allowlist,
                        license_family check) ·
                        T1 local_fast (iMac warm + MacBook dynamic — ONE rung,
                        TWO health-checked deployments: classifier = Gemma 4 E4B
                        on the iMac at keep-alive -1; code_small = Gemma 4 12B Q4
                        on the MacBook, order 1, with E4B on the iMac as order 2;
                        embedding = nomic-embed-text, iMac) ·
                        T2 local_large (DORMANT: future 128GB node, enabled: auto) ·
                        T3 remote_open_direct (DeepSeek, first-party
                        api.deepseek.com — V4 Flash is the cheap first attempt,
                        V4 Pro the primary occupant; direct because DeepSeek's
                        automatic prefix caching is why this rung is not
                        aggregated) ·
                        T4 remote_open_broad (Morph — bf16, no quantization, one
                        key; MiniMax M3 primary, GLM-5.2 and Qwen in-slot without
                        a new account. "Flash Max" — DeepSeek V4 Flash re-run at
                        `effort: max` (the registry field; renders to LiteLLM's
                        `reasoning_effort`), the same checkpoint, not a second
                        model — sits after this occupant, before the Fable
                        tier) ·
                        T5 remote_open_reserve (DORMANT — CW-02's
                        `remote_open_direct` renamed, absorbing Together. Two
                        independent re-enable triggers: (a) a latency-sensitive
                        alias no local rung can serve → Groq GPT-OSS 120B, benched
                        as its own capability cell, never a route to an existing
                        roster model; (b) sustained Morph unavailability →
                        Together) ·
                        T6 proprietary (ONE occupant: GPT-5.6 Sol as
                        `proprietary_research`, `enabled: false` — hybrid only.
                        Anthropic/`proprietary_code` is GONE: deleted from the
                        registry, not capped, not gated. The deployment declares
                        six capability aliases now, not seven) ·
                        T7 CEILING_STALL (terminal state, stall artifact).
                      ── off the T1→T6 chain ──────────────────────────────────
                        FABLE TIER (Kimi K3, moonshot/kimi-k3) — not a T-number
                        and not rung 7. Reached only by an explicit human
                        declaration that a specific task warrants it, logged;
                        never by ordinary stall/failure escalation. Carried as
                        `fable_tier: true` + `enabled: false`.
                        OpenRouter — OFF THE LADDER. Not a rung at any T-number:
                        a non-routable failover path tagged `unbenched`, reachable
                        only when a first-party endpoint health-checks down. The
                        schema carries a `failover_only` field for this and NO row
                        sets it, so nothing routes through OpenRouter today — the
                        mechanism is HB-2 work, not a shipped path.
                        EduCloud profile inserts institutional_sovereign
                        between T2 and T3 by config — no personal sovereign rung
                                    ▼
                       OpenHands execution (Code/Science/Design/Cowork profiles,
                        sandboxes, subagent fleets, plan-first decomposer for
                        large tasks with runnable acceptance checks + human gate)
                                    ▼
                       VERIFIER (deterministic, lane-specific — §4): decides
                        pass/fail; fail-up guard escalates one tier and retries.
                        A rung that is offline (not reachable) logs `unavailable`
                        and is skipped — it is never scored as a model failure.
                                    ▼
                       Postgres outcome store ─▶ short-term: adaptive-router
                        priors (unavailable events excluded — see §6) ·
                        long-term: RouteLLM offline retrain
                       Langfuse traces ─▶ custom quality-adjusted metrics
```

Escalation policy: **open-to-open first** (T1→[T2]→T3→T4→[T5]) before any
open-to-closed step; T6 exists only in `hybrid` mode and is boundary-gated, never
reached just because it would perform better. **The Fable tier is not part of
"open-to-open first"** — Kimi K3 sits outside the escalation chain entirely and
no amount of open failure reaches it; only an explicit, logged human declaration
does. Note also what the T6 boundary gate *is* in this repo: a policy sentence
plus `enabled: false` on the row. There is no confirm-prompt and no
logged-reason mechanism in code (`P6-report.md` §1 established this by grep;
`failup.py` never reads `registry.yaml` at all). Full ladder, mode table, and
the transition plan are in `REVISION-PLAN.md` and `docs/specs/10`–`11`.

## 3. Modes

| Mode | Rungs | Constraint | Use |
|---|---|---|---|
| `open_weight_only` | T0–T5 | model_list contains no commercial endpoints. Eligibility tests **`license_family` against an allowlist, not `open_weight`** — published weights do not imply an acceptable grant. Hosted-open (T3/T4) is allowed because the weights are downloadable *and* the license passes; only the compute is rented. The Fable tier is excluded here on `license_family` (`non_permissive`), not on hosting | end state; also offline/air-gapped |
| `hybrid` | T0–T6 (T7 is the terminal stall, not a rung) | T6 allowed only as a boundary-gated fail-up ceiling (verified open failure / documented specialist / explicit override) — never a fixed subscription rung. One occupant: GPT-5.6 Sol, `enabled: false`. The gate is that flag plus policy, not code | **current mode.** Daily driving during the Scale-1 pilot |
| `sovereign` | T0–T2 (+`institutional_sovereign` at Scale 2) | all routes pinned local + institutional; commercial *and* hosted-open both absent | clinical/regulated/EduCloud student-facing lanes |

**Why `license_family` and not `open_weight`.** Kimi K3 is the case that
falsified the original assumption: its weights were published on 2026-07-27,
and its license is a bespoke grant with a revenue-triggered separate-agreement
clause and a UI-attribution mandate — neither MIT nor Apache. `open_weight:
true` would have passed it. `license_family: non_permissive` does not. The field
is required on every registry row and takes one of six values — `permissive`,
`weak_copyleft`, `strong_copyleft`, `non_permissive`, `proprietary`,
`unverified` — and `unverified` fails **closed**: it is deliberately not
allowlist-eligible, so an unread grant cannot pass on the strength of
downloadable weights (CW-04 §2.5; `P6-report.md` §2). Today all three local
Gemma 4 rows and both `unverified` hosted rows (MiniMax M3, DeepSeek V4 Pro)
sit in that state. Like the T-numbers, the mode itself is still a label rather
than a runtime check: nothing in `src/` reads `license_family` except the
renderer that copies it into `model_info`, so `open_weight_only` is enforced by
which rows a config variant carries, not by a selector.

`sovereign` is stricter than `open_weight_only`: it excludes hosted-open
infrastructure too, not just proprietary weights. Sensitive workspaces remain a
*config variant with tiers absent*, never a runtime check. Mode is switched by
swapping the LiteLLM config variant — no code change (`docs/specs/10` §"target
state"; `docs/specs/11` Phase C). The flip from `hybrid` to `open_weight_only` is
triggered by the `proprietary_displacement` metric (§5.3), not by calendar or
preference.

## 4. Lane-specific verifiers (new — this is what makes "Science/Design" real)

The guard's principle — a runner decides, never the model — generalized per
lane. Without these, only Code was actually verifiable:

- **Code:** non-empty diff + lint + tests (existing), plus optional typecheck.
- **Science:** every citation must **resolve** (URL/DOI fetch 200 + title
  match); every keyed claim in the task's rubric present with a source;
  numbers in the report traceable to a fetched source or produced by included
  code; report re-runs from included code/data (reproducibility check).
  Hallucinated-citation rate is a first-class metric, not an anecdote.
- **Design:** build passes, accessibility lint (axe) clean, optional
  screenshot-diff against reference within threshold, design-token lint (no
  hardcoded values where tokens exist).
- **Cowork/plans:** per-subtask runnable acceptance commands + integration
  check (existing decomposer).

## 5. The Parity Bench — comparison suite (the centerpiece)

Purpose: test the full-open platform **against the subscriptions** — Claude
Code above all, Codex, and Perplexity — with results a skeptic would accept.

### 5.1 The confound, and the factorial design that removes it

"Open platform vs Claude Code" confounds **harness** with **model**. So the
core experiment is a 2×2 factorial, per task:

| | our harness (Portage) | native harness |
|---|---|---|
| **open model** | A1 (the platform) | A3 Claude Code → LiteLLM → open model |
| **frontier model** | A2 hybrid-ablation | A4 native Claude Code / Codex |

A1 vs A4 is the headline; A2 and A3 decompose any gap into *harness effect*
vs *model effect* vs their interaction. This is what makes a loss
diagnosable and a win credible.

### 5.2 Task suites (preregistered before any arm runs)

- **Code-private (n≈20–30):** real tasks from your repos (taskcapture,
  course-infra), each with a runnable acceptance check written *first*.
- **Code-public (n≈10):** a fixed SWE-bench-Verified-style sample for external
  comparability.
- **Science (n≈10–15):** research questions with keyed rubrics (required
  facts, resolvable-citation requirement). Perplexity Deep Research is the
  baseline arm here — **human-executed** (app-only), same wall-clock budget,
  outputs scored by the same rubric.
- **Cowork/multistage (n≈5):** plan-first tasks through the decomposer in
  each capable arm.

Preregistration = task list, acceptance checks, metrics, non-inferiority
margin, and analysis plan committed to the repo before run 1. All logs
published.

### 5.3 Metrics

**Primary**
1. **Verified success rate** (deterministic verifier; per lane).
2. **Cost per verified success**, under all three accounting models (§5.4).
3. **Wall-clock to verified success** (fixed per-task budget; timeout = fail).
4. **Human interventions** (count + minutes: clarifications answered,
   approvals, manual fixes).

**Secondary**
5. Escalation depth and win-tier distribution; 6. ceiling-stall rate;
7. human-fix edit distance (diff between agent output and what you actually
kept); 8. discard/revert rate; 9. Science lane: rubric coverage %, citation
resolvability %, hallucinated-citation rate; 10. tokens and energy proxy
(tokens × model size class) for the sovereignty story; 11. **`proprietary_displacement`**
— of currently-verified successes, what % would become ceiling-stalls if **T6 and
the Fable tier** were removed today (the `hybrid` → `open_weight_only` flip
trigger, tracked weekly). Both, not just T6: Kimi K3 is open-weight but
`license_family: non_permissive`, so it is equally absent under
`open_weight_only`, and counting only T6 would overstate readiness for the flip;
12. **rescue efficiency** — non-open-ladder dollars (T6 plus any declared Fable
call) that converted a verified failure into a verified success, divided by total
such dollars spent (the ceiling must earn its place in flipped outcomes, not
plausible-sounding output).

**Honesty gates (platform invariants applied to the benchmark)**
- **Non-inferiority first:** no arm may claim a cost/speed win unless its
  verified success rate is within a preregistered margin (default 5 pp) of
  the best arm on that suite. The stall-gate rule, generalized.
- Paired analysis only (same task across arms), bootstrap CIs on paired
  differences; no metric reported without its n.
- Thin-data label under preregistered minimum n, exactly as in
  `measure.py downscale`.

### 5.4 Cost accounting for flat subscriptions (novel, required)

Comparing per-token arms with flat-rate arms needs three prices, reported
side by side:

- **Marginal $/task** — API arms: tokens×price; subscription arms: ≈0.
- **Amortized $/task** — subscription price ÷ verified successes on that lane
  that month (the number that answers "is the subscription worth it").
- **Quota-share cost** — fraction of the binding cap consumed × subscription
  price (Claude: Opus cap tracked separately; Codex: Plus 5h window). The
  scarcity price of a "free" task.

Downscale decisions read amortized + quota-share; API-substitution decisions
read marginal. Conflating them is how every public comparison lies.

### 5.5 Runner

`bench.py` (build item): reads the preregistered suite, executes arms A1–A4
(A-Perplexity human-guided with a scripted checklist), enforces wall-clock
budgets, writes every attempt to the same Postgres/Langfuse schema the
platform already uses, and refuses to emit a summary that violates a gate.
Subscription arms run through Lane B non-interactive paths where automated,
respecting ToS (no multi-account, no scraping around limits).

## 6. Learning loop (closing the circle)

Verifier outcomes are the training signal: short-term, LiteLLM's adaptive
router updates per-request-type priors (documented to stabilize after ~10
requests per model); long-term, periodic RouteLLM-style retraining on the
Postgres log. **Availability events are excluded from this signal** — a rung
being asleep or off-network (`unavailable`) is capacity noise, not a quality
verdict, and must not poison priors or retraining data the way a real
`model_failed` should (see `docs/specs/10`/`11`, `failup.py`). The benchmark suite
doubles as the evaluation set for router retraining — the platform literally
learns from the comparison against its competitors. Routing changes are
versioned; a retrained router must beat the prior router on the held-out suite
before deployment (same non-inferiority gate).

## 7. What was missing and is now added (explicit)

1. Lane-specific verifiers for Science and Design (§4) — without them the
   platform was a coding tool with aspirations.
2. **Open research stack** for the Science profile: SearXNG (self-hosted
   metasearch) + open fetch/crawl + the citation verifier. Required to test
   against Perplexity at all; also the sovereign research path.
3. The factorial ablation design (§5.1) and `bench.py`.
4. The three-model cost accounting (§5.4).
5. Learning-loop wiring with versioned, gated router updates (§6).
6. Artifact & session memory: Postgres-backed artifact store + generalized
   state snapshots (the PreCompact pattern platform-wide), so Cowork teams
   and Science reports persist across sessions and machines.
7. Profile definitions as config (Code/Science/Design/Cowork = interaction
   profiles: system prompts, toolsets, verifiers, default tiers) — the
   product-surface analogue without cloning vendor features.
8. A working name, a license decision to make (recommend Apache-2.0 to match
   the stack), and this document as the single source of truth.
9. **The steward model** (`docs/specs/09`): one warm local model doing all five
   pre-dispatch jobs — triage, classify, route, shape, propose acceptance
   checks — prompted+rules now, verifier-fine-tuned later. Prompt shaping is
   additive-only with the original always preserved, so it is measurable
   rather than assumed. Its training label is the deterministic verifier's
   verdict, which makes the platform's ground truth do double duty: it trains
   the router (§6) and the steward from the same records.

## 8. Honest limits

- **OpenHands is a large dependency.** Adopt its control plane; keep our core
  (guard, triage, verifiers, metrics) framework-agnostic so it survives a
  substrate change.
- **Benchmark labor is real.** Full suite × 4 arms is days of runtime and
  attention. Start with a 12-task pilot cut to debug the runner and rubrics
  before the preregistered run.
- **The Perplexity arm cannot be automated** (consumer tier is app-only); its
  protocol is human-executed and therefore noisier — say so in reporting.
- **Open-model pricing/rankings in the overview are point-in-time** (DeepSeek
  V4 Flash/Pro, MiniMax M3, Gemma 4 etc. — Qwen3-Coder was retired from the
  documented roster by CW-04 §2.4); the ladder is config, re-checked at bench
  time, never hardcoded in claims.
- **The hosted `model_id`s are vendor-documented, not vendor-confirmed.** Every
  one of `deepseek-v4-flash`, `deepseek-v4-pro`, `minimax-m3`, `kimi-k3`,
  `gpt-5.6-sol` carries a `TODO(native)` in `registry.yaml` and has not been
  checked against a live `/v1/models` on that vendor's own API. The B7 gate
  governs: pins change only after the model is reached and passes the per-model
  tool-call smoke test.
- The learning loop needs volume; until a few hundred verified outcomes
  exist, adaptive routing priors are weak — run static ladder + fail-up
  until the log earns the learner.
- Subscription arms are moving targets (models, limits, harness updates);
  every benchmark report carries a date and exact versions, and comparisons
  expire.

## 9. Build-order delta (appends to docs/BUILD-PLAN.md)

**Phase 6a** (inserted before Phase 6 — see `REVISION-PLAN.md` §5, which carries
the execution record): the hosted deployment groups are wired, but not the ones
originally drafted here. CC-P6 rendered DeepSeek (T3), Morph (T4) and the gated
Moonshot Fable row instead of OpenRouter + Together, because CW-04 §2.2 took
OpenRouter off the ladder and folded Together into the dormant T5 reserve. The
proprietary ceiling is **T6, not T7** — T7 is the terminal stall, and the earlier
"wire T7" wording predates CW-02 §3's renumbering, when the proprietary ceiling
was T7 and `proprietary_specialist` was T6. T6 now has exactly one occupant
(GPT-5.6 Sol, `enabled: false`); Anthropic's row is deleted, not capped; and the
Fable tier sits outside the numbering entirely, so there is no T7 provider group
to wire and none is planned. What remains of Phase 6a: split `unavailable` vs
`model_failed` in `failup.py`; add displacement + rescue-efficiency reporting to
`measure.py`; HB-0 Gates 2–4; the two-layer budget caps; and native
confirmation of the hosted model IDs. This is config + telemetry, not new
architecture — it operationalizes modes already defined in §3.

Phase 7: lane verifiers (science citation-resolver first) + open research
stack. Phase 8: Postgres outcome store + Langfuse wiring; migrate measure.py
metrics onto it (keep the JSONL path as fallback). Phase 9: `bench.py` +
preregistration templates + the 12-task pilot. Phase 10: adaptive-router
enablement + first gated RouteLLM retrain, and steward Phase B/C
(distillation bootstrap, then verifier-tuned fine-tune) — both gated by the
same held-out non-inferiority rule. OpenHands adoption can proceed in
parallel from Phase 7; nothing earlier depends on it.
