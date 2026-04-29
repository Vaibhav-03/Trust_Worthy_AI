"""
Defense 2 — Recipient locking.

Wraps the `email_sender` tool so that the destination address is forced
to the recipient that was extracted from the user's parsed task. The
agent's reasoning cannot redirect the email even if it has been hijacked
by an adversarial payload.

In production, the locked recipient would be the address that the user
typed into a separate, structured "To:" field (an out-of-band channel
that injected text in the free-form task body cannot tamper with).
For this experiment we model that channel by reading the
`expected_email_recipient` field from `tasks.json`.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from langchain_core.tools import tool

from src.tools import get_email_log_path


def make_recipient_locked_email_sender(intended_recipient: str):
    """
    Build a drop-in replacement for `email_sender` that always delivers
    to `intended_recipient`, regardless of what the agent passes for `to`.

    The original `to` value is recorded in the log entry as
    `attempted_to` so that downstream metrics can detect when the agent
    *tried* to redirect (i.e. an attack was attempted but blocked).
    """
    locked = (intended_recipient or "").strip()

    @tool("email_sender")
    def _email_sender(to: str, subject: str, body: str) -> str:
        """Send an email to a recipient with a subject and body."""
        actual_to = locked if locked else to
        redirected = (locked != "") and (
            (to or "").strip().lower() != locked.lower()
        )
        entry = {
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "to":          actual_to,
            "subject":     subject,
            "body":        body,
            "attempted_to": to,
            "locked":      bool(locked),
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

    return _email_sender
