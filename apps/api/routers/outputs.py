"""Research output retrieval — read-only access to research_outputs rows.

Nested under /coverages like documents.py. Writes happen exclusively through
the agent pipeline (``agents.orchestrator.tasks._run_agent``), which is the
only path that runs the Citation Enforcer before a row lands here — POST
stays a 501 stub so a client can never insert unvalidated content directly.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from shared.models import Coverage, OutputTypeEnum, ResearchOutput

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user
from apps.api.services.report_generator import NoApprovedOutputsError, ReportGenerator

router = APIRouter(prefix="/coverages", tags=["outputs"])

_501 = JSONResponse(
    status_code=501,
    content={
        "type": "https://stockanalyst.ai/errors/not-implemented",
        "title": "Not Implemented",
        "status": 501,
        "detail": "This endpoint is not yet implemented",
    },
)


def _problem(status: int, title: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "type": f"https://stockanalyst.ai/errors/{title.lower().replace(' ', '-')}",
            "title": title,
            "status": status,
            "detail": detail,
        },
    )


async def _get_owned_coverage(db: DbSession, coverage_id: str, tenant_id: uuid.UUID) -> Coverage:
    try:
        coverage_uuid = uuid.UUID(coverage_id)
    except ValueError:
        raise _problem(404, "Not Found", "Coverage not found")

    coverage = await db.get(Coverage, coverage_uuid)
    if coverage is None or coverage.tenant_id != tenant_id:
        raise _problem(404, "Not Found", "Coverage not found")
    return coverage


def _output_dict(o: ResearchOutput) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "coverage_id": str(o.coverage_id),
        "output_type": o.output_type.value,
        "content": o.content,
        "citations": o.citations,
        "citation_coverage_pct": o.citation_coverage_pct,
        "approved_by_enforcer": o.approved_by_enforcer,
        "enforcer_status": o.enforcer_status.value,
        "llm_used": o.llm_used,
        "tokens_used": o.tokens_used,
        "generated_at": o.generated_at.isoformat(),
        "approved_at": o.approved_at.isoformat() if o.approved_at else None,
        "version": o.version,
        "output_metadata": o.output_metadata,
    }


@router.get("/{coverage_id}/outputs")
async def list_outputs(
    coverage_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
    output_type: OutputTypeEnum | None = None,
) -> list[dict[str, Any]]:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)

    stmt = select(ResearchOutput).where(ResearchOutput.coverage_id == coverage.id)
    if output_type is not None:
        stmt = stmt.where(ResearchOutput.output_type == output_type)
    stmt = stmt.order_by(ResearchOutput.generated_at.desc())

    rows = (await db.execute(stmt)).scalars().all()
    return [_output_dict(o) for o in rows]


@router.get("/{coverage_id}/outputs/{output_id}")
async def get_output(
    coverage_id: str,
    output_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)

    try:
        output_uuid = uuid.UUID(output_id)
    except ValueError:
        raise _problem(404, "Not Found", "Output not found")

    output = await db.get(ResearchOutput, output_uuid)
    if output is None or output.coverage_id != coverage.id:
        raise _problem(404, "Not Found", "Output not found")

    return _output_dict(output)


@router.post("/{coverage_id}/outputs/{output_id}")
async def create_output(coverage_id: str, output_id: str):
    return _501


@router.get("/{coverage_id}/report.pdf")
async def download_report(
    coverage_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
    sections: str | None = None,
) -> Response:
    """Full coverage PDF report. No role floor beyond authentication — every
    role including viewer may download (per TASK 1 spec: "viewer minimum").
    """
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)

    include_sections: list[str] | None = None
    if sections:
        include_sections = [s.strip() for s in sections.split(",") if s.strip()]
        valid_values = {e.value for e in OutputTypeEnum}
        invalid = [s for s in include_sections if s not in valid_values]
        if invalid:
            raise _problem(
                422, "Unprocessable Entity", f"Invalid section(s): {', '.join(invalid)}"
            )

    try:
        pdf_bytes = await ReportGenerator().generate_coverage_report(
            db=db,
            coverage_id=str(coverage.id),
            tenant_id=str(current_user.tenant_id),
            include_sections=include_sections,
        )
    except NoApprovedOutputsError:
        raise _problem(404, "Not Found", "No approved research outputs found")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{coverage.ticker}_report.pdf"'},
    )
