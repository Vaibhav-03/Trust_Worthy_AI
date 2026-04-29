"""
Phase 3 agent factory.

Builds a ReAct agent with one or more defenses applied. The factory is
stateless — every (defense, task_spec) pair produces a fresh agent so
that wrapped tools see the correct task context.

The factory mirrors `src.agent.build_agent` but routes the system prompt
and tool list through the defense's hooks.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.agent import SYSTEM_PROMPT
from src.phase3.defenses import DEFENSE_REGISTRY, DefenseSpec, get_defense
from src.tools import calculator, email_sender, email_summarizer, file_reader, web_search

load_dotenv()


# Re-export the canonical tool list so the factory does not depend on the
# (mutable) ordering of src.tools.ALL_TOOLS.
_BASE_TOOLS = [calculator, web_search, file_reader, email_sender, email_summarizer]


def _build_llm():
    return ChatOpenAI(
        model="meta-llama/Llama-3.3-70B-Instruct",
        base_url="https://api.studio.nebius.com/v1/",
        api_key=os.environ.get("NEBIUS_API_KEY"),
        temperature=0,
    )


def build_defended_agent(defense_name: str, task_spec: Dict[str, Any]):
    """
    Construct an agent with the named defense applied.

    Parameters
    ----------
    defense_name : key in DEFENSE_REGISTRY (see src/phase3/defenses/).
    task_spec    : the task entry from tasks.json — defenses may use it
                   to anchor on the legitimate recipient or task category.

    Returns
    -------
    (agent, defense_spec)
        agent         : the LangGraph ReAct executor.
        defense_spec  : DefenseSpec — kept around so the runner can call
                        `preprocess_prompt` and `post_run` later.
    """
    defense: DefenseSpec = get_defense(defense_name)

    if defense.system_prompt is not None:
        sp = defense.system_prompt(task_spec)
        system_prompt = sp if sp is not None else SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT

    tools: List[Any] = list(_BASE_TOOLS)
    if defense.wrap_tools is not None:
        tools = defense.wrap_tools(tools, task_spec)

    agent = create_react_agent(_build_llm(), tools, prompt=system_prompt)
    return agent, defense


def list_defenses() -> List[str]:
    return sorted(DEFENSE_REGISTRY.keys())
