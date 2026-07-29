"""Admin-only endpoints: tenant list, LLM usage/cost reporting, agent health.

`/usage` deliberately queries through a bare session (`AsyncSessionLocal`,
no `SET LOCAL app.current_tenant_id`) rather than the request-scoped
`DbSession` every other router uses -- an admin cost report is inherently
cross-tenant, and `DbSession` would only ever see the calling admin's own
tenant under RLS. Every other tenant-scoped table's isolation in this app
comes from two layers: Postgres RLS *and* an explicit `tenant_id` check in
the router (see `outputs._get_owned_coverage`); this endpoint is one of the
few places relying on the second layer alone, gated by `role_required("admin")`.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from shared.models import AgentAuditLog, Coverage, Tenant

from apps.api.db import AsyncSessionLocal
from apps.api.middleware.auth import CurrentUser, role_required

router = APIRouter(prefix="/admin", tags=["admin"])

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


# ── Cost estimation ──────────────────────────────────────────────────────────
# Prices as of 2026-07-29 ($ per 1M tokens) -- MUST be refreshed quarterly as
# vendor pricing changes; there is no live pricing API wired up here.
_INPUT_PRICE_PER_1M = {"claude": 15.00, "gpt-4o": 2.50}
_OUTPUT_PRICE_PER_1M = {"claude": 75.00, "gpt-4o": 10.00}

# agent_audit_log stores one combined `tokens_used`, not an input/output
# split, so cost estimation blends the two rates at a fixed 75/25
# input/output ratio -- an approximation of this platform's actual usage
# pattern (large retrieved context in, concise cited prose out), not an
# exact figure. "local" (Ollama) models are treated as free.
_BLENDED_PRICE_PER_1M = {
    model: 0.75 * _INPUT_PRICE_PER_1M[model] + 0.25 * _OUTPUT_PRICE_PER_1M[model]
    for model in _INPUT_PRICE_PER_1M
}

_USAGE_WINDOW_DAYS = 365


def _classify_model(llm_used: str | None) -> str:
    if not llm_used:
        return "local"
    lowered = llm_used.lower()
    if "claude" in lowered:
        return "claude"
    if "gpt" in lowered:
        return "gpt-4o"
    return "local"


def _cost_usd(llm_used: str | None, tokens_used: int) -> float:
    price_per_1m = _BLENDED_PRICE_PER_1M.get(_classify_model(llm_used), 0.0)
    return (tokens_used / 1_000_000) * price_per_1m


@router.get("/tenants")
async def list_tenants():
    return _501


@router.get("/usage")
async def get_usage(current_user: CurrentUser = Depends(role_required("admin"))) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=_USAGE_WINDOW_DAYS)

    async with AsyncSessionLocal() as session:
        tenants = (await session.execute(select(Tenant))).scalars().all()
        logs = (
            (await session.execute(select(AgentAuditLog).where(AgentAuditLog.created_at >= since)))
            .scalars()
            .all()
        )

        coverage_ids = {log.coverage_id for log in logs if log.coverage_id is not None}
        coverage_tickers: dict[uuid.UUID, str] = {}
        if coverage_ids:
            coverages = (
                (await session.execute(select(Coverage).where(Coverage.id.in_(coverage_ids))))
                .scalars()
                .all()
            )
            coverage_tickers = {c.id: c.ticker for c in coverages}

    monthly: dict[uuid.UUID, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_model: dict[uuid.UUID, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"tokens_used": 0.0, "cost_usd": 0.0})
    )
    by_coverage: dict[uuid.UUID, dict[uuid.UUID, dict[str, Any]]] = defaultdict(dict)

    for log in logs:
        cost = _cost_usd(log.llm_used, log.tokens_used)
        month_key = log.created_at.strftime("%Y-%m")
        monthly[log.tenant_id][month_key] += cost

        model = _classify_model(log.llm_used)
        model_bucket = by_model[log.tenant_id][model]
        model_bucket["tokens_used"] += log.tokens_used
        model_bucket["cost_usd"] += cost

        if log.coverage_id is not None:
            coverage_bucket = by_coverage[log.tenant_id].setdefault(
                log.coverage_id,
                {
                    "coverage_id": str(log.coverage_id),
                    "ticker": coverage_tickers.get(log.coverage_id, "Unknown"),
                    "tokens_used": 0,
                    "cost_usd": 0.0,
                },
            )
            coverage_bucket["tokens_used"] += log.tokens_used
            coverage_bucket["cost_usd"] += cost

    result_tenants = []
    for tenant in tenants:
        month_costs = monthly.get(tenant.id, {})
        model_costs = by_model.get(tenant.id, {})
        coverage_costs = by_coverage.get(tenant.id, {})

        result_tenants.append(
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "monthly_costs": [
                    {"month": month, "cost_usd": round(cost, 2)}
                    for month, cost in sorted(month_costs.items())
                ],
                "by_model": [
                    {
                        "llm_used": model,
                        "tokens_used": int(bucket["tokens_used"]),
                        "cost_usd": round(bucket["cost_usd"], 2),
                    }
                    for model, bucket in sorted(model_costs.items())
                ],
                "by_coverage": sorted(
                    (
                        {**bucket, "cost_usd": round(bucket["cost_usd"], 2)}
                        for bucket in coverage_costs.values()
                    ),
                    key=lambda b: -b["cost_usd"],
                ),
                "alert_threshold_usd": tenant.settings.get("alert_threshold_usd"),
            }
        )

    return {"tenants": result_tenants}


class AlertThresholdUpdate(BaseModel):
    alert_threshold_usd: float | None = None


@router.put("/tenants/{tenant_id}/alert-threshold")
async def set_alert_threshold(
    tenant_id: str,
    body: AlertThresholdUpdate,
    current_user: CurrentUser = Depends(role_required("admin")),
) -> dict[str, Any]:
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise _problem(404, "Not Found", "Tenant not found")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            tenant = await session.get(Tenant, tenant_uuid)
            if tenant is None:
                raise _problem(404, "Not Found", "Tenant not found")
            tenant.settings = {**tenant.settings, "alert_threshold_usd": body.alert_threshold_usd}

    return {"tenant_id": tenant_id, "alert_threshold_usd": body.alert_threshold_usd}


@router.get("/agents/health")
async def agents_health():
    return _501
