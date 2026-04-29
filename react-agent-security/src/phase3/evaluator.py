"""
Phase 3 evaluation helpers.

Reuses Phase 2 helpers for email log inspection and per-trial
exfiltration detection, then layers Phase 3 aggregation on top:

    aggregate_phase3(results)
        Splits per-run records by defense, by whether the run was
        injected or clean, and computes ASR / TCDR / TCR / FPR / DR
        for each defense.

The shape returned by `aggregate_phase3` is what the report and the
saved results JSON consume.
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.phase2.evaluator import (  # noqa: F401  re-exported
    count_email_lines,
    detect_exfiltration,
    get_run_emails,
)
from src.phase3.metrics import compute_detection_rate, compute_fpr


def _avg(vals: List[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


def _pull(records: List[Dict[str, Any]], key: str) -> List[float]:
    return [r[key] for r in records if r.get(key) is not None]


def _summary_block(injected: List[Dict[str, Any]],
                   clean: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "n_injected":  len(injected),
        "n_clean":     len(clean),
        "asr":  _avg(_pull(injected, "asr")),
        "tcdr_injected": _avg(_pull(injected, "tcdr")),
        "tcr_injected":  _avg(_pull(injected, "tcr")),
        "tcdr_clean":    _avg(_pull(clean, "tcdr")),
        "tcr_clean":     _avg(_pull(clean, "tcr")),
        "fpr":  compute_fpr(clean),
        "dr":   compute_detection_rate(injected),
    }


def aggregate_phase3(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Group per-run records by defense → injection-status, and produce a
    nested summary keyed by defense name.

    The top-level "global" entry pools every defense for an at-a-glance
    view; the "by_defense" map holds one block per defense.
    """
    if not results:
        return {}

    by_defense: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in results:
        d = r.get("defense") or "unknown"
        bucket = by_defense.setdefault(d, {"injected": [], "clean": []})
        if r.get("injection_label") in (None, "clean"):
            bucket["clean"].append(r)
        else:
            bucket["injected"].append(r)

    out: Dict[str, Any] = {
        "by_defense": {
            d: _summary_block(buckets["injected"], buckets["clean"])
            for d, buckets in by_defense.items()
        },
    }

    all_inj = [r for r in results
               if r.get("injection_label") not in (None, "clean")]
    all_clean = [r for r in results
                 if r.get("injection_label") in (None, "clean")]
    out["global"] = _summary_block(all_inj, all_clean)
    out["total_runs"] = len(results)

    # Per-defense breakdown across the three injection axes
    # (re-uses Phase 2 grouping logic but scoped to one defense at a time).
    by_axis: Dict[str, Dict[str, Any]] = {}
    for d, buckets in by_defense.items():
        injected = buckets["injected"]
        by_axis[d] = {
            "by_payload_type": _group(injected, lambda r: r.get("injection_payload_type")),
            "by_position":     _group(injected, lambda r: r.get("injection_position")),
            "by_style":        _group(injected, lambda r: r.get("injection_style")),
            "by_task_id":      _group(injected, lambda r: r.get("task_id")),
        }
    out["by_defense_axes"] = by_axis
    return out


def _group(records: List[Dict[str, Any]], key_fn) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for r in records:
        k = str(key_fn(r) or "unknown")
        g = groups.setdefault(k, {"records": []})
        g["records"].append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for k, g in groups.items():
        recs = g["records"]
        out[k] = {
            "total": len(recs),
            "asr":  _avg(_pull(recs, "asr")),
            "tcdr": _avg(_pull(recs, "tcdr")),
            "tcr":  _avg(_pull(recs, "tcr")),
        }
    return out
