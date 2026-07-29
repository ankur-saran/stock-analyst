"""Analyst notes: one free-form content blob per coverage.

Edited via the Tiptap notes editor
(apps/web/components/notes/analyst-notes-editor.tsx) and autosaved every 2s
— POST is an upsert (unique on coverage_id), never an append, since the
editor always sends the full current document, not a delta.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from shared.models import CoverageNotes

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user, role_required
from apps.api.routers.outputs import _get_owned_coverage

router = APIRouter(prefix="/coverages", tags=["notes"])


class NotesUpdate(BaseModel):
    content: str


def _notes_dict(notes: CoverageNotes | None, coverage_id: uuid.UUID) -> dict[str, Any]:
    if notes is None:
        return {"coverage_id": str(coverage_id), "content": "", "updated_at": None}
    return {
        "coverage_id": str(notes.coverage_id),
        "content": notes.content,
        "updated_at": notes.updated_at.isoformat(),
    }


@router.get("/{coverage_id}/notes")
async def get_notes(
    coverage_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)
    notes = (
        await db.execute(select(CoverageNotes).where(CoverageNotes.coverage_id == coverage.id))
    ).scalar_one_or_none()
    return _notes_dict(notes, coverage.id)


@router.post("/{coverage_id}/notes")
async def upsert_notes(
    coverage_id: str,
    body: NotesUpdate,
    db: DbSession,
    current_user: CurrentUser = Depends(role_required("analyst")),
) -> dict[str, Any]:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)
    notes = (
        await db.execute(select(CoverageNotes).where(CoverageNotes.coverage_id == coverage.id))
    ).scalar_one_or_none()

    if notes is None:
        notes = CoverageNotes(
            id=uuid.uuid4(),
            coverage_id=coverage.id,
            tenant_id=current_user.tenant_id,
            content=body.content,
        )
        db.add(notes)
    else:
        notes.content = body.content

    await db.flush()
    await db.refresh(notes)
    return _notes_dict(notes, coverage.id)
