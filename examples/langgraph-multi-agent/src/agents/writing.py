"""Writing agent for the LangGraph multi-agent example."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.memory import SharedLangGraphMemory, invoke_text, parse_json_block


@dataclass
class WritingAgent:
    llm: Any
    memory: SharedLangGraphMemory

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        topic = state["topic"]
        findings = self.memory.research_findings(topic) or state.get("research_findings", [])
        prompt = "\n".join(
            [
                "You are the writing agent in a three-agent pipeline.",
                "Write a tight draft using the research findings.",
                'Return JSON with key "draft".',
                f"Topic: {topic}",
                "Research findings:",
                *(f"- {item}" for item in findings),
            ]
        )
        payload = parse_json_block(
            invoke_text(self.llm, prompt),
            fallback={"draft": "\n".join(findings)},
        )
        draft = str(payload.get("draft", "")).strip() or "\n".join(findings)
        self.memory.write_memory(
            agent="writing",
            topic=topic,
            kind="draft",
            content=draft,
        )
        return {"draft": draft}
