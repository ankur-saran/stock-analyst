"""
Development seed script.

Creates:
  - 2 tenants:  Acme Capital (tenant-a), Beta Fund (tenant-b)
  - 4 users in tenant-a: one per role
  - 1 admin user in tenant-b
  - 3 industries: Enterprise Software, Semiconductor Capital Equipment, Regional Banking

Run from the project root:
    python scripts/seed_dev.py

Pass --force to drop existing seed data and re-seed:
    python scripts/seed_dev.py --force
"""

from __future__ import annotations

import asyncio
import sys
import os

# Make `shared` importable from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "shared", "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.config import Settings
from shared.models import (
    Industry,
    PlanEnum,
    Tenant,
    User,
    UserRoleEnum,
)

_TENANT_A_NAME = "Acme Capital"
_TENANT_B_NAME = "Beta Fund"


async def seed(force: bool = False) -> None:
    settings = Settings()
    engine = create_async_engine(settings.get_db_url(), echo=False)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            # ── Pre-flight: check for existing seed data ───────────────────────
            existing = (
                await session.execute(
                    select(Tenant).where(Tenant.name.in_([_TENANT_A_NAME, _TENANT_B_NAME]))
                )
            ).scalars().all()

            if existing and not force:
                print(
                    "Seed data already present "
                    f"({[t.name for t in existing]}). "
                    "Pass --force to re-seed."
                )
                return

            if existing and force:
                print("--force: removing existing seed tenants (cascade deletes users)…")
                for tenant in existing:
                    await session.delete(tenant)
                # Industries have no tenant FK — remove by name.
                existing_industries = (
                    await session.execute(
                        select(Industry).where(
                            Industry.name.in_([
                                "Enterprise Software",
                                "Semiconductor Capital Equipment",
                                "Regional Banking",
                            ])
                        )
                    )
                ).scalars().all()
                for ind in existing_industries:
                    await session.delete(ind)
                await session.commit()

            # ── Tenants ────────────────────────────────────────────────────────
            async with session.begin():
                tenant_a = Tenant(name=_TENANT_A_NAME, plan=PlanEnum.professional)
                tenant_b = Tenant(name=_TENANT_B_NAME, plan=PlanEnum.starter)
                session.add_all([tenant_a, tenant_b])
                await session.flush()  # resolves server-side defaults (created_at)

                # ── Users in tenant-a — one per role ──────────────────────────
                users_a = [
                    User(
                        tenant_id=tenant_a.id,
                        email="viewer@acme.example",
                        role=UserRoleEnum.viewer,
                    ),
                    User(
                        tenant_id=tenant_a.id,
                        email="analyst@acme.example",
                        role=UserRoleEnum.analyst,
                    ),
                    User(
                        tenant_id=tenant_a.id,
                        email="senior@acme.example",
                        role=UserRoleEnum.senior_analyst,
                    ),
                    User(
                        tenant_id=tenant_a.id,
                        email="admin@acme.example",
                        role=UserRoleEnum.admin,
                    ),
                ]
                session.add_all(users_a)

                # ── User in tenant-b — admin only ─────────────────────────────
                user_b_admin = User(
                    tenant_id=tenant_b.id,
                    email="admin@beta.example",
                    role=UserRoleEnum.admin,
                )
                session.add(user_b_admin)

                # ── Industries (no tenant FK) ──────────────────────────────────
                industries = [
                    Industry(name="Enterprise Software"),
                    Industry(name="Semiconductor Capital Equipment"),
                    Industry(name="Regional Banking"),
                ]
                session.add_all(industries)

                await session.flush()
            # transaction committed on __aexit__

    finally:
        await engine.dispose()

    # ── Print created IDs ──────────────────────────────────────────────────────
    _sep = "─" * 60
    print(f"\n{_sep}")
    print("  Seed complete")
    print(_sep)

    print("\nTENANTS")
    print(f"  {'Name':<30} {'Plan':<14} ID")
    print(f"  {_sep}")
    print(f"  {tenant_a.name:<30} {tenant_a.plan.value:<14} {tenant_a.id}")
    print(f"  {tenant_b.name:<30} {tenant_b.plan.value:<14} {tenant_b.id}")

    print("\nUSERS — Acme Capital (tenant-a)")
    print(f"  {'Role':<18} {'Email':<30} ID")
    print(f"  {_sep}")
    for u in users_a:
        print(f"  {u.role.value:<18} {u.email:<30} {u.id}")

    print("\nUSERS — Beta Fund (tenant-b)")
    print(f"  {'Role':<18} {'Email':<30} ID")
    print(f"  {_sep}")
    print(f"  {user_b_admin.role.value:<18} {user_b_admin.email:<30} {user_b_admin.id}")

    print("\nINDUSTRIES")
    print(f"  {'Name':<40} ID")
    print(f"  {_sep}")
    for ind in industries:
        print(f"  {ind.name:<40} {ind.id}")

    print(f"\n{_sep}\n")

    # Emit shell-friendly env-var hints for use in manual RLS testing
    print("# Copy these for RLS isolation tests:")
    print(f'export TENANT_A_ID="{tenant_a.id}"')
    print(f'export TENANT_B_ID="{tenant_b.id}"')


if __name__ == "__main__":
    _force = "--force" in sys.argv
    asyncio.run(seed(force=_force))
