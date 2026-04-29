# Phase 3 — Defensive Mitigations Against Adversarial Prompt Injection

Phase 3 introduces a multi-layered defense-in-depth architecture to protect the ReAct agent against the adversarial prompt injections identified in Phase 2. By applying hooks at various stages of the agent's lifecycle—from prompt preprocessing to tool execution—we evaluate how effectively these mitigations reduce the Attack Success Rate (ASR) while maintaining system utility.

---

## 1. Overview

Phase 3 transitions from vulnerability assessment to mitigation. The experiment evaluates seven defense configurations (including a baseline and a combined stack) against the same 180-trial adversarial matrix used in Phase 2 plus a clean baseline of 15 trials per defense to measure the False-Positive Rate (FPR).

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

## 7. Preliminary Execution Results

Based on the latest parallel execution logs, completion rates demonstrate varying levels of stability across defense types:

| Defense | Completed / Total | Completion Rate |
| :--- | :--- | :--- |
| `none` | 195 / 195 | 100% |
| `input_sanitization` | 195 / 195 | 100% |
| `grounding_augmentation` | 195 / 195 | 100% |
| `all_combined` | 195 / 195 | 100% |
| `recipient_locking` | 194 / 195 | 99.5% |
| `goal_verification` | 185 / 195 | 94.8% |

> **Note on Reliability**: The `goal_verification` defense exhibits the lowest completion rate (94.8%), suggesting that the complexity of pre-execution checks and rejection logic may lead to agent hangs or timeouts during reasoning.