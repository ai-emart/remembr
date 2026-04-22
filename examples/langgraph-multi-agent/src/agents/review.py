"""Review agent for the LangGraph multi-agent example."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.memory import SharedLangGraphMemory, invoke_text, parse_json_block


@dataclass
class ReviewAgent:
    llm: Any
    memory: SharedLangGraphMemory

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        topic = state["topic"]
        findings = self.memory.research_findings(topic) or state.get("research_findings", [])
        draft = state.get("draft") or self.memory.latest_draft(topic)
        prompt = "\n".join(
            [
                "You are the review agent in a research -> writing -> review loop.",
                "Judge the draft against the research findings.",
                'Return JSON with keys feedback, confidence, and needs_revision.',
                f"Topic: {topic}",
                "Research findings:",
                *(f"- {item}" for item in findings),
                "Draft:",
                draft,
            ]
        )
        payload = parse_json_block(
            invoke_text(
                self.llm,
                prompt,
            ),
            fallback={
                "feedback": "No structured review returned. Add more evidence.",
                "confidence": 0.5,
                "needs_revision": True,
            },
        )
        feedback = str(payload.get("feedback", "")).strip() or "Review feedback unavailable."
        confidence = float(payload.get("confidence", 0.0))
        needs_revision = bool(payload.get("needs_revision", confidence < 0.7))

        self.memory.write_memory(
            agent="review",
            topic=topic,
            kind="feedback",
            content=feedback,
            extra_tags=[f"confidence:{confidence:.2f}"],
            metadata={"confidence": confidence, "needs_revision": needs_revision},
        )
        return {
            "review": {
                "feedback": feedback,
                "confidence": confidence,
                "needs_revision": needs_revision,
            },
            "loop_count": int(state.get("loop_count", 0)) + 1,
        }
