"""Unit tests for the coverage LangGraph state machine.

Every node function is a stub (raises ``NotImplementedError`` — the real
logic lands with its owning agent), including the entry node
``coverage_init`` itself. That rules out exercising routing by invoking the
compiled graph end-to-end: the entry node would raise before a single
conditional edge ever runs. So routing is verified by calling
``route_from_init`` / ``route_citation_result`` directly against
constructed ``CoverageState`` values — exactly the function LangGraph itself
calls from ``add_conditional_edges`` — while a separate compile-only test
checks the graph wires those functions to the right nodes at all.
"""
from __future__ import annotations

import pytest

from agents.orchestrator import graph as graph_module
from agents.orchestrator.graph import (
    CoverageState,
    build_coverage_graph,
    route_citation_result,
    route_from_init,
)
from agents.shared.citation_enforcer import ValidationResult


def _base_state(**overrides: object) -> CoverageState:
    state: CoverageState = {
        "coverage_id": "cov-1",
        "tenant_id": "tenant-1",
        "user_intent": "bull",
        "current_step": "",
        "prerequisites_met": True,
        "missing_prerequisites": [],
        "industry_loaded": True,
        "documents_loaded": True,
        "min_filings_present": True,
        "lynch_pitch_complete": False,
        "munger_invert_complete": False,
        "quarterly_monitor_active": False,
        "task_history": [],
        "output": None,
        "error": None,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# ── 1. Graph compiles ───────────────────────────────────────────────────────


def test_build_coverage_graph_compiles() -> None:
    graph = build_coverage_graph()
    expected_nodes = {
        "coverage_init",
        "industry_analysis",
        "doc_ingestion",
        "lynch_pitch",
        "munger_invert",
        "citation_validation",
        "quarterly_monitor",
        "prerequisite_error",
    }
    assert expected_nodes.issubset(set(graph.nodes.keys()))


# ── 2-4. Routing from coverage_init ─────────────────────────────────────────


def test_missing_industry_routes_to_prerequisite_error() -> None:
    # coverage_init_node is responsible for computing prerequisites_met from
    # industry_loaded/documents_loaded/min_filings_present before routing —
    # a state where industry isn't loaded is a state where that node would
    # have set prerequisites_met=False.
    state = _base_state(
        user_intent="bull",
        prerequisites_met=False,
        industry_loaded=False,
        missing_prerequisites=["industry"],
    )
    assert route_from_init(state) == "missing_prerequisites"


def test_missing_documents_routes_to_prerequisite_error() -> None:
    state = _base_state(
        user_intent="bull",
        prerequisites_met=False,
        documents_loaded=False,
        missing_prerequisites=["documents"],
    )
    assert route_from_init(state) == "missing_prerequisites"


def test_industry_intent_with_prerequisites_met_routes_to_industry_analysis() -> None:
    state = _base_state(user_intent="industry", prerequisites_met=True)
    assert route_from_init(state) == "industry"


def test_route_from_init_covers_all_intents() -> None:
    assert route_from_init(_base_state(user_intent="industry")) == "industry"
    assert route_from_init(_base_state(user_intent="documents")) == "ingest"
    assert route_from_init(_base_state(user_intent="bull")) == "lynch"
    assert route_from_init(_base_state(user_intent="bear")) == "munger"
    assert route_from_init(_base_state(user_intent="quarterly")) == "quarterly"


def test_route_from_init_missing_prerequisites() -> None:
    state = _base_state(prerequisites_met=False)
    assert route_from_init(state) == "missing_prerequisites"


def test_route_from_init_unrecognized_intent_falls_back_to_missing_prerequisites() -> None:
    # An unknown intent must resolve to a key that's actually wired in
    # build_coverage_graph()'s conditional_edges mapping, or the graph
    # raises at run time instead of routing to the error node.
    state = _base_state(user_intent="not-a-real-intent")
    assert route_from_init(state) == "missing_prerequisites"


# ── 5-7. citation_validation routing ────────────────────────────────────────


def test_citation_validation_approved_routes_to_approved() -> None:
    state = _base_state(output={"enforcer_status": "approved", "retry_count": 0})
    assert route_citation_result(state) == "approved"


def test_citation_validation_retries_below_max() -> None:
    state = _base_state(output={"enforcer_status": "failed", "retry_count": 2})
    assert route_citation_result(state) == "retry"


def test_citation_validation_max_retries_exceeded_ends() -> None:
    state = _base_state(output={"enforcer_status": "failed", "retry_count": 3})
    assert route_citation_result(state) == "failed"


def test_citation_validation_partial_after_max_retries() -> None:
    state = _base_state(output={"enforcer_status": "partial", "retry_count": 3})
    assert route_citation_result(state) == "partial"


def test_citation_validation_handles_missing_output() -> None:
    state = _base_state(output=None)
    assert route_citation_result(state) == "retry"


# ── citation_validation_node ─────────────────────────────────────────────────


def _agent_output_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "message_id": "msg-1",
        "agent": "lynch_pitch",
        "task_id": "task-1",
        "coverage_id": "cov-1",
        "tenant_id": "tenant-1",
        "content": "Revenue grew.",
        "citations": [],
        "citation_coverage_pct": 0.0,
        "llm_used": "primary",
        "tokens_used": 10,
        "latency_ms": 5,
        "retry_count": 0,
    }
    base.update(overrides)
    return base


async def test_citation_validation_node_updates_output_on_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(self: object, output: object, tenant_id: str, coverage_id: str) -> ValidationResult:
        return ValidationResult(
            approved=True,
            enforcer_status="approved",
            failed_checks=[],
            citation_coverage_pct=1.0,
            retry_prompt=None,
            hallucination_count=0,
        )

    monkeypatch.setattr(graph_module, "get_retriever", lambda: None)
    monkeypatch.setattr(graph_module.CitationEnforcer, "validate", fake_validate)

    state = _base_state(output=_agent_output_dict())
    new_state = await graph_module.citation_validation_node(state)

    assert new_state["output"]["approved_by_enforcer"] is True
    assert new_state["output"]["enforcer_status"] == "approved"
    assert new_state["output"]["retry_count"] == 0
    assert new_state["output"]["hallucination_count"] == 0


async def test_citation_validation_node_increments_retry_count_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(self: object, output: object, tenant_id: str, coverage_id: str) -> ValidationResult:
        return ValidationResult(
            approved=False,
            enforcer_status="failed",
            failed_checks=[],
            citation_coverage_pct=0.4,
            retry_prompt="fix your citations",
            hallucination_count=2,
        )

    monkeypatch.setattr(graph_module, "get_retriever", lambda: None)
    monkeypatch.setattr(graph_module.CitationEnforcer, "validate", fake_validate)

    state = _base_state(output=_agent_output_dict(retry_count=2))
    new_state = await graph_module.citation_validation_node(state)

    assert new_state["output"]["approved_by_enforcer"] is False
    assert new_state["output"]["retry_count"] == 3
    assert route_citation_result(new_state) == "failed"
