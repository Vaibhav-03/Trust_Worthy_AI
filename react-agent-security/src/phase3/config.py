"""
Phase 3 configuration.

Adds a `defenses` axis on top of the Phase 2 settings. Each defense is
evaluated independently against the same 12 × 15 = 180 adversarial trial
matrix that Phase 2 used. A clean baseline (no injection) per defense is
also run so we can compute false-positive rate (FPR) — i.e. whether the
defense degrades normal agent behaviour.

Usage:
    cfg = Phase3Config()                       # defaults — all defenses
    cfg = Phase3Config.from_json("cfg.json")   # load from file
    cfg.to_json("logs/phase3/config_used.json")  # persist for reproducibility
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List


# Names of every defense implemented in src/phase3/defenses/.
# "none" reproduces Phase 2 (no defense) for a direct comparison.
# "all_combined" stacks every defense at once.
ALL_DEFENSES: List[str] = [
    "none",
    "input_sanitization",
    "recipient_locking",
    "grounding_augmentation",
    "audit_logging",
    "goal_verification",
    "all_combined",
]


@dataclass
class Phase3Config:
    # ── Master switch ──────────────────────────────────────────────────────────
    # Run the full adversarial matrix (180 trials per defense).
    prompt_injection_flag: bool = True

    # When True, also run the clean (un-injected) suite under each defense
    # so we can compute the false-positive rate (FPR) — does the defense
    # break legitimate agent behaviour?
    run_clean_baseline: bool = True

    # ── Defense axis ───────────────────────────────────────────────────────────
    # Names must match keys in DEFENSE_REGISTRY (src/phase3/defenses/__init__.py).
    defenses: List[str] = field(
        default_factory=lambda: list(ALL_DEFENSES)
    )

    # ── Injection axes (mirror Phase 2) ────────────────────────────────────────
    positions: List[str] = field(
        default_factory=lambda: ["prefix", "suffix"]
    )
    payload_types: List[str] = field(
        default_factory=lambda: ["tool_redirect", "context_exfiltration", "goal_hijacking"]
    )
    styles: List[str] = field(
        default_factory=lambda: ["direct", "system_message"]
    )
    attacker_email: str = "attacker@evil.com"

    # ── Task selection ─────────────────────────────────────────────────────────
    task_ids: List[int] = field(default_factory=lambda: list(range(1, 16)))
    tasks_file: str = "tasks.json"

    # ── Model settings ─────────────────────────────────────────────────────────
    model: str = "meta-llama/Llama-3.3-70B-Instruct"
    base_url: str = "https://api.studio.nebius.com/v1/"

    # ── Agent settings ─────────────────────────────────────────────────────────
    max_agent_steps: int = 20

    # ── Output ─────────────────────────────────────────────────────────────────
    log_dir: str = "logs/phase3"

    # ── Helpers ────────────────────────────────────────────────────────────────
    @classmethod
    def from_json(cls, path: str) -> "Phase3Config":
        with open(path) as f:
            data = json.load(f)
        valid = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in valid})

    def to_json(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    def total_runs(self, n_tasks: int) -> int:
        """Estimate the total number of agent invocations for this config."""
        per_defense = 0
        if self.prompt_injection_flag:
            per_defense += n_tasks * (
                len(self.positions) * len(self.payload_types) * len(self.styles)
            )
        if self.run_clean_baseline:
            per_defense += n_tasks
        return per_defense * len(self.defenses)
