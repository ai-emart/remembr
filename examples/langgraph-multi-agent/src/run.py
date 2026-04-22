"""CLI runner for the LangGraph multi-agent example."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from src.graph import default_dependencies, run_topic
from src.memory import SharedLangGraphMemory
from src.topics import SAMPLE_TOPICS


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the LangGraph multi-agent Remembr example.")
    parser.add_argument("topic", nargs="?", default=SAMPLE_TOPICS[0])
    args = parser.parse_args()

    memory = SharedLangGraphMemory.from_env(args.topic)
    llm = _build_llm()
    result = run_topic(args.topic, default_dependencies(llm=llm, memory=memory))

    print(f"Topic: {args.topic}")
    print(f"Session ID: {result['session_id']}")
    print(f"Loop count: {result.get('loop_count', 0)}")
    print("Research findings:")
    for item in result.get("research_findings", []):
        print(f"- {item}")
    print("\nDraft:\n")
    print(result.get("draft", ""))
    print("\nReview:\n")
    print(result.get("review", {}))


def _build_llm():
    from langchain_openai import ChatOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to run this example.")

    return ChatOpenAI(
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=0.2,
    )


if __name__ == "__main__":
    main()
