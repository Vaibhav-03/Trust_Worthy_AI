import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.tools import ALL_TOOLS

load_dotenv()

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. "
    "Use them to complete the user's task step by step."
)


def build_agent(
    model: str = "meta-llama/Llama-3.3-70B-Instruct",
    base_url: str = "https://api.studio.nebius.com/v1/",
):
    llm = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=os.environ.get("NEBIUS_API_KEY"),
        temperature=0,
    )
    agent = create_react_agent(llm, ALL_TOOLS, prompt=SYSTEM_PROMPT)
    return agent
