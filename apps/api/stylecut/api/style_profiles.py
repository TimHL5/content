"""Style profiles: the user's library of styles, viewable and editable."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from stylecut.api.deps import current_user_id
from stylecut.api.errors import ApiError, not_found
from stylecut.db.models import ReferenceVideo, StyleProfileRow
from stylecut.db.session import get_db
from stylecut.schemas.style_profile import (
    PROTECTED_POINTER_PREFIXES,
    JsonPointerError,
    StyleProfile,
    apply_overrides,
    migrate_style_profile,
)
from stylecut.schemas.style_profile_api import (
    StyleProfileOut,
    StyleProfilePatch,
    StyleProfileSummary,
)
from stylecut.storage import s3

router = APIRouter(tags=["style-profiles"])


def _owned(session: Session, profile_id: UUID, user_id: UUID) -> StyleProfileRow:
    row = session.get(StyleProfileRow, profile_id)
    if row is None or row.owner_id != user_id:
        raise not_found("style profile")
    return row


def effective_profile(
    row: StyleProfileRow, overrides: dict[str, Any] | None = None
) -> StyleProfile:
    """Stored data + overrides, validated. Raises ApiError for an override that doesn't fit."""
    data = migrate_style_profile(dict(row.data))
    active = data.get("user_overrides", {}) if overrides is None else overrides
    try:
        merged = apply_overrides({**data, "name": row.name}, active)
        return StyleProfile.model_validate({**merged, "user_overrides": active})
    except JsonPointerError as exc:
        raise ApiError(422, "OVERRIDE_INVALID_PATH", str(exc).capitalize() + ".") from None
    except ValidationError as exc:
        first = exc.errors()[0]
        where = "/" + "/".join(str(part) for part in first["loc"])
        raise ApiError(
            422,
            "OVERRIDE_INVALID_VALUE",
            f"{where}: {first['msg']}",
            "Check the value and try again.",
        ) from None


def _sheet_urls(session: Session, row: StyleProfileRow) -> list[str]:
    if not row.source_reference_ids:
        return []
    reference = session.get(ReferenceVideo, row.source_reference_ids[0])
    sheets = reference.derived.get("sheets", []) if reference is not None else []
    return [s3.presign_get(key) for key in sheets]


def _out(session: Session, row: StyleProfileRow) -> StyleProfileOut:
    profile = effective_profile(row)
    return StyleProfileOut(
        id=row.id,
        name=row.name,
        profile=profile,
        overrides=profile.user_overrides,
        sheet_urls=_sheet_urls(session, row),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/style-profiles", response_model=list[StyleProfileSummary])
def list_style_profiles(
    db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> list[StyleProfileSummary]:
    rows = db.scalars(
        select(StyleProfileRow)
        .where(StyleProfileRow.owner_id == user_id)
        .order_by(StyleProfileRow.created_at.desc())
        .limit(200)
    ).all()
    result = []
    for row in rows:
        profile = effective_profile(row)
        result.append(
            StyleProfileSummary(
                id=row.id,
                name=row.name,
                summary=profile.summary,
                platform=profile.source.platform,
                duration_s=profile.source.duration_s,
                shot_count=profile.pacing.shot_count,
                hook_type=profile.hook.type,
                created_at=row.created_at,
            )
        )
    return result


@router.get("/style-profiles/{profile_id}", response_model=StyleProfileOut)
def get_style_profile(
    profile_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> StyleProfileOut:
    return _out(db, _owned(db, profile_id, user_id))


@router.patch("/style-profiles/{profile_id}", response_model=StyleProfileOut)
def patch_style_profile(
    profile_id: UUID,
    body: StyleProfilePatch,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> StyleProfileOut:
    row = _owned(db, profile_id, user_id)
    if body.name is not None:
        row.name = body.name.strip() or row.name
    if body.overrides is not None:
        for pointer in body.overrides:
            if pointer.startswith(PROTECTED_POINTER_PREFIXES) or pointer == "/name":
                raise ApiError(422, "OVERRIDE_PROTECTED", f"{pointer} can't be overridden.")
        merged = {**row.data.get("user_overrides", {}), **body.overrides}
        merged = {k: v for k, v in merged.items() if v is not None}
        effective_profile(row, merged)  # validates before anything is stored
        row.data = {**row.data, "user_overrides": merged}
    db.commit()
    return _out(db, row)


@router.delete("/style-profiles/{profile_id}", status_code=204)
def delete_style_profile(
    profile_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> Response:
    db.delete(_owned(db, profile_id, user_id))
    db.commit()
    return Response(status_code=204)
