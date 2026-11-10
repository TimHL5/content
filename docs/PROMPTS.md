# Prompt Registry

Each prompt lives in `apps/api/stylecut/llm/prompts/{id}.py` with `ID`, `VERSION`, `MODEL` (`smart`|`fast`), `SYSTEM`, `USER_TEMPLATE` (Jinja2), and `OUTPUT_MODEL`.
Output is always structured output constrained to the Pydantic model (`messages.parse`); see ARCHITECTURE.md for why this replaced forced tool use. Output models live in `analysis/judgment.py` and contain judgment fields only. **Bump VERSION on any change** (it busts the cache and appears in `llm_calls`).

Shared system preamble (prepend to all):
> You are part of StyleCut, a video-editing system. You analyze and plan short-form vertical video. Measured values given to you are ground truth: never change or re-estimate them. Describe style, structure, and technique, never reproduce the reference's specific words beyond short templates. When evidence is weak, choose the most conservative option and lower the confidence.

---

## `visual_breakdown` (v1, smart, vision)
**Input:** contact sheets (images), shot table `[{idx, start_s, end_s, motion_score, punch_in}]`, aspect.
**Output:** `VisualBreakdown {shots:[{idx, kind, framing, camera_motion, description}], captions: CaptionStyle, overlays:[Overlay], setting_notes, confidence}`
**User template (sketch):**
```
Here are contact sheets of a {{duration_s}}s {{aspect}} video. Each tile is labeled "#<shot_idx> t=<seconds>".
Shot table (measured): {{shots_json}}
Caption presets available: {{caption_presets_json}}
Fonts available: {{fonts_list}}

For every shot idx, classify kind, framing, camera_motion (use motion_score: <0.5 static, >2.5 strong movement), and write a content-agnostic description (≤12 words).
Describe the burned-in caption style by choosing the nearest preset and font from the lists, then fill each CaptionStyle field from what you see.
List recurring on-screen overlays (not captions).
```

## `style_synthesis` (v1, smart)
**Input:** deterministic JSON (pacing, speech, audio, color), transcript with timestamps, VisualBreakdown.
**Output:** `SynthesisOut {summary, hook: {type, template, visual}, beats: [{id, function, start_s, end_s, technique, must_have}], rules: {zoom_on, jump_cut_silences, transitions, loop_ending, text_card_usage}, audio_judgment: {sfx_density, sfx_types, music_mood}, speech_judgment: {delivery, voice_type}, color_look, confidence}`. Code then snaps beat edges to cuts, assigns `Shot.beat_id`, and fills `hook.duration_s`, `rules.punch_in_every_s`, `rules.punch_in_scale`, and `rules.broll_ratio`.
**Key instructions:**
- Identify the narrative beats with time ranges that align to shot boundaries.
- `hook.template` must be a fill-in-the-blank pattern with `<placeholders>`, ≤ 15 words, not the original sentence.
- Mark a beat `must_have` only if removing it would break the format.
- Rules must be actionable by an automatic editor (numbers > adjectives).

## `shoot_plan` (v1, smart)
**Input:** StyleProfile (summary, hook, beats, pacing, speech, rules, captions.present), ProjectBrief, word_budget, scaled beat scaffold, constraints, reference contact-sheet captions for shots.
**Output:** `PlanDraft {title_options, script: [{id, beat_id, text, emphasis_words, delivery_note}], shots: [...], setups, checklist_notes, music_brief, script_changes}`. Everything code can compute (`est_duration_s`, `record_s`, `takes`, `shoot_order`, budgets) is absent from the draft.
**Key instructions:**
```
Write a script for "{{brief.topic}}" that follows this structure exactly: {{beat_scaffold}}.
Word budget: {{word_budget}} words (±10%). Delivery: {{delivery}}. Speaking pace: {{wpm}} wpm.
Hook: use the "{{hook.type}}" pattern (template: {{hook.template}}), but write original words about the user's topic.
{% if brief.script %}The user provided a script; keep their wording, trim or reorder to fit the beats, and note what you changed.{% endif %}
Then design shots so that: b-roll is ~{{broll_ratio*100}}% of runtime; no single shot exceeds {{max_shot_s}}s except a_roll that will be jump-cut; each must-have beat has a must shot.
Respect constraints: {{constraints}}. Give plain-language filming directions a beginner can follow on a phone.
For b-roll, prefer things the user can film at their listed locations. Give 1–2 alternatives for anything hard.
Group shots into setups (same location + framing + lighting) and minimize the number of setups.
Write 3 on-screen title options in the style of the reference's overlays.
```

## `shoot_plan_regen` (v1, smart)
**Input:** topic, delivery, the part being replaced (one beat's lines and shots, or one shot), its beat, the hook pattern, the rest of the plan for context, existing setups, constraints, and the creator's optional instruction.
**Output:** `PartDraft {script, shots, setups}`: the replacement only. Code merges it so nothing outside the target changes.

## `coverage_classify` (v1, fast, vision)
**Input:** contact sheet of one clip (6 frames), its transcript snippet (if any), and candidate shots `[{id, kind, framing, description}]`.
**Output:** `{best_shot_id | null, score 0–1, framing_detected, issues:[ "too dark", "shaky", "subject cut off" ]}`

## `take_ranking` (v1, fast)
**Input:** for one script line, 2–5 takes: `{take_id, transcript, filler_count, restarts, duration_s, rms_db, face_present_pct}`; target delivery.
**Output:** `{ranking:[take_id…], reason_short}`
Instruction: prefer the complete, fluent take closest to target delivery; tie-break on shorter duration.

## `emphasis_picker` (v1, fast)
**Input:** timed words of the assembled a_roll, rules (`zoom_on`, `punch_in_every_s`, `sfx_density`, caption `emoji` level), existing cut points.
**Output:** `{punch_ins:[{word_idx}], highlights:[word_idx], emojis:[{word_idx, emoji}], sfx:[{word_idx, type}]}`
Constraints (also enforced in code): punch-ins ≥ 1.2s apart, average spacing ≈ `punch_in_every_s`; emoji count per density (`sparse` ≤ 1 per 8s); never on filler words.

## Plan-repair addendum (appended on validation failure)
```
Your previous output failed these checks:
{{violations}}
Return a corrected full output. Change only what is needed to pass.
```

## Eval & recording
- `tests/llm_cassettes/{prompt_id}_v{n}/*.json` stores recorded responses for tests.
- `make eval` prints per-prompt token cost and diffs vs the last run.
