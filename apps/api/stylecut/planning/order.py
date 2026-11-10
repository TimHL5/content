"""Takes, record lengths, and shoot order. Fully deterministic (PLAN_MODE_SPEC steps 5-6).

Shoot order groups shots by setup so the creator changes location, framing, and lighting
as rarely as possible. Talking setups come first, and the hook is filmed last within its
setup, once the creator is warmed up.
"""

from stylecut.schemas.shoot_plan import PlannedShot, ScriptLine

SPEAKING_KINDS = frozenset({"a_roll", "reaction"})
HOOK_TAKES, MUST_A_ROLL_TAKES, DEFAULT_TAKES = 3, 2, 1
RECORD_MULTIPLIER = 2.0
MIN_NON_SPEECH_RECORD_S = 3.0


def is_hook(shot: PlannedShot, hook_beat_ids: set[str]) -> bool:
    return shot.beat_id in hook_beat_ids


def takes_for(shot: PlannedShot, hook_beat_ids: set[str]) -> int:
    if is_hook(shot, hook_beat_ids) and shot.kind in SPEAKING_KINDS:
        return HOOK_TAKES
    if shot.kind == "a_roll" and shot.priority == "must":
        return MUST_A_ROLL_TAKES
    return DEFAULT_TAKES


def record_seconds(shot: PlannedShot) -> float:
    """Record twice the on-screen time; silent shots get at least 3s so there is room to trim."""
    length = shot.duration_s * RECORD_MULTIPLIER
    if not shot.line_ids:
        length = max(length, MIN_NON_SPEECH_RECORD_S)
    return round(length, 1)


def shoot_order(
    shots: list[PlannedShot], script: list[ScriptLine], hook_beat_ids: set[str]
) -> list[str]:
    """Shot ids in the order to film them."""
    line_pos = {line.id: i for i, line in enumerate(script)}
    edit_pos = {shot.id: i for i, shot in enumerate(shots)}

    by_setup: dict[str, list[PlannedShot]] = {}
    for shot in shots:
        by_setup.setdefault(shot.setup_id, []).append(shot)

    def setup_rank(setup_id: str) -> tuple[int, int]:
        group = by_setup[setup_id]
        speaking = sum(1 for s in group if s.kind in SPEAKING_KINDS)
        # Talking setups first (most of them first), then by first appearance in the edit.
        return (-speaking, min(edit_pos[s.id] for s in group))

    def shot_rank(shot: PlannedShot) -> tuple[int, int, int]:
        hook_last = 1 if is_hook(shot, hook_beat_ids) and shot.kind in SPEAKING_KINDS else 0
        first_line = min(
            (line_pos.get(i, len(line_pos)) for i in shot.line_ids), default=len(line_pos)
        )
        return (hook_last, first_line, edit_pos[shot.id])

    ordered: list[str] = []
    for setup_id in sorted(by_setup, key=setup_rank):
        ordered.extend(s.id for s in sorted(by_setup[setup_id], key=shot_rank))
    return ordered
