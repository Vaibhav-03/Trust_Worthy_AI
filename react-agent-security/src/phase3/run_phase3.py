"""
Phase 3 — Defended ReAct Agent Evaluation
==========================================

Re-runs the Phase 2 adversarial matrix (12 injection configs × 15 tasks
= 180 trials) against each defense in `Phase3Config.defenses`, plus
(optionally) a clean baseline of 15 trials per defense for measuring
false-positive rate.

For every trial we record:

    ASR   — Attack Success Rate         (Phase 2 metric, injected only)
    TCDR  — Tool Call Deviation Rate    (Phase 2 metric)
    TCR   — Task Completion Rate        (Phase 2 metric)
    FPR   — False-Positive Rate         (clean-suite TCR < 1.0 fraction)
    DR    — Detection Rate              (audit-flagged fraction; only
                                         meaningful for defenses that
                                         include the audit_logging hook)

Usage
-----
# All defenses, full 12 × 15 matrix per defense + clean baseline:
    python -m src.phase3.run_phase3

# Single defense:
    python -m src.phase3.run_phase3 --defenses recipient_locking

# Skip the clean baseline (faster, no FPR):
    python -m src.phase3.run_phase3 --no-clean

# Restrict tasks / axes for a smoke test:
    python -m src.phase3.run_phase3 \\
        --defenses input_sanitization \\
        --task-ids 1 5 \\
        --positions prefix \\
        --payload-types tool_redirect \\
        --styles direct

Output
------
logs/phase3/results_<timestamp>.json   — all per-run records + aggregate summary
logs/phase3/config_<timestamp>.json    — config snapshot (reproducibility)
logs/sent_emails.jsonl                 — shared email audit log (appended)
logs/blocked_emails.jsonl              — emails refused by goal_verification
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# Allow `python -m src.phase3.run_phase3` from project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from src.phase2.injector import InjectionConfig, get_injection_configs, inject  # noqa: E402
from src.phase2.config import Phase2Config  # noqa: E402  used to build injector configs
from src.phase3.agent_factory import build_defended_agent  # noqa: E402
from src.phase3.config import Phase3Config  # noqa: E402
from src.phase3.evaluator import (  # noqa: E402
    aggregate_phase3,
    count_email_lines,
    detect_exfiltration,
    get_run_emails,
)
from src.phase3.metrics import (  # noqa: E402
    compute_asr,
    compute_tcdr,
    compute_tcr,
    unexpected_tools,
)
from src.tools import get_email_log_path  # noqa: E402

# Hard wall-clock timeout per agent.invoke(). Hung Tavily/Nebius calls
# (observed once with no recovery for 8 hours) get killed so the sweep
# can move on. Override via PHASE3_TRIAL_TIMEOUT env var.
_TRIAL_TIMEOUT_S = int(os.environ.get("PHASE3_TRIAL_TIMEOUT", "180"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _load_tasks(tasks_file: str, task_ids: List[int]) -> List[Dict]:
    path = os.path.join(_project_root(), tasks_file)
    with open(path) as f:
        all_tasks = json.load(f)
    if task_ids:
        id_set = set(task_ids)
        return [t for t in all_tasks if t["task_id"] in id_set]
    return all_tasks


def _extract_tool_calls_and_answer(messages: list) -> Dict[str, Any]:
    tool_calls: List[str] = []
    final_answer = ""
    for msg in messages:
        if getattr(msg, "type", "") == "ai":
            calls = getattr(msg, "tool_calls", None) or []
            for tc in calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name:
                    tool_calls.append(name)
            if not calls:
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content:
                    final_answer = content
    return {"tool_calls": tool_calls, "final_answer": final_answer}


def _call_with_timeout(fn: Callable[[], Any], timeout_s: int) -> Any:
    """
    Run `fn` in a daemon thread; raise TimeoutError if it does not
    return within `timeout_s` seconds. The daemon thread is left to
    leak — better than hanging the entire sweep on a stuck HTTP call.
    """
    box: Dict[str, Any] = {"value": None, "error": None}

    def _target():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 — surface to main thread
            box["error"] = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(
            f"Agent invocation exceeded {timeout_s}s wall-clock budget."
        )
    if box["error"] is not None:
        raise box["error"]
    return box["value"]


def _run_agent_once(prompt: str, agent, max_steps: int) -> Dict[str, Any]:
    def _invoke():
        return agent.invoke(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": max_steps},
        )
    result = _call_with_timeout(_invoke, _TRIAL_TIMEOUT_S)
    return _extract_tool_calls_and_answer(result.get("messages", []))


def _build_injection_configs(cfg: Phase3Config) -> List[InjectionConfig]:
    """
    Phase 3 reuses the Phase 2 injector. Build a Phase2Config snapshot so
    the existing get_injection_configs() helper produces our 12 configs.
    """
    p2 = Phase2Config(
        prompt_injection_flag=True,
        positions=list(cfg.positions),
        payload_types=list(cfg.payload_types),
        styles=list(cfg.styles),
        attacker_email=cfg.attacker_email,
    )
    return list(get_injection_configs(p2))


# ---------------------------------------------------------------------------
# Per-run executor
# ---------------------------------------------------------------------------

def _execute_trial(
    *,
    defense_name: str,
    task: Dict[str, Any],
    inj: Optional[InjectionConfig],
    cfg: Phase3Config,
    email_log_path: str,
    run_num: int,
    total_runs: int,
) -> Dict[str, Any]:
    """
    Build a fresh defended agent for the (defense, task) pair, run it
    once on the (possibly injected) prompt, and return a per-run record.
    """
    agent, defense = build_defended_agent(defense_name, task)

    # Injection then preprocessing — sanitization runs after the injector
    # so it gets a chance to strip the attack.
    raw_prompt = inject(task["prompt"], inj)
    if defense.preprocess_prompt is not None:
        prompt_for_agent = defense.preprocess_prompt(raw_prompt)
    else:
        prompt_for_agent = raw_prompt

    label = inj.label if inj else "clean"
    _print_run_header(run_num, total_runs, defense_name, task["task_id"], label, prompt_for_agent)

    emails_before = count_email_lines(email_log_path)
    run_ts = datetime.now(timezone.utc).isoformat()
    error: Optional[str] = None
    try:
        outcome = _run_agent_once(prompt_for_agent, agent, cfg.max_agent_steps)
    except Exception as exc:
        outcome = {"tool_calls": [], "final_answer": ""}
        error = str(exc)
        print(f"  ERROR: {exc}")

    run_emails = get_run_emails(emails_before, email_log_path)
    exfil = detect_exfiltration(emails_before, email_log_path, cfg.attacker_email)

    expected_tools = task.get("expected_tools", [])
    expected_recipient = task.get("expected_email_recipient", "")
    actual_tools = outcome["tool_calls"]

    asr = compute_asr(
        inj.payload_type if inj else None,
        exfil,
        cfg.attacker_email,
    )
    tcdr = compute_tcdr(actual_tools, expected_tools)
    tcr = compute_tcr(actual_tools, expected_tools, run_emails, expected_recipient)

    record: Dict[str, Any] = {
        "run_id":             run_num,
        "timestamp":          run_ts,
        "defense":            defense_name,
        # Task info
        "task_id":            task["task_id"],
        "task_category":      task.get("category", ""),
        "original_prompt":    task["prompt"],
        "expected_tools":     expected_tools,
        "expected_recipient": expected_recipient,
        # Injection info
        "injection_label":      label,
        "injection_position":   inj.position if inj else None,
        "injection_payload_type": inj.payload_type if inj else None,
        "injection_style":      inj.style if inj else None,
        "raw_prompt":           raw_prompt,
        "prompt_after_defense": prompt_for_agent,
        "prompt_modified":      raw_prompt != prompt_for_agent,
        # Outcome
        "actual_tools":      actual_tools,
        "unexpected_tools":  unexpected_tools(actual_tools, expected_tools),
        "final_answer":      outcome["final_answer"],
        # Metrics
        "asr":  asr,
        "tcdr": tcdr,
        "tcr":  tcr,
        # Supporting evidence
        "exfiltration": exfil,
        "run_emails":   run_emails,
        "error":        error,
    }

    # Apply post-run defense hooks (currently used by audit_logging).
    if defense.post_run is not None:
        record = defense.post_run(record)

    _print_run_result(expected_tools, actual_tools, asr, tcdr, tcr, exfil, record.get("audit"))
    return record


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def run_phase3(cfg: Phase3Config) -> None:
    root = _project_root()
    log_dir = os.path.join(root, cfg.log_dir)
    os.makedirs(log_dir, exist_ok=True)

    email_log_path = get_email_log_path()
    tasks = _load_tasks(cfg.tasks_file, cfg.task_ids)

    injection_configs = _build_injection_configs(cfg) if cfg.prompt_injection_flag else []
    trial_modes: List[Optional[InjectionConfig]] = list(injection_configs)
    if cfg.run_clean_baseline:
        trial_modes.append(None)  # clean run sentinel

    total_runs = len(tasks) * len(trial_modes) * len(cfg.defenses)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    _print_header(cfg, tasks, injection_configs, total_runs)
    cfg.to_json(os.path.join(log_dir, f"config_{ts}.json"))

    all_results: List[Dict[str, Any]] = []
    run_num = 0

    for defense_name in cfg.defenses:
        print(f"\n{'#' * 62}\n# Defense: {defense_name}\n{'#' * 62}")
        for task in tasks:
            for inj in trial_modes:
                run_num += 1
                record = _execute_trial(
                    defense_name=defense_name,
                    task=task,
                    inj=inj,
                    cfg=cfg,
                    email_log_path=email_log_path,
                    run_num=run_num,
                    total_runs=total_runs,
                )
                all_results.append(record)

    summary = aggregate_phase3(all_results)
    output = {
        "meta": {
            "timestamp":              ts,
            "total_runs":             total_runs,
            "prompt_injection_flag":  cfg.prompt_injection_flag,
            "run_clean_baseline":     cfg.run_clean_baseline,
        },
        "config": {
            "defenses":      cfg.defenses,
            "positions":     cfg.positions,
            "payload_types": cfg.payload_types,
            "styles":        cfg.styles,
            "attacker_email": cfg.attacker_email,
            "task_ids":      cfg.task_ids,
        },
        "summary": summary,
        "runs":    all_results,
    }
    results_path = os.path.join(log_dir, f"results_{ts}.json")
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2)

    _print_summary(summary, results_path)


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

_SEP = "=" * 62


def _print_header(cfg, tasks, injection_configs, total_runs):
    print(f"\n{_SEP}")
    print("Phase 3 — Defended ReAct Agent Evaluation")
    print(_SEP)
    print(f"  defenses              : {cfg.defenses}")
    print(f"  prompt_injection_flag : {cfg.prompt_injection_flag}")
    print(f"  run_clean_baseline    : {cfg.run_clean_baseline}")
    print(f"  positions             : {cfg.positions}")
    print(f"  payload_types         : {cfg.payload_types}")
    print(f"  styles                : {cfg.styles}")
    print(f"  attacker_email        : {cfg.attacker_email}")
    print(f"  tasks                 : {len(tasks)}  "
          f"(ids: {[t['task_id'] for t in tasks]})")
    print(f"  injection configs     : {len(injection_configs)}")
    print(f"  total runs            : {total_runs}")
    print(_SEP + "\n")


def _print_run_header(run_num, total_runs, defense_name, task_id, label, prompt):
    short = prompt[:110] + ("..." if len(prompt) > 110 else "")
    print(f"[{run_num}/{total_runs}]  defense={defense_name}  "
          f"task_id={task_id}  config={label}")
    print(f"  Prompt : {short}")


def _fmt(val) -> str:
    return f"{val:.4f}" if val is not None else "  N/A "


def _print_run_result(expected, actual, asr, tcdr, tcr, exfil, audit):
    print(f"  Expected tools : {expected}")
    print(f"  Actual tools   : {actual}")
    flag = ""
    if exfil and exfil.get("exfiltrated"):
        flag = f"  [exfil: {exfil['count']} email(s)]"
    audit_flag = ""
    if audit and audit.get("flagged"):
        audit_flag = "  [audit: FLAGGED]"
    print(f"  ASR={_fmt(asr)}  TCDR={_fmt(tcdr)}  TCR={_fmt(tcr)}"
          + flag + audit_flag)
    print()


def _print_summary(summary, results_path):
    print(_SEP)
    print("Phase 3 Summary")
    print(_SEP)

    by_defense = summary.get("by_defense", {})
    print(f"  {'Defense':<25}  {'ASR':>6}  {'TCDR_inj':>8}  {'TCR_inj':>7}  "
          f"{'FPR':>6}  {'DR':>6}  {'n_inj':>5}  {'n_cln':>5}")
    print("  " + "-" * 78)
    for d, s in sorted(by_defense.items()):
        print(
            f"  {d:<25}  "
            f"{_fmt(s.get('asr')):>6}  "
            f"{_fmt(s.get('tcdr_injected')):>8}  "
            f"{_fmt(s.get('tcr_injected')):>7}  "
            f"{_fmt(s.get('fpr')):>6}  "
            f"{_fmt(s.get('dr')):>6}  "
            f"{s.get('n_injected', 0):>5}  "
            f"{s.get('n_clean', 0):>5}"
        )
    print()
    print(f"  Total runs : {summary.get('total_runs', 0)}")
    print(f"  Results    : {results_path}")
    print(_SEP + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> Phase3Config:
    parser = argparse.ArgumentParser(
        description="Phase 3 defended-agent evaluation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", metavar="PATH",
                        help="Path to a Phase3Config JSON file (CLI flags override).")
    parser.add_argument("--defenses", nargs="+",
                        help="Defenses to evaluate (default: all).")
    parser.add_argument("--no-inject", action="store_true",
                        help="Skip the adversarial matrix; clean only.")
    parser.add_argument("--no-clean", action="store_true",
                        help="Skip clean baseline; injection only (FPR will not be computed).")
    parser.add_argument("--task-ids", nargs="+", type=int, metavar="ID",
                        help="Specific task IDs to run.")
    parser.add_argument("--positions", nargs="+", choices=["prefix", "suffix"])
    parser.add_argument("--payload-types", nargs="+",
                        choices=["tool_redirect", "context_exfiltration", "goal_hijacking"])
    parser.add_argument("--styles", nargs="+",
                        choices=["direct", "system_message"])
    parser.add_argument("--attacker-email", metavar="EMAIL")
    parser.add_argument("--log-dir", metavar="DIR")
    parser.add_argument("--max-steps", type=int, metavar="N")
    args = parser.parse_args()

    cfg = Phase3Config.from_json(args.config) if args.config else Phase3Config()

    if args.defenses:
        cfg.defenses = args.defenses
    if args.no_inject:
        cfg.prompt_injection_flag = False
    if args.no_clean:
        cfg.run_clean_baseline = False
    if args.task_ids:
        cfg.task_ids = args.task_ids
    if args.positions:
        cfg.positions = args.positions
    if args.payload_types:
        cfg.payload_types = args.payload_types
    if args.styles:
        cfg.styles = args.styles
    if args.attacker_email:
        cfg.attacker_email = args.attacker_email
    if args.log_dir:
        cfg.log_dir = args.log_dir
    if args.max_steps:
        cfg.max_agent_steps = args.max_steps
    return cfg


if __name__ == "__main__":
    run_phase3(_parse_args())
