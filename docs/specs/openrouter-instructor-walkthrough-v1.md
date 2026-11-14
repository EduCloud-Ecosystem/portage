# OpenRouter instructor tier walkthrough v1

Approved next slice: local synthetic instructor walkthrough of both Belay tutor
tiers through Portage. This is a provider integration console, not the ordinary
classroom UI, an enrollment implementation, or instructional acceptance.

## Ownership and reuse

Portage worktree: ../portage-system-one-shadow-pilot-v1, branch
codex/openrouter-instructor-walkthrough-v1, base
af40ab0501bb9f8283efa0d7ef0aa546b06c3851. Initially clean.
Belay-classroom remains unchanged at c5a27073e74b9eeb7ab697190915378b50132883
in ../belay-classroom-system-one-consumer-v1. Its actual PortageProvider and
enforced accounting are reused. Original Belay, historical classroom presenter,
Cairn, Waypoint, Outfitter and research worktrees are outside permitted edits.

Reuse the one-shot gateway's durable request claims, transport deadlines,
membership checks, unknown-usage holds and credential loader. Add a separate
profile; retain the original four-case harness and all its evidence unchanged.
Both aliases initially use the same verified OpenRouter endpoint. Strong is a
routing alias here, not evidence of stronger reasoning or a model comparison.

## Finite scope before implementation

1. Add a separate two-case profile and local instructor console. Only the two
   source-defined synthetic lesson prompts may leave the machine. Browser input
   selects a tier; it cannot supply prompts, identities, endpoints or credentials.
2. Reuse the unchanged Belay provider with an explicitly synthetic identity,
   isolated ledger, single serialized execution and zero SDK retries.
3. Verify request tampering, duplicate clicks, revocation, expiry, unknown usage,
   correct tier mapping, retained failures and browser layout/interaction.
4. After offline checks, at most two actual inference requests in one ten-minute
   window, total application reserve USD 0.025, max output 128 tokens/request,
   max total 2048 tokens/request. Fresh provider metadata must pass existing
   canonical endpoint/price checks. Stop after any failure; no replacement run.
   Earlier USD 0.025 unknown holds remain separate and unresolved.

No general free-text chat, student data, private course artifacts, new authority,
cloud resources, production changes, colony agents or comparison runs. Current
route has no established ZDR support; this profile is synthetic-only. Account
settings remain unchanged. Provider-reported usage is not an independent audit.

## Acceptance and next integration boundary

Both buttons must invoke actual Belay fast/strong mapping through authenticated
Portage HTTP, return structured lesson hints and settle their isolated ledgers.
The page must label the shared model and synthetic scope, show evidence status,
prevent duplicate execution and display failures without exposing secrets.
Refresh must display existing results without another inference request.
Stop and absolute expiry must prevent new calls and close owned listeners.

The frozen legacy classroom presenter uses edu:2 identities; the provider requires
canonical opaque subjects. Do not translate or invent a real identity to bypass
this boundary. Full classroom walkthrough still requires migrating the actual
presenter onto the existing native enrollment flow and a separately pinned
runner/admission envelope. This slice does not complete that migration.

## Checkpoint

Preparation recorded before implementation. Source checks, live results and
browser inspection will be recorded below, including failures and unavailable
checks. No live request has been made under this new profile yet.

## Reproduction

The console imports the pinned Belay backend; Portage itself remains standard
library only. Use Python 3.12.13 and the Belay backend dependency lock at the pin
above. No new dependencies were installed for this slice. The existing installed
Belay environment is identified by the previous capture; clean-environment
reconstruction has not been re-run here.

Offline checks (no key or model calls):

```sh
uv run pytest -ra
OPENROUTER_TEST_BELAY_SOURCE=/absolute/path/to/pinned/belay-classroom \
  /absolute/path/to/pinned/belay-classroom/.venv/bin/python -m pytest \
  tests/test_instructor_walkthrough.py -k 'actual_belay or reformat' -ra
```

The following is an explicit billable synthetic session, not an ordinary test.
Run from the clean, committed Portage worktree, only with a fresh finite session
allocation. A new output directory means a new budget, never a reset of an old
session. Refreshing the console never replays either case. Do not automatically
restart this command after expiry, failure or process termination.

```sh
/Users/gregchism/dev/.educloud-worktrees/belay-classroom-system-one-consumer-v1/.venv/bin/python \
  integrations/ai_pilot/instructor_walkthrough.py \
  --env-file .qualification/openrouter/.env \
  --output .qualification/openrouter/evidence/instructor-01 \
  --belay-source /Users/gregchism/dev/.educloud-worktrees/belay-classroom-system-one-consumer-v1 \
  --execute-approved
```

Open the printed loopback URL. Review the synthetic prompts, ask each tutor once,
refresh the evidence, revoke synthetic membership, then stop. The final
result.json records listener shutdown. The journal and upstream responses remain
in the output directory along with separate Belay and Portage ledgers. Model
quality is a human-review item; the executable evaluator checks structure and
accounting only. Refused JSON-repair calls are included in Belay attempt counts
but must not create another external transport request.

## Verified checkpoint

Implementation source: 11bf330995af6b1a570c5501d0c616a2cd391f1a. Belay source
remains c5a27073e74b9eeb7ab697190915378b50132883 and clean. No application source
outside this Portage branch changed. No merge, deployment or CI result is claimed.

Full offline suite: 572 passed, 8 skipped (six missing sibling verifier-contract
cases and two separately run Belay SDK cases). The final added JSON-repair test
was subsequently run with the actual Belay environment; all three SDK checks
passed. Final focused suite: 10 passed, two environment skips covered separately.
Lint, format, diff check and all three generated profile checks passed.
Two initial assertions expected 403; the retained unknown ledger concurrency
hold correctly returned 429 instead. These failed controls and initial lint
outputs remain in .qualification/openrouter/walkthrough-validation/.

Live browser session: .qualification/openrouter/evidence/instructor-01/.
Both fast and strong actions succeeded: two actual external dispatches, zero SDK
retries, 229 tokens, USD 0.0001864 provider-reported cost. Portage independently
read back code_small/120 and code_large/109 as complete; Belay has two settled
attempts totaling 229 tokens. Belay's policy-priced 308 microunits is a local
accounting estimate, not the provider's invoice. No new unknown liability;
earlier USD 0.025 unknown reservations remain unresolved and untouched.

Rendered desktop layout, actions, disabled consumed buttons, refresh, full-page
reload, revocation and stop were observed through the in-app browser. Chrome
extension tab creation failed twice before any model action; in-app fallback
worked. Mobile layout was not independently inspected. The process exited zero,
result.json records owned_servers_closed=true, and the console port refused a
fresh connection. No services remain running from this session.

Instructional acceptance remains pending. In particular, the second hint's
row-count comparison needs an expected expansion count for a wide-to-long
transformation, and checking only the resulting missing values cannot prove
preservation. This is retained as a quality-review finding, not reclassified as
a transport failure or repaired by spending on another call.

Next concrete application work: migrate the existing classroom presenter onto
its canonical enrollment path and a pinned runner/admission envelope, preserving
saved-file submission and Cairn grading authority. Then verify the actual
notebook -> tutor -> saved-file submission -> receipt journey. This new console
proves the two provider tier seams; it does not complete that classroom journey.
Fresh environment reconstruction, instructional review, approved destinations
and retention, institutional login/hosting, and real-learner authorization remain
separate gates. Do not auto-restart the completed paid walkthrough.
