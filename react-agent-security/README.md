# ReAct Agent Security Research — Phase 1: Baseline Agent

Vanilla ReAct agent with four tools, built as a baseline for security vulnerability research.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in GROQ_API_KEY and TAVILY_API_KEY in .env
```

## Usage

```bash
python -m src.run_task "Your task here"
```

## Tools

| Tool | Description |
|------|-------------|
| `calculator` | Evaluates basic arithmetic expressions |
| `web_search` | Searches the web via Tavily (top 3 results) |
| `file_reader` | Reads files from the `files/` directory |
| `email_sender` | **Mocked** — logs to `logs/sent_emails.jsonl` |

## Output

- Console: prints every reasoning step, tool call, tool output, and final answer
- `logs/run_<timestamp>.json`: full execution trace
- `logs/sent_emails.jsonl`: mocked email log
