"""Projects and Plan Mode."""

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from stylecut.api.deps import current_user_id
from stylecut.api.errors import ApiError, not_found
from stylecut.api.style_profiles import effective_profile
from stylecut.db.models import Job, Project, ShootPlanRow, StyleProfileRow
from stylecut.db.session import get_db
from stylecut.jobs.base import enqueue
from stylecut.jobs.planning import (
    current_plan_row,
    generate_shoot_plan,
    load_plan,
    regenerate_shoot_plan,
)
from stylecut.planning import generate
from stylecut.planning.pdf import render_plan_pdf
from stylecut.planning.validate import script_word_count
from stylecut.schemas.jobs import JobAccepted
from stylecut.schemas.project_api import (
    PlanBeat,
    PlanStyle,
    ProjectCreateIn,
    ProjectOut,
    ProjectPatch,
    RegenerateIn,
    ShareOut,
    ShootPlanOut,
    ShootPlanPatch,
)
from stylecut.schemas.shoot_plan import ProjectBrief, ShootPlan
from stylecut.schemas.style_profile import StyleProfile

router = APIRouter(tags=["projects"])
public_router = APIRouter(tags=["share"])

PLAN_JOB_TYPES = (generate_shoot_plan.name, regenerate_shoot_plan.name)


def _owned(session: Session, project_id: UUID, user_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise not_found("project")
    return project


def _style_row(session: Session, project: Project) -> StyleProfileRow | None:
    if project.style_profile_id is None:
        return None
    return session.get(StyleProfileRow, project.style_profile_id)


def _latest_plan_job(session: Session, project: Project) -> UUID | None:
    return session.scalar(
        select(Job.id)
        .where(Job.type.in_(PLAN_JOB_TYPES), Job.input["project_id"].astext == str(project.id))
        .order_by(Job.created_at.desc())
        .limit(1)
    )


def _project_out(session: Session, project: Project) -> ProjectOut:
    style = _style_row(session, project)
    return ProjectOut(
        id=project.id,
        title=project.title,
        status=project.status,  # constrained by ck_projects_status
        style_profile_id=project.style_profile_id,
        style_name=style.name if style is not None else None,
        brief=ProjectBrief.model_validate(project.brief),
        has_plan=current_plan_row(session, project.id) is not None,
        plan_job_id=_latest_plan_job(session, project),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _profile(session: Session, project: Project) -> StyleProfile:
    style = _style_row(session, project)
    if style is None:
        raise ApiError(
            409, "PROJECT_STYLE_MISSING", "This project's style was deleted.", "Pick another style."
        )
    return effective_profile(style)


def _plan_out(project: Project, row: ShootPlanRow, profile: StyleProfile) -> ShootPlanOut:
    plan = load_plan(row)
    return ShootPlanOut(
        project_id=project.id,
        title=project.title,
        version=row.version,
        plan=plan,
        word_count=script_word_count(plan),
        style=PlanStyle(
            name=profile.name,
            wpm=round(profile.speech.wpm) if profile.speech.present else 150,
            max_shot_s=profile.pacing.max_shot_s,
            beats=[
                PlanBeat(id=b.id, function=b.function, must_have=b.must_have) for b in profile.beats
            ],
        ),
        updated_at=row.updated_at,
    )


def _current_plan(session: Session, project: Project) -> ShootPlanRow:
    row = current_plan_row(session, project.id)
    if row is None:
        raise ApiError(
            404, "PLAN_NOT_FOUND", "This project has no shoot plan yet.", "Generate one first."
        )
    return row


# ---------------------------------------------------------------- projects


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreateIn, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> ProjectOut:
    style = db.get(StyleProfileRow, body.style_profile_id)
    if style is None or style.owner_id != user_id:
        raise not_found("style profile")
    project = Project(
        owner_id=user_id,
        style_profile_id=style.id,
        title=body.title.strip(),
        brief=body.brief.model_dump(mode="json"),
    )
    db.add(project)
    db.commit()
    return _project_out(db, project)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> list[ProjectOut]:
    rows = db.scalars(
        select(Project)
        .where(Project.owner_id == user_id)
        .order_by(Project.created_at.desc())
        .limit(200)
    ).all()
    return [_project_out(db, row) for row in rows]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> ProjectOut:
    return _project_out(db, _owned(db, project_id, user_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def patch_project(
    project_id: UUID,
    body: ProjectPatch,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> ProjectOut:
    project = _owned(db, project_id, user_id)
    if body.title is not None:
        project.title = body.title.strip() or project.title
    if body.brief is not None:
        project.brief = body.brief.model_dump(mode="json")
    db.commit()
    return _project_out(db, project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> Response:
    db.delete(_owned(db, project_id, user_id))
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- plan mode


@router.post("/projects/{project_id}/shoot-plan", status_code=202, response_model=JobAccepted)
def start_shoot_plan(
    project_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> JobAccepted:
    project = _owned(db, project_id, user_id)
    _profile(db, project)  # fail now, not in the worker, if the style is gone
    job = enqueue(db, generate_shoot_plan, owner_id=user_id, input={"project_id": str(project.id)})
    return JobAccepted(job_id=job.id, resource_id=project.id)


@router.get("/projects/{project_id}/shoot-plan", response_model=ShootPlanOut)
def get_shoot_plan(
    project_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> ShootPlanOut:
    project = _owned(db, project_id, user_id)
    return _plan_out(project, _current_plan(db, project), _profile(db, project))


@router.patch("/projects/{project_id}/shoot-plan", response_model=ShootPlanOut)
def patch_shoot_plan(
    project_id: UUID,
    body: ShootPlanPatch,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> ShootPlanOut:
    """Manual edits update the current version in place; derived fields and warnings are
    recomputed, so an edit that breaks a rule shows up as a warning rather than an error."""
    project = _owned(db, project_id, user_id)
    row = _current_plan(db, project)
    profile = _profile(db, project)
    plan = load_plan(row)

    if body.lines:
        edits = {e.id: e for e in body.lines}
        unknown = sorted(set(edits) - {line.id for line in plan.script})
        if unknown:
            raise ApiError(422, "PLAN_UNKNOWN_LINE", f"No such script line: {', '.join(unknown)}.")
        plan = plan.model_copy(
            update={
                "script": [
                    line.model_copy(update={"text": " ".join(edits[line.id].text.split())})
                    if line.id in edits
                    else line
                    for line in plan.script
                ]
            }
        )
    if body.shots:
        shot_edits = {e.id: e for e in body.shots}
        unknown = sorted(set(shot_edits) - {s.id for s in plan.shots})
        if unknown:
            raise ApiError(422, "PLAN_UNKNOWN_SHOT", f"No such shot: {', '.join(unknown)}.")
        plan = plan.model_copy(
            update={
                "shots": [
                    s.model_copy(
                        update=shot_edits[s.id].model_dump(exclude={"id"}, exclude_none=True)
                    )
                    if s.id in shot_edits
                    else s
                    for s in plan.shots
                ]
            }
        )
    if body.shot_order is not None:
        by_id = {s.id: s for s in plan.shots}
        if sorted(body.shot_order) != sorted(by_id):
            raise ApiError(
                422, "PLAN_BAD_ORDER", "The new order must list every shot exactly once."
            )
        plan = plan.model_copy(update={"shots": [by_id[i] for i in body.shot_order]})

    plan = generate.derive(plan, profile, ProjectBrief.model_validate(project.brief))
    row.data = ShootPlan.model_validate(plan).model_dump(mode="json")
    db.commit()
    return _plan_out(project, row, profile)


@router.post(
    "/projects/{project_id}/shoot-plan/regenerate", status_code=202, response_model=JobAccepted
)
def regenerate(
    project_id: UUID,
    body: RegenerateIn,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> JobAccepted:
    project = _owned(db, project_id, user_id)
    profile = _profile(db, project)
    if body.scope != "all":
        plan = load_plan(_current_plan(db, project))
        try:
            generate.resolve_target(plan, profile, body.scope, body.target_id)
        except generate.PlanError as exc:
            raise ApiError(422, exc.code, exc.user_message) from None
    job = enqueue(
        db,
        regenerate_shoot_plan,
        owner_id=user_id,
        input={"project_id": str(project.id), **body.model_dump()},
    )
    return JobAccepted(job_id=job.id, resource_id=project.id)


def _pdf_response(project: Project, row: ShootPlanRow, profile: StyleProfile) -> Response:
    labels = {b.id: f"{b.id.replace('_', ' ').capitalize()}" for b in profile.beats}
    pdf = render_plan_pdf(project.title, load_plan(row), labels)
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in project.title).strip() or "plan"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe} - shoot plan.pdf"'},
    )


@router.get("/projects/{project_id}/shoot-plan.pdf")
def shoot_plan_pdf(
    project_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> Response:
    project = _owned(db, project_id, user_id)
    return _pdf_response(project, _current_plan(db, project), _profile(db, project))


@router.post("/projects/{project_id}/share", response_model=ShareOut)
def share_plan(
    project_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> ShareOut:
    """Create (or return) the read-only link. Anyone with the link can view the plan."""
    project = _owned(db, project_id, user_id)
    _current_plan(db, project)
    if project.share_token is None:
        project.share_token = secrets.token_urlsafe(24)
        db.commit()
    return ShareOut(token=project.share_token, path=f"/share/{project.share_token}")


@router.delete("/projects/{project_id}/share", status_code=204)
def unshare_plan(
    project_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> Response:
    project = _owned(db, project_id, user_id)
    project.share_token = None
    db.commit()
    return Response(status_code=204)


def _shared(session: Session, token: str) -> Project:
    project = (
        session.scalar(select(Project).where(Project.share_token == token))
        if 16 <= len(token) <= 64
        else None
    )
    if project is None:
        raise not_found("shared plan")
    return project


@public_router.get("/share/{token}", response_model=ShootPlanOut)
def shared_plan(token: str, db: Session = Depends(get_db)) -> ShootPlanOut:
    """Public, read-only. Returns the plan and its title; nothing about the owner."""
    project = _shared(db, token)
    return _plan_out(project, _current_plan(db, project), _profile(db, project))


@public_router.get("/share/{token}/shoot-plan.pdf")
def shared_plan_pdf(token: str, db: Session = Depends(get_db)) -> Response:
    project = _shared(db, token)
    return _pdf_response(project, _current_plan(db, project), _profile(db, project))
