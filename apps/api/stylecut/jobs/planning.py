"""Plan Mode jobs: generate a shoot plan, or regenerate part of one."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from stylecut.api.style_profiles import effective_profile
from stylecut.db.models import Project, ShootPlanRow, StyleProfileRow
from stylecut.jobs.base import JobContext, JobTask
from stylecut.jobs.celery_app import celery_app
from stylecut.planning import generate
from stylecut.schemas.shoot_plan import (
    SCHEMA_VERSION,
    ProjectBrief,
    RegenerateScope,
    ShootPlan,
    migrate_shoot_plan,
)
from stylecut.schemas.style_profile import StyleProfile


class PlanJobError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


def load_context(session: Session, project_id: UUID) -> tuple[Project, StyleProfile, ProjectBrief]:
    project = session.get(Project, project_id)
    if project is None:
        raise PlanJobError("That project no longer exists.")
    row = (
        session.get(StyleProfileRow, project.style_profile_id)
        if project.style_profile_id is not None
        else None
    )
    if row is None:
        raise PlanJobError("This project's style was deleted. Pick another style for it.")
    return project, effective_profile(row), ProjectBrief.model_validate(project.brief)


def current_plan_row(session: Session, project_id: UUID) -> ShootPlanRow | None:
    return session.scalar(
        select(ShootPlanRow)
        .where(ShootPlanRow.project_id == project_id, ShootPlanRow.is_current.is_(True))
        .order_by(ShootPlanRow.version.desc())
        .limit(1)
    )


def load_plan(row: ShootPlanRow) -> ShootPlan:
    return ShootPlan.model_validate(migrate_shoot_plan(dict(row.data)))


def save_new_version(session: Session, project_id: UUID, plan: ShootPlan) -> ShootPlanRow:
    """Plans are versioned: the new one becomes current, earlier ones are kept."""
    latest = session.scalar(
        select(func.max(ShootPlanRow.version)).where(ShootPlanRow.project_id == project_id)
    )
    session.execute(
        update(ShootPlanRow).where(ShootPlanRow.project_id == project_id).values(is_current=False)
    )
    row = ShootPlanRow(
        project_id=project_id,
        version=(latest or 0) + 1,
        data=plan.model_dump(mode="json"),
        is_current=True,
    )
    session.add(row)
    session.commit()
    return row


@celery_app.task(name="llm.generate_shoot_plan", base=JobTask)
def generate_shoot_plan(
    ctx: JobContext, project_id: str, instruction: str | None = None
) -> dict[str, Any]:
    ctx.progress(0.05, "Reading the style")
    project, profile, brief = load_context(ctx.session, UUID(project_id))
    ctx.progress(0.15, "Writing the script and shot list")
    plan = generate.generate_plan(
        project_id=project.id, profile=profile, brief=brief, session=ctx.session,
        job_id=ctx.job_id, instruction=instruction,
    )  # fmt: skip
    ctx.progress(0.95, "Ordering the shoot")
    row = save_new_version(ctx.session, project.id, plan)
    return {"version": row.version, "warnings": len(plan.warnings), "schema": SCHEMA_VERSION}


@celery_app.task(name="llm.regenerate_shoot_plan", base=JobTask)
def regenerate_shoot_plan(
    ctx: JobContext,
    project_id: str,
    scope: RegenerateScope,
    target_id: str | None = None,
    instruction: str | None = None,
) -> dict[str, Any]:
    ctx.progress(0.05, "Reading the plan")
    project, profile, brief = load_context(ctx.session, UUID(project_id))
    row = current_plan_row(ctx.session, project.id)
    if scope == "all" or row is None:
        ctx.progress(0.15, "Writing a new plan")
        plan = generate.generate_plan(
            project_id=project.id, profile=profile, brief=brief, session=ctx.session,
            job_id=ctx.job_id, instruction=instruction,
        )  # fmt: skip
    else:
        ctx.progress(0.15, "Writing another option")
        plan = generate.regenerate_part(
            plan=load_plan(row), profile=profile, brief=brief, scope=scope,
            target_id=target_id, instruction=instruction, session=ctx.session,
            job_id=ctx.job_id,
        )  # fmt: skip
    new_row = save_new_version(ctx.session, project.id, plan)
    return {"version": new_row.version, "warnings": len(plan.warnings)}
