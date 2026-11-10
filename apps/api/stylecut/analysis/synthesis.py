"""Build the StyleProfile.

Two LLM calls supply judgment (`visual_breakdown`, `style_synthesis`); `assemble_profile`
merges them with the measurements. Every [D] field is copied from code output here. The
LLM output models have no field for them, so they cannot be invented or changed.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from stylecut.analysis.audio import AudioResult, cut_on_beat_fraction
from stylecut.analysis.color import ColorResult
from stylecut.analysis.judgment import (
    BeatJudgment,
    ShotJudgment,
    SynthesisOut,
    VisualBreakdown,
)
from stylecut.analysis.scene import SceneResult
from stylecut.analysis.speech import SpeechStats, Transcript
from stylecut.analysis.visual import VisualResult, punch_in_summary
from stylecut.llm.client import call_structured
from stylecut.llm.prompts import style_synthesis, visual_breakdown
from stylecut.schemas.style_profile import (
    BUNDLED_FONTS,
    CAPTION_PRESETS,
    Aspect,
    Audio,
    Beat,
    Color,
    EditingRules,
    Hook,
    Pacing,
    Shot,
    SourceInfo,
    Speech,
    StyleProfile,
)

BROLL_KINDS = frozenset({"b_roll", "screen", "product"})
BEAT_SNAP_S = 0.3  # a beat edge this close to a cut is moved onto the cut
HOOK_FALLBACK_S = 3.0
TRANSCRIPT_LINE_GAP_S = 0.6

_ASPECTS: dict[Aspect, float] = {"9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5, "16:9": 16 / 9}


def nearest_aspect(width: int | None, height: int | None) -> Aspect:
    if not width or not height:
        return "9:16"
    ratio = width / height
    return min(_ASPECTS, key=lambda name: abs(_ASPECTS[name] - ratio))


def transcript_lines(transcript: Transcript) -> str:
    """`[12.4] words words` lines, split at pauses, as compact evidence for the LLM."""
    lines: list[str] = []
    current: list[str] = []
    start = 0.0
    previous_end: float | None = None
    for word in transcript.words:
        if previous_end is not None and word.start - previous_end > TRANSCRIPT_LINE_GAP_S:
            lines.append(f"[{start:.1f}] {' '.join(current)}")
            current = []
        if not current:
            start = word.start
        current.append(word.text)
        previous_end = word.end
    if current:
        lines.append(f"[{start:.1f}] {' '.join(current)}")
    return "\n".join(lines)


def shot_table(scene: SceneResult, visual: VisualResult) -> list[dict[str, Any]]:
    measures = {m.idx: m for m in visual.shots}
    return [
        {
            "idx": s.idx,
            "start_s": s.start_s,
            "end_s": s.end_s,
            "motion_score": measures[s.idx].motion_score if s.idx in measures else 0.0,
            "punch_in": measures[s.idx].punch_in if s.idx in measures else False,
        }
        for s in scene.shots
    ]


def run_visual_breakdown(
    *, scene: SceneResult, visual: VisualResult, sheets: list[bytes], aspect: Aspect,
    session: Session, job_id: UUID | None = None,
) -> VisualBreakdown:  # fmt: skip
    return call_structured(
        visual_breakdown.PROMPT,
        {
            "duration_s": scene.duration_s,
            "aspect": aspect,
            "sheet_count": len(sheets),
            "frame_count": len(visual.frames),
            "shots": shot_table(scene, visual),
            "caption_presets": list(CAPTION_PRESETS),
            "fonts": list(BUNDLED_FONTS),
        },
        VisualBreakdown,
        session=session,
        images=sheets,
        job_id=job_id,
    )


def run_style_synthesis(
    *, source: SourceInfo, scene: SceneResult, audio: AudioResult, speech: SpeechStats,
    transcript: Transcript, color: ColorResult, visual: VisualResult,
    breakdown: VisualBreakdown, session: Session, job_id: UUID | None = None,
) -> SynthesisOut:  # fmt: skip
    judged = {s.idx: s for s in breakdown.shots}
    shots = [
        {**row, **(judged[row["idx"]].model_dump(exclude={"idx"}) if row["idx"] in judged else {})}
        for row in shot_table(scene, visual)
    ]
    return call_structured(
        style_synthesis.PROMPT,
        {
            "duration_s": scene.duration_s,
            "aspect": source.aspect,
            "platform": source.platform,
            "pacing": {
                "shot_count": len(scene.shots),
                "shot_len_s": scene.shot_len_s.model_dump(),
                "cuts_per_5s": scene.cuts_per_5s,
                "acceleration": scene.acceleration,
                "cut_on_beat_pct": cut_on_beat_fraction(scene.cuts_s, audio.beats_s),
            },
            "speech": speech.model_dump(),
            "audio": audio.model_dump(exclude={"beats_s"}),
            "color": color.model_dump(exclude={"frames_sampled"}),
            "shots": shots,
            "visual": {
                "captions": breakdown.captions.model_dump(),
                "overlays": [o.model_dump() for o in breakdown.overlays],
                "setting_notes": breakdown.setting_notes,
            },
            "transcript": transcript_lines(transcript),
        },
        SynthesisOut,
        session=session,
        job_id=job_id,
    )


def _unit(value: float) -> float:
    return round(min(max(float(value), 0.0), 1.0), 3)


def normalize_beats(beats: list[BeatJudgment], scene: SceneResult) -> list[Beat]:
    """Clamp to the video, snap edges to nearby cuts, drop empties, de-duplicate ids."""
    edges = [0.0, *scene.cuts_s, scene.duration_s]

    def snap(t: float) -> float:
        t = min(max(t, 0.0), scene.duration_s)
        nearest = min(edges, key=lambda e: abs(e - t))
        return nearest if abs(nearest - t) <= BEAT_SNAP_S else round(t, 3)

    result: list[Beat] = []
    seen: dict[str, int] = {}
    for beat in sorted(beats, key=lambda b: b.start_s):
        start, end = snap(beat.start_s), snap(beat.end_s)
        if end - start <= 0:
            continue
        base = beat.id.strip() or beat.function
        seen[base] = seen.get(base, 0) + 1
        beat_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        result.append(
            Beat(
                id=beat_id,
                function=beat.function,
                start_s=start,
                end_s=end,
                technique=beat.technique,
                must_have=beat.must_have,
            )  # fmt: skip
        )
    return result


def _beat_for(midpoint: float, beats: list[Beat]) -> str | None:
    return next((b.id for b in beats if b.start_s <= midpoint < b.end_s), None)


def assemble_profile(
    *, profile_id: UUID, name: str, source: SourceInfo, scene: SceneResult, audio: AudioResult,
    speech: SpeechStats, color: ColorResult, visual: VisualResult,
    breakdown: VisualBreakdown, synthesis: SynthesisOut,
) -> StyleProfile:  # fmt: skip
    """Pure. Measurements from code, judgment from the two LLM outputs."""
    beats = normalize_beats(synthesis.beats, scene)
    judged: dict[int, ShotJudgment] = {s.idx: s for s in breakdown.shots}
    measures = {m.idx: m for m in visual.shots}

    shots: list[Shot] = []
    for span in scene.shots:
        judgment = judged.get(span.idx)
        measure = measures.get(span.idx)
        shots.append(
            Shot(
                idx=span.idx,
                start_s=span.start_s,
                end_s=span.end_s,
                kind=judgment.kind if judgment else "other",
                framing=judgment.framing if judgment else "ms",
                camera_motion=judgment.camera_motion if judgment else "static",
                punch_in=measure.punch_in if measure else False,
                motion_score=measure.motion_score if measure else 0.0,
                description=judgment.description.strip() if judgment else "",
                beat_id=_beat_for((span.start_s + span.end_s) / 2, beats),
            )
        )

    duration = scene.duration_s
    broll_time = sum(s.end_s - s.start_s for s in shots if s.kind in BROLL_KINDS)
    punch_every, punch_scale = punch_in_summary(visual.shots, duration)
    hook_beat = next((b for b in beats if b.function == "hook"), beats[0] if beats else None)
    hook_duration = (
        hook_beat.end_s - hook_beat.start_s if hook_beat else min(HOOK_FALLBACK_S, duration)
    )
    music = audio.music_present

    return StyleProfile(
        id=profile_id,
        name=name,
        source=source,
        summary=synthesis.summary.strip(),
        pacing=Pacing(
            shot_count=len(scene.shots),
            shot_len_s=scene.shot_len_s,
            cuts_per_5s=scene.cuts_per_5s,
            acceleration=scene.acceleration,
            max_shot_s=scene.max_shot_s,
            cut_on_beat_pct=cut_on_beat_fraction(scene.cuts_s, audio.beats_s) if music else None,
        ),
        shots=shots,
        captions=breakdown.captions.to_caption_style(),
        overlays=[
            o.model_copy(
                update={
                    "start_s": min(max(o.start_s, 0.0), duration),
                    "end_s": min(max(o.end_s, 0.0), duration),
                }
            )
            for o in breakdown.overlays
        ],
        speech=Speech(
            present=speech.present,
            coverage_pct=_unit(speech.coverage_pct),
            wpm=speech.wpm,
            pause_ms_p50=speech.pause_ms_p50,
            pause_ms_p90=speech.pause_ms_p90,
            filler_rate=speech.filler_rate,
            delivery=synthesis.speech_judgment.delivery if speech.present else None,
            voice_type=synthesis.speech_judgment.voice_type if speech.present else "none",
        ),
        audio=Audio(
            integrated_lufs=audio.integrated_lufs,
            music_present=music,
            bpm=audio.bpm if music else None,
            energy_curve=audio.energy_curve,
            drops_s=audio.drops_s,
            sfx_density=synthesis.audio_judgment.sfx_density if audio.has_audio else "none",
            sfx_types=list(dict.fromkeys(synthesis.audio_judgment.sfx_types))
            if audio.has_audio
            else [],
            music_mood=synthesis.audio_judgment.music_mood if music else None,
        ),
        color=Color(
            luma_mean=color.luma_mean,
            contrast=color.contrast,
            saturation=color.saturation,
            warmth=color.warmth,
            eq=color.eq,
            look=synthesis.color_look.strip(),
        ),
        hook=Hook(
            type=synthesis.hook.type,
            duration_s=round(hook_duration, 3),
            template=synthesis.hook.template.strip(),
            visual=synthesis.hook.visual.strip(),
        ),
        beats=beats,
        rules=EditingRules(
            punch_in_every_s=punch_every,
            punch_in_scale=punch_scale,
            zoom_on=list(dict.fromkeys(synthesis.rules.zoom_on)),
            broll_ratio=_unit(broll_time / duration) if duration > 0 else 0.0,
            jump_cut_silences=synthesis.rules.jump_cut_silences,
            transitions=list(dict.fromkeys(synthesis.rules.transitions)) or ["hard_cut"],
            loop_ending=synthesis.rules.loop_ending,
            text_card_usage=synthesis.rules.text_card_usage,
        ),
        confidence={
            "shots": _unit(breakdown.confidence.shots),
            "captions": _unit(breakdown.confidence.captions),
            "overlays": _unit(breakdown.confidence.overlays),
            **{k: _unit(v) for k, v in synthesis.confidence.model_dump().items()},
        },
    )
