# SPDX-License-Identifier: Apache-2.0
"""Finite synthetic notebook profile for the actual Belay planner/reasoner/evaluator.

Not a general classroom route. Operator supplies context generated from pinned
synthetic source, never browser input. Historical smoke profiles stay unchanged.
"""

from __future__ import annotations

import copy
import json

from openrouter_adapter import SmokeGuard, walkthrough_manifest
from pilot_ledger import Denied


def notebook_manifest():
    value = walkthrough_manifest()
    value["project"] = "notebook01"
    value["project_allowance"] = value["participant_allowance"] = 114688
    for model in value["models"].values():
        model.update(max_output_tokens=800, max_request_tokens=16384)
    return value


class NotebookGuard(SmokeGuard):
    """Only fixed context plus responses derived from this finite model session."""

    budget = 0.175
    request_limit = 7
    token_limit = 16384
    profile_manifest = staticmethod(notebook_manifest)
    stages = (
        "planner",
        "reasoner",
        "self_eval",
        "reasoner",
        "self_eval",
        "reasoner",
        "self_eval",
    )

    def __init__(self, directory, catalog, context, systems):
        self.context = copy.deepcopy(context)
        self.systems = copy.deepcopy(systems)
        if set(systems) != {"planner", "reasoner", "self_eval"}:
            raise ValueError("three exact pinned system prompts required")
        super().__init__(directory, catalog)

    def check_body(self, body):
        self.check()
        with self.lock:
            if any(a["state"] != "complete" for a in self.attempts.values()):
                raise Denied("notebook_unresolved_attempt")
            slot = len(self.attempts)
            if slot >= self.request_limit:
                raise Denied("notebook_request_limit")
            stage = self.stages[slot]
            expected = {
                "model",
                "messages",
                "max_tokens",
                "temperature",
                "response_format",
            }
            if (
                not isinstance(body, dict)
                or set(body) != expected
                or body["model"]
                != ("code_large" if stage == "reasoner" else "code_small")
                or body["max_tokens"] != (800 if stage == "reasoner" else 400)
                or body["temperature"] != 0.0
                or body["response_format"] != {"type": "json_object"}
            ):
                raise Denied("notebook_profile_required", 400)
            messages = body["messages"]
            if (
                not isinstance(messages, list)
                or len(messages) != 2
                or messages[0] != {"role": "system", "content": self.systems[stage]}
                or not isinstance(messages[1], dict)
                or set(messages[1]) != {"role", "content"}
                or messages[1]["role"] != "user"
                or not isinstance(messages[1]["content"], str)
                or len(messages[1]["content"].encode()) > 18000
            ):
                raise Denied("notebook_fixed_context_required", 400)
            user = messages[1]["content"]
            try:
                if stage == "planner":
                    valid = json.loads(user) == self.context
                elif stage == "reasoner":
                    head, tail = user.split("\n\nCHOSEN PLAN FOR THIS TURN:\n", 1)
                    plan, *critique = tail.split(
                        "\n\nSELF-EVALUATION ASKED YOU TO REVISE. "
                        "Address these and rewrite:\n"
                    )
                    valid = (
                        head.startswith("CONTEXT:\n")
                        and json.loads(head[len("CONTEXT:\n") :]) == self.context
                        and isinstance(json.loads(plan), dict)
                        and len(critique) <= 1
                        and all(isinstance(json.loads(c), dict) for c in critique)
                    )
                else:
                    value = json.loads(user)
                    valid = (
                        set(value)
                        == {"exercise", "student_state", "chosen_plan", "sol_draft"}
                        and value["exercise"] == self.context["exercise"]
                        and value["student_state"]
                        == {
                            k: self.context[k]
                            for k in (
                                "current_functional_model",
                                "last_result",
                                "attempt_signals",
                            )
                        }
                        and isinstance(value["chosen_plan"], dict)
                        and isinstance(value["sol_draft"], dict)
                    )
            except (ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                raise Denied("notebook_fixed_context_required", 400)
            return f"{slot + 1:02d}-{stage}"
