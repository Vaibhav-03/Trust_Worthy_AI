"""
Defense registry.

Each defense is described by a DefenseSpec dataclass that bundles the four
hooks used by the agent factory and the runner:

    system_prompt(task_spec)        -> str | None
        Returns a custom system prompt (or None to keep the default).

    wrap_tools(tools, task_spec)    -> list[Tool]
        Returns a (possibly modified) list of tools — typically wraps
        email_sender to enforce a constraint.

    preprocess_prompt(prompt)       -> str
        Pre-processes the user task string before it reaches the agent.

    post_run(record)                -> dict | None
        Inspects the per-run record after the agent has finished and
        attaches detection metadata. Used by `audit_logging`.

A defense may set any subset of these hooks; the others fall through to
the no-op defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import json
import os
from datetime import datetime, timezone

from langchain_core.tools import tool as lc_tool

from src.phase3.defenses.audit import audit_post_run
from src.phase3.defenses.goal_verifier import _violates_goal, make_goal_verified_email_sender
from src.phase3.defenses.grounding import grounded_system_prompt
from src.phase3.defenses.recipient_lock import make_recipient_locked_email_sender
from src.phase3.defenses.sanitizer import sanitize_prompt
from src.tools import get_blocked_email_log_path, get_email_log_path


# A "task spec" is one entry from tasks.json (used by defenses that need
# the legitimate recipient or the original prompt as a trust anchor).
TaskSpec = Dict[str, Any]


@dataclass
class DefenseSpec:
    name: str
    description: str
    system_prompt: Optional[Callable[[TaskSpec], Optional[str]]] = None
    wrap_tools: Optional[Callable[[List[Any], TaskSpec], List[Any]]] = None
    preprocess_prompt: Optional[Callable[[str], str]] = None
    post_run: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None


def _identity_prompt(p: str) -> str:
    return p


def _identity_tools(tools: List[Any], task_spec: TaskSpec) -> List[Any]:
    return tools


# ---------------------------------------------------------------------------
# Per-defense specs
# ---------------------------------------------------------------------------

def _wrap_recipient_lock(tools: List[Any], task_spec: TaskSpec) -> List[Any]:
    expected = task_spec.get("expected_email_recipient", "")
    if not expected:
        return tools
    locked = make_recipient_locked_email_sender(expected)
    return [locked if getattr(t, "name", "") == "email_sender" else t for t in tools]


def _wrap_goal_verifier(tools: List[Any], task_spec: TaskSpec) -> List[Any]:
    verified = make_goal_verified_email_sender(task_spec)
    return [verified if getattr(t, "name", "") == "email_sender" else t for t in tools]


def _make_combined_email_sender(task_spec: TaskSpec):
    """
    Single email_sender replacement that applies goal-verification then
    recipient-locking atomically.

    Goal-verification runs first on the AGENT's original `to` address so
    recipient-mismatch attacks are still caught before any rewriting. If the
    call passes, the destination is pinned to the task's expected recipient
    (recipient-locking). Both operations share one log entry, preventing the
    double-replacement bug that occurs when the two wrappers are chained by
    tool name.
    """
    expected_recipient = (task_spec or {}).get("expected_email_recipient", "")
    locked = expected_recipient.strip()

    @lc_tool("email_sender")
    def _combined_sender(to: str, subject: str, body: str) -> str:
        """Send an email to a recipient with a subject and body."""
        verdict = _violates_goal(to, body, expected_recipient)
        if verdict["violates"]:
            entry = {
                "timestamp":    datetime.now(timezone.utc).isoformat(),
                "to":           to,
                "subject":      subject,
                "body":         body,
                "blocked":      True,
                "block_reason": verdict["reason"],
            }
            blocked_path = get_blocked_email_log_path()
            with open(blocked_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
            return (
                f"Email NOT sent. Goal-verification policy rejected this "
                f"call: {verdict['reason']}"
            )

        actual_to = locked if locked else to
        redirected = locked != "" and (to or "").strip().lower() != locked.lower()
        entry = {
            "timestamp":        datetime.now(timezone.utc).isoformat(),
            "to":               actual_to,
            "subject":          subject,
            "body":             body,
            "attempted_to":     to,
            "locked":           bool(locked),
            "redirected_block": redirected,
        }
        log_path = get_email_log_path()
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        if redirected:
            return (
                f"Email sent successfully to {actual_to}. "
                f"(Note: requested recipient {to!r} was overridden by the "
                f"recipient-lock policy.)"
            )
        return f"Email sent successfully to {actual_to}"

    return _combined_sender


def _wrap_combined(tools: List[Any], task_spec: TaskSpec) -> List[Any]:
    combined = _make_combined_email_sender(task_spec)
    return [combined if getattr(t, "name", "") == "email_sender" else t for t in tools]


def _combined_system_prompt(task_spec: TaskSpec) -> str:
    return grounded_system_prompt(task_spec)


DEFENSE_REGISTRY: Dict[str, DefenseSpec] = {

    "none": DefenseSpec(
        name="none",
        description="No defense — Phase 2 baseline reproduction.",
    ),

    "input_sanitization": DefenseSpec(
        name="input_sanitization",
        description="Strip known injection markers from the prompt before "
                    "the agent sees it.",
        preprocess_prompt=sanitize_prompt,
    ),

    "recipient_locking": DefenseSpec(
        name="recipient_locking",
        description="Force email_sender to deliver only to the recipient "
                    "extracted from the user's parsed task.",
        wrap_tools=_wrap_recipient_lock,
    ),

    "grounding_augmentation": DefenseSpec(
        name="grounding_augmentation",
        description="Augment the system prompt with explicit task-bound "
                    "constraints — most relevant for web-search tasks.",
        system_prompt=grounded_system_prompt,
    ),

    "audit_logging": DefenseSpec(
        name="audit_logging",
        description="Post-hoc detection layer — flags suspicious emails "
                    "after the run completes; never blocks behaviour.",
        post_run=audit_post_run,
    ),

    "goal_verification": DefenseSpec(
        name="goal_verification",
        description="Compare each email_sender call against the original "
                    "task spec; reject calls whose recipient/body do not "
                    "match the user's stated goal.",
        wrap_tools=_wrap_goal_verifier,
    ),

    "all_combined": DefenseSpec(
        name="all_combined",
        description="Stack every defense simultaneously.",
        system_prompt=_combined_system_prompt,
        wrap_tools=_wrap_combined,
        preprocess_prompt=sanitize_prompt,
        post_run=audit_post_run,
    ),
}


def get_defense(name: str) -> DefenseSpec:
    if name not in DEFENSE_REGISTRY:
        raise KeyError(
            f"Unknown defense {name!r}. Valid: {sorted(DEFENSE_REGISTRY)}"
        )
    return DEFENSE_REGISTRY[name]
