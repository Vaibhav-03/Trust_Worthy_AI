# Phase 3 — Defensive Mitigations Against Adversarial Prompt Injection

Phase 3 introduces a multi-layered defense-in-depth architecture to protect the ReAct agent against the adversarial prompt injections identified in Phase 2. By applying hooks at various stages of the agent's lifecycle—from prompt preprocessing to tool execution—we evaluate how effectively these mitigations reduce the Attack Success Rate (ASR) while maintaining system utility.

---

## 1. Overview

Phase 3 transitions from vulnerability assessment to mitigation. The experiment evaluates seven defense configurations (including a baseline and a combined stack) against the same 180-trial adversarial matrix used in Phase 2 plus a clean baseline of 15 trials per defense to measure the False-Positive Rate (FPR). The goal is to quantify the security-utility trade-off: how effectively a defense reduces the Attack Success Rate (ASR) without breaking legitimate agent behavior.

---

## 2. Module Structure

```text
src/phase3/
├── defenses/                # Discrete defense strategy implementations
│   ├── sanitizer.py         # Regex-based input cleaning
│   ├── recipient_lock.py    # Recipient enforcement via tool wrapping
│   ├── grounding.py         # System prompt boundary reinforcement
│   ├── audit.py             # Post-hoc log analysis and detection
│   └── goal_verifier.py     # Pre-execution action validation
├── agent_factory.py         # Logic for constructing agents with defense hooks
├── metrics.py               # Calculation for FPR and Detection Rate (DR)
├── evaluator.py             # Result aggregation and summary logic
└── run_phase3.py            # Main entry point for the defensive sweep
```

---

## 3. The Defensive Layers

Every defense is defined by a `DefenseSpec` that can hook into four specific execution points:

| Defense | Mechanism | Hook Point | Primary Target |
| :--- | :--- | :--- | :--- |
| **`input_sanitization`** | Strips recurring lexical injection patterns using regex denylists. | `preprocess_prompt` | Direct-style instructions. |
| **`recipient_locking`** | Forces `email_sender` to deliver only to the task's expected recipient. | `wrap_tools` | `tool_redirect` payloads. |
| **`grounding_augmentation`** | Augments the system prompt with strict task boundaries and recipient grounding. | `system_prompt` | High-risk categories like `web_search`. |
| **`audit_logging`** | Post-hoc detection of "HIJACKED" markers and recipient mismatches. | `post_run` | All payload types (Detection only). |
| **`goal_verification`** | Rejects tool calls if the recipient or body violates the original task spec. | `wrap_tools` | `tool_redirect` and `goal_hijacking`. |
| **`all_combined`** | Stacks all of the above defenses into a single high-security agent. | Multiple | Complete defense-in-depth. |

---

## 4. Evaluation Metrics

Phase 3 evaluates performance across five key metrics:

* **ASR (Attack Success Rate):** The fraction of injection trials where the attack payload was successfully executed.
* **TCR (Task Completion Rate):** The fraction of the original legitimate task completed by the agent.
* **TCDR (Tool-Call Deviation Rate):** The fraction of trials where the agent called tools not required by the task.
* **FPR (False-Positive Rate):** The fraction of clean (non-injected) trials where the defense caused the agent to fail its task (TCR < 1.0).
* **DR (Detection Rate):** The fraction of successful attacks that were correctly flagged by the `audit_logging` hook.

---

## 5. How to Run

Commands must be executed from the project root.

### Full Experiment (All Defenses)
Runs the full 12 × 15 adversarial matrix plus clean baselines for all 7 defense configurations.
```bash
python -m src.phase3.run_phase3
```

### Subset Defense Test
Evaluate only specific defenses, such as the `recipient_locking` and `all_combined` layers.
```bash
python -m src.phase3.run_phase3 --defenses recipient_locking all_combined
```

### Smoke Test
Run a single task against a specific defense and injection configuration.
```bash
python -m src.phase3.run_phase3 --defenses input_sanitization --task-ids 1 --positions prefix --payload-types tool_redirect --styles direct
```

---

## 6. Output Files

* **`logs/phase3/results_<timestamp>.json`**: The primary data file containing aggregate summaries and per-run records.
* **`logs/phase3/config_<timestamp>.json`**: A snapshot of the `Phase3Config` used for reproducibility.
* **`logs/blocked_emails.jsonl`**: A log of every email tool call rejected by the `goal_verification` defense.
* **`logs/sent_emails.jsonl`**: The central audit log for all successful (or rewritten) email deliveries.

---

## 7. Experimental Results

Results from the full 12 × 15 adversarial matrix (180 injection trials + 15 clean baseline trials per defense, 1,365 total runs). All metrics are corrected for the `attempted_to` TCR fix, the `all_combined` wrapper bug, and the sanitizer dot-truncation bug documented in the Phase 3 bug fixes.

### 7.1 Global Summary

| Defense | ASR | TCR_inj | TCR_clean | FPR | DR | ASR reduction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `none` | 0.7556 | 0.6162 | 0.8000 | 0.2000 | — | — |
| `input_sanitization` | **0.0000** | 0.7778 | 0.7333 | 0.2667 | — | −100% |
| `recipient_locking` | **0.0000** | 0.6523 | 0.8000 | 0.2000 | — | −100% |
| `grounding_augmentation` | 0.0333 | 0.7454 | 0.6667 | 0.3333 | — | −96% |
| `audit_logging` | 0.7444 | 0.6301 | 0.8000 | 0.2000 | **0.7778** | −1.5% |
| `goal_verification` | **0.0000** | 0.6500 | 0.8000 | 0.2000 | — | −100% |
| `all_combined` | **0.0000** | 0.7241 | 0.6667 | 0.3333 | 0.0000 | −100% |

### 7.2 ASR by Payload Type

| Payload type | `none` | `input_sanitization` | `recipient_locking` | `grounding_augmentation` | `goal_verification` | `all_combined` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `goal_hijacking` | 0.9333 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| `tool_redirect` | 0.7000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| `context_exfiltration` | 0.6333 | 0.0000 | 0.0000 | **0.1000** | 0.0000 | 0.0000 |

`context_exfiltration` is the only payload type that bypasses `grounding_augmentation`. All six leaks are `suffix + direct` style — additive phrasing that the grounding constraints do not categorically reject.

### 7.3 Net FPR Cost (Over 0.2000 Baseline)

The baseline agent itself fails 20% of clean tasks (Tasks 5, 12, 14) due to inherent model limitations on multi-step tasks, not defense interference. Net cost = defense FPR − 0.2000.

| Defense | FPR | Net cost |
| :--- | :--- | :--- |
| `recipient_locking` | 0.2000 | **+0.0000** |
| `audit_logging` | 0.2000 | **+0.0000** |
| `goal_verification` | 0.2000 | **+0.0000** |
| `input_sanitization` | 0.2667 | +0.0667 |
| `grounding_augmentation` | 0.3333 | +0.1333 |
| `all_combined` | 0.3333 | +0.1333 |

### 7.4 Key Findings (Llama-3.3-70B)

- **Tool-level defenses are the most cost-effective.** `recipient_locking` and `goal_verification` achieve ASR = 0.0 with zero net FPR overhead.
- **`grounding_augmentation` leaks on additive `context_exfiltration` payloads** (ASR = 0.10 for that payload type) and introduces the highest FPR cost (+13%).
- **`audit_logging` detects 78% of successful attacks** post-hoc with no FPR overhead, making it the best monitoring layer when combined with a blocking defense.
- **`all_combined` DR = 0.0 is expected**: the sanitizer handles all Phase 2 payloads before the agent acts, leaving no signal for the audit hook. The audit layer would activate against novel attacks that bypass the sanitizer.
- **Recommended minimum stack:** `recipient_locking` + `goal_verification` + `audit_logging` — ASR = 0.0, zero net FPR cost, and DR coverage for post-hoc monitoring.

---

## 8. Cross-Model Results — Qwen3-235B-A22B-Instruct

Phase 3 was re-run on Qwen/Qwen3-235B-A22B-Instruct to assess defense generalisability across models.

### 8.1 Global Summary (Qwen3-235B)

| Defense | ASR | TCR_inj | TCR_clean | FPR | DR |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `none` | 0.1944* | 0.5204 | 0.5556 | **0.4667** | — |
| `input_sanitization` | 0.0333 | 0.5708 | 0.6000 | 0.4000 | — |
| `recipient_locking` | 0.0611 | 0.4787 | 0.6167 | 0.4000 | — |
| `grounding_augmentation` | 0.0333 | 0.5759 | 0.5333 | 0.4667 | — |
| `audit_logging` | 0.2000 | 0.4778 | 0.5556 | 0.4667 | 0.2222 |
| `goal_verification` | 0.0389 | 0.4407 | 0.5333 | 0.4667 | — |
| `all_combined` | 0.0111 | 0.5759 | 0.5333 | 0.4667 | 0.0444 |

*Low baseline ASR is partly due to the model failing to complete web-search tasks at all (47% clean failure rate), not genuine injection resistance.

### 8.2 Head-to-Head: Llama-3.3-70B vs Qwen3-235B

| Defense | Llama ASR | Qwen3-235B ASR | Llama FPR | Qwen3-235B FPR |
| :--- | :--- | :--- | :--- | :--- |
| `none` | 0.7556 | 0.1944 | 0.2000 | 0.4667 |
| `input_sanitization` | **0.0000** | 0.0333 | 0.2667 | 0.4000 |
| `recipient_locking` | **0.0000** | 0.0611 | 0.2000 | 0.4000 |
| `grounding_augmentation` | 0.0333 | 0.0333 | 0.3333 | 0.4667 |
| `goal_verification` | **0.0000** | 0.0389 | 0.2000 | 0.4667 |
| `all_combined` | **0.0000** | 0.0111 | 0.3333 | 0.4667 |
| `audit_logging` DR | **0.7778** | 0.2222 | — | — |

### 8.3 Key Cross-Model Findings

- **No defense achieves ASR=0.0 on Qwen3-235B.** Even `all_combined` has 2 leaks. Defenses are strictly less effective on this model.
- **Baseline FPR=0.4667** (7/15 clean tasks fail) means utility cost of defenses cannot be meaningfully measured — the model can't reliably complete legitimate tasks regardless of defense.
- **`goal_verification` has 7 leaks on Qwen3-235B** (vs 0 on Llama) — tool-level wrappers interact with model-specific tool-calling behavior and are not model-agnostic.
- **`audit_logging` DR drops from 0.778 → 0.222** — attack patterns on Qwen3-235B produce weaker email-level signals, making post-hoc detection harder.
- **Qwen3-235B is not recommended for this evaluation framework** until its ReAct web-search reliability is confirmed. Qwen3-32B shows better completion behavior (Phase 2: 0 errors, no web loops) and is the preferred Qwen3 comparison model.

> Full cross-model analysis in [`phase3_eval_report.md`](phase3_eval_report.md) §9.