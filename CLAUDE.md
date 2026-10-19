# CLAUDE.md

> **Ladder rewritten 2026-08-05** per CW-04 and CC-P6; decision record in `portage-local/docs/reports/`.

Constitution for this repo. Loaded every turn — kept deliberately lean, because everything here re-sends on each turn
and taxes the shared pool. Situational guidance lives in skills (`.claude/skills/`), not here.

## Environment

- Python only, managed with `uv`. Run tests with `uv run pytest -q`.
- Never write files outside the repo.

## Model & effort discipline

- Default to Sonnet 5. Use `/model opus` only for judgment: architecture, ambiguous debugging, planning a large task,
  reviewing consequential diffs, milestone-gate decisions.
- Default effort. Escalate effort only for those judgment cases — never for routine execution.

## Lanes

- This interactive session is Lane A: native Claude Code. claude-code-router was deleted in Phase 2 — Claude Code
  reaches LiteLLM directly.
- Automation (CI, scheduled, batch) is Lane B and runs through the LiteLLM gateway, off the interactive session. Don't
  start Lane B work from an interactive session.

## Large tasks

- If a task spans multiple files/stages or needs sequencing, use the
  `/large-task` skill: plan first, get the plan approved, then execute.
- Do not fan out. Sequential by default; parallelize only provably independent stages, and only in Lane B.

## Subagents

- Reviewer and planner subagents are read-only. All edits stay on the parent agent (subagents can't answer permission
  prompts).

## Gates (non-negotiable)

- Milestone-gate decisions and large-task plan approvals are human-approved, pinned to Opus, and never downshifted for
  quota.
- Gate on green tests. A red suite blocks the gate.

## EduCloud ecosystem — shared conventions

`portage` is the LLM routing engine of the EduCloud ecosystem (an open-source GitHub Classroom replacement). Siblings:
`cairn`
(classroom/LMS), `belay` (AI tutor), `outfitter` (compute broker),
`waypoint` (hosting/identity), `educloud` (umbrella strategy/SYSTEM.md).
`portage-local` is a separate personal deployment, on hold — prompts here are **EduCloud-scoped only**, don't touch it.

**Platform invariant:** no component trusts a vendor's self-report. Verify pricing/precision/catalog/uptime claims
against the live API/service before writing them into a spec — Morph's precision claim was this ladder's reason for
existing at T4, and replacing it (CC-P15) required re-verifying against Jetstream2/AI Verde rather than assuming parity.

**CC-* prompt namespace** (`CC-P*` here, plus `CC-CA*`/`CC-B*`/`CC-O*`/
`CC-W*` in siblings, `CC-HB*`/`CC-C*` historical) is shared platform-wide — two real collisions have happened
(CC-P9/P10, CC-C1). Before numbering a new prompt: read `../educloud/DOCUMENTATION.md`'s namespace tracker, cross- check
this repo's own `docs/prompts/` directory (ground truth over the registry), use one higher than the max of both, update
the registry. Note
`portage` deliberately skips P9-P10 (claimed by `portage-local`'s own history). The `/new-cc-prompt` command does this
automatically.

Prompt shape: real title; italicized context line (what's known/verified vs. what this prompt resolves); numbered
sections; closing numbered **Report**
section (never omit) covering anything unverified or diverged.

No `Co-Authored-By: Claude` trailers in commits. Check actual trailers, not prose:
`git log -5 --format='%(trailers:key=Co-Authored-By)'` should print nothing — a plain `grep -c Co-Authored-By` over the
log can false-positive on prose describing the convention (caught in Cairn by CC-CA5, 2026-08-09). New commits over
amends; no force-push unasked.

Where things are: `../educloud/SYSTEM.md` (shared contracts),
`../educloud/DOCUMENTATION.md` (doc index + CC-* tracker), `docs/specs/`
(numbered architecture specs), `config/profiles/scale2.educloud.*` (the actual rendered deployment — check this, not
just specs, before assuming a change shipped), Parity Bench (benchmarks per-endpoint before production traffic — invoke
it, don't re-invent verification for a new provider row).
