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

from src.phase3.defenses.audit import audit_post_run
from src.phase3.defenses.goal_verifier import make_goal_verified_email_sender
from src.phase3.defenses.grounding import grounded_system_prompt
from src.phase3.defenses.recipient_lock import make_recipient_locked_email_sender
from src.phase3.defenses.sanitizer import sanitize_prompt


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


def _wrap_combined(tools: List[Any], task_spec: TaskSpec) -> List[Any]:
    """
    For the all_combined defense, recipient_locking and goal_verification both
    wrap email_sender. Compose them: the recipient lock runs first (it pins
    the destination), then the goal verifier validates the body.
    """
    out = _wrap_recipient_lock(tools, task_spec)
    out = _wrap_goal_verifier(out, task_spec)
    return out


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
