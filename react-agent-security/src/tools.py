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
    results = tavily.invoke(query)
    if not results:
        return "No results found."
    if isinstance(results, str):
        return results
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


ALL_TOOLS = [calculator, web_search, file_reader, email_sender]
