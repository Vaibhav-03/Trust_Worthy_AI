import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agent import build_agent


def run(task: str):
    agent = build_agent()
    result = agent.invoke({"messages": [("user", task)]})
    messages = result["messages"]

    tool_calls_log = []

    for msg in messages:
        kind = msg.type
        if kind == "human":
            print(f"\n{'=' * 60}")
            print(f"USER: {msg.content}")
            print(f"{'=' * 60}")
        elif kind == "ai":
            if msg.content:
                print(f"\nASSISTANT: {msg.content}")
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    print(f"\n  -> TOOL CALL: {tc['name']}({json.dumps(tc['args'])})")
                    tool_calls_log.append({"name": tc["name"], "args": tc["args"]})
        elif kind == "tool":
            preview = msg.content[:500] if isinstance(msg.content, str) else str(msg.content)[:500]
            print(f"  <- TOOL OUTPUT [{msg.name}]: {preview}")

    final_output = ""
    for msg in reversed(messages):
        if msg.type == "ai" and msg.content:
            final_output = msg.content
            break

    print(f"\n{'=' * 60}")
    print(f"FINAL ANSWER: {final_output}")
    print(f"{'=' * 60}")

    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trace = {
        "task": task,
        "messages": [
            {
                "type": m.type,
                "content": m.content if isinstance(m.content, str) else str(m.content),
                "name": getattr(m, "name", None),
                "tool_calls": [
                    {"name": tc["name"], "args": tc["args"]}
                    for tc in (getattr(m, "tool_calls", None) or [])
                ],
            }
            for m in messages
        ],
        "tool_calls": tool_calls_log,
        "final_output": final_output,
    }
    trace_path = os.path.join(log_dir, f"run_{timestamp}.json")
    with open(trace_path, "w") as f:
        json.dump(trace, f, indent=2)
    print(f"\nTrace saved to {trace_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.run_task '<task string>'")
        sys.exit(1)
    run(sys.argv[1])
