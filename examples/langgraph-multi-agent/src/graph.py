"""LangGraph definition for the multi-agent Remembr example."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover
    START = "__start__"
    END = "__end__"

    class _CompiledGraph:
        def __init__(
            self,
            nodes: dict[str, Any],
            edges: dict[str, str],
            routers: dict[str, tuple[Any, dict[str, str]]],
        ) -> None:
            self._nodes = nodes
            self._edges = edges
            self._routers = routers

        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            current = self._edges[START]
            data = dict(state)
            while current != END:
                updates = self._nodes[current](data)
                if isinstance(updates, dict):
                    data.update(updates)
                if current in self._routers:
                    router, mapping = self._routers[current]
                    current = mapping[router(data)]
                else:
                    current = self._edges[current]
            return data

    class StateGraph:  # type: ignore[override]
        def __init__(self, _state_type: Any):
            self._nodes: dict[str, Any] = {}
            self._edges: dict[str, str] = {}
            self._routers: dict[str, tuple[Any, dict[str, str]]] = {}

        def add_node(self, name: str, fn: Any) -> None:
            self._nodes[name] = fn

        def add_edge(self, source: str, target: str) -> None:
            self._edges[source] = target

        def add_conditional_edges(self, source: str, router: Any, mapping: dict[str, str]) -> None:
            self._routers[source] = (router, mapping)

        def compile(self) -> _CompiledGraph:
            return _CompiledGraph(self._nodes, self._edges, self._routers)

from src.agents.research import DuckDuckGoSearchTool, ResearchAgent
from src.agents.review import ReviewAgent
from src.agents.writing import WritingAgent
from src.memory import SharedLangGraphMemory


class PipelineState(TypedDict, total=False):
    topic: str
    session_id: str
    research_findings: list[str]
    draft: str
    review: dict[str, Any]
    loop_count: int


@dataclass
class GraphDependencies:
    llm: Any
    memory: SharedLangGraphMemory
    search_tool: Any
    max_loops: int = 3
    confidence_threshold: float = 0.7


def build_graph(deps: GraphDependencies):
    research_agent = ResearchAgent(llm=deps.llm, memory=deps.memory, search_tool=deps.search_tool)
    writing_agent = WritingAgent(llm=deps.llm, memory=deps.memory)
    review_agent = ReviewAgent(llm=deps.llm, memory=deps.memory)

    builder = StateGraph(PipelineState)
    builder.add_node("research", research_agent.run)
    builder.add_node("write", writing_agent.run)
    builder.add_node("review", review_agent.run)

    builder.add_edge(START, "research")
    builder.add_edge("research", "write")
    builder.add_edge("write", "review")
    builder.add_conditional_edges(
        "review",
        lambda state: _next_step(state, deps.max_loops, deps.confidence_threshold),
        {"research": "research", "end": END},
    )
    return builder.compile()


def run_topic(topic: str, deps: GraphDependencies) -> PipelineState:
    graph = build_graph(deps)
    return graph.invoke(
        {
            "topic": topic,
            "session_id": deps.memory.session_id,
            "research_findings": [],
            "draft": "",
            "review": {},
            "loop_count": 0,
        }
    )


def default_dependencies(llm: Any, memory: SharedLangGraphMemory) -> GraphDependencies:
    return GraphDependencies(llm=llm, memory=memory, search_tool=DuckDuckGoSearchTool())


def _next_step(state: PipelineState, max_loops: int, confidence_threshold: float) -> str:
    review = state.get("review", {})
    confidence = float(review.get("confidence", 0.0))
    loop_count = int(state.get("loop_count", 0))
    if confidence < confidence_threshold and loop_count < max_loops:
        return "research"
    return "end"
