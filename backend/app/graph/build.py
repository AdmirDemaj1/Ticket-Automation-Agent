"""The LangGraph pipeline: StateGraph + SQLite checkpointer, `thread_id = run_id`."""

import itertools
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.events import Events, tracked
from app.graph.nodes import Deps, Nodes, route_after_review
from app.graph.state import RunState

Graph = CompiledStateGraph[RunState, None, RunState, RunState]

PIPELINE: tuple[tuple[str, str], ...] = (
    ("load_transcript", "Loading transcript"),
    ("analyze_meeting", "Analyzing meeting and screenshots"),
    ("extract_requirements", "Extracting requirements"),
    ("plan_code_reading", "Choosing files to read"),
    ("read_code", "Reading code"),
    ("compare_with_code", "Comparing requirements with code"),
    ("draft_tickets", "Drafting tickets"),
)


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any]) -> Graph:
    nodes = Nodes(deps)
    events = Events(deps.db)
    g = StateGraph(RunState)

    for name, label in PIPELINE:
        g.add_node(name, tracked(events, name, label)(getattr(nodes, name)))
    g.add_node("human_review", nodes.human_review)  # not tracked: see events.tracked
    g.add_node(
        "create_tickets",
        tracked(events, "create_tickets", "Creating Jira issues")(nodes.create_tickets),
    )
    g.add_node("finalize", nodes.finalize)

    g.add_edge(START, PIPELINE[0][0])
    for (a, _), (b, _) in itertools.pairwise(PIPELINE):
        g.add_edge(a, b)
    g.add_edge(PIPELINE[-1][0], "human_review")
    g.add_conditional_edges("human_review", route_after_review, ["create_tickets", "finalize"])
    g.add_edge("create_tickets", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def thread_config(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id}}
