# ReAct Agent Security Research — Phase 1: Baseline Agent

Vanilla ReAct agent with four tools, built as a baseline for security vulnerability research.

## Stack

- **LLM:** Llama-3.1-8B-Instruct via [Groq](https://console.groq.com) (`langchain-groq`)
- **Agent framework:** LangGraph `create_react_agent` (v1.1.6)
- **Web search:** Tavily (`langchain-tavily`)
- **Python:** 3.10+

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

Example smoke test:

```bash
python -m src.run_task "Look up the current stock price of AAPL and email a one-sentence summary to user@example.com"
```

## Tools

| Tool | Description |
|------|-------------|
| `calculator` | Evaluates basic arithmetic expressions safely |
| `web_search` | Searches the web via Tavily (top 3 results) |
| `file_reader` | Reads files from the `files/` directory; rejects `..` paths |
| `email_sender` | **Mocked** — appends JSON to `logs/sent_emails.jsonl`, never sends real email |

## Output

- **Console:** every reasoning step, tool call, tool output, and final answer
- `logs/run_<timestamp>.json`: full execution trace (`task`, `messages`, `tool_calls`, `final_output`)
- `logs/sent_emails.jsonl`: mocked email log (`timestamp`, `to`, `subject`, `body`)

## Project Structure

```
react-agent-security/
├── .env.example          # API key template
├── .gitignore
├── requirements.txt      # Pinned dependencies
├── src/
│   ├── agent.py          # build_agent() — LLM + tools wired into ReAct graph
│   ├── tools.py          # calculator, web_search, file_reader, email_sender
│   └── run_task.py       # CLI entry point
├── files/
│   └── sample.txt        # Sample file for file_reader tool
└── logs/                 # Runtime output (gitignored)
    ├── sent_emails.jsonl
    └── run_<timestamp>.json
```

## Notes

- `logs/` is gitignored — all runtime output stays local
- `.env` is gitignored — never commit API keys
- No attack logic, defenses, or evaluation metrics — this is Phase 1 only
