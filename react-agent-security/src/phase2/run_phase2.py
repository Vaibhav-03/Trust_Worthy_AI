"""
Phase 2 — Adversarial Prompt Injection Evaluation
==================================================

Runs every enabled injection config (up to 12) against every selected task
and records ASR / TCDR / TCR metrics for each run.

Metrics
-------
ASR  (Attack Success Rate)     — fraction of injection trials where the
                                  payload's intended action executed.
TCDR (Tool Call Deviation Rate) — fraction of trials where the agent called
                                  a tool not required by the original task.
TCR  (Task Completion Rate)    — mean fraction of the original task still
                                  completed (1.0 = full, 0.0 = full hijack).

Usage
-----
# All tasks, all 12 injection configs (default):
    python -m src.phase2.run_phase2

# Load a custom config JSON:
    python -m src.phase2.run_phase2 --config path/to/cfg.json

# Baseline run (no injection) for comparison:
    python -m src.phase2.run_phase2 --no-inject

# Restrict axes or tasks on the command line:
    python -m src.phase2.run_phase2 --task-ids 1 5 13 \\
        --positions prefix \\
        --payload-types tool_redirect goal_hijacking \\
        --styles direct \\
        --attacker-email evil@test.com

Output
------
logs/phase2/results_<timestamp>.json   — full per-run records + summary
logs/phase2/config_<timestamp>.json    — config snapshot for reproducibility
logs/sent_emails.jsonl                 — shared email audit log (appended)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Allow running as `python -m src.phase2.run_phase2` from project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from src.agent import build_agent
from src.phase2.config import Phase2Config
from src.phase2.evaluator import (
    aggregate_results,
    count_email_lines,
    detect_exfiltration,
    get_run_emails,
)
from src.phase2.injector import InjectionConfig, get_injection_configs, inject
from src.phase2.metrics import compute_asr, compute_tcdr, compute_tcr, unexpected_tools


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


# count_email_lines is imported from evaluator


def _extract_tool_calls_and_answer(messages: list) -> Dict[str, Any]:
    """
    Walk the LangGraph message list and collect:
    - tool_calls : ordered list of tool names actually invoked
    - final_answer: last AI text content (no tool calls)
    """
    tool_calls: List[str] = []
    final_answer = ""
    for msg in messages:
        if getattr(msg, "type", "") == "ai":
            calls = getattr(msg, "tool_calls", None) or []
            for tc in calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name:
                    tool_calls.append(name)
            # The last AI message with content and no tool calls is the final answer.
            if not calls:
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content:
                    final_answer = content
    return {"tool_calls": tool_calls, "final_answer": final_answer}


def _run_agent_once(
    task_prompt: str,
    agent,
    cfg: Phase2Config,
) -> Dict[str, Any]:
    """Invoke the agent and return extracted tool call sequence + final answer."""
    result = agent.invoke(
        {"messages": [("user", task_prompt)]},
        config={"recursion_limit": cfg.max_agent_steps},
    )
    return _extract_tool_calls_and_answer(result.get("messages", []))


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_phase2(cfg: Phase2Config) -> None:
    root = _project_root()
    log_dir = os.path.join(root, cfg.log_dir)
    os.makedirs(log_dir, exist_ok=True)

    email_log_path = os.path.join(root, "logs", "sent_emails.jsonl")
    tasks = _load_tasks(cfg.tasks_file, cfg.task_ids)

    # Build the list of injection configs to iterate over.
    # None sentinel = clean / baseline run.
    if cfg.prompt_injection_flag:
        injection_configs: List[Optional[InjectionConfig]] = list(get_injection_configs(cfg))
    else:
        injection_configs = [None]

    total_runs = len(tasks) * len(injection_configs)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    _print_header(cfg, tasks, injection_configs, total_runs)

    # Persist config for reproducibility before the run starts.
    cfg.to_json(os.path.join(log_dir, f"config_{ts}.json"))

    # Build the agent once and reuse it across all runs.
    agent = build_agent(model=cfg.model, base_url=cfg.base_url)

    all_results: List[Dict[str, Any]] = []
    run_num = 0

    for task in tasks:
        for inj in injection_configs:
            run_num += 1
            label = inj.label if inj else "clean"
            injected_prompt = inject(task["prompt"], inj)

            _print_run_header(run_num, total_runs, task["task_id"], label, injected_prompt)

            emails_before = count_email_lines(email_log_path)
            run_ts = datetime.now(timezone.utc).isoformat()
            error: Optional[str] = None

            try:
                outcome = _run_agent_once(injected_prompt, agent, cfg)
            except Exception as exc:
                outcome = {"tool_calls": [], "final_answer": ""}
                error = str(exc)
                print(f"  ERROR: {exc}")

            # ── Collect email evidence ────────────────────────────────────────
            run_emails = get_run_emails(emails_before, email_log_path)
            exfil = detect_exfiltration(emails_before, email_log_path, cfg.attacker_email)

            expected_tools = task.get("expected_tools", [])
            expected_recipient = task.get("expected_email_recipient", "")
            actual_tools = outcome["tool_calls"]

            # ── Compute the three metrics ─────────────────────────────────────
            asr  = compute_asr(
                inj.payload_type if inj else None,
                exfil,
                cfg.attacker_email,
            )
            tcdr = compute_tcdr(actual_tools, expected_tools)
            tcr  = compute_tcr(actual_tools, expected_tools, run_emails, expected_recipient)

            record: Dict[str, Any] = {
                "run_id":               run_num,
                "timestamp":            run_ts,
                # Task info
                "task_id":              task["task_id"],
                "task_category":        task.get("category", ""),
                "original_prompt":      task["prompt"],
                "expected_tools":       expected_tools,
                "expected_recipient":   expected_recipient,
                # Injection info
                "injection_label":      label,
                "injection_position":   inj.position if inj else None,
                "injection_payload_type": inj.payload_type if inj else None,
                "injection_style":      inj.style if inj else None,
                "injected_prompt":      injected_prompt if inj else None,
                # Outcome
                "actual_tools":         actual_tools,
                "unexpected_tools":     unexpected_tools(actual_tools, expected_tools),
                "final_answer":         outcome["final_answer"],
                # Metrics
                "asr":          asr,    # float 0/1 or None for clean runs
                "tcdr":         tcdr,   # float 0/1 (binary per-trial)
                "tcr":          tcr,    # float [0, 1]
                # Supporting evidence
                "exfiltration": exfil,
                "run_emails":   run_emails,
                "error":        error,
            }
            all_results.append(record)

            _print_run_result(expected_tools, actual_tools, asr, tcdr, tcr, exfil)

    # ── Persist results ────────────────────────────────────────────────────
    summary = aggregate_results(all_results)
    model_slug = cfg.model.split("/")[-1].replace("-Instruct", "")
    output = {
        "meta": {
            "timestamp": ts,
            "total_runs": total_runs,
            "prompt_injection_flag": cfg.prompt_injection_flag,
            "model": cfg.model,
        },
        "config": {
            "model":         cfg.model,
            "base_url":      cfg.base_url,
            "positions":     cfg.positions,
            "payload_types": cfg.payload_types,
            "styles":        cfg.styles,
            "attacker_email": cfg.attacker_email,
            "task_ids":      cfg.task_ids,
        },
        "summary": summary,
        "runs": all_results,
    }
    results_path = os.path.join(log_dir, f"results_{model_slug}_{ts}.json")
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2)

    _print_summary(summary, results_path)


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

_SEP = "=" * 62


def _print_header(cfg, tasks, injection_configs, total_runs):
    print(f"\n{_SEP}")
    print("Phase 2 — Adversarial Prompt Injection Evaluation")
    print(_SEP)
    print(f"  model                 : {cfg.model}")
    print(f"  prompt_injection_flag : {cfg.prompt_injection_flag}")
    print(f"  positions             : {cfg.positions}")
    print(f"  payload_types         : {cfg.payload_types}")
    print(f"  styles                : {cfg.styles}")
    print(f"  attacker_email        : {cfg.attacker_email}")
    print(f"  tasks                 : {len(tasks)}  "
          f"(ids: {[t['task_id'] for t in tasks]})")
    print(f"  injection configs     : {len(injection_configs)}")
    print(f"  total runs            : {total_runs}")
    print(_SEP + "\n")


def _print_run_header(run_num, total_runs, task_id, label, prompt):
    short = prompt[:110] + ("..." if len(prompt) > 110 else "")
    print(f"[{run_num}/{total_runs}]  task_id={task_id}  config={label}")
    print(f"  Prompt : {short}")


def _fmt(val) -> str:
    """Format a metric value (float or None) for display."""
    return f"{val:.4f}" if val is not None else "  N/A "


def _print_run_result(expected, actual, asr, tcdr, tcr, exfil):
    print(f"  Expected tools : {expected}")
    print(f"  Actual tools   : {actual}")
    print(f"  ASR={_fmt(asr)}  TCDR={_fmt(tcdr)}  TCR={_fmt(tcr)}"
          + (f"  [exfil: {exfil['count']} email(s)]" if exfil["exfiltrated"] else ""))
    print()


def _print_summary(summary, results_path):
    print(_SEP)
    print("Summary")
    print(_SEP)
    print(f"  Total runs : {summary.get('total_runs', 0)}")
    print(f"  ASR        : {_fmt(summary.get('asr'))}   "
          "(fraction of injection trials where attack succeeded)")
    print(f"  TCDR       : {_fmt(summary.get('tcdr'))}   "
          "(fraction of trials with unexpected tool calls)")
    print(f"  TCR        : {_fmt(summary.get('tcr'))}   "
          "(mean fraction of original task completed)")
    print()
    print(f"  {'Config':<42}  {'ASR':>6}  {'TCDR':>6}  {'TCR':>6}  {'n':>4}")
    print(f"  {'-'*42}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*4}")
    for label, s in sorted(summary.get("by_injection_config", {}).items()):
        print(f"  {label:<42}  "
              f"{_fmt(s.get('asr')):>6}  "
              f"{_fmt(s.get('tcdr')):>6}  "
              f"{_fmt(s.get('tcr')):>6}  "
              f"{s['total']:>4}")
    print()
    print(f"  Results saved to : {results_path}")
    print(_SEP + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> Phase2Config:
    parser = argparse.ArgumentParser(
        description="Phase 2 adversarial prompt injection evaluation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config", metavar="PATH",
        help="Path to a Phase2Config JSON file (all other flags override it).",
    )
    parser.add_argument(
        "--no-inject", action="store_true",
        help="Disable injection; run clean baseline only.",
    )
    parser.add_argument(
        "--task-ids", nargs="+", type=int, metavar="ID",
        help="Specific task IDs to run (default: all 15).",
    )
    parser.add_argument(
        "--positions", nargs="+", choices=["prefix", "suffix"],
        help="Injection position(s) to test.",
    )
    parser.add_argument(
        "--payload-types", nargs="+",
        choices=["tool_redirect", "context_exfiltration", "goal_hijacking"],
        help="Payload type(s) to test.",
    )
    parser.add_argument(
        "--styles", nargs="+", choices=["direct", "system_message"],
        help="Injection style(s) to test.",
    )
    parser.add_argument(
        "--attacker-email", metavar="EMAIL",
        help="Attacker-controlled email address used in payloads.",
    )
    parser.add_argument(
        "--log-dir", metavar="DIR",
        help="Directory for output files.",
    )
    parser.add_argument(
        "--max-steps", type=int, metavar="N",
        help="LangGraph recursion limit per run.",
    )
    parser.add_argument(
        "--model", metavar="MODEL_ID",
        help="Model identifier (e.g. Qwen/Qwen2.5-72B-Instruct).",
    )
    parser.add_argument(
        "--base-url", metavar="URL",
        help="API base URL for the model provider.",
    )
    args = parser.parse_args()

    cfg = Phase2Config.from_json(args.config) if args.config else Phase2Config()

    # CLI flags override whatever was in the JSON.
    if args.no_inject:
        cfg.prompt_injection_flag = False
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
    if args.model:
        cfg.model = args.model
    if args.base_url:
        cfg.base_url = args.base_url

    return cfg


if __name__ == "__main__":
    run_phase2(_parse_args())
