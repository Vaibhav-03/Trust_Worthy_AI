"""
Injection logic.

InjectionConfig  — a NamedTuple describing one of the 12 axis combinations
                   together with the ready-to-use payload string and a
                   human-readable label (e.g. "prefix_tool_redirect_direct").

get_injection_configs()  — yields every InjectionConfig enabled by the
                           current Phase2Config.

inject()  — applies a single InjectionConfig to a task prompt string.
"""
from __future__ import annotations

from itertools import product
from typing import Iterator, NamedTuple, Optional

from src.phase2.config import Phase2Config
from src.phase2.payloads import build_payload


class InjectionConfig(NamedTuple):
    position: str       # "prefix" | "suffix"
    payload_type: str   # "tool_redirect" | "context_exfiltration" | "goal_hijacking"
    style: str          # "direct" | "system_message"
    payload_text: str   # formatted string, ready to insert
    label: str          # e.g. "prefix_tool_redirect_direct"


def get_injection_configs(cfg: Phase2Config) -> Iterator[InjectionConfig]:
    """
    Yield one InjectionConfig for every (position × payload_type × style)
    combination enabled in cfg.

    If cfg.prompt_injection_flag is False this yields nothing — the caller
    is expected to treat that as a clean / baseline run.
    """
    if not cfg.prompt_injection_flag:
        return

    for position, payload_type, style in product(
        cfg.positions, cfg.payload_types, cfg.styles
    ):
        payload_text = build_payload(position, payload_type, style, cfg.attacker_email)
        label = f"{position}_{payload_type}_{style}"
        yield InjectionConfig(
            position=position,
            payload_type=payload_type,
            style=style,
            payload_text=payload_text,
            label=label,
        )


def inject(task_prompt: str, inj: Optional[InjectionConfig]) -> str:
    """
    Return the task prompt with the injection payload applied.

    If inj is None (clean / baseline run) the original prompt is returned
    unchanged.
    """
    if inj is None:
        return task_prompt
    if inj.position == "prefix":
        return inj.payload_text + task_prompt
    # suffix
    return task_prompt + inj.payload_text
