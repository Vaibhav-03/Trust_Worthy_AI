import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_tavily import TavilySearch

load_dotenv()


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression.
    Input: a math expression string like '2 + 3 * 4'.
    Output: the numerical result.
    """
    allowed_names: dict = {"__builtins__": {}}
    try:
        result = eval(expression, allowed_names, {})
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {e}"


@tool
def web_search(query: str) -> str:
    """Search the web for current information.
    Input: a search query string.
    Output: top 3 search results with titles, URLs, and snippets.
    """
    tavily = TavilySearch(max_results=3)
    response = tavily.invoke(query)
    if not response:
        return "No results found."
    if isinstance(response, str):
        return response
    # TavilySearch returns a dict with a "results" key containing the list
    if isinstance(response, dict):
        results = response.get("results", [])
    else:
        results = response
    if not results:
        return "No results found."
    parts = []
    for r in results:
        if isinstance(r, dict):
            parts.append(
                f"Title: {r.get('title', '')}\n"
                f"URL: {r.get('url', '')}\n"
                f"Content: {r.get('content', '')}"
            )
        else:
            parts.append(str(r))
    return "\n\n".join(parts)


@tool
def file_reader(filename: str) -> str:
    """Read a file from the files/ directory.
    Input: a filename (e.g. 'sample.txt').
    Output: the file contents as a string.
    """
    if ".." in filename:
        return "Error: path traversal is not allowed."
    base_dir = os.path.join(os.path.dirname(__file__), "..", "files")
    filepath = os.path.normpath(os.path.join(base_dir, filename))
    try:
        with open(filepath, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: file '{filename}' not found."


@tool
def email_sender(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient with a subject and body."""
    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "to": to,
        "subject": subject,
        "body": body,
    }
    log_path = os.path.join(log_dir, "sent_emails.jsonl")
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return f"Email sent successfully to {to}"


@tool
def email_summarizer(max_emails: int = 10) -> str:
    """Summarize the most recently sent emails from the email log.
    Input: max_emails (optional, default 10) — number of recent emails to summarize.
    Output: a structured summary listing each email's timestamp, recipient, subject,
    and a brief excerpt of the body.
    """
    log_path = os.path.join(os.path.dirname(__file__), "..", "logs", "sent_emails.jsonl")
    if not os.path.exists(log_path):
        return "No sent emails found."

    entries = []
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not entries:
        return "No sent emails found."

    recent = entries[-max_emails:]
    parts = [f"Showing {len(recent)} of {len(entries)} sent email(s):\n"]
    for i, e in enumerate(recent, 1):
        body_excerpt = e.get("body", "")
        if len(body_excerpt) > 100:
            body_excerpt = body_excerpt[:100].rstrip() + "..."
        parts.append(
            f"{i}. [{e.get('timestamp', 'unknown time')}]\n"
            f"   To:      {e.get('to', '')}\n"
            f"   Subject: {e.get('subject', '')}\n"
            f"   Body:    {body_excerpt}"
        )
    return "\n".join(parts)


ALL_TOOLS = [calculator, web_search, file_reader, email_sender, email_summarizer]
