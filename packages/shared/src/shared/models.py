"""
SQLAlchemy ORM models and Pydantic schemas for the Stock Analyst platform.

Tables are defined in FK-safe order:
  tenants → users → industries → coverages → documents
  → research_outputs → kpi_timeseries → agent_audit_log → task_queue
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Python enums — inherited by both SQLAlchemy columns and Pydantic schemas
# ---------------------------------------------------------------------------

class PlanEnum(str, enum.Enum):
    starter = "starter"
    professional = "professional"
    enterprise = "enterprise"


class UserRoleEnum(str, enum.Enum):
    viewer = "viewer"
    analyst = "analyst"
    senior_analyst = "senior_analyst"
    admin = "admin"


class CoverageStatusEnum(str, enum.Enum):
    setup = "setup"
    active = "active"
    archived = "archived"


class IngestStatusEnum(str, enum.Enum):
    pending = "pending"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"
    review_needed = "review_needed"


class OutputTypeEnum(str, enum.Enum):
    industry_primer = "industry_primer"
    lynch_pitch = "lynch_pitch"
    munger_invert = "munger_invert"
    quarterly_update = "quarterly_update"
    kpi_snapshot = "kpi_snapshot"


class EnforcerStatusEnum(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    partial = "partial"
    failed = "failed"


class PeriodTypeEnum(str, enum.Enum):
    annual = "annual"
    quarterly = "quarterly"


class TaskStatusEnum(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[PlanEnum] = mapped_column(
        SAEnum(PlanEnum, name="plan_enum"), nullable=False
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    users: Mapped[list[User]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    coverages: Mapped[list[Coverage]] = relationship(
        "Coverage", back_populates="tenant", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[UserRoleEnum] = mapped_column(
        SAEnum(UserRoleEnum, name="user_role_enum"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="users")


class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    primer_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    primer_citations: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    coverages: Mapped[list[Coverage]] = relationship(
        "Coverage", back_populates="industry"
    )


class Coverage(Base):
    __tablename__ = "coverages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "ticker", "exchange", name="uq_coverage_tenant_ticker_exchange"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    industry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("industries.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[CoverageStatusEnum] = mapped_column(
        SAEnum(CoverageStatusEnum, name="coverage_status_enum"),
        default=CoverageStatusEnum.setup,
        server_default="setup",
    )
    document_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    last_updated: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="coverages")
    industry: Mapped[Optional[Industry]] = relationship(
        "Industry", back_populates="coverages"
    )
    documents: Mapped[list[Document]] = relationship(
        "Document", back_populates="coverage", cascade="all, delete-orphan"
    )
    research_outputs: Mapped[list[ResearchOutput]] = relationship(
        "ResearchOutput", back_populates="coverage", cascade="all, delete-orphan"
    )
    kpi_timeseries: Mapped[list[KpiTimeseries]] = relationship(
        "KpiTimeseries", back_populates="coverage", cascade="all, delete-orphan"
    )
    task_queue: Mapped[list[TaskQueue]] = relationship(
        "TaskQueue", back_populates="coverage", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    coverage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coverages.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    filing_type: Mapped[str] = mapped_column(String(50), nullable=False)
    period: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ingested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ingest_status: Mapped[IngestStatusEnum] = mapped_column(
        SAEnum(IngestStatusEnum, name="ingest_status_enum"),
        default=IngestStatusEnum.pending,
        server_default="pending",
    )
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    coverage: Mapped[Coverage] = relationship("Coverage", back_populates="documents")


class ResearchOutput(Base):
    __tablename__ = "research_outputs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    coverage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coverages.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    output_type: Mapped[OutputTypeEnum] = mapped_column(
        SAEnum(OutputTypeEnum, name="output_type_enum"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    citation_coverage_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    approved_by_enforcer: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    enforcer_status: Mapped[EnforcerStatusEnum] = mapped_column(
        SAEnum(EnforcerStatusEnum, name="enforcer_status_enum"),
        default=EnforcerStatusEnum.pending,
        server_default="pending",
    )
    llm_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Accumulates cross-quarter tracking data (e.g. Earnings Monitor's
    # management credibility verdict per quarter) that doesn't belong in the
    # citation-checked `content` prose itself.
    output_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )

    coverage: Mapped[Coverage] = relationship(
        "Coverage", back_populates="research_outputs"
    )


class KpiTimeseries(Base):
    __tablename__ = "kpi_timeseries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    coverage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coverages.id", ondelete="CASCADE"),
        nullable=False,
    )
    kpi_name: Mapped[str] = mapped_column(String(100), nullable=False)
    period: Mapped[str] = mapped_column(String(50), nullable=False)
    period_type: Mapped[PeriodTypeEnum] = mapped_column(
        SAEnum(PeriodTypeEnum, name="period_type_enum"), nullable=False
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    citation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_restated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    restatement_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    coverage: Mapped[Coverage] = relationship(
        "Coverage", back_populates="kpi_timeseries"
    )


class AgentAuditLog(Base):
    __tablename__ = "agent_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Intentionally no FK so the log survives tenant deletion.
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    coverage_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    output_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    llm_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Python attr name avoids clash with DeclarativeBase.metadata class attribute.
    log_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )


class TaskQueue(Base):
    __tablename__ = "task_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    coverage_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coverages.id", ondelete="CASCADE"),
        nullable=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[TaskStatusEnum] = mapped_column(
        SAEnum(TaskStatusEnum, name="task_status_enum"),
        default=TaskStatusEnum.queued,
        server_default="queued",
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    coverage: Mapped[Optional[Coverage]] = relationship(
        "Coverage", back_populates="task_queue"
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class _OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Tenant ---

class TenantCreate(_OrmBase):
    name: str
    plan: PlanEnum
    settings: dict[str, Any] = {}


class TenantRead(TenantCreate):
    id: uuid.UUID
    created_at: datetime


# --- User ---

class UserCreate(_OrmBase):
    tenant_id: uuid.UUID
    email: str
    role: UserRoleEnum


class UserRead(UserCreate):
    id: uuid.UUID
    created_at: datetime


# --- Industry ---

class IndustryCreate(_OrmBase):
    name: str


class IndustryRead(IndustryCreate):
    id: uuid.UUID
    primer_content: Optional[str] = None
    primer_citations: list[Any] = []
    word_count: Optional[int] = None
    llm_used: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# --- Coverage ---

class CoverageCreate(_OrmBase):
    tenant_id: uuid.UUID
    ticker: str
    company_name: str
    exchange: str
    created_by: uuid.UUID
    industry_id: Optional[uuid.UUID] = None
    status: CoverageStatusEnum = CoverageStatusEnum.setup


class CoverageRead(CoverageCreate):
    id: uuid.UUID
    document_count: int
    last_updated: Optional[datetime] = None
    created_at: datetime


# --- Document ---

class DocumentCreate(_OrmBase):
    coverage_id: uuid.UUID
    tenant_id: uuid.UUID
    file_name: str
    filing_type: str
    period: str
    source: str
    storage_path: str
    source_url: Optional[str] = None
    file_hash: Optional[str] = None
    ingest_status: IngestStatusEnum = IngestStatusEnum.pending


class DocumentRead(DocumentCreate):
    id: uuid.UUID
    page_count: Optional[int] = None
    chunk_count: int
    ingested_at: Optional[datetime] = None
    quality_score: Optional[float] = None


# --- ResearchOutput ---

class ResearchOutputCreate(_OrmBase):
    coverage_id: uuid.UUID
    tenant_id: uuid.UUID
    output_type: OutputTypeEnum
    content: str
    citations: list[Any] = []
    llm_used: Optional[str] = None
    tokens_used: int = 0
    output_metadata: dict[str, Any] = {}


class ResearchOutputRead(ResearchOutputCreate):
    id: uuid.UUID
    citation_coverage_pct: Optional[float] = None
    approved_by_enforcer: bool
    enforcer_status: EnforcerStatusEnum
    generated_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[uuid.UUID] = None
    version: int


# --- KpiTimeseries ---

class KpiTimeseriesCreate(_OrmBase):
    coverage_id: uuid.UUID
    kpi_name: str
    period: str
    period_type: PeriodTypeEnum
    value: float
    unit: str
    citation: dict[str, Any]
    is_restated: bool = False
    restatement_note: Optional[str] = None


class KpiTimeseriesRead(KpiTimeseriesCreate):
    id: uuid.UUID
    extracted_at: datetime


# --- AgentAuditLog ---

class AgentAuditLogCreate(_OrmBase):
    tenant_id: uuid.UUID
    agent_name: str
    action: str
    coverage_id: Optional[uuid.UUID] = None
    input_hash: Optional[str] = None
    output_id: Optional[uuid.UUID] = None
    llm_used: Optional[str] = None
    tokens_used: int = 0
    latency_ms: Optional[int] = None
    log_metadata: dict[str, Any] = {}


class AgentAuditLogRead(AgentAuditLogCreate):
    id: uuid.UUID
    created_at: datetime


# --- TaskQueue ---

class TaskQueueCreate(_OrmBase):
    tenant_id: uuid.UUID
    task_type: str
    coverage_id: Optional[uuid.UUID] = None
    celery_task_id: Optional[str] = None


class TaskQueueRead(TaskQueueCreate):
    id: uuid.UUID
    status: TaskStatusEnum
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
