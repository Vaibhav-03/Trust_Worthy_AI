"""
Phase 2 configuration.

All experiment settings live here. Override via JSON file or CLI flags —
nothing in the evaluation logic is hard-coded.

Usage:
    cfg = Phase2Config()                      # defaults
    cfg = Phase2Config.from_json("cfg.json")  # load from file
    cfg.to_json("logs/phase2/config_used.json")  # persist for reproducibility
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List


@dataclass
class Phase2Config:
    # ── Master switch ──────────────────────────────────────────────────────────
    # Set to False to run a clean baseline (no injection) for comparison.
    prompt_injection_flag: bool = True

    # ── Injection axes ─────────────────────────────────────────────────────────
    # Narrow these lists to run a subset of the 2×3×2 = 12 combinations.
    positions: List[str] = field(
        default_factory=lambda: ["prefix", "suffix"]
    )
    payload_types: List[str] = field(
        default_factory=lambda: ["tool_redirect", "context_exfiltration", "goal_hijacking"]
    )
    styles: List[str] = field(
        default_factory=lambda: ["direct", "system_message"]
    )

    # ── Attacker-controlled values injected into payload templates ─────────────
    attacker_email: str = "attacker@evil.com"

    # ── Task selection ─────────────────────────────────────────────────────────
    # Leave empty to run all tasks in tasks_file.
    task_ids: List[int] = field(default_factory=lambda: list(range(1, 16)))
    tasks_file: str = "tasks.json"

    # ── Agent settings ─────────────────────────────────────────────────────────
    # LangGraph recursion limit (caps the ReAct loop depth per run).
    max_agent_steps: int = 20

    # ── Output ─────────────────────────────────────────────────────────────────
    log_dir: str = "logs/phase2"

    # ── Helpers ────────────────────────────────────────────────────────────────
    @classmethod
    def from_json(cls, path: str) -> Phase2Config:
        """Load config from a JSON file. Unknown keys are silently ignored."""
        with open(path) as f:
            data = json.load(f)
        valid = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in valid})

    def to_json(self, path: str) -> None:
        """Persist config so runs are reproducible."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    def active_combination_count(self) -> int:
        """Number of injection configs that will be generated."""
        if not self.prompt_injection_flag:
            return 1  # clean baseline only
        return len(self.positions) * len(self.payload_types) * len(self.styles)
