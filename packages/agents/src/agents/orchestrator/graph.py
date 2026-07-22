"""LangGraph state machine for the full coverage research workflow.

Each node below is a placeholder — the real logic lands with its owning
agent (industry analysis, Lynch pitch, Munger invert, citation enforcer,
...). What's implemented for real here is the graph topology and the two
routing functions, since those define the contract every future node has to
honor and are what ``tests/unit/test_langgraph_graph.py`` exercises.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph


class CoverageState(TypedDict):
    coverage_id: str
    tenant_id: str
    user_intent: str  # what the user asked for
    current_step: str
    prerequisites_met: bool
    missing_prerequisites: list[str]
    industry_loaded: bool  # True if industry primer exists
    documents_loaded: bool  # True if >=1 document indexed
    min_filings_present: bool  # True if >=3 years of annual filings present
    lynch_pitch_complete: bool
    munger_invert_complete: bool
    quarterly_monitor_active: bool
    task_history: Annotated[list[dict[str, Any]], operator.add]  # append-only log
    output: dict[str, Any] | None  # final output from completed step
    error: str | None


def build_coverage_graph() -> CompiledStateGraph[CoverageState]:
    graph: StateGraph[CoverageState] = StateGraph(CoverageState)

    # Add nodes (each node is an async function)
    graph.add_node("coverage_init", coverage_init_node)
    graph.add_node("industry_analysis", industry_analysis_node)
    graph.add_node("doc_ingestion", doc_ingestion_node)
    graph.add_node("lynch_pitch", lynch_pitch_node)
    graph.add_node("munger_invert", munger_invert_node)
    graph.add_node("citation_validation", citation_validation_node)
    graph.add_node("quarterly_monitor", quarterly_monitor_node)
    graph.add_node("prerequisite_error", prerequisite_error_node)

    # Entry point
    graph.set_entry_point("coverage_init")

    # Routing from coverage_init based on user_intent
    graph.add_conditional_edges(
        "coverage_init",
        route_from_init,
        {
            "industry": "industry_analysis",
            "ingest": "doc_ingestion",
            "lynch": "lynch_pitch",
            "munger": "munger_invert",
            "quarterly": "quarterly_monitor",
            "missing_prerequisites": "prerequisite_error",
        },
    )

    # After industry analysis -> citation_validation
    graph.add_edge("industry_analysis", "citation_validation")

    # Lynch + Munger both go through citation_validation
    graph.add_edge("lynch_pitch", "citation_validation")
    graph.add_edge("munger_invert", "citation_validation")

    # Citation validation: approved -> end, rejected -> retry or partial
    graph.add_conditional_edges(
        "citation_validation",
        route_citation_result,
        {
            "approved": END,
            "retry": "lynch_pitch",  # or "munger_invert" -- determined by state.current_step
            "partial": END,  # surface PARTIAL flag to user
            "failed": END,  # max retries exceeded
        },
    )

    graph.add_edge("doc_ingestion", END)
    graph.add_edge("quarterly_monitor", END)
    graph.add_edge("prerequisite_error", END)

    # mypy can't resolve langgraph's ContextT/InputT/OutputT default TypeVars
    # through compile()'s return type; at runtime this is a CompiledStateGraph
    # over CoverageState like the declared return type says.
    return graph.compile()  # type: ignore[return-value]


# ── Node functions (stubs — filled in by each agent's implementation) ──────────


async def coverage_init_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("coverage_init_node: implemented by the Orchestrator agent")


async def industry_analysis_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("industry_analysis_node: implemented by the Industry Analyst agent")


async def doc_ingestion_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("doc_ingestion_node: implemented by the Document Ingestion agent")


async def lynch_pitch_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("lynch_pitch_node: implemented by the Lynch Pitch agent")


async def munger_invert_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("munger_invert_node: implemented by the Munger Invert agent")


async def citation_validation_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("citation_validation_node: implemented by the Citation Enforcer agent")


async def quarterly_monitor_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("quarterly_monitor_node: implemented by the Earnings Monitor agent")


async def prerequisite_error_node(state: CoverageState) -> CoverageState:
    raise NotImplementedError("prerequisite_error_node: implemented by the Orchestrator agent")


# ── Routing functions ───────────────────────────────────────────────────────


def route_from_init(state: CoverageState) -> str:
    if not state["prerequisites_met"]:
        return "missing_prerequisites"
    # Map user_intent to node name
    intent_map = {
        "industry": "industry",
        "documents": "ingest",
        "bull": "lynch",
        "bear": "munger",
        "quarterly": "quarterly",
    }
    # An unrecognized intent is itself a precondition failure, not a valid
    # routing key -- falling through to "prerequisite_error" (not a key in
    # add_conditional_edges' mapping) would raise at graph-run time.
    return intent_map.get(state["user_intent"], "missing_prerequisites")


def route_citation_result(state: CoverageState) -> str:
    output = state.get("output") or {}
    enforcer_status = output.get("enforcer_status", "pending")
    retry_count = output.get("retry_count", 0)
    if enforcer_status == "approved":
        return "approved"
    elif retry_count < 3:
        return "retry"
    elif enforcer_status == "partial":
        return "partial"
    return "failed"
