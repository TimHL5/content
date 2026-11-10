"""`make eval`: run style analysis on every clip in eval/ and summarize the results.

For each video it writes `eval/out/<name>.json` (the StyleProfile, or the measurements
alone when no API key is configured) and the contact sheets, prints a summary table,
lists what changed since the previous run, and totals LLM tokens and cost per prompt.

Clips are analyzed straight from disk: nothing is uploaded and no job rows are created.
The LLM cache and call log do use the database.
"""

import argparse
import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select

from stylecut.analysis import audio, color, scene, speech, synthesis, visual
from stylecut.db.models import LlmCall
from stylecut.db.session import get_sessionmaker
from stylecut.llm.client import LlmError
from stylecut.media.extract import analysis_wav_args
from stylecut.media.ffmpeg import run_ffmpeg
from stylecut.media.probe import probe
from stylecut.media.proxy import proxy_args, speech_wav_args
from stylecut.schemas.style_profile import SourceInfo
from stylecut.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}


def analyze_clip(path: Path, out_dir: Path, use_llm: bool) -> dict[str, Any]:
    """Returns the JSON written for this clip."""
    timings: dict[str, float] = {}

    def timed(name: str, started: float) -> None:
        timings[name] = round(time.perf_counter() - started, 2)

    with tempfile.TemporaryDirectory(prefix="eval-") as tmp:
        work = Path(tmp)
        info = probe(path)
        t = time.perf_counter()
        proxy = work / "proxy.mp4"
        run_ffmpeg(proxy_args(path, proxy, info.has_audio))
        timed("proxy", t)

        t = time.perf_counter()
        scenes = scene.detect_scenes(proxy, info.duration_s, 30.0)
        timed("scenes", t)

        t = time.perf_counter()
        if info.has_audio:
            mix, speech_wav = work / "mix.wav", work / "speech.wav"
            run_ffmpeg(analysis_wav_args(proxy, mix))
            run_ffmpeg(speech_wav_args(path, speech_wav))
            audio_result = audio.analyze_audio(mix)
            timed("audio", t)
            t = time.perf_counter()
            transcript = speech.transcribe(speech_wav)
        else:
            audio_result = audio.silent_result(info.duration_s)
            transcript = speech.Transcript(text="", words=[])
        speech_stats = speech.speech_stats(transcript.words, info.duration_s)
        timed("speech", t)

        t = time.perf_counter()
        color_result = color.analyze_color(proxy, info.duration_s)
        timed("color", t)

        t = time.perf_counter()
        visual_result, sheets = visual.analyze_visual(proxy, scenes.shots)
        timed("visual", t)

    for n, sheet in enumerate(sheets):
        (out_dir / f"{path.stem}_sheet{n}.jpg").write_bytes(sheet)

    source = SourceInfo(
        platform="upload",
        duration_s=info.duration_s,
        aspect=synthesis.nearest_aspect(info.width, info.height),
        fps=float(info.fps or 30.0),
    )
    measured = {
        "source": source.model_dump(),
        "scenes": scenes.model_dump(exclude={"shots"}),
        "audio": audio_result.model_dump(exclude={"beats_s", "onsets_s"}),
        "speech": speech_stats.model_dump(),
        "color": color_result.model_dump(),
        "punch_ins": [m.model_dump() for m in visual_result.shots if m.punch_in],
        "motion_mean": round(
            sum(m.motion_score for m in visual_result.shots) / max(len(visual_result.shots), 1), 3
        ),
    }
    result: dict[str, Any] = {"clip": path.name, "measured": measured, "profile": None}

    if use_llm:
        t = time.perf_counter()
        try:
            with get_sessionmaker()() as session:
                breakdown = synthesis.run_visual_breakdown(
                    scene=scenes, visual=visual_result, sheets=sheets,
                    aspect=source.aspect, session=session,
                )  # fmt: skip
                judgment = synthesis.run_style_synthesis(
                    source=source, scene=scenes, audio=audio_result, speech=speech_stats,
                    transcript=transcript, color=color_result, visual=visual_result,
                    breakdown=breakdown, session=session,
                )  # fmt: skip
            profile = synthesis.assemble_profile(
                profile_id=uuid5(NAMESPACE_URL, path.name), name=path.stem, source=source,
                scene=scenes, audio=audio_result, speech=speech_stats, color=color_result,
                visual=visual_result, breakdown=breakdown, synthesis=judgment,
            )  # fmt: skip
            result["profile"] = profile.model_dump(mode="json")
        except LlmError as exc:
            result["llm_error"] = exc.as_dict()
        timed("llm", t)

    result["timings_s"] = timings
    return result


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}/{key}"))
        return out
    if isinstance(value, list):
        return {prefix: json.dumps(value, sort_keys=True)}
    return {prefix: value}


def diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    """Paths whose value changed since the last run (timings ignored)."""
    if previous is None:
        return []
    old = flatten({k: v for k, v in previous.items() if k != "timings_s"})
    new = flatten({k: v for k, v in current.items() if k != "timings_s"})
    return sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))


def summary_row(result: dict[str, Any]) -> list[str]:
    m = result["measured"]
    profile = result["profile"]
    scenes, sp, au = m["scenes"], m["speech"], m["audio"]
    return [
        result["clip"][:28],
        f"{m['source']['duration_s']:.1f}",
        str(len(scenes["cuts_s"]) + 1),
        f"{scenes['shot_len_s']['median']:.2f}",
        scenes["acceleration"],
        f"{sp['wpm']:.0f}" if sp["present"] else "-",
        f"{au['bpm']:.0f}" if au["bpm"] else "-",
        f"{au['integrated_lufs']:.1f}",
        str(len(m["punch_ins"])),
        profile["hook"]["type"] if profile else "-",
        profile["captions"]["preset"] if profile and profile["captions"]["present"] else "-",
        f"{sum(result['timings_s'].values()):.1f}",
    ]


HEADERS = [
    "clip", "dur", "shots", "med shot", "pacing", "wpm", "bpm", "LUFS", "punch", "hook",
    "captions", "secs",
]  # fmt: skip


def print_table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in [HEADERS, *rows]) for i in range(len(HEADERS))]
    for row in [HEADERS, ["-" * w for w in widths], *rows]:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=REPO_ROOT / "eval")
    parser.add_argument("--no-llm", action="store_true", help="measurements only")
    args = parser.parse_args()

    clips = sorted(p for p in args.dir.glob("*") if p.suffix.lower() in VIDEO_SUFFIXES)
    if not clips:
        print(f"No clips in {args.dir}. Add reference videos you have the right to use.")
        return
    key = get_settings().anthropic_api_key
    use_llm = not args.no_llm and key is not None and bool(key.get_secret_value())
    if not use_llm:
        print("LLM steps skipped (no ANTHROPIC_API_KEY, or --no-llm): measurements only.\n")

    out_dir = args.dir / "out"
    out_dir.mkdir(exist_ok=True)
    started = datetime.now(UTC)
    rows: list[list[str]] = []
    changes: dict[str, list[str]] = {}
    for clip in clips:
        target = out_dir / f"{clip.stem}.json"
        previous = json.loads(target.read_text()) if target.exists() else None
        result = analyze_clip(clip, out_dir, use_llm)
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        rows.append(summary_row(result))
        changed = diff(previous, result)
        if changed:
            changes[clip.name] = changed
        if "llm_error" in result:
            print(f"! {clip.name}: {result['llm_error']['message']}")

    print_table(rows)
    print(f"\nProfiles and contact sheets written to {out_dir}")

    if changes:
        print("\nChanged since the last run:")
        for name, paths in changes.items():
            shown = ", ".join(paths[:6]) + (f" (+{len(paths) - 6} more)" if len(paths) > 6 else "")
            print(f"  {name}: {shown}")
    else:
        print("\nNo changes since the last run (or first run).")

    if use_llm:
        with get_sessionmaker()() as session:
            usage = session.execute(
                select(
                    LlmCall.prompt_id,
                    func.count(),
                    func.sum(LlmCall.input_tokens),
                    func.sum(LlmCall.output_tokens),
                    func.sum(LlmCall.cost_usd),
                    func.sum(func.cast(LlmCall.cache_hit, LlmCall.input_tokens.type)),
                )
                .where(LlmCall.created_at >= started)
                .group_by(LlmCall.prompt_id)
            ).all()
        print("\nLLM usage this run:")
        for prompt_id, calls, tokens_in, tokens_out, cost, hits in usage:
            print(
                f"  {prompt_id}: {calls} calls ({hits} cached), "
                f"{tokens_in} in / {tokens_out} out, ${cost:.4f}"
            )


if __name__ == "__main__":
    main()
