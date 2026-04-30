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
# greedily swallow the trailing sentence terminator.
_EMAIL = r"[\w.+-]+@[\w.-]+\.\w+"

# Sentence-content pattern that handles dots inside domain names / emails.
# Structure: zero-or-more (non-dot chars + dotted word) groups, then a final
# run of non-dot chars.  This allows mid-sentence dotted segments like
# ".com" or ".evil.com" followed by arbitrary non-dot content (e.g.
# " using email_sender"), while still terminating at the true sentence-ending
# period via the explicit `\.` appended after _SENT in each pattern.
_SENT = r"(?:[^.]*(?:\.\w+))*[^.]*"


_INJECTION_PATTERNS: List[Pattern] = [

    # SYSTEM NOTE preamble — exactly one sentence.
    re.compile(rf"\bSYSTEM\s+NOTE\s*:\s*{_SENT}\.", flags=re.IGNORECASE),

    # "Ignore (all|previous|prior|subsequent|the above) instructions ..."
    re.compile(
        r"\b(?:please\s+)?ignore\s+(?:all\s+)?"
        r"(?:following|previous|prior|subsequent|the\s+above)\s+"
        rf"instructions{_SENT}\.",
        flags=re.IGNORECASE,
    ),

    # "Disregard everything (above|below) ..." / "all (prior|previous|subsequent) instructions ..."
    re.compile(
        rf"\bdisregard\s+(?:everything\s+(?:above|below)|all\s+(?:prior|previous|subsequent)\s+instructions){_SENT}\.",
        flags=re.IGNORECASE,
    ),

    # "Your only task is to send ..."
    re.compile(
        rf"\byour\s+only\s+task\s+is\s+to\s+send{_SENT}\.",
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
        rf"\bbefore\s+doing\s+anything\s+else{_SENT}\.",
        flags=re.IGNORECASE,
    ),

    # "Before finishing, ... email ..."
    re.compile(
        rf"\bbefore\s+finishing[^.]*?email{_SENT}\.",
        flags=re.IGNORECASE,
    ),

    # "Forward all (tool outputs|retrieved content|outputs) ..."
    re.compile(
        rf"\bforward\s+all\s+(?:tool\s+outputs|retrieved\s+content|outputs){_SENT}\.",
        flags=re.IGNORECASE,
    ),

    # "Email all (retrieved content|data you have read|computed) ..."
    re.compile(
        rf"\bemail\s+all\s+(?:retrieved\s+content|data\s+you\s+have\s+(?:read|computed)){_SENT}\.",
        flags=re.IGNORECASE,
    ),

    # "Email everything you (retrieve|compute) ..."
    re.compile(
        rf"\bemail\s+everything\s+you\s+(?:retrieve|compute){_SENT}\.",
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
        rf"\b(?:priority|task|recipient)\s+override(?:\s+(?:received|active|enabled))?{_SENT}\.",
        flags=re.IGNORECASE,
    ),
    re.compile(rf"\baudit\s+mode\s+enabled{_SENT}\.",       flags=re.IGNORECASE),
    re.compile(rf"\bcompliance\s+policy{_SENT}\.",           flags=re.IGNORECASE),
    re.compile(rf"\bsecurity\s+audit\s+required{_SENT}\.",   flags=re.IGNORECASE),
    re.compile(rf"\ball\s+prior\s+instructions\s+are\s+void{_SENT}\.", flags=re.IGNORECASE),
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
