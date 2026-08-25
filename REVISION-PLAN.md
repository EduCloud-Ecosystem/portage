# REVISION-PLAN — Scale-1 transition: open-first ladder with a PAYG ceiling

> **Ladder rewritten 2026-08-05** per CW-04 and CC-P6; decision record in `portage-local/docs/reports/`. §4 below is
> deliberately left as history — see the note above it.

> **July 2026 update: `LINE-P-ROADMAP.md` is now the staging plan of record
> (S0–S5).** This file remains the doc-revision record and the Phase 6a
> acceptance reference; where they differ, Line P wins. The two material
> changes: (1) the proprietary rescue line is a **$10/30-day Opus key**,
> confirm-gated behind a verified open failure, 24-hour window, no fallbacks —
> narrower than the per-task-class PAYG budgets drafted below; (2)
> subscriptions are **not** cancelled after a one-time bench baseline —
> Pro-tier arms (Claude Pro, Perplexity Education Pro) ride through the S3
> calibration window (60–90 days, $60–80 envelope, $100 ceiling) as
> instrumented comparison arms, and S4 cuts what the evidence says to cut.

*Drafted 2026-07-21 from review of `docs/specs/10` (Open-Weight Only) and `docs/specs/11`
(Hybrid Open-First + Proprietary PAYG) against PLATFORM.md, docs/BUILD-PLAN.md, PROJECT.md, docs/specs/02/03/08/09,
`.claude/tiers.claude.json`, and
`docs/phase-1-findings.md`. This plan is the work order for the next build sessions; nothing in the repo has been
rewritten yet except the addition of docs/specs/10, docs/specs/11, and this file.*

## 0. Decision recorded

- **Operating mode now:** `policy_mode: hybrid` (docs/specs/11) — local open → hosted open (DeepSeek T3, Morph T4) → a
  single proprietary rescue line **only after verified open failure**. As of CC-P6 that line is GPT-5.6 Sol
  (`proprietary_research`), disabled by default; the Anthropic row is deleted and Perplexity stays gated behind the
  science-lane citation verifier. Fixed subscription rungs (Claude Max / Codex Plus) exit the production ladder.
- **End state:** `policy_mode: open_weight_only` (docs/specs/10). The switch is **empirical, not ideological**: flip
  when `proprietary_displacement` (docs/specs/11 §measure.py additions) stays below threshold — proposed **< 5% of
  verified successes over a 4-week window** (tune in prereg).
- **Scope now:** Greg's personal Scale-1 pilot (iMac + MacBook Pro). EduCloud deployment planning is in place (§6) but
  not scheduled.

## 1. What the new architecture improves (assessment)

1. **Subscription rungs removed.** The old production ladder (`local → Claude Max/Codex → …`, docs/specs/08 Scale 1;
   `tiers.claude.json`)
   entangled routing with flat-rate psychology — docs/specs/03's own finding was that discipline beats orchestration on
   a flat plan. All-PAYG makes every marginal call carry a marginal price, so *cost per verified success* is finally a
   single honest number and the router's decisions are real economic decisions. Amortized/quota-share accounting
   (PLATFORM §5.4)
   survives, but only inside the Parity Bench baseline arms.
2. **`proprietary_displacement` is the missing transition metric.** "If we switched to open-weight-only today, what % of
   currently successful tasks become ceiling stalls?" turns the sovereignty goal into a dashboard number with a flip
   threshold. It completes measure.py's story: the honesty gate said *don't claim wins that cost quality*; displacement
   says *when the frontier tier stops earning its place*.
3. **The escalation boundary is now policy, not habit.** Proprietary requires (a) verified open failure, (b) documented
   specialist need, or (c) explicit override (docs/specs/11). This is the fail-up guard's philosophy promoted to the
   provider boundary — it prevents hybrid from silently re-becoming proprietary-first.
4. **Serving precision replaces model-policy/infra-policy delegation.** The original form of this item delegated infra
   choice to OpenRouter under price/throughput/latency + ZDR + quantization constraints. CW-04 §2.2 reverses it: every
   alias is a benchmark cell, and an aggregator that can change quantization under a stable model ID makes that cell
   irreproducible. So Herdr picks the model *and* the surface serving it — DeepSeek first-party at T3, Morph at T4
   (bf16, no quantization, stated publicly). There is no delegated provider choice left to constrain, which is a
   simplification, not a loss: the sovereignty argument now rests on a documented precision commitment rather than on
   filters applied to an aggregator.
5. **`unavailable ≠ model_failed`.** A sleeping MacBook is a capacity event, not a quality signal. Without this split,
   local_burst's uptime pattern poisons win-tier stats, adaptive-router priors (PLATFORM §6), and Parity data. Small
   change, large integrity payoff.
6. **Capability aliases over model names** (`local/code-large`,
   `proprietary/reasoning`…). Matches the steward design (docs/specs/09) and LiteLLM model-groups; Parity Bench assigns
   the winner behind each alias. Business logic stops churning with model releases.
7. **Rescue-efficiency metric**: proprietary dollars that converted verified failure → success ÷ total proprietary
   dollars. The ceiling must earn its keep in flipped outcomes, not plausible prose.
8. **Hardware purchase becomes a measured decision.** The 128 GB node is bought when telemetry shows local-too-small
   failures that hosted-open solves at volume (docs/specs/10 §hardware rule) — capex version of buy-over-build.
9. **Two hosted keys, both first-party.** DeepSeek (T3) and Morph (T4) are two independent surfaces, so the displacement
   metric has something to compare and the fallback path actually gets exercised. Together is not a live backup — CW-04
   §2.2 folded it into the dormant T5 reserve, re-enabled only on sustained Morph unavailability. DeepInfra and the
   other aggregators were rejected outright on undocumented per-endpoint serving precision (CW-04 §3).
10. **Perplexity demoted from fixed app subscription to metered specialist**
    behind the open research stack (SearXNG + citation-resolution verifier, already PLATFORM §7). Same pattern as code:
    open first, PAYG rescue, measured.

## 2. Conflicts, gaps, and sequencing risks (resolve during revision)

1. **The sovereign HPC rung is absent from docs/specs/10–11.** Understandable at personal Scale 1 (no allocation wired
   yet), but `local → sovereign →
   subscription → API` is PROJECT.md's *thesis*. The unified ladder (§3) no longer
   reinserts a sovereign rung between local and hosted-open — the CW-04 renumbering gave that slot to Morph at T4 — so
   sovereign survives only as a policy **mode** (mode table: T0–T2, no remote at all) and, at Scale 2, as the
   `institutional_sovereign` profile insert between T2 and T3, populated when Jetstream2/campus endpoints exist
   (HANDOFF Phase 6; PLATFORM §2). There is no personal sovereign rung. Do not let the Scale-1 docs erase the novelty
   claim.
2. **Cancel subscriptions AFTER the bench baseline.** Parity Bench arm A4 (native Claude Code on Max) and the
   amortized/quota-share accounting require live subscriptions. Sequence: run the 12-task pilot cut (PLATFORM §8) across
   A1/A4 while Max is active → then cancel (docs/specs/11 Phase A
   "cancel once the PAYG hatch is tested"). If cancellation happens first, A4 becomes API-priced and the amortized arm
   is declared historical in the prereg — acceptable, but decide, don't drift.
3. **PROJECT.md's novelty wording needs a careful edit, not a rewrite.**
   "Subscription-quota-awareness" generalizes to **meter-awareness**: meters are now PAYG budgets, allocation balance,
   and displacement — subscriptions remain only as instrumented baseline. The fusion claim (meter-aware routing
    + sovereign compute + deterministic gate) is intact and arguably cleaner.
4. **Quantization variance — resolved by removing the aggregator.** The concern was that the same allowlisted model can
   be served at different quants by different providers under one model ID. CW-04 §2.2 makes serving precision the
   deciding constraint instead of a filter: T4 is Morph because Morph serves at bf16 without quantization and says so,
   and T3 is DeepSeek first-party. Parity Bench still benchmarks **per endpoint**, not per model name, before an
   endpoint earns production traffic.
5. **ZDR is not the sensitive pin.** Retention posture on the hosted-open rungs (T3 DeepSeek, T4 Morph) is defense in
   depth for *ordinary* work, and it is now a per-vendor property of each first-party surface rather than a filter set
   on an aggregator. The sensitive lane remains **config absence** (no non-local deployments exist in that model_list) —
   never a runtime check, never delegated to a provider's retention promise.
6. **Ladder-walk latency on known-hard tasks.** Walking T1→T6 before rescue costs wall-clock. Mitigation already in
   docs/specs/11: per-task-class
   `proprietary_budget` — classes with a displacement track record get a bounded pre-authorized ceiling; routine classes
   get budget 0. Triage (R1/R2)
   assigns the class; the guard still requires the open attempt unless the class is documented specialist.
7. **Supersessions.** docs/specs/03 (Max-wallet pilot) → mark HISTORICAL (its findings stand; its config retires).
   `.claude/tiers.claude.json` → retire after Phase A (Lane A native fallback may keep a copy pointed at LiteLLM
   aliases). docs/specs/02's ladder and docs/specs/08's Scale-1 table → rewritten per §4.

## 3. The unified ladder (one ladder, three modes)

```
T0 deterministic     pins, overrides, triage, license_family/allowlist
                     checks                                              (always)
T1 local_fast        iMac warm + MacBook dynamic — ONE capability rung,
                     TWO health-checked deployments. classifier = Gemma 4
                     E4B (iMac, keep-alive -1); code_small = Gemma 4 12B
                     Q4 (MacBook, order 1) + E4B (iMac, order 2);
                     embedding = nomic-embed-text (iMac). A sleeping
                     MacBook logs `unavailable`, never `model_failed`    (always)
T2 local_large       DORMANT — future 128 GB node, enabled: auto,
                     bought on the hardware-case dashboard trigger       (always)
T3 remote_open_direct DeepSeek, first-party api.deepseek.com. V4 Flash is
                     the cheap first attempt (MIT, license_family:
                     permissive); V4 Pro is the primary occupant
                     (license unverified). Direct because DeepSeek's
                     automatic prefix caching is the reason this rung
                     is not aggregated                                   (open+hybrid)
T4 remote_open_broad Morph — bf16, no quantization, one key. MiniMax M3
                     is the primary occupant; GLM-5.2 and Qwen sit
                     in-slot without a new account if ever needed.
                     "Flash Max" — DeepSeek V4 Flash re-run at
                     `effort: max` (the registry field; renders to
                     LiteLLM's `reasoning_effort`), the same checkpoint
                     and not a second model — sits after this occupant,
                     before the Fable tier                              (open+hybrid)
T5 remote_open_reserve DORMANT — CW-02's `remote_open_direct` renamed
                     (don't let the two names collide in prose); absorbs
                     Together. Two independent re-enable triggers:
                     (a) a latency-sensitive alias no local rung can
                     serve → Groq GPT-OSS 120B, benched as its own
                     capability cell, never a route to an existing
                     roster model; (b) sustained Morph unavailability
                     → Together                                          (open+hybrid)
T6 proprietary       ONE occupant — GPT-5.6 Sol (`proprietary_research`),
                     `enabled: false`. Rescue only: verified open failure
                     + budget envelope + logged reason + confirm gate,
                     which in this repo is a policy sentence plus that
                     flag, not code. Anthropic (`proprietary_code`) is
                     GONE — deleted from the registry, not capped, not
                     gated; the deployment declares six aliases, not
                     seven                                               (hybrid only)
T7 CEILING_STALL     terminal state, not a routable rung — emits the
                     stall artifact (attempted tiers + verifier evidence)

── off the T1→T6 chain ──────────────────────────────────────────────────────
FABLE TIER           Kimi K3 (`moonshot/kimi-k3`) — NOT a T-number, not
                     rung 7, and not reachable by escalation of any kind.
                     Entered only by an explicit human declaration that a
                     specific task warrants it, with the reason logged.
                     Carried as `fable_tier: true` + `enabled: false`.
                     Weights are published but `license_family:
                     non_permissive`, so it is absent under
                     `open_weight_only` as well
OpenRouter           OFF THE LADDER — not a rung at any T-number. A
                     non-routable failover path tagged `unbenched`,
                     reachable only when a first-party endpoint
                     health-checks down. The schema carries a
                     `failover_only` field for exactly this and NO row
                     sets it, so nothing routes through OpenRouter today;
                     the mechanism that would make such a row genuinely
                     non-routable is HB-2 work
EduCloud profiles    insert `institutional_sovereign` between T2 and T3
                     by config — no personal sovereign rung (Scale 2
                     only)
```

| Mode               | Rungs                                         | Use                                                                                                                                    |
|--------------------|-----------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `open_weight_only` | T0–T5                                         | end state; hosted open allowed when the row's `license_family` is allowlist-eligible — downloadable weights alone are **not** the test |
| `hybrid`           | T0–T6 (T7 is the terminal stall, not a rung)  | **now** — transition; T6 behind the escalation boundary                                                                                |
| `sovereign`        | T0–T2 (+`institutional_sovereign` at Scale 2) | clinical / student-data / EduCloud sensitive lanes — **no remote at all**, commercial or open-hosted                                   |

Note `sovereign ≠ open_weight_only`: sovereign also excludes hosted-open (commercial infra serving open weights).
Escalation stays open-to-open before any open-to-closed step (PLATFORM §2 rule, unchanged), and the Fable tier is
outside that rule rather than the last step in it.

`open_weight_only` tests `license_family`, not `open_weight`. Kimi K3 is the case that forced the distinction — public
weights under a bespoke grant, `license_family: non_permissive`; the `unverified` value fails closed too, so an unread
license cannot pass on the strength of published weights (CW-04 §2.5).

> **Revised 2026-07-28 per CW02-decisions.md §3** (dormant-slot synthesis):
> local_burst collapsed into local_fast as a second deployment; Groq added at
> T3; Together dormant at T5; sovereign is an EduCloud-profile config insert,
> not a personal rung. §4's file-by-file rows below predate this revision —
> CW-03 executed the documentation changes; read those rows as history.

> **Revised again 2026-08-05 per `CW04-model-roster.md` §2.1–2.3 and CC-P6**:
> Groq's T3 slot vacates into the dormant T5 reserve; OpenRouter leaves the
> ladder entirely; T3/T4/T5 are reassigned to DeepSeek first-party, Morph, and
> `remote_open_reserve`; Anthropic's `proprietary_code` row is deleted, leaving
> T6 with one occupant; and the Kimi K3 Fable tier is added off the chain. The
> ladder above is the current one. §4 still reads as history and is unchanged
> by this revision.

## 4. File-by-file revisions

| File                                     | Change                                                                                                                                                                                                                                                                                                                                                                                        |
|------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `PLATFORM.md`                            | §2 ladder → §3 above (T0–T7 + stall); §3 modes: rename full-open → `open_weight_only`, keep hybrid/sovereign, add mode-switch-is-config-only; §5.3 add displacement + rescue-efficiency to metrics; §6 note unavailable events excluded from router priors; §9 add transition phases (§5 below).                                                                                              |
| `docs/BUILD-PLAN.md`                     | §2 buy-over-build: add rows — OpenRouter (config, not code), Together/DeepInfra (config), SearXNG (deploy, not build); §3 diagram: Lane B deployments become local(order1) → sovereign(order2) → openrouter-allowlist(order3) → together(order4) → anthropic/openai PAYG(order5, hybrid); §4: insert Phase 6a (§5); Phase 2 gains unavailable-vs-failed in failup; Phase 4 gains new metrics. |
| `PROJECT.md`                             | Thesis edit per §2.3 (meter-awareness generalization); ladder line → `local → sovereign HPC → hosted open-weight → PAYG frontier (boundary-gated)`; scope-in adds allowlist governance + displacement report; subscriptions move to "benchmark baseline only".                                                                                                                                |
| `README.md`                              | Read-order table: add docs/specs/10–11 + this plan; one-paragraph ladder summary update.                                                                                                                                                                                                                                                                                                      |
| `docs/specs/02`                          | Local ladder → `local_fast → local_burst → [local_large] → remote_open → remote_open_direct → PAYG (hybrid)`; EduCloud section gains per-lane policy_mode table (§6).                                                                                                                                                                                                                         |
| `docs/specs/03`                          | Prepend HISTORICAL banner: pilot complete, subscriptions exiting production ladder; findings preserved for bench protocol.                                                                                                                                                                                                                                                                    |
| `docs/specs/08`                          | Scale-1 table rewritten (new ladder; OpenRouter/Together roles; "nothing new to adopt" still true — both are LiteLLM config); Scale-2 note: sovereign rung slots at T4 unchanged.                                                                                                                                                                                                             |
| `docs/specs/09`                          | No structural change; add license/allowlist check to R2 routing's deterministic layer; note R3 templates gain `code.remote-open.md` key.                                                                                                                                                                                                                                                      |
| `.claude/tiers.claude.json`              | Retire in Phase A (see §2.7).                                                                                                                                                                                                                                                                                                                                                                 |
| `KNOWN_GOOD_VERSIONS.md`                 | Add OpenRouter + Together endpoints/models as pinned entries; allowlist is versioned config with license + quant floor per model.                                                                                                                                                                                                                                                             |
| `litellm.config.yaml` (Phase 1 artifact) | Add openrouter/together deployments with `order`, budgets, cooldowns; per-mode variants: `litellm.open-only.yaml`, `litellm.hybrid.yaml`, `litellm.sensitive.yaml` (unchanged — local-only by absence).                                                                                                                                                                                       |
| `src/portage/failup.py`                  | Distinguish connection-refused/timeout (skip rung, log `unavailable`) from verifier failure (escalate, log `model_failed`).                                                                                                                                                                                                                                                                   |
| `src/portage/measure.py`                 | New columns/reports: per-rung solve %, unavailable vs not-good-enough, `proprietary_displacement`, rescue efficiency ($→flip rate), open-inference cost per verified success.                                                                                                                                                                                                                 |
| `plugins/herdr-meters/models.json`       | Becomes the allowlist manifest: license, weights-source, quant floor, ZDR-capable providers.                                                                                                                                                                                                                                                                                                  |
| `KICKOFF-PROMPT.md`                      | Next-session scope = Phase 6a items 1–4 (§5), not Phase 0 (done).                                                                                                                                                                                                                                                                                                                             |

## 5. Pilot transition sequence (maps docs/specs/11 Phases A→C onto HANDOFF)

> **Execution note, 2026-08-05 — Phase 6a executed, but not as specified
> below.** Items 1 and 2 as drafted are superseded and should not be worked.
> The actual execution record is `docs/prompts/CC-P6-registry-rewrite-and-fable-tier.md`
> and `portage-local/docs/reports/P6-report.md`. What happened instead:
>
> - **Item 1** — no OpenRouter deployment group and no Together group exist.
>   CW-04 §2.2 took OpenRouter off the ladder before this work started, and
>   folded Together into the dormant T5 reserve. CC-P6 rendered `deepseek`
>   (T3), `morph` (T4) and a gated `moonshot` row instead, all first-party
>   native LiteLLM providers verified present in the pinned v1.93.0. The
>   acceptance criteria as written ("a non-allowlisted model name 404s; killing
>   OpenRouter fails over to Together") no longer describe anything the system
>   does, and are retired rather than restated: the allowlist is expressed as
>   which rows exist in `registry.yaml`, and the failover path OpenRouter would
>   have served is unbuilt — `failover_only` is in the schema with no row using
>   it (HB-2 work).
> - **Item 2** — there is no T7 provider group. The proprietary ceiling is T6,
>   and CW-02 §3's renumbering made T7 the terminal stall; the "wire T7" wording
>   here predates that. T6 now carries exactly one occupant, GPT-5.6 Sol at
>   `enabled: false`. Anthropic's row was deleted outright, not capped, and
>   Perplexity is gated behind the science-lane citation verifier (CW-04 §3), so
>   neither is wired. The Kimi K3 Fable tier landed instead — outside the
>   T-numbering, `fable_tier: true` + `enabled: false`.
> - **Items 3–6** are untouched by CC-P6 and remain as written.
>
> **The real remaining Phase 6a work**, per `P6-report.md` §4:
>
> 1. **HB-0 Gates 2–4** — need live Tailscale/Ollama/Docker state. Gate 2 will
>    now see **six** aliases at `/v1/models`, not seven; `proprietary_code` is
>    absent from the declaration rather than hidden from the listing, so the
>    invariant holds in the form HB-0 states it, but anything asserting seven
>    needs updating before the gate is run.
> 2. **Console-side budget caps** — no code in either repo can set them, and
>    neither layer is set today. Moonshot $10/30d (new, before `MOONSHOT_API_KEY`
>    is provisioned), OpenAI raised to $20/30d, Anthropic's cap removed or
>    zeroed, DeepSeek and Morph confirmed at $5/30d each. Then the matching
>    LiteLLM per-key budgets, which are runtime database state reached through
>    the admin API — not version-controlled config, so they have no home in this
>    repo. Total ceiling lands at $40/30d, up from CW-04 §2.7's $30.
> 3. **Native model-ID confirmation** — `deepseek-v4-flash`, `deepseek-v4-pro`,
>    `minimax-m3`, `kimi-k3`, `gpt-5.6-sol` are vendor-documented names never
>    checked against a live `/v1/models`, each carrying a `TODO(native)`. Also
>    `gemma4:12b`'s resolved quant at pull time, and whether DeepSeek accepts
>    the rendered `reasoning_effort: max` at all (the registry field `effort: max`
>    maps to it) — `drop_params: true` means a rejected value
>    is dropped silently and the "Flash Max" rung collapses into a duplicate of
>    order 1 without erroring.

**Phase 6a — PAYG transition (insert after current Phase 4/5 work, before Phase 6 sovereign):**

1. **[SUPERSEDED 2026-08-05 — see the execution note above. Do not work this item.]** Extend `litellm.config.yaml`:
   OpenRouter deployment group (allowlist enforced in config — models not on the list simply don't exist as
   deployments), Together direct group, budgets + cooldowns. *Accept:* curl through LiteLLM reaches an allowlisted model
   via OpenRouter; a non-allowlisted model name 404s; killing OpenRouter fails over to Together.
2. **[SUPERSEDED 2026-08-05 — see the execution note above. Do not work this item.]** Wire Anthropic + OpenAI PAYG keys
   as T7 with LiteLLM budget caps; Perplexity Sonar API for the Science lane behind the open research stack. *Accept:*
   T7 refuses dispatch without a `proprietary_budget > 0` task class; spend logs show T7 separately.
3. failup.py + measure.py telemetry changes (§4). *Accept:* stub-runner tests — a stubbed offline rung logs
   `unavailable`
   and is skipped; fixtures produce a displacement report.
4. **Bench baseline while subscriptions live:** run the 12-task pilot cut, arms A1 (platform) and A4 (native Claude Code
   on Max). *Accept:* results committed with prereg; date-stamped.
5. Cancel Claude Max / Codex / Perplexity Pro. Record the date in KNOWN_GOOD_VERSIONS (it's a cost-accounting epoch).
6. Displacement cadence: `measure.py report` weekly; flip criterion per §0.

**Phase B (hardware):** buy the 128 GB node only on docs/specs/10's four-condition rule; it enters as T2 `local_large`
deployments — no other change. (The "T3"
this line originally carried predates CW-02 §3's renumbering, which moved
`local_large` into the freed T2 slot.)

**Phase C (flip):** `policy_mode: hybrid` → `open_weight_only` = swap LiteLLM config variant + policy flag. No code
change. Announce in the changelog with the displacement evidence attached.

## 6. EduCloud deployment plan (planning in place now; scheduled later)

Scale-invariance rule (docs/specs/08) holds: the custom core — guard, triage, steward, meters, metrics — is identical;
only the ladder population and tenancy change.

- **Topology:** one LiteLLM proxy per institution (or per department), virtual keys per course/lane; Keycloak (Waypoint)
  fronts authn; per-key budgets are the course-level meter. Postgres outcome store shared; Langfuse optional.
- **Per-lane policy modes (default posture):**

  | Lane | Mode | Rationale |
    |---|---|---|
  | Student-facing (Belay tutoring, feedback on student work) | `sovereign` | student prompts never leave institutional infra — stronger than ZDR; FERPA-aligned; the pin is config absence, per invariant |
  | Course automation (grading pipelines via Cairn) | `sovereign` or `open_weight_only` | grading content may be sensitive; hosted-open only with ZDR + institutional sign-off |
  | Staff/research lanes | `hybrid` | boundary-gated PAYG rescue, budget per PI/course |
- **Sovereign pool:** Jetstream2 / campus vLLM endpoints as `institutional_sovereign` deployments (the Scale-2 config
  insert between T2 and T3 — not a T-number). Cross-module: **Outfitter provisions the
  inference nodes** (its jetstream2/hpc adapters stand up and reap GPU instances under budget); Portage routes onto
  whatever endpoints Outfitter reports healthy. Attribution labels (course/assignment/student, opaque) are shared
  vocabulary across Portage spend logs and Outfitter's cost ledger.
- **Belay integration:** Belay's leak gate stays Belay's own deterministic verifier (never Portage's job); Portage
  supplies routed inference under the lane's policy mode; Belay's DomainPack calls declare task class so triage assigns
  budget 0 (student lanes have no T6 at all — mode, not budget, enforces it; T7 is the terminal stall, never a provider
  rung).
- **Adoption gate per institution:** a lane flips to `open_weight_only` / stays `sovereign` based on per-lane
  displacement measured during a pilot term. The same metric that governs Greg's personal flip governs institutional
  posture — one instrument, every scale.
- **Grant narrative hook:** displacement + rescue-efficiency reports are the evidence base for "public infrastructure,
  no proprietary dependency" claims in PESOSE/IUSE materials — measured, dated, reproducible.

## 7. Invariants that do not change (re-affirmed)

Verifier decides, never the model (failup.py authoritative). Sensitive pin by config absence, never runtime check, never
a provider's retention promise. Triage before routing; deterministic pins always win. Honesty/non-inferiority gates on
every claim. Buy-over-build: the hosted rungs — DeepSeek, Morph, the gated Moonshot row — and SearXNG are
**config/deploys, not code**, exactly as OpenRouter and Together were when they held those slots. Open-to-open
escalation before any open-to-closed step; the Fable tier is outside that chain, not its last step. No fan-out
orchestration.

## 8. Acceptance for the revision work itself

- Docs updated per §4; `docs/specs/10`/`11` referenced as normative Scale-1 inputs.
- `litellm.hybrid.yaml` validates; allowlist manifest carries license + quant floor for every remote-open model.
- Stub tests: unavailable-vs-failed split; displacement + rescue reports from fixtures; T6 refuses without budget.
- Bench prereg updated with the accounting decision from §2.2 (baseline-first or historical-amortized), dated.

## 9. Phase-numbering map (canonical: S0–S5, per LINE-P-ROADMAP.md)

| S-stage | Absorbs                                                                             |
|---------|-------------------------------------------------------------------------------------|
| S0      | CC-P0 v2 (split + push), HB-0 (gateway/registry), HB-1 (frontends)                  |
| S1      | HB-2 (verification, budgets, paired baseline) + CC-P1 verifier-contract consumption |
| S2      | HB-3 (cache affinity, shared memory)                                                |
| S3      | Calibration + staged cutover (the old "Phase 4")                                    |
| S4      | HB-4 (learning loop, collapse guards)                                               |
| S5      | Full implementation (Line P definition of done)                                     |

PLATFORM §9's Phases 7–10 are post-S5 / Line E work. HANDOFF's Phases 0–5 and pilot-reconciled §8's Phases 0–5 are
historical numbering; where any phase number conflicts with an S-stage, the S-stage wins (header rule, this file).
