"""Shoot plan generation (docs/PLAN_MODE_SPEC.md).

    budget + beat scaffold (code)  ->  shoot_plan prompt (LLM)  ->  finalize (code)
      ->  validate (code)  ->  one repair attempt with the violations  ->  ShootPlan

Whatever still fails after the repair is kept on the plan as `warnings`: a plan the
creator can adjust is more useful than no plan.
"""

import re
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from stylecut.llm.client import call_structured
from stylecut.llm.prompts import shoot_plan as prompts
from stylecut.planning import budget, order
from stylecut.planning.drafts import LineDraft, PartDraft, PlanDraft, ShotDraft
from stylecut.planning.validate import downgrade_camera_moves, validate_plan
from stylecut.schemas.shoot_plan import (
    PlannedShot,
    ProjectBrief,
    RegenerateScope,
    ScriptLine,
    Setup,
    ShootPlan,
)
from stylecut.schemas.style_profile import StyleProfile

MAX_REFERENCE_SHOTS_IN_PROMPT = 40


class PlanError(Exception):
    """A request that cannot be carried out; `user_message` is shown to the creator."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


def hook_beat_ids(profile: StyleProfile) -> set[str]:
    return {b.id for b in profile.beats if b.function == "hook"}


def _line(draft: LineDraft, wpm: float) -> ScriptLine:
    text = " ".join(draft.text.split())
    return ScriptLine(
        id=draft.id,
        beat_id=draft.beat_id,
        text=text,
        est_duration_s=budget.estimate_line_seconds(text, wpm),
        emphasis_words=[w.strip() for w in draft.emphasis_words if w.strip()][:3],
        delivery_note=(draft.delivery_note or "").strip() or None,
    )


def _shot(draft: ShotDraft) -> PlannedShot:
    return PlannedShot(
        **draft.model_dump(exclude={"duration_s"}),
        duration_s=round(max(draft.duration_s, 0.0), 2),
        record_s=0.0,
        takes=1,
    )


def derive(plan: ShootPlan, profile: StyleProfile, brief: ProjectBrief) -> ShootPlan:
    """Recompute every [D] field and re-run validation. Call after any change to a plan."""
    wpm = budget.speaking_wpm(profile)
    hooks = hook_beat_ids(profile)
    shots = downgrade_camera_moves(plan.shots, brief.constraints)
    shots = [
        s.model_copy(
            update={"takes": order.takes_for(s, hooks), "record_s": order.record_seconds(s)}
        )
        for s in shots
    ]
    used_setups = {s.setup_id for s in shots}
    updated = plan.model_copy(
        update={
            "script": [
                line.model_copy(
                    update={"est_duration_s": budget.estimate_line_seconds(line.text, wpm)}
                )
                for line in plan.script
            ],
            "shots": shots,
            "setups": [s for s in plan.setups if s.id in used_setups] or plan.setups,
            "shoot_order": order.shoot_order(shots, plan.script, hooks),
        }
    )
    return updated.model_copy(
        update={"warnings": validate_plan(updated, profile, brief.constraints)}
    )


def finalize(
    draft: PlanDraft, *, project_id: UUID, profile: StyleProfile, brief: ProjectBrief
) -> ShootPlan:
    """LLM draft + code-computed fields -> a validated ShootPlan (warnings filled in)."""
    target = budget.target_duration(brief, profile)
    wpm = budget.speaking_wpm(profile)
    plan = ShootPlan(
        project_id=project_id,
        style_profile_id=profile.id,
        target_duration_s=target,
        word_budget=budget.word_budget(target, profile),
        title_options=[t.strip() for t in draft.title_options if t.strip()][:3],
        script=[_line(line, wpm) for line in draft.script],
        shots=[_shot(shot) for shot in draft.shots],
        setups=draft.setups,
        shoot_order=[],
        checklist_notes=[n.strip() for n in draft.checklist_notes if n.strip()],
        music_brief=(draft.music_brief or "").strip() or None,
    )
    return derive(plan, profile, brief)


def _style_inputs(profile: StyleProfile) -> dict[str, Any]:
    music = (
        f"{profile.audio.music_mood or 'present'}, about {round(profile.audio.bpm)} BPM"
        if profile.audio.music_present and profile.audio.bpm
        else "none"
    )
    return {
        "summary": profile.summary,
        "hook": profile.hook.model_dump(include={"type", "template", "visual"}),
        "broll_ratio": profile.rules.broll_ratio,
        "max_shot_s": profile.pacing.max_shot_s,
        "captions_present": profile.captions.present,
        "music": music,
        "shots": [
            {"idx": s.idx, "kind": s.kind, "framing": s.framing, "description": s.description}
            for s in profile.shots[:MAX_REFERENCE_SHOTS_IN_PROMPT]
        ],
    }


def _delivery(profile: StyleProfile, brief: ProjectBrief) -> str:
    return brief.tone or profile.speech.delivery or "conversational"


def generate_plan(
    *, project_id: UUID, profile: StyleProfile, brief: ProjectBrief, session: Session,
    job_id: UUID | None = None, instruction: str | None = None,
) -> ShootPlan:  # fmt: skip
    target = budget.target_duration(brief, profile)
    inputs: dict[str, Any] = {
        "brief": brief.model_dump(),
        "delivery": _delivery(profile, brief),
        "wpm": round(budget.speaking_wpm(profile)),
        "target_duration_s": target,
        "word_budget": budget.word_budget(target, profile),
        "beat_scaffold": [b.model_dump() for b in budget.scale_beats(profile, target)],
        "style": _style_inputs(profile),
        "constraints": brief.constraints.model_dump(),
        "instruction": instruction,
        "violations": [],
    }

    def attempt(violations: list[str]) -> ShootPlan:
        draft = call_structured(
            prompts.PROMPT, {**inputs, "violations": violations}, PlanDraft,
            session=session, job_id=job_id,
        )  # fmt: skip
        return finalize(draft, project_id=project_id, profile=profile, brief=brief)

    plan = attempt([])
    if plan.warnings:
        repaired = attempt(plan.warnings)
        if len(repaired.warnings) <= len(plan.warnings):
            plan = repaired
    return plan


# ---------------------------------------------------------------- regeneration


def _next_ids(prefix: str, taken: set[str], count: int) -> list[str]:
    numbers = [int(m.group(1)) for i in taken if (m := re.fullmatch(rf"{prefix}(\d+)", i))]
    start = max(numbers, default=0) + 1
    return [f"{prefix}{n}" for n in range(start, start + count)]


def merge_beat(plan: ShootPlan, beat_id: str, part: PartDraft, wpm: float) -> ShootPlan:
    """Swap one beat's lines and shots for the replacement. Everything else keeps its ids."""
    kept_lines = [line for line in plan.script if line.beat_id != beat_id]
    kept_shots = [shot for shot in plan.shots if shot.beat_id != beat_id]
    line_at = next((i for i, x in enumerate(plan.script) if x.beat_id == beat_id), len(plan.script))
    shot_at = next((i for i, x in enumerate(plan.shots) if x.beat_id == beat_id), len(plan.shots))
    line_at = min(line_at, len(kept_lines))
    shot_at = min(shot_at, len(kept_shots))

    new_line_ids = _next_ids("L", {x.id for x in plan.script}, len(part.script))
    line_map = {draft.id: new for draft, new in zip(part.script, new_line_ids, strict=True)}
    new_shot_ids = _next_ids("S", {x.id for x in plan.shots}, len(part.shots))

    lines = [
        _line(draft.model_copy(update={"id": line_map[draft.id], "beat_id": beat_id}), wpm)
        for draft in part.script
    ]
    shots = [
        _shot(
            draft.model_copy(
                update={
                    "id": new_id,
                    "beat_id": beat_id,
                    "line_ids": [line_map[i] for i in draft.line_ids if i in line_map],
                }
            )
        )
        for draft, new_id in zip(part.shots, new_shot_ids, strict=True)
    ]
    known = {s.id for s in plan.setups}
    return plan.model_copy(
        update={
            "script": kept_lines[:line_at] + lines + kept_lines[line_at:],
            "shots": kept_shots[:shot_at] + shots + kept_shots[shot_at:],
            "setups": plan.setups + [s for s in part.setups if s.id not in known],
        }
    )


def merge_shot(plan: ShootPlan, shot_id: str, part: PartDraft) -> ShootPlan:
    """Swap one shot. It keeps its id, beat, and script lines; how it is filmed changes."""
    if not part.shots:
        raise PlanError("PLAN_REGEN_EMPTY", "No replacement shot came back. Try again.")
    old = next(s for s in plan.shots if s.id == shot_id)
    new = _shot(part.shots[0]).model_copy(
        update={"id": old.id, "beat_id": old.beat_id, "line_ids": old.line_ids}
    )
    known = {s.id for s in plan.setups}
    return plan.model_copy(
        update={
            "shots": [new if s.id == shot_id else s for s in plan.shots],
            "setups": plan.setups + [s for s in part.setups if s.id not in known],
        }
    )


def resolve_target(
    plan: ShootPlan, profile: StyleProfile, scope: RegenerateScope, target_id: str | None
) -> tuple[str, str]:
    """-> ("beat" | "shot", id). Raises PlanError when the target does not exist."""
    if scope == "hook":
        hooks = sorted(hook_beat_ids(profile))
        if not hooks:
            raise PlanError("PLAN_NO_HOOK", "This style has no hook beat to regenerate.")
        return "beat", hooks[0]
    if scope == "beat":
        if target_id not in {b.id for b in profile.beats}:
            raise PlanError("PLAN_TARGET_NOT_FOUND", "That beat isn't part of this plan.")
        return "beat", str(target_id)
    if scope == "shot":
        if target_id not in {s.id for s in plan.shots}:
            raise PlanError("PLAN_TARGET_NOT_FOUND", "That shot isn't part of this plan.")
        return "shot", str(target_id)
    raise PlanError("PLAN_BAD_SCOPE", "Unknown regeneration scope.")


def regenerate_part(
    *, plan: ShootPlan, profile: StyleProfile, brief: ProjectBrief, scope: RegenerateScope,
    target_id: str | None, instruction: str | None, session: Session,
    job_id: UUID | None = None,
) -> ShootPlan:  # fmt: skip
    """Regenerate the hook, one beat, or one shot. Only the target changes."""
    kind, target = resolve_target(plan, profile, scope, target_id)
    if kind == "beat":
        part_lines = [x for x in plan.script if x.beat_id == target]
        part_shots = [x for x in plan.shots if x.beat_id == target]
        beat = next(b for b in profile.beats if b.id == target)
        description = f"all script lines and shots of the '{target}' beat ({beat.function})"
    else:
        shot = next(s for s in plan.shots if s.id == target)
        part_lines = [x for x in plan.script if x.id in shot.line_ids]
        part_shots = [shot]
        beat = next((b for b in profile.beats if b.id == shot.beat_id), profile.beats[0])
        description = f"shot {target} only (keep its script lines; change how it is filmed)"

    part_line_ids = {x.id for x in part_lines} if kind == "beat" else set()
    part_shot_ids = {x.id for x in part_shots}
    draft = call_structured(
        prompts.REGEN_PROMPT,
        {
            "topic": brief.topic,
            "delivery": _delivery(profile, brief),
            "wpm": round(budget.speaking_wpm(profile)),
            "target_description": description,
            "instruction": instruction,
            "current_part": {
                "script": [x.model_dump(include={"id", "text"}) for x in part_lines],
                "shots": [
                    x.model_dump(exclude={"record_s", "takes", "alternatives"}) for x in part_shots
                ],
            },
            "beat": beat.model_dump(),
            "hook": profile.hook.model_dump(include={"type", "template"}),
            "max_shot_s": profile.pacing.max_shot_s,
            "other_script": [
                x.model_dump(include={"id", "beat_id", "text"})
                for x in plan.script
                if x.id not in part_line_ids
            ],
            "other_shots": [
                x.model_dump(
                    include={"id", "beat_id", "kind", "setup_id", "duration_s", "description"}
                )
                for x in plan.shots
                if x.id not in part_shot_ids
            ],
            "setups": [s.model_dump() for s in plan.setups],
            "constraints": brief.constraints.model_dump(),
        },
        PartDraft,
        session=session,
        job_id=job_id,
    )
    merged = (
        merge_beat(plan, target, draft, budget.speaking_wpm(profile))
        if kind == "beat"
        else merge_shot(plan, target, draft)
    )
    return derive(merged, profile, brief)


def apply_setups(plan: ShootPlan, setups: list[Setup]) -> ShootPlan:
    return plan.model_copy(update={"setups": setups})
