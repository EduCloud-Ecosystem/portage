# Local Platform — Open-Weight Only

> **Ladder rewritten 2026-08-05** per CW-04 and CC-P6; decision record in `portage-local/docs/reports/`.

*Recommended Scale 1 architecture for eliminating proprietary-model dependence while retaining local and hosted
open-weight inference.*

> **Revised 2026-07-28 per CW02-decisions.md §3 (dormant-slot synthesis) —
> HISTORICAL, superseded in part by the note below.** local_burst is no longer a
> tier (this part stands) — the MacBook is a second health-checked deployment of
> `local_fast`, and the freed T2 slot holds `local_large` (dormant, enabled:
> auto). *Superseded:* this revision put Groq at T3 (`remote_open_fast`) and
> Together at a defined-but-dormant T5. Neither holds — see below. Capability
> aliases are the seven-cell set in CW02 §3.

> **Revised again 2026-08-05 per `CW04-model-roster.md` §2.1–2.5 and CC-P6.**
> Groq vacates T3 — its self-serve catalog serves none of the models this roster
> selects — and drops into the dormant reserve. **OpenRouter leaves the ladder
> entirely**: not demoted in place, removed, because serving precision is now
> the deciding constraint and an aggregator that can change quantization under a
> stable model ID makes a benchmark cell irreproducible. T3 becomes
> `remote_open_direct` (DeepSeek, first-party); T4 becomes `remote_open_broad`
> (Morph, bf16 unquantized); T5 becomes `remote_open_reserve`, dormant,
> absorbing both Groq and Together. Capability aliases remain the seven-cell
> set, but the deployment now declares **six** of them — `proprietary_code` was
> deleted outright by CC-P6, not disabled. And the mode this document defines
> now tests **`license_family`**, not `open_weight`; see "Core principle".

## Purpose

This mode is the long-term sovereignty target.

The platform keeps the existing Herdr + LiteLLM routing spine, deterministic triage, prompt adaptation, `failup.py`
verification, plan-first decomposition, and `measure.py` telemetry. The policy boundary changes: **no proprietary model
is ever eligible for inference**.

Hosted inference is still allowed. The requirement is that the model weights are publicly downloadable **and** the grant
they ship under is on the approved list. Remote providers supply compute, not a closed intellectual dependency.

Those are two conditions, not one, and conflating them was the original defect in this document. See "Core principle".

---

## Core principle

> **Open weights first, local whenever practical, hosted when economically rational, proprietary inference never.**

The goal is not “every token must be generated inside the house.”

The goal is:

> **100% of normal model inference is served by approved open-weight models, with local hardware handling the
economically sensible share and metered remote GPUs handling workloads that exceed local capacity.**

### The eligibility test is `license_family`, not `open_weight`

This mode was originally written on the assumption that published weights imply an acceptable license. **Kimi K3
falsified that assumption** (CW-04 §2.5): its weights shipped publicly on 2026-07-27 under a bespoke grant carrying a
revenue-triggered separate-agreement clause for Model-as-a-Service operators and a UI attribution mandate above 100M
monthly active users. Neither MIT nor Apache. `open_weight: true` would have admitted it.

So the registry carries a required `license_family` field, and **this policy mode tests that field**. Its six values are
`permissive`, `weak_copyleft`,
`strong_copyleft`, `non_permissive`, `proprietary`, `unverified`.
`unverified` **fails closed** — it is deliberately not allowlist-eligible, so a grant nobody has actually read cannot
pass on the strength of downloadable weights.

Where the live roster sits today:

| `license_family` | Rows                                                                                                    |
|------------------|---------------------------------------------------------------------------------------------------------|
| `permissive`     | `nomic-embed-text` (Apache-2.0); all four DeepSeek V4 Flash rows (MIT)                                  |
| `unverified`     | all three Gemma 4 rows (custom Google grant, use restrictions, unread); `minimax-m3`; `deepseek-v4-pro` |
| `non_permissive` | both Kimi K3 rows (`Kimi-K3-Custom`)                                                                    |
| `proprietary`    | `gpt-5.6-sol` — absent from this mode by definition                                                     |

Two consequences worth stating plainly. First, **most of the local ladder is
`unverified` right now**, so a strict reading of this mode does not yet clear its own local rungs; reading the Gemma
grant is outstanding work, not a formality. Second, like the T-numbers, the mode is a label rather than a runtime check:
nothing in `src/` reads `license_family` except the renderer that copies it into `model_info`. `open_weight_only` is
enforced by which rows a config variant carries, not by a selector that could reject one.

---

## Scale 1 footprint

### Existing hardware

- **iMac** — always-on routing and local inference host
- **MacBook Pro** — opportunistic second local inference worker
- **2 TB NVMe** — fast active AI workspace, models, vector stores, environments, and working datasets
- **8 TB Seagate** — bulk storage, model archive, dataset archive, and backup tier

### Future hardware

- **High-memory local AI node** — target roughly 128 GB of model-accessible memory
- Added only when Herdr telemetry shows that local model capacity is a recurring constraint

---

## Recommended topology

```text
                         HERDR
                           |
                 classify / adapt
                           |
                        LiteLLM
                           |
        +------------------+-------------------+
        |                  |                   |
   local-fast                            local-large
   iMac + MacBook Pro                  future 128GB node
   Gemma 4 E4B (warm) + 12B Q4         (dormant, enabled: auto)
   (two deployments, one rung)
        |                  |                   |
        +------------------+-------------------+
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
                       CEILING_STALL
```

There is no Claude, proprietary GPT, Gemini, Sonar, or other closed-model fallback. `proprietary_research` (GPT-5.6 Sol)
exists in the hybrid registry at T6 and is simply absent from this mode's config variant; `proprietary_code` (Anthropic)
does not exist in either — CC-P6 deleted the row outright.

**Two things sit off that chain and are drawn apart from it deliberately:**

```text
  ── not rungs, at any T-number ──────────────────────────────────────────

  FABLE TIER — Kimi K3  (moonshot/kimi-k3)
      Reached ONLY by an explicit human declaration that a specific task
      warrants it, with the reason logged. Never by a stall, a verifier
      failure, or any other escalation. It is not rung 7 and it is not
      the step after CEILING_STALL — it is off the escalation graph.
      Carried as `fable_tier: true` + `enabled: false`.
      ABSENT IN THIS MODE: weights are public, but `license_family` is
      `non_permissive`, so it fails the eligibility test above. It is
      excluded on LICENSE, not on hosting — which is exactly the
      distinction this mode exists to make.

  OpenRouter
      OFF THE LADDER entirely (CW-04 §2.2) — not a rung at any
      T-number, and not drawn as one because it is not one. Its defined
      role is a non-routable failover path tagged `unbenched`, reachable
      only when a first-party endpoint health-checks down.
      THAT PATH IS UNBUILT. The schema carries a `failover_only` field
      for it and NO row sets it, because any row rendered into an
      alias's model group is routable by LiteLLM's own retry/fallback
      regardless of what `model_info` says — the tag would be a comment,
      not a control. Nothing routes through OpenRouter today. Building
      the health-check-gated call path is HB-2 work.
```

---

## Inference ladder

### 0. `deterministic`

No model call yet.

Responsibilities:

- sensitive-content pinning
- explicit overrides
- task-shape rules
- triage for underspecified requests
- lint/test command discovery
- routing-policy enforcement
- `license_family` allowlist checks (not `open_weight` — see "Core principle")

This remains the cheapest and most reliable rung.

---

### 1. `local_fast`

**Primary host:** always-on iMac.

Purpose:

- task classification
- prompt adaptation support
- bounded code edits
- routine R/Python/SQL work
- summarization
- extraction
- lightweight code review
- embeddings
- small specialist models
- inexpensive first-pass agent work

This tier should favor models that remain responsive on the iMac rather than chasing maximum parameter count.

**Current occupants** (CW-04 §2.4; live in `registry.yaml`):

| Alias        | Model              | Host    | Notes                                                                                                                                              |
|--------------|--------------------|---------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `classifier` | `gemma4:e4b`       | iMac    | sole occupant, no `order` needed. Kept warm at `OLLAMA_KEEP_ALIVE=-1` — the alias that wants a warm model lives where the warm model lives         |
| `code_small` | `gemma4:12b` (Q4)  | MacBook | `order: 1`                                                                                                                                         |
| `code_small` | `gemma4:e4b`       | iMac    | `order: 2`, the fallback                                                                                                                           |
| `embedding`  | `nomic-embed-text` | iMac    | single deployment, no failover. Changing the embedder mid-corpus invalidates the vector store, so this pin is stickier than the rest of the ladder |

Qwen3-Coder 7B is retired from the documented roster entirely (CW-04 §2.4) and appears nowhere in the live registry.

The 12B lands on the **MacBook** first, deliberately: that machine carries no service co-tenancy, so it gives a clean
quality read. The iMac runs LiteLLM, Postgres, Qdrant, Open WebUI, SearXNG and Docker on 16GB, and 12B Q4 is roughly 8GB
of weights before KV cache. A steward swap requires a head-to-head bench against E4B under live co-tenancy first.

All three Gemma rows are `license_family: unverified` — the Gemma terms carry use restrictions, so `permissive` would be
wrong and `non_permissive` would be a guess about a grant nobody in this repo has read. That value fails closed, which
means this mode does not currently clear its own local rungs on a strict reading. Reading the grant is real outstanding
work.

Recommended policy:

```yaml
capability: local_fast
availability: required
cost_class: local
privacy: local
```

---

### 2. `local_fast`, second deployment (formerly `local_burst`)

**Host:** MacBook Pro when online.

No longer a tier (CW02 §2.1): tiers are capability rungs, machines are deployments. The MacBook runs the same models as
the iMac, so escalating to it buys no capability — LiteLLM load-balances it inside `local_fast` with health checks. It
is not extra RAM for the iMac; it is a second inference worker.

Best uses:

- parallel subtasks
- independent code review
- test generation
- secondary-agent work
- specialist models
- background indexing
- larger local models when the MacBook itself has more unified memory

If the MacBook is asleep or off-network:

```text
result = unavailable
```

not:

```text
result = model_failed
```

This distinction is essential so `measure.py` does not interpret missing hardware as a model-quality failure.

---

### 3. `local_large`

**Future host:** high-memory local AI node.

Recommended target:

- roughly **128 GB** of model-accessible memory
- fast local NVMe
- high-speed Ethernet preferred
- headless operation
- Tailscale/SSH administration
- Ollama, llama.cpp, or another approved local inference runtime behind LiteLLM

This tier should expose **capability aliases**, not hard-coded permanent model names:

```text
code_large
research_synthesis
```

The model behind each alias should be selected by Parity Bench results. The alias vocabulary is the seven-cell set in
CW02-decisions §3; the former
`local/*` namespace is retired — where a capability runs is a deployment property, not part of the alias.

The purpose of this node is to make substantially larger open-weight models locally available without replacing the iMac
as the normal workstation.

---

### 4. `remote_open_direct` (T3)

**Provider: DeepSeek, first-party** — `api.deepseek.com`, reached through LiteLLM's native `deepseek/` route.

Herdr selects the model *and* the surface serving it. There is no delegated infrastructure choice at this rung, and that
is the point rather than a limitation.

**Why direct rather than aggregated.** DeepSeek's first-party API does automatic prefix caching, billing a repeated
prefix at roughly 2% of the miss rate. That cache is the reason this rung's economics work, and it is a first-party
behaviour — routing the same model through an intermediary forfeits it. This is the single reason T3 exists as a
separate rung from T4 rather than collapsing into it (CW-04 §2.2, and §4 item 1 keeps the collapse open as a live
question if Morph turns out to carry an equivalent cache).

**Occupants.** Two checkpoints and one re-run:

| Model                               | Where                                              | `license_family`                                                         | Role                                                                      |
|-------------------------------------|----------------------------------------------------|--------------------------------------------------------------------------|---------------------------------------------------------------------------|
| `deepseek-v4-flash`                 | `code_large` order 1, `research_synthesis` order 1 | `permissive` (MIT, confirmed 2026-08-05, weights public on Hugging Face) | the **cheap first attempt**, before the primary occupant — not a fallback |
| `deepseek-v4-pro`                   | `research_synthesis` order 2                       | `unverified`                                                             | the primary occupant for research synthesis                               |
| `deepseek-v4-flash` @ `effort: max` | order 3 on both ladders                            | `permissive`                                                             | "Flash Max" — see §5                                                      |

Note the shape: **Flash comes *before* the primary occupant, not after.** The order numbers ascend by cost, so they are
literally the escalation order.

**Controls that apply here:**

- hard model allowlist, expressed as *which rows exist in `registry.yaml`* — a model that is not a row is not a
  deployment
- `license_family` on every row, checked at T0, `unverified` failing closed
- no fallback to a model outside the registry
- benchmark per endpoint, not per model name

Serving precision needs no filter at this rung because there is no intermediary that could change it.

**What this actually renders to.** `render_config.py` reads `registry.yaml` and emits `model_list.generated.yaml`; both
it and `config.yaml` are gitignored build artifacts — never hand-edit them. This is the real rendered shape, not an
illustration:

```yaml
model_list:
  - model_name: research_synthesis
    litellm_params:
      model: deepseek/deepseek-v4-flash
      api_key: os.environ/DEEPSEEK_API_KEY
      order: 1
    model_info:
      portage_alias: research_synthesis
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
  - model_name: research_synthesis
    litellm_params:
      model: deepseek/deepseek-v4-pro
      api_key: os.environ/DEEPSEEK_API_KEY
      order: 2
    model_info:
      portage_alias: research_synthesis
      enabled: true
      open_weight: true
      license: UNVERIFIED
      license_family: unverified
      max_context: 1048576
      supports_tools: true
      supports_json: true
      data_classification: public
      benchmark_version: null
      bfclv3: null
      ifeval: null
```

Endpoints and keys are `os.environ/` references, never literals, so the file stays portable. `DEEPSEEK_API_KEY` is
LiteLLM's own key name for this provider.

`deepseek-v4-flash` and `deepseek-v4-pro` are the vendor's **documented** names and have not been confirmed against a
live `/v1/models` on DeepSeek's own API. Both carry a `TODO(native)` in `registry.yaml`. The B7 gate governs: pins
change only after the model is reached and passes the per-model tool-call smoke test.

---

### 5. `remote_open_broad` (T4)

**Provider: Morph** — bf16 activations, no quantization, one key, reached through LiteLLM's native `morph/` route.

**Why Morph and not an aggregator.** Every alias in this platform is a benchmark cell, and reproducibility is one of the
six inclusion criteria. An aggregator that can change quantization under a stable model ID makes the cell
irreproducible — the same model name silently becomes a different measurement. Morph serves open models at 16-bit
activations without quantization *and says so*. That single test is what removed six providers from consideration (CW-04
§2.2, §3) and it is why this rung is a named vendor rather than a routing layer.

**Occupant:** MiniMax M3 (`morph/minimax-m3`), `code_large` order 2 —
`license_family: unverified`, because MiniMax M2 shipped MIT but M3's grant is not confirmed. GLM-5.2 and Qwen sit
in-slot behind the same key if either is ever wanted, with no new account and no new inclusion review.

**"Flash Max" — a second rung on the same checkpoint.** After the Morph occupant comes `deepseek/deepseek-v4-flash`
again at `effort: max` (order 3 on both ladders). This is **the same checkpoint as order 1, not a separate model**.
Buying more thinking on a model that already passed the cheap attempt is a cheaper escalation than onboarding a new
vendor.

> **Caveat, unresolved.** `litellm_settings.yaml` sets `drop_params: true`. If
> DeepSeek's API does not accept the literal `reasoning_effort: max`, LiteLLM
> drops the parameter **silently** and this rung collapses into a duplicate of
> order 1. It would not error; it would just quietly stop being a rung. Confirm
> at HB-0 Gate 2.

**What this actually renders to** — the complete `code_large` model group, which is the clearest artifact in the whole
config because a single alias's group spans three tiers plus the Fable row:

```yaml
- model_name: code_large            # T3 — cheap first attempt
  litellm_params:
    model: deepseek/deepseek-v4-flash
    api_key: os.environ/DEEPSEEK_API_KEY
    order: 1
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
- model_name: code_large            # T4 — the primary occupant
  litellm_params:
    model: morph/minimax-m3
    api_key: os.environ/MORPH_API_KEY
    order: 2
  model_info:
    portage_alias: code_large
    enabled: true
    open_weight: true
    license: UNVERIFIED
    license_family: unverified
    max_context: 1048576
    supports_tools: true
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
- model_name: code_large            # T4 — "Flash Max", same checkpoint as order 1
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
- model_name: code_large            # FABLE TIER — off the ladder, see below
  litellm_params:
    model: moonshot/kimi-k3
    api_key: os.environ/MOONSHOT_API_KEY
    order: 5
  model_info:
    portage_alias: code_large
    enabled: false
    open_weight: true
    license: Kimi-K3-Custom
    license_family: non_permissive
    max_context: 262144
    supports_tools: true
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    fable_tier: true
```

**`order: 4` is deliberately vacant.** CC-P6 pinned the K3 row to `order: 5` on this ladder and `order: 4` on
research's, reasoning that research has no local tier so its ladder is one shorter — which assumes `code_large` opens
with a local rung. CW-04 §2.3 does not give it one; the local coding rung is
`code_small`. So the K3 order is honoured literally and the implied slot is left empty rather than silently renumbered.
`order` gaps are inert: LiteLLM sorts on the value and does not require contiguity. It is a decision, not a typo.

---

### 6. `remote_open_reserve` (T5) — DORMANT

Defined, disabled, and holding two unrelated re-enable triggers. Following the CW-02 §2.1 dormant-slot idiom rather than
deletion, so a vacated rung leaves a written trigger behind instead of a hole.

> **Naming hazard.** This slot was called `remote_open_direct` under CW-02.
> CW-04 reassigned that name to **T3** (DeepSeek). Two different tiers have held
> the same name at different times — when reading anything dated before
> 2026-08-02, check which one is meant.

**Trigger (a) — a latency-sensitive alias that no local rung can serve.**
Occupant would be **Groq GPT-OSS 120B**, at roughly $0.15/$0.60 and ~500 tok/s, and it enters **benched as its own
capability cell, never as a route to an existing roster model**. Groq previously held T3 and vacated it: its self-serve
catalog is Llama 3.1 8B / 3.3 70B, GPT-OSS 20B / Safeguard 20B / 120B, and Qwen 3.6 27B, plus MiniMax M2.7
enterprise-only — DeepSeek, Kimi, GLM and Mistral have no path there, so it cannot serve the models this roster actually
selects. It also offers no prompt-caching discount, which removes the mechanism that makes the direct-provider economics
work (CW-04 §2.1).

**Trigger (b) — sustained Morph unavailability.** Occupant would be **Together AI**: serverless per-token inference, no
GPU provisioning, broad open-model catalog, OpenAI-compatible. Together's original CW-02 trigger referenced OpenRouter
unavailability and is superseded by this one. This trigger is also the standing mitigation for the one open half of
Morph's inclusion-test assessment, vendor durability (CW-04 §4 item 4).

**Neither is wired.** There are no Groq or Together rows in `registry.yaml`, no keys in `.env.example`, and nothing
routes to either. Re-enabling means adding rows and running the inclusion test, not flipping a flag.

DeepInfra, Fireworks, Novita, Atlas, GMICloud and the other aggregators are **rejected, not dormant** — serving
precision is undocumented per endpoint, which breaks a benchmark cell (CW-04 §3). They are recorded there with reasons
so a later pass does not silently reopen them.

---

## Model strategy

Do not build the architecture around a single “Claude replacement model.”

Use role-specific capability aliases.

```text
classifier
code_small
code_large
research_synthesis
embedding
```

Herdr then maps each capability to the currently best validated model. Five open aliases here. `proprietary_research`
exists only in hybrid mode (docs/specs/11); **`proprietary_code` exists nowhere** — CC-P6 deleted the Anthropic row
outright rather than disabling it, so the deployment declares six of the seven fixed aliases, and the seventh is absent
rather than hidden.
`code_medium`, `vision`, `reranker` earn cells when telemetry shows a routing decision that needs them (scale-mapping
§4.3).

Candidate families should be selected from current downloadable open-weight models — but "downloadable" is the entry
condition, not the test. Each candidate still has to clear `license_family`:

| Family          | Status on this roster                                                                                                                          |
|-----------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| DeepSeek        | **in use** — V4 Flash (MIT, `permissive`) at T3 and as the Flash Max rung; V4 Pro (`unverified`) as research's primary                         |
| MiniMax         | **in use** — M3 via Morph at T4, `unverified`                                                                                                  |
| Gemma           | **in use** — E4B and 12B Q4 locally, all `unverified`                                                                                          |
| GPT-OSS         | dormant-only — 120B is T5's trigger-(a) occupant, benched as its own cell                                                                      |
| GLM / Z.ai      | available in-slot on Morph's key; Z.ai's own direct API is rejected (a second surface for one vendor, priced above MiniMax)                    |
| Qwen            | available in-slot on Morph's key. Qwen3-Coder 7B is retired from the local roster                                                              |
| Kimi / Moonshot | **rejected for the routine roster** (CW-04 §2.5) on cost and license together. K3 survives only as the off-ladder Fable tier, `non_permissive` |
| Llama, Mistral  | no current occupant                                                                                                                            |

The exact winner is intentionally not permanent.

**Parity Bench decides — subject to the license gate, which Parity Bench does not get a vote on.**

---

## Recommended coding path

```text
task
 |
deterministic triage
 |
local_fast
 |
verified?
 +-- yes --> complete
 |
 no
 |
local_fast #2 (MacBook) or local_large
 |
verified?
 +-- yes --> complete
 |
 no
 |
remote_open_direct  (T3 — DeepSeek v4-flash, the cheap first attempt)
 |
verified?
 +-- yes --> complete
 |
 no
 |
remote_open_broad   (T4 — Morph / MiniMax M3)
 |
verified?
 +-- yes --> complete
 |
 no
 |
"Flash Max"         (T4 — v4-flash again at `effort: max`)
 |
verified?
 +-- yes --> complete
 |
 no
 |
[remote_open_reserve — T5, dormant: nothing here today]
 |
decompose / retry
 |
CEILING_STALL


  ── and never from any box above ──────────────────────────────
  FABLE TIER (Kimi K3) is NOT the next step after CEILING_STALL
  and is not reachable from any arrow in this diagram. It is
  entered by a logged human declaration or not at all.
```

`failup.py` remains authoritative.

The model's statement that it succeeded is never sufficient.

One structural note, because the per-tier headings above can mislead: the registry does **not** model these as separate
deployment groups. Each capability alias is one LiteLLM model group, and the rungs are `order` values inside it — so
`code_large` alone spans T3, T4, the Flash Max re-run, and the Fable row. The tier vocabulary is documentation over a
flat, ordered list, and `failup.py`
does not read it: the guard's ladder comes from `.claude/tiers.*.json`, whose rung names and the registry's alias names
do not intersect at all.

---

## Ceiling behavior

The final open-weight failure must **not** silently cross into proprietary inference.

Instead:

```text
last eligible open rung ("Flash Max", T4)
        |
      failure
        |
decompose task
        |
retry eligible open tiers
        |
      failure
        |
   CEILING_STALL     <- terminal. Not a doorway to the Fable
                        tier, and not a doorway to T6.
```

Log:

- task profile
- model attempts
- local vs. hosted
- context size
- acceptance command
- verifier result
- availability failures
- quality failures
- total open-inference cost
- best prior Parity Bench comparison

This makes the remaining open-model gap measurable.

---

## Research profile without Perplexity

The Science lane must replace Perplexity-style research with an open stack.

Recommended flow:

```text
query decomposition
       |
web / scholarly retrieval
       |
source normalization
       |
open-weight synthesis
       |
citation extraction
       |
citation-resolution verifier
       |
final answer
```

A self-hosted metasearch layer such as **SearXNG** is appropriate for general web discovery, supplemented by direct
scholarly APIs/indexes for academic work.

The model must never be trusted to invent citations.

Every cited source must have been retrieved and validated by the citation-resolution verifier.

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

The NVMe is the workbench.

The 8 TB Seagate is the warehouse.

---

## Hardware-purchase rule

Do not buy the 128 GB node merely because larger models exist.

Buy it when Herdr data shows:

1. a material percentage of tasks fail because the best local model is too small;
2. hosted open-weight models solve those same tasks;
3. the expected local inference volume makes hardware economically preferable;
4. the quality gain from the larger open model is demonstrated by the personal Parity Bench.

This turns hardware acquisition into a measured capacity decision rather than a benchmark-driven guess.

---

## Recommended policy configuration

The provider-block form this section used to carry (`groq:`, `openrouter:`,
`together:`, `deepinfra:`, each with an `open_weight_only: true` toggle) never existed in the built system and does not
exist now. Two corrections at once:
those four providers are not the roster any more, and **there is no per-provider policy toggle at all**. Policy is
expressed as which rows exist in
`registry.yaml` and what `license_family` each carries. This is the real shape:

```yaml
# registry.yaml — the hand-edited source of truth. `render_config.py` turns
# this into litellm/config.yaml + model_list.generated.yaml, both gitignored
# build artifacts. Never hand-edit those.
#
# For open_weight_only, the config variant simply carries no row whose
# license_family is outside the allowlist — no toggle refuses one at runtime.

models:
  # T1 — local. Sole occupant, so no `order` is required.
  - alias: classifier
    provider_route: ollama_chat
    model_id: gemma4:e4b
    endpoint: os.environ/PORTAGE_IMAC_HOST
    open_weight: true
    license: UNVERIFIED
    license_family: unverified   # fails closed — Gemma's grant is unread
    max_context: 131072
    supports_tools: true
    supports_json: true
    thinking_disabled_for_structured: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    enabled: true

  # T3 — DeepSeek first-party, the cheap first attempt.
  - alias: code_large
    provider_route: deepseek
    model_id: deepseek-v4-flash
    order: 1
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

  # T4 — Morph, the primary open-weight ceiling.
  - alias: code_large
    provider_route: morph
    model_id: minimax-m3
    order: 2
    open_weight: true
    license: UNVERIFIED
    license_family: unverified
    max_context: 1048576
    supports_tools: true
    supports_json: true
    data_classification: public
    benchmark_version: null
    bfclv3: null
    ifeval: null
    enabled: true

  # T4 — "Flash Max": the SAME checkpoint as order 1, more thinking.
  - alias: code_large
    provider_route: deepseek
    model_id: deepseek-v4-flash
    order: 3
    effort: max
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

  # FABLE TIER — off the ladder. Present in the hybrid registry, and NOT
  # eligible for this mode: license_family is non_permissive. order 4 is
  # deliberately vacant; see §5.
  - alias: code_large
    provider_route: moonshot
    model_id: kimi-k3
    order: 5
    open_weight: true            # public weights, and still ineligible —
    license: Kimi-K3-Custom      # which is the whole point of the field below
    license_family: non_permissive
    max_context: 262144
    supports_tools: true
    supports_json: true
    data_classification: public
    fable_tier: true             # never selected by ordinary escalation
    enabled: false               # and disabled on top of that
    benchmark_version: null
    bfclv3: null
    ifeval: null

# No `proprietary_research` row in this mode's variant, and no
# `proprietary_code` row in ANY variant — CC-P6 deleted it outright.
#
# No groq:, openrouter:, together: or deepinfra: rows anywhere. Groq and
# Together are dormant triggers with no rows; OpenRouter is off the ladder;
# the rest are rejected on serving precision.

on_open_ceiling_failure:
  action: ceiling_stall
```

The schema also defines `failover_only` (optional boolean, default false) for CW-04 §2.2's OpenRouter demotion. **No row
sets it**, deliberately: a row rendered into an alias's model group is routable by LiteLLM's own retry/fallback whatever
`model_info` says, so a `failover_only: true` row inside
`code_large` would be exactly the routable rung the demotion removed. The field is in place and waiting; the rows come
back when HB-2 ships the mechanism that makes them genuinely non-routable.

The same limitation is the honest caveat on the Fable gate: `enabled: false`
keeps K3 out of every downstream selector that filters on the flag, but LiteLLM itself does not read
`model_info.enabled`. A sustained outage of orders 1–3 could in principle have the proxy exhaust its retry budget and
reach the K3 deployment. Narrowed, **not closed** — recorded as open in `P6-report.md` §1.

---

## Success metrics

Track at minimum:

```text
% solved by local_fast
% solved by the MacBook deployment (local_fast #2)
% solved by local_large
% solved by hosted open-weight
% ending in ceiling stall

cost per verified successful task
median latency by rung
tokens / context by rung
unavailable vs. not-good-enough failures
```

The critical metric is:

> **What percentage of real tasks receive a verified successful result without proprietary inference?**

---

## End state

The platform runs open-weight models locally whenever practical, rents remote GPU inference only when larger open models
are justified, and treats a model-quality ceiling as measurable evidence rather than permission to invoke a closed
model.

No recurring LLM subscription is required.

No proprietary model dependency remains.

---

## Current provider references

Provider capabilities change, so these should be revalidated periodically.

**Live rungs:**

- DeepSeek API (T3): https://api-docs.deepseek.com/ — model list, and the automatic prefix-caching behaviour this rung's
  economics depend on
- Morph (T4): https://docs.morphllm.com/ — the bf16 / no-quantization serving commitment is the inclusion criterion, so
  revalidate it specifically
- LiteLLM provider routes: `deepseek`, `morph`, `moonshot` are native in the pinned v1.93.0, resolving to
  `api.deepseek.com/beta`, `api.morphllm.com/v1`
  and `api.moonshot.ai/v1`; key names `DEEPSEEK_API_KEY`, `MORPH_API_KEY`,
  `MOONSHOT_API_KEY` come from LiteLLM's own transformation modules

**Dormant-slot references — not live rungs, listed only so the re-enable triggers can be evaluated without
re-researching from scratch:**

- Groq (T5 trigger (a)): https://console.groq.com/docs/models
- Together AI (T5 trigger (b)): https://docs.together.ai/docs/inference/overview

OpenRouter is intentionally not listed. It is not a rung, nothing routes through it, and a link here would imply
otherwise.
