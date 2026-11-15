# 08 — Scale tiers (post-landscape-report architecture)

> **Scale-1 ladder rewritten 2026-08-05** per CW-04 and CC-P6; decision record in `portage-local/docs/reports/`.

Source: `routing-layer-landscape-2026.md` (uploaded survey). Its verdicts:
**build** the fail-up guard, herdr-meters, and the quality-adjusted-efficiency metric (all three confirmed as gaps — 112
herdr plugins surveyed, none do cross-vendor quota; no library does verifier-decides + tier-escalation; no observability
tool ships the stall-gated efficiency metric). **Partially adopt**
OpenSpec (plan schema only), vLLM Semantic Router (classifier backend only), and Langfuse (trace store only).
**Reference, don't adopt** STREAM (no public repo yet) and FIRST (production at ALCF but DOE-gated, not ACCESS).

**The design rule that falls out:** the custom core — fail-up guard, triage wrapper (deterministic pins +
clarify-before-dispatch), herdr-meters, metric logic — is *identical at every scale*. Scales differ only in (a) the tier
ladder and (b) which heavy backends are justified. Adopt infrastructure only when the scale earns it; every adoption
below is reversible because the custom core never depends on backend internals.

> **Updated 2026-08-05 (Scale-1 transition, `docs/specs/10`–`11`, `REVISION-PLAN.md`).**
> The Scale-1 ladder below has changed: fixed subscription rungs (Claude Max /
> Codex Plus) are removed from the production ladder and replaced by hosted
> open-weight + a boundary-gated proprietary **PAYG** ceiling. Subscriptions
> survive only as Parity Bench baseline arms. The scale-invariance rule is
> unchanged. Ladder revised 2026-07-28 per CW02-decisions.md §3 (dormant-slot
> synthesis), then again 2026-08-05 per CW-04 §2.1–2.3 and CC-P6: Groq's T3 slot
> vacates into the dormant T5 reserve, OpenRouter leaves the ladder entirely,
> DeepSeek first-party and Morph take T3 and T4, Anthropic's row is deleted so
> T6 has one occupant, and the Kimi K3 Fable tier is added off the chain. The
> Scale-2/3 sections below move to the EduCloud umbrella at CC-P0 v2 (CW02 §4).

---

## Scale 1 — Personal (laptop/iMac + open-weight + PAYG ceiling)

Ladder (`policy_mode: hybrid`): `local_fast (iMac + MacBook, two deployments) →
[local_large: future 128GB, dormant] → remote_open_direct (DeepSeek
first-party) → remote_open_broad (Morph, + the "Flash Max" rung) →
[remote_open_reserve: Groq / Together, dormant] → proprietary (GPT-5.6 Sol
PAYG, boundary-gated, one occupant, disabled by default)`. Perplexity is **not**
the Science-lane specialist any more — CW-04 §3 gates its API behind the science-lane citation verifier ("do not open
before that ships"), and the
`proprietary_research` alias now points at GPT-5.6 Sol. End state (`open_weight_only`, `docs/specs/10`) drops the last
rung.

Off the chain: the **Fable tier**, Kimi K3 (`moonshot/kimi-k3`). Not a rung, not a T-number, not rung 7 — reachable only
by an explicit human declaration that a specific task warrants it, with the reason logged, never by escalation.
`fable_tier: true` + `enabled: false`. Public weights, `license_family:
non_permissive`, so `open_weight_only` excludes it on license.

OpenRouter is off the ladder entirely (CW-04 §2.2): a non-routable failover path tagged `unbenched`, reachable only on a
first-party health-check failure — and that path is unbuilt. The schema carries a `failover_only` field for it and no
row sets it, so OpenRouter serves no traffic at any tier today.

| Component                      | Scale-1 choice                                                                                                                                                                                                        | Why                                                                                                                                                                                                                                                                                                                                                                          |
|--------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Proxy spine                    | **LiteLLM**, one config.yaml per mode                                                                                                                                                                                 | Already decided; lightweight at n=1                                                                                                                                                                                                                                                                                                                                          |
| Guard / triage / meters plugin | **Custom core, as drafted**                                                                                                                                                                                           | Report confirms no substitute exists                                                                                                                                                                                                                                                                                                                                         |
| Hosted-open direct             | **DeepSeek, first-party** (T3) — config, not code; `api.deepseek.com`, V4 Flash as the cheap first attempt then V4 Pro (license unverified)                                                                           | Direct rather than aggregated because DeepSeek's automatic prefix caching bills repeated prefixes at roughly 2% of the miss rate, and that cache is the reason this rung's economics work (CW-04 §2.2). V4 Flash is MIT, `license_family: permissive`                                                                                                                        |
| Hosted-open broad              | **Morph** (T4) — config, not code; MiniMax M3 primary, GLM-5.2 and Qwen in-slot without a new account. Followed by "Flash Max": DeepSeek V4 Flash re-run at `effort: max`, the same checkpoint, before the Fable tier | Serving precision is the deciding constraint. Every alias is a benchmark cell, and an aggregator free to change quantization under a stable model ID makes that cell irreproducible. Morph serves open models at bf16 without quantization and says so. Buying more thinking on a checkpoint that already passed the cheap attempt is a cheaper escalation than a new vendor |
| Hosted-open reserve            | **DORMANT slot** (T5) — Groq or Together, defined and disabled                                                                                                                                                        | Two independent re-enable triggers: (a) a latency-sensitive alias no local rung can serve → Groq GPT-OSS 120B, benched as its own capability cell, never a route to an existing roster model; (b) sustained Morph unavailability → Together. Groq's catalog serves none of the models this roster selects, which is why it vacated T3 (CW-04 §2.1)                           |
| Proprietary ceiling            | **GPT-5.6 Sol alone** (T6) behind LiteLLM budgets, `enabled: false`                                                                                                                                                   | No fixed subscription rung; reached only on verified open failure / documented specialist / explicit override. Anthropic's `proprietary_code` row is **deleted, not capped** — six aliases are declared now, not seven. The gate is policy plus that flag, not code                                                                                                          |
| Fable tier                     | **Kimi K3** — off the ladder, `fable_tier: true` + `enabled: false`                                                                                                                                                   | Not a rung and not rung 7. CW-04 §2.5 rejected K3 for the routine roster on cost and license together; this is the narrow declared-exception that rejection leaves room for, entered by a logged human declaration only                                                                                                                                                      |
| Classifier backend             | **Gemma 4 E4B on Ollama + keyword rules** — do NOT deploy vLLM Semantic Router                                                                                                                                        | vLLM SR is deployment-grade (BERT models, dashboard, Envoy); overkill for one user, and the report confirms the clarify/override wrapper stays custom regardless. E4B is the warm iMac model at keep-alive `-1`, so the alias that wants a warm model lives where the warm model lives                                                                                       |
| Plan schema                    | plan.json as drafted; **OpenSpec format optional**                                                                                                                                                                    | Cheap to adopt early (it's just a schema + 28k-star tooling), required at Scale 3 — adopting now avoids a migration                                                                                                                                                                                                                                                          |
| Measurement                    | **measure.py + JSONL** — no Langfuse                                                                                                                                                                                  | A hosted/unit-priced trace store is infrastructure weight one user doesn't need; the JSONL already feeds the metric, now incl. `proprietary_displacement` + rescue efficiency                                                                                                                                                                                                |

This scale is complete with what's in the repo + LiteLLM. **Nothing new to adopt** — DeepSeek, Morph, Moonshot, and the
PAYG ceiling are all LiteLLM config, not new dependencies, exactly as OpenRouter and Together were when they held those
slots. All three are native providers in the pinned LiteLLM v1.93.0 (`api.deepseek.com/beta`, `api.morphllm.com/v1`,
`api.moonshot.ai/v1`), so the change is four new API keys and a re-render, not a new integration. The transition itself
is Phase 6a in `REVISION-PLAN.md` — see the execution note there for what of it CC-P6 already did and what remains.

---

## Scale 2 and Scale 3

Relocated to the EduCloud umbrella at CC-P0 v2 (CW02 §4):
`~/dev/educloud/docs/specs/portage-scale-2-3.md`. The scale-invariance rule above still holds across all three scales;
only the ladder and backend adoption differ, which is exactly why that content now lives with the umbrella's other
Scale-2/3 planning material rather than in the engine.

---

## Standing re-evaluation triggers (from the report's time-sensitive flags)

1. vLLM Semantic Router ships clarify-before-dispatch or deterministic pre-model overrides → shrink or retire the custom
   triage wrapper.
2. DOE↔NSF Globus federation opens FIRST-class services to ACCESS users → retire most of the JS2 adapter.
3. Any quota router adds a sovereign/institutional tier → the fusion novelty erodes; differentiation falls back to the
   guard + measurement method. Recheck quarterly; the publication window is now.
