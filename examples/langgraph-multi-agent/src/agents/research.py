"""Research agent for the LangGraph multi-agent example."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus
from urllib.request import urlopen

from src.memory import SharedLangGraphMemory, invoke_text, parse_json_block


class DuckDuckGoSearchTool:
    """Lightweight search tool using the DuckDuckGo instant answer endpoint."""

    endpoint = "https://api.duckduckgo.com/?format=json&no_html=1&skip_disambig=1&q="

    def search(self, query: str, max_results: int = 5) -> list[str]:
        with urlopen(self.endpoint + quote_plus(query), timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        findings: list[str] = []
        abstract = payload.get("AbstractText")
        if isinstance(abstract, str) and abstract.strip():
            findings.append(abstract.strip())

        related = payload.get("RelatedTopics") or []
        for item in related:
            if len(findings) >= max_results:
                break
            if isinstance(item, dict) and isinstance(item.get("Text"), str):
                findings.append(item["Text"].strip())
            elif isinstance(item, dict):
                for nested in item.get("Topics", []):
                    if len(findings) >= max_results:
                        break
                    if isinstance(nested, dict) and isinstance(nested.get("Text"), str):
                        findings.append(nested["Text"].strip())

        return findings[:max_results] or [f"No direct search results were returned for: {query}"]


@dataclass
class ResearchAgent:
    llm: Any
    memory: SharedLangGraphMemory
    search_tool: Any

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        topic = state["topic"]
        prior_feedback = self.memory.previous_feedback(topic)
        prior_findings = self.memory.research_findings(topic)
        search_results = self.search_tool.search(topic)

        prompt = "\n".join(
            [
                "You are the research agent in a three-agent pipeline.",
                "Use the search results and any past review feedback to produce better findings.",
                "Return JSON with keys summary and findings (a list of concise bullets).",
                f"Topic: {topic}",
                "Past review feedback:",
                *(prior_feedback or ["- none"]),
                "Past findings already in memory:",
                *(prior_findings or ["- none"]),
                "Current web search results:",
                *(f"- {item}" for item in search_results),
            ]
        )
        payload = parse_json_block(
            invoke_text(self.llm, prompt),
            fallback={"summary": "No structured summary returned.", "findings": search_results[:3]},
        )

        findings = [str(item).strip() for item in payload.get("findings", []) if str(item).strip()]
        if not findings:
            findings = search_results[:3]

        for finding in findings:
            self.memory.write_memory(
                agent="research",
                topic=topic,
                kind="finding",
                content=finding,
            )

        return {
            "research_findings": findings,
        }
