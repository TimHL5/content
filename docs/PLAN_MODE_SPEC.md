# Plan Mode Spec (v1)

Plan Mode tells the creator **exactly what to film** so the auto-editor has everything the style needs.

## Inputs: `ProjectBrief`
```python
class ProjectBrief(BaseModel):
    topic: str                              # "3 mistakes first-time renters make"
    key_points: list[str] = []
    script: str | None = None               # if provided, we fit it to the style instead of writing one
    target_duration_s: float | None = None  # default: reference duration ±15%
    audience: str | None = None
    tone: str | None = None                 # override profile delivery
    constraints: Constraints

class Constraints(BaseModel):
    crew: Literal["solo","two_person"] = "solo"
    gear: list[Literal["phone","tripod","gimbal","lav_mic","ring_light","camera"]] = ["phone"]
    locations: list[str] = []               # "home office", "kitchen", "street"
    can_show_face: bool = True
    has_screen_content: bool = False        # app demos / screen recordings available
    max_setups: int | None = None
```

## Output: `ShootPlan`
```python
class ScriptLine(BaseModel):
    id: str                                 # "L1"
    beat_id: str                            # links to StyleProfile.beats
    text: str
    est_duration_s: float                   # words / (profile.speech.wpm / 60)
    emphasis_words: list[str]               # will drive punch-ins/highlights
    delivery_note: str | None               # "pause before the number", "smirk"

class PlannedShot(BaseModel):
    id: str                                 # "S1"
    beat_id: str
    line_ids: list[str]                     # empty for pure b-roll
    kind: Literal["a_roll","b_roll","screen","text_card","reaction","product","pov","other"]
    framing: Literal["ecu","cu","mcu","ms","ws","overhead","pov","screen"]
    camera_motion: Literal["static","handheld","push_in","pull_out","pan","whip","tracking"]
    setup_id: str                           # shots sharing location+framing+lighting
    duration_s: float                       # target on-screen duration
    record_s: float                         # how long to record (duration × 2, min 3s for b-roll)
    takes: int                              # default 2 for a_roll lines, 3 for hook
    priority: Literal["must","nice"]
    description: str                        # "Close-up of hands signing lease, slow push-in"
    direction: str                          # filming instructions in plain language
    will_be_cut: bool = False               # a long a_roll the editor will jump-cut; may exceed max_shot_s
    reference_shot_idx: int | None          # which reference shot this mirrors
    alternatives: list[str] = []            # fallback if they can't get it

class Setup(BaseModel):
    id: str
    location: str
    framing_summary: str
    lighting: str                           # "face a window, no overhead light"
    audio: str                              # "lav mic or phone ≤ 1m away"
    orientation: Literal["vertical"] = "vertical"
    props: list[str]

class ShootPlan(BaseModel):
    schema_version: Literal[1] = 1
    project_id: UUID
    style_profile_id: UUID
    target_duration_s: float
    word_budget: int
    title_options: list[str]                # 3 on-screen hook text options
    script: list[ScriptLine]
    shots: list[PlannedShot]                # in EDIT order
    setups: list[Setup]
    shoot_order: list[str]                  # shot ids in SHOOT order
    checklist_notes: list[str]              # "Film the hook last when you're warmed up"
    music_brief: str | None                 # mood + BPM range to pick from library
    warnings: list[str] = []                # rules still broken after one repair; shown, not fatal
```

## Generation algorithm (`planning/generate.py`)
1. **Budget**:
   `speech_time = target_duration × profile.speech.coverage_pct`
   `word_budget = round(speech_time × profile.speech.wpm / 60)`
2. **Beat scaffold**: scale `profile.beats` proportionally to `target_duration`. Keep the hook at its absolute length (clamped 1.5–4s).
3. **LLM call** (`shoot_plan` prompt, smart model) with: profile (minus raw shot list noise), brief, budget, beat scaffold, constraints. The model returns a `PlanDraft` (`planning/drafts.py`): creative fields only. Code fills `est_duration_s`, `record_s`, `takes`, `shoot_order`, `word_budget`, and `target_duration_s`.
4. **Validate & repair** (deterministic checks; on failure re-prompt once with the list of violations; the repaired plan is kept if it has no more violations than the first, and whatever remains is stored in `warnings`):
   - Script word count within ±10% of budget.
   - Every `must_have` beat has ≥1 `must` shot.
   - Sum of shot durations within ±10% of target.
   - b-roll share of duration within ±0.1 of `profile.rules.broll_ratio`.
   - No shot longer than `profile.pacing.max_shot_s`, unless it's an a_roll that the editor will punch-in/jump-cut (flag it so).
   - Constraints respected (no face shots if `can_show_face=false`; no screen shots unless `has_screen_content`; at most `max_setups` setups). A `tracking` move without a gimbal is not a violation: code downgrades it to `handheld` and adds a walk-slowly note.
   - References resolve: every beat, setup, and script line a shot or line points at exists; ids are unique.
   - A reference with no speech has a word budget of 0 and expects an empty script.
5. **Shoot order** (deterministic): group shots by `setup_id`; order setups to minimize changes (a_roll setup first; the hook gets its own extra takes at the end of the a_roll setup); within a setup, order by `line_ids`.
6. **Takes**: hook ×3, must a_roll ×2, nice ×1, b-roll records `record_s`.

## Regeneration
`POST /projects/{id}/shoot-plan/regenerate` with `{scope: "hook"|"beat"|"shot"|"all", target_id?, instruction?}`. Only the targeted part changes. The validator still runs on the full plan.

- `hook` / `beat`: the `shoot_plan_regen` prompt returns replacement lines and shots for that beat. Code swaps them in at the same position with fresh ids; every other line and shot keeps its id and content.
- `shot`: one replacement shot. It keeps its id, beat, and script lines; how it is filmed changes.
- `all`: a full new plan.
- Every regeneration saves a new plan version; earlier versions are kept. Manual edits (`PATCH`) update the current version in place and re-derive takes, record lengths, shoot order, and warnings.

## Coverage Check (after footage upload)
For each `PlannedShot`:
1. **a_roll / lines**: align each clip's transcript to script lines with fuzzy matching (rapidfuzz `token_set_ratio` ≥ 75). Multiple matches mean multiple takes.
2. **b-roll / non-speech**: `coverage_classify` (fast vision model) with a contact sheet of the clip plus the list of unassigned b-roll shot descriptions → best match + score.
3. Status per shot:
   - ✅ `covered`: matched with good quality (no clipping, blur score OK, ≥ duration_s usable).
   - ⚠️ `weak`: matched but quality issue or too short ("only 1.2s usable, need 2s").
   - ❌ `missing`.
4. If a must shot is missing, offer: (a) reshoot list in shoot order, (b) auto-substitute (a punch-in on a_roll, a text card, or a different b-roll), (c) continue anyway.

## UI (mobile-first)
- **Script** tab: beats as colored sections; tap a line to edit; word budget meter.
- **Shots** tab: cards in edit order with framing icon, duration, priority badge, and the matching reference contact-sheet tile ("like this").
- **Shoot** tab: checklist in shoot order, grouped by setup with setup instructions on top; big tap targets; "Teleprompter" button per a_roll shot. Ticks are stored on the device (per project and plan version), so the checklist works on set without a connection.
- **Teleprompter**: scrolls at `profile.speech.wpm`, adjustable ±20%; mirror toggle; highlights emphasis words; front-camera friendly (text near the top).
- **Export**: PDF (one page per setup) + share link.
