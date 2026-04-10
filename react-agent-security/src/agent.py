from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent

from src.tools import ALL_TOOLS

load_dotenv()

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. "
    "Use them to complete the user's task step by step."
)


def build_agent():
    llm = ChatGroq(model="llama3-8b-8192", temperature=0)
    agent = create_react_agent(llm, ALL_TOOLS, prompt=SYSTEM_PROMPT)
    return agent
