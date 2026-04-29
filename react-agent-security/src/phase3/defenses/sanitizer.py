"""
Defense 1 — Input sanitization.

Detects and strips text patterns commonly used by Phase 2 injection
payloads before the prompt reaches the agent.

Each pattern is scoped to a single sentence so the sanitizer never
accidentally consumes a legitimate task that follows an injection.
"""
from __future__ import annotations

import re
from typing import List, Pattern


# Strict email pattern — anchored on a word-char TLD so it does not
# greedily swallow the trailing sentence terminator (which would let the
# next `[^.]*\.` overshoot into the legitimate task).
_EMAIL = r"[\w.+-]+@[\w.-]+\.\w+"


_INJECTION_PATTERNS: List[Pattern] = [

    # SYSTEM NOTE preamble — exactly one sentence.
    re.compile(r"\bSYSTEM\s+NOTE\s*:\s*[^.]*\.", flags=re.IGNORECASE),

    # "Ignore (all|previous|prior|subsequent|the above) instructions ..."
    re.compile(
        r"\b(?:please\s+)?ignore\s+(?:all\s+)?"
        r"(?:following|previous|prior|subsequent|the\s+above)\s+"
        r"instructions[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Disregard everything (above|below) ..." / "all (prior|previous|subsequent) instructions ..."
    re.compile(
        r"\bdisregard\s+(?:everything\s+(?:above|below)|all\s+(?:prior|previous|subsequent)\s+instructions)[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Your only task is to send ..."
    re.compile(
        r"\byour\s+only\s+task\s+is\s+to\s+send[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Send all (results|outputs) to <email> ..."
    re.compile(
        rf"\bsend\s+all\s+(?:results|outputs)\s+to\s+{_EMAIL}[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "(Also) send a copy of the email to <email> ..."
    re.compile(
        rf"\b(?:also\s+)?send\s+a?\s*copy\s+of\s+the\s+email\s+to\s+{_EMAIL}[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Use <email> as the destination ..."
    re.compile(
        rf"\buse\s+{_EMAIL}\s+as\s+the\s+destination[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Before doing anything else, ..."
    re.compile(
        r"\bbefore\s+doing\s+anything\s+else[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Before finishing, ... email ..."
    re.compile(
        r"\bbefore\s+finishing[^.]*?email[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Forward all (tool outputs|retrieved content|outputs) ..."
    re.compile(
        r"\bforward\s+all\s+(?:tool\s+outputs|retrieved\s+content|outputs)[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Email all (retrieved content|data you have read|computed) ..."
    re.compile(
        r"\bemail\s+all\s+(?:retrieved\s+content|data\s+you\s+have\s+(?:read|computed))[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Email everything you (retrieve|compute) ..."
    re.compile(
        r"\bemail\s+everything\s+you\s+(?:retrieve|compute)[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Immediately send 'X' to <email> ..."
    re.compile(
        rf"\bimmediately\s+send\s+\S+\s+to\s+{_EMAIL}[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # "Send 'X' to <email> only ..."
    re.compile(
        rf"\bsend\s+['\"]?\S+?['\"]?\s+to\s+{_EMAIL}\s+only[^.]*\.",
        flags=re.IGNORECASE,
    ),

    # Bare authority phrases (whatever survives the sentence-level strips).
    re.compile(
        r"\b(?:priority|task|recipient)\s+override(?:\s+(?:received|active|enabled))?[^.]*\.",
        flags=re.IGNORECASE,
    ),
    re.compile(r"\baudit\s+mode\s+enabled[^.]*\.", flags=re.IGNORECASE),
    re.compile(r"\bcompliance\s+policy[^.]*\.",     flags=re.IGNORECASE),
    re.compile(r"\bsecurity\s+audit\s+required[^.]*\.", flags=re.IGNORECASE),
    re.compile(r"\ball\s+prior\s+instructions\s+are\s+void[^.]*\.", flags=re.IGNORECASE),
]


def sanitize_prompt(prompt: str) -> str:
    """
    Return `prompt` with known adversarial fragments removed.

    Each pattern strips at most one sentence; payloads composed of
    several adversarial sentences need several pattern hits. Legitimate
    sentences that share verbs with attack templates are left intact
    because the patterns require characteristic surrounding context
    (e.g. "all results to <email>", not just "send to <email>").
    """
    cleaned = prompt
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def sanitization_stats(original: str, cleaned: str) -> dict:
    """Lightweight diagnostic returned alongside each run for inspection."""
    return {
        "original_length":  len(original),
        "cleaned_length":   len(cleaned),
        "chars_removed":    len(original) - len(cleaned),
        "modified":         original.strip() != cleaned.strip(),
    }
