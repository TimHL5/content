"""Deterministic checks a ShootPlan must pass (docs/PLAN_MODE_SPEC.md, step 4).

`validate_plan` returns violations as plain sentences. They are fed back to the LLM for
one repair attempt, and whatever remains is shown to the creator as warnings.
"""

from stylecut.planning.budget import count_words
from stylecut.schemas.shoot_plan import Constraints, PlannedShot, ShootPlan
from stylecut.schemas.style_profile import StyleProfile

TOLERANCE = 0.10  # word count and total duration may be off by 10%
BROLL_TOLERANCE = 0.10  # absolute, on the share of runtime
MIN_WORDS_FOR_TOLERANCE = 5  # very small budgets get an absolute tolerance instead

FACE_KINDS = frozenset({"a_roll", "reaction"})
BROLL_KINDS = frozenset({"b_roll", "screen", "product"})
GIMBAL_MOVES = frozenset({"tracking"})


def downgrade_camera_moves(shots: list[PlannedShot], constraints: Constraints) -> list[PlannedShot]:
    """Without a gimbal, a tracking move becomes a handheld walk. Applied before validation
    so the plan is filmable rather than merely flagged."""
    if "gimbal" in constraints.gear:
        return shots
    fixed: list[PlannedShot] = []
    for shot in shots:
        if shot.camera_motion in GIMBAL_MOVES:
            note = "No gimbal: hold the phone with both hands and walk forward slowly."
            direction = (
                shot.direction if note in shot.direction else f"{shot.direction} {note}".strip()
            )
            shot = shot.model_copy(update={"camera_motion": "handheld", "direction": direction})
        fixed.append(shot)
    return fixed


def script_word_count(plan: ShootPlan) -> int:
    return sum(count_words(line.text) for line in plan.script)


def broll_share(plan: ShootPlan) -> float:
    total = sum(s.duration_s for s in plan.shots)
    if total <= 0:
        return 0.0
    return sum(s.duration_s for s in plan.shots if s.kind in BROLL_KINDS) / total


def validate_plan(plan: ShootPlan, profile: StyleProfile, constraints: Constraints) -> list[str]:
    violations: list[str] = []
    beat_ids = {b.id for b in profile.beats}
    line_ids = {line.id for line in plan.script}
    setup_ids = {s.id for s in plan.setups}

    # References must resolve, or nothing downstream can use the plan.
    for collection, ids in (
        ("script line", [x.id for x in plan.script]),
        ("shot", [s.id for s in plan.shots]),
    ):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            violations.append(f"Duplicate {collection} ids: {', '.join(duplicates)}.")
    for line in plan.script:
        if beat_ids and line.beat_id not in beat_ids:
            violations.append(f"Script line {line.id} uses unknown beat '{line.beat_id}'.")
    for shot in plan.shots:
        if beat_ids and shot.beat_id not in beat_ids:
            violations.append(f"Shot {shot.id} uses unknown beat '{shot.beat_id}'.")
        if shot.setup_id not in setup_ids:
            violations.append(f"Shot {shot.id} uses unknown setup '{shot.setup_id}'.")
        missing = [i for i in shot.line_ids if i not in line_ids]
        if missing:
            violations.append(
                f"Shot {shot.id} refers to missing script lines: {', '.join(missing)}."
            )
        if shot.duration_s <= 0:
            violations.append(f"Shot {shot.id} has no duration.")

    # Script fits the word budget.
    words = script_word_count(plan)
    if plan.word_budget == 0:
        if words > 0:
            violations.append(
                f"The reference has no speech, so the script should be empty; it has {words} words."
            )
    else:
        allowed = max(plan.word_budget * TOLERANCE, MIN_WORDS_FOR_TOLERANCE)
        if abs(words - plan.word_budget) > allowed:
            violations.append(
                f"Script is {words} words; the budget is {plan.word_budget} (±{round(allowed)})."
            )

    # Every must-have beat is covered by a must shot.
    for beat in profile.beats:
        if beat.must_have and not any(
            s.beat_id == beat.id and s.priority == "must" for s in plan.shots
        ):
            violations.append(f"Must-have beat '{beat.id}' has no must-priority shot.")

    # Shots add up to the target length.
    total = sum(s.duration_s for s in plan.shots)
    if abs(total - plan.target_duration_s) > plan.target_duration_s * TOLERANCE:
        violations.append(
            f"Shots total {total:.1f}s; the target is {plan.target_duration_s:.1f}s (±10%)."
        )

    # B-roll share matches the style.
    share = broll_share(plan)
    wanted = profile.rules.broll_ratio
    if abs(share - wanted) > BROLL_TOLERANCE:
        violations.append(
            f"B-roll is {share:.0%} of runtime; the style uses about {wanted:.0%} (±10 points)."
        )

    # No shot outlasts the style's longest, unless it is a_roll the editor will cut up.
    for shot in plan.shots:
        if shot.duration_s > profile.pacing.max_shot_s + 0.05:
            if shot.kind == "a_roll" and shot.will_be_cut:
                continue
            violations.append(
                f"Shot {shot.id} runs {shot.duration_s:.1f}s; the style's longest shot is "
                f"{profile.pacing.max_shot_s:.1f}s. Split it, or for a_roll set will_be_cut."
            )

    # The creator's constraints.
    if not constraints.can_show_face:
        for shot in plan.shots:
            if shot.kind in FACE_KINDS:
                violations.append(
                    f"Shot {shot.id} shows the creator's face, which the brief rules out. "
                    "Use voiceover with b-roll, hands, screen, or pov instead."
                )
    if not constraints.has_screen_content and any(s.kind == "screen" for s in plan.shots):
        screen_ids = ", ".join(s.id for s in plan.shots if s.kind == "screen")
        violations.append(
            f"Shots {screen_ids} need screen recordings, which the brief says are unavailable."
        )
    if constraints.max_setups is not None and len(plan.setups) > constraints.max_setups:
        violations.append(
            f"The plan uses {len(plan.setups)} setups; the brief allows {constraints.max_setups}."
        )
    unused = sorted(setup_ids - {s.setup_id for s in plan.shots})
    if unused:
        violations.append(f"Setups with no shots: {', '.join(unused)}.")

    return violations
