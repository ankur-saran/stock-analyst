"""
Integration tests for the KPI Tracker agent and its DB tools.

Prerequisites:
  - Postgres running and migrated: alembic upgrade head
  - Qdrant running and reachable at settings.qdrant_host:settings.qdrant_port
  - Ollama running at settings.ollama_base_url with `nomic-embed-text:v1.5` pulled
    (same as tests/integration/test_retriever.py)

The SECONDARY-tier (GPT-4o) extraction call is monkeypatched with a
deterministic, per-document response rather than hitting a live LiteLLM
proxy -- every other seam (Postgres writes, Qdrant indexing, hybrid
retrieval, KPI normalization, upsert idempotency/restatement, YoY
computation) runs against real services. This keeps the suite fast, free of
LLM cost/flakiness, and deterministic while still exercising the full
non-LLM pipeline for real -- the same boundary tests/unit/test_lynch_pitch_agent.py
mocks for the PRIMARY tier.

Run:
    alembic upgrade head
    pytest tests/integration/test_kpi_tracker.py -v
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from qdrant_client import QdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag.connectors.qdrant_client import QdrantConnector
from rag.ingestion.chunkers.hierarchical import Chunk
from rag.ingestion.pipeline import EmbeddingPipeline
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.config import Settings
from shared.models import (
    Coverage,
    CoverageStatusEnum,
    Document,
    IngestStatusEnum,
    KpiTimeseries,
    PeriodTypeEnum,
    PlanEnum,
    Tenant,
    User,
    UserRoleEnum,
)

from agents.kpi_tracker.agent import KPITrackerAgent
from agents.kpi_tracker.tools import compute_yoy_change, upsert_kpi_timeseries
from agents.shared.message import AgentMessage, AgentType

settings = Settings()

# ── Agent-run fixture identifiers (Qdrant-backed, one shared coverage) ───────
AGENT_TENANT_ID = str(uuid.uuid4())
AGENT_USER_ID = str(uuid.uuid4())
AGENT_COVERAGE_ID = str(uuid.uuid4())

_FILINGS = [
    {"year": "FY2021", "document_id": str(uuid.uuid4()), "revenue": "$300.0 billion",
     "gross_margin": "40.0%", "net_income": "$50.0 billion"},
    {"year": "FY2022", "document_id": str(uuid.uuid4()), "revenue": "$350.0 billion",
     "gross_margin": "42.0%", "net_income": "$55.0 billion"},
    {"year": "FY2023", "document_id": str(uuid.uuid4()), "revenue": "$394.3 billion",
     "gross_margin": "45.2%", "net_income": "$60.0 billion"},
]

# ── Tools-only fixture identifiers (pure Postgres, no Qdrant needed) ────────
TOOLS_TENANT_ID = str(uuid.uuid4())
TOOLS_USER_ID = str(uuid.uuid4())
TOOLS_COVERAGE_ID = str(uuid.uuid4())


def _file_name(filing: dict[str, str]) -> str:
    return f"AAPL_10K_{filing['year']}.pdf"


def _passage(filing: dict[str, str]) -> str:
    return (
        f"Total net revenue for {filing['year']} was {filing['revenue']}. "
        f"Gross margin was {filing['gross_margin']} for {filing['year']}. "
        f"Net income was {filing['net_income']} for {filing['year']}."
    )


def _make_chunk(filing: dict[str, str]) -> Chunk:
    metadata = {
        "document_id": filing["document_id"],
        "document_name": _file_name(filing),
        "filing_type": "10-K",
        "period": filing["year"],
        "section_name": "mda",
        "tenant_id": AGENT_TENANT_ID,
        "coverage_id": AGENT_COVERAGE_ID,
        "page_number": 28,
        "chunk_type": "child",
        "parent_chunk_id": None,
        "char_start": 0,
        "char_end": len(_passage(filing)),
        "token_estimate": len(_passage(filing).split()),
    }
    return Chunk(
        chunk_id=str(uuid.uuid4()),
        content=_passage(filing),
        chunk_type="child",
        parent_chunk_id=None,
        metadata=metadata,
    )


def _fake_extraction_response(filing: dict[str, str]) -> str:
    doc_name = _file_name(filing)
    items = [
        {"kpi_name": "revenue", "raw_value": filing["revenue"], "period": filing["year"],
         "exact_quote": f"Total net revenue for {filing['year']} was {filing['revenue']}.",
         "document_name": doc_name, "section": "mda", "page_number": 28},
        {"kpi_name": "gross_margin", "raw_value": filing["gross_margin"], "period": filing["year"],
         "exact_quote": f"Gross margin was {filing['gross_margin']} for {filing['year']}.",
         "document_name": doc_name, "section": "mda", "page_number": 28},
        {"kpi_name": "net_income", "raw_value": filing["net_income"], "period": filing["year"],
         "exact_quote": f"Net income was {filing['net_income']} for {filing['year']}.",
         "document_name": doc_name, "section": "mda", "page_number": 28},
    ]
    return json.dumps({"kpis": items})


async def _seed_tenant_user_coverage(
    session: AsyncSession, tenant_id: str, user_id: str, coverage_id: str
) -> None:
    session.add(Tenant(id=uuid.UUID(tenant_id), name="Test Tenant", plan=PlanEnum.professional))
    session.add(
        User(
            id=uuid.UUID(user_id),
            tenant_id=uuid.UUID(tenant_id),
            email=f"{user_id}@example.com",
            role=UserRoleEnum.analyst,
        )
    )
    session.add(
        Coverage(
            id=uuid.UUID(coverage_id),
            tenant_id=uuid.UUID(tenant_id),
            ticker="AAPL",
            company_name="Apple Inc.",
            exchange="NASDAQ",
            industry_id=None,
            created_by=uuid.UUID(user_id),
            status=CoverageStatusEnum.active,
            document_count=0,
        )
    )
    await session.commit()


# ── Engine / session fixtures ────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def engine():
    eng = create_async_engine(settings.get_db_url(), pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="module")
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


# ── Agent-run fixtures (Qdrant + Postgres) ───────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def embedding_pipeline() -> EmbeddingPipeline:
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    return EmbeddingPipeline(ollama_url=settings.ollama_base_url, qdrant_client=client)


@pytest_asyncio.fixture(scope="module")
async def qdrant_connector() -> QdrantConnector:
    return QdrantConnector(host=settings.qdrant_host, port=settings.qdrant_port)


@pytest_asyncio.fixture(scope="module")
async def retriever(qdrant_connector: QdrantConnector, embedding_pipeline: EmbeddingPipeline) -> HybridRetriever:
    return HybridRetriever(qdrant=qdrant_connector, embedding_pipeline=embedding_pipeline)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def seeded_aapl_coverage(session_factory, embedding_pipeline: EmbeddingPipeline):
    """Tenant/user/coverage + 3 indexed 10-K documents, with matching Qdrant chunks."""
    async with session_factory() as session:
        await _seed_tenant_user_coverage(session, AGENT_TENANT_ID, AGENT_USER_ID, AGENT_COVERAGE_ID)
        for filing in _FILINGS:
            session.add(
                Document(
                    id=uuid.UUID(filing["document_id"]),
                    coverage_id=uuid.UUID(AGENT_COVERAGE_ID),
                    tenant_id=uuid.UUID(AGENT_TENANT_ID),
                    file_name=_file_name(filing),
                    filing_type="10-K",
                    period=filing["year"],
                    source="test",
                    storage_path=f"test/{_file_name(filing)}",
                    ingest_status=IngestStatusEnum.indexed,
                    ingested_at=datetime.now(timezone.utc),
                )
            )
        await session.commit()

    chunks = [_make_chunk(filing) for filing in _FILINGS]
    await embedding_pipeline.index_chunks(chunks, AGENT_TENANT_ID)
    yield


@pytest_asyncio.fixture()
async def agent_db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture()
def kpi_tracker_agent(agent_db_session: AsyncSession, retriever: HybridRetriever, monkeypatch: pytest.MonkeyPatch) -> KPITrackerAgent:
    agent = KPITrackerAgent(db_session=agent_db_session, retriever=retriever)

    async def _fake_call_llm(messages, tier, max_tokens=4096, extended_thinking=False, response_format=None):
        user_content = messages[-1]["content"]
        for filing in _FILINGS:
            if _file_name(filing) in user_content:
                return _fake_extraction_response(filing), "gpt-4o-test", 123
        return json.dumps({"kpis": []}), "gpt-4o-test", 10

    monkeypatch.setattr(agent, "_call_llm", _fake_call_llm)
    return agent


# ── Tools-only fixtures (Postgres only, no Qdrant) ──────────────────────────


@pytest_asyncio.fixture(scope="module", autouse=True)
async def seeded_tools_coverage(session_factory):
    async with session_factory() as session:
        await _seed_tenant_user_coverage(session, TOOLS_TENANT_ID, TOOLS_USER_ID, TOOLS_COVERAGE_ID)
    yield


@pytest_asyncio.fixture()
async def tools_db_session(session_factory):
    async with session_factory() as session:
        yield session


def _revenue_kpi(period: str, value: float) -> dict:
    return {
        "kpi_name": "revenue",
        "period": period,
        "period_type": PeriodTypeEnum.annual,
        "value": value,
        "unit": "USD_millions",
        "citation": {
            "document_name": f"AAPL_10K_{period}.pdf",
            "section": "mda",
            "page_number": 28,
            "exact_quote": f"Total net revenue for {period} was ${value} million.",
            "raw_value": f"${value} million",
        },
    }


# ── 1 & 2. Full agent run populates 3 years of KPIs, each with a citation ───


@pytest.mark.asyncio
async def test_kpi_tracker_agent_populates_three_years_of_kpis(
    kpi_tracker_agent: KPITrackerAgent, agent_db_session: AsyncSession
) -> None:
    message = AgentMessage(
        sender=AgentType.ORCHESTRATOR,
        recipient=AgentType.KPI_TRACKER,
        task_id=str(uuid.uuid4()),
        coverage_id=AGENT_COVERAGE_ID,
        tenant_id=AGENT_TENANT_ID,
        payload={},
    )

    output = await kpi_tracker_agent._execute(message)
    assert output.approved_by_enforcer is True

    rows = (
        await agent_db_session.execute(
            select(KpiTimeseries).where(
                KpiTimeseries.coverage_id == uuid.UUID(AGENT_COVERAGE_ID),
                KpiTimeseries.kpi_name.in_(["revenue", "gross_margin", "net_income"]),
            )
        )
    ).scalars().all()

    assert len(rows) == 9  # 3 KPIs x 3 fiscal years

    revenue_rows = {r.period: r for r in rows if r.kpi_name == "revenue"}
    assert set(revenue_rows) == {"FY2021", "FY2022", "FY2023"}
    assert revenue_rows["FY2023"].value == pytest.approx(394300.0)

    for row in rows:
        assert row.citation["document_name"].startswith("AAPL_10K_")
        assert row.citation["exact_quote"]


# ── 3. compute_yoy_change returns correct periods for revenue ───────────────


@pytest.mark.asyncio
async def test_compute_yoy_change_for_revenue(agent_db_session: AsyncSession) -> None:
    yoy = await compute_yoy_change(AGENT_COVERAGE_ID, "revenue", agent_db_session)

    assert yoy is not None
    assert yoy["prior_period"] == "FY2022"
    assert yoy["current_period"] == "FY2023"
    expected_pct = (394300.0 - 350000.0) / 350000.0 * 100
    assert yoy["yoy_change_pct"] == pytest.approx(expected_pct, rel=1e-6)


# ── 4. Upserting the same value twice is idempotent ─────────────────────────


@pytest.mark.asyncio
async def test_upsert_kpi_timeseries_is_idempotent(tools_db_session: AsyncSession) -> None:
    kpi_data = [_revenue_kpi("FY2020", 200000.0)]

    first_count = await upsert_kpi_timeseries(TOOLS_COVERAGE_ID, kpi_data, tools_db_session)
    second_count = await upsert_kpi_timeseries(TOOLS_COVERAGE_ID, kpi_data, tools_db_session)

    assert first_count == 1
    assert second_count == 0  # identical value already recorded -- no-op

    rows = (
        await tools_db_session.execute(
            select(KpiTimeseries).where(
                KpiTimeseries.coverage_id == uuid.UUID(TOOLS_COVERAGE_ID),
                KpiTimeseries.kpi_name == "revenue",
                KpiTimeseries.period == "FY2020",
            )
        )
    ).scalars().all()
    assert len(rows) == 1


# ── 5. Upserting a different value for the same period marks a restatement ─


@pytest.mark.asyncio
async def test_upsert_kpi_timeseries_marks_restatement(tools_db_session: AsyncSession) -> None:
    await upsert_kpi_timeseries(TOOLS_COVERAGE_ID, [_revenue_kpi("FY2019", 100000.0)], tools_db_session)

    count = await upsert_kpi_timeseries(
        TOOLS_COVERAGE_ID, [_revenue_kpi("FY2019", 110000.0)], tools_db_session
    )
    assert count == 1

    rows = (
        (
            await tools_db_session.execute(
                select(KpiTimeseries)
                .where(
                    KpiTimeseries.coverage_id == uuid.UUID(TOOLS_COVERAGE_ID),
                    KpiTimeseries.kpi_name == "revenue",
                    KpiTimeseries.period == "FY2019",
                )
                .order_by(KpiTimeseries.extracted_at.desc())
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 2
    newest = rows[0]
    assert newest.value == pytest.approx(110000.0)
    assert newest.is_restated is True
    assert newest.restatement_note is not None
