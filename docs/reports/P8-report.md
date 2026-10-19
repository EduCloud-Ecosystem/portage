# P8-report — Fable-tier exclusion requirement recorded for a future displacement metric

*Decision-record closure for CC-P8 (executed 2026-08-05; commit `d3e1039` for the source notes). Companion to
`P6-report.md` and `CW04-model-roster.md`. No functional code was written — this is a requirement recorded for a
future implementer, not a metric implementation. The canonical decision-record home is
`portage-local/docs/reports/`; this in-repo copy was added because that location is not part of this checkout.*

## What was checked, and why there is no live bug

- `proprietary_displacement` does not exist in any `.py` file in this repo. It is referenced in nine markdown
  documents and implemented nowhere.
- `measure.py`'s `summarize()` reads only `failup-log.jsonl`, produced by `failup.py` walking `.claude/tiers.json`'s
  ladder (rungs named `local-small`, `local-big`, `sovereign-work`, `sonnet`, `opus`).
- Kimi K3 lives only in `registry.yaml`, a structurally separate system `failup.py` never opens (the schema's own
  `fable_tier` description already says so). A K3 call therefore cannot appear in `measure.py`'s output today.
- No `failup-log.jsonl` exists anywhere on disk — the system has produced zero real runs, so there is no traffic a
  displacement metric could be validated against.

Conclusion: the CC-P7 §"Ambiguities" concern is real but future-facing; there is no live bug to fix.

## What was added, and where

- `src/portage/measure.py` — a block comment at the top of the measurement section, directly above `summarize()`
  (lines ~134–163), recording: the module sees only the `.claude/tiers.json`-driven ladder via `failup-log.jsonl` and
  has no visibility into `registry.yaml`'s alias-based LiteLLM deployments, including the Kimi K3 Fable tier; if
  `proprietary_displacement` or any future metric over registry-alias traffic is ever implemented, it MUST exclude
  from any "open-ladder win" (a) every row with `fable_tier: true` and (b) every row whose `license_family` is
  outside the `open_weight_only` allowlist — and the second exclusion is not implied by the first, because a K3 rescue
  remains reachable in principle through LiteLLM's own retry/fallback even while `enabled: false` (P6-report §1, "the
  honest limit of a declarative gate"). Sources cited: CW-04 §2.5 and P7-report's ambiguity note, both in
  `portage-local/docs/reports/`.
- `schema/registry.schema.json` — one sentence appended to `license_family`'s description stating that any future
  consumer computing an "open-ladder win" or displacement-style metric over this registry must exclude both
  `fable_tier: true` rows and rows whose `license_family` is outside the allowlist, pointing to the measure.py comment
  so the two notes stay in sync.
- `docs/reports/P8-report.md` — this file.

## Stopgap, not a final decision

This is a deliberate stopgap, not a decision to skip the metric. The full `proprietary_displacement` implementation
is deferred to a future Claude Code prompt, to be scoped once there is real registry-alias LiteLLM traffic to measure
against — i.e., after HB-0's Gates 2–4 run and a live proxy actually produces logs. CC-P8's job was only to make sure
that future build cannot miss the Fable-tier / `license_family` exclusion, not to declare the metric out of scope
permanently.
