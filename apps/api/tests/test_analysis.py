from pathlib import Path

import cv2
import numpy as np
import pytest

from stylecut.analysis import audio, color, scene, speech, visual
from stylecut.analysis.scene import ShotSpan
from stylecut.analysis.speech import Word
from stylecut.media.extract import FrameReader, analysis_wav_args
from stylecut.media.ffmpeg import run_ffmpeg
from stylecut.media.fixtures import CLICK_BPM, FPS, HARDCUT_DURATION_S, HARDCUT_TIMES_S

# ---------------------------------------------------------------- scene


def test_detects_every_hard_cut_within_one_frame(clips: Path) -> None:
    result = scene.detect_scenes(clips / "vertical_hardcuts_15s.mp4", HARDCUT_DURATION_S, FPS)

    assert len(result.cuts_s) == len(HARDCUT_TIMES_S)
    for found, expected in zip(result.cuts_s, HARDCUT_TIMES_S, strict=True):
        assert abs(found - expected) <= 1 / FPS + 1e-6, (found, expected)
    assert result.detector == "content"
    assert len(result.shots) == len(HARDCUT_TIMES_S) + 1
    assert (result.shots[0].start_s, result.shots[-1].end_s) == (0.0, HARDCUT_DURATION_S)
    assert result.shot_len_s.min == pytest.approx(1.0, abs=0.05)
    assert result.shot_len_s.max == pytest.approx(2.0, abs=0.05)
    assert result.cuts_per_5s == [3.0, 4.0, 3.0]


def test_single_shot_video_has_no_cuts(clips: Path) -> None:
    result = scene.detect_scenes(clips / "broll_5s.mp4", 5.0, FPS)
    assert result.cuts_s == []
    assert len(result.shots) == 1
    assert result.acceleration == "steady"
    assert result.max_shot_s == 5.0


def test_build_scene_result_merges_close_cuts_and_clamps_max_shot() -> None:
    result = scene.build_scene_result([0.05, 2.0, 2.1, 4.0, 29.95], duration_s=30.0, fps=30.0)
    assert result.cuts_s == [2.0, 4.0]  # 0.05 and 29.95 are at the edges; 2.1 merges into 2.0
    assert [s.idx for s in result.shots] == [0, 1, 2]
    assert result.max_shot_s == 6.0  # p90 is ~21s, clamped

    fast = scene.build_scene_result([i * 0.5 for i in range(1, 20)], duration_s=10.0, fps=30.0)
    assert fast.max_shot_s == 1.5


@pytest.mark.parametrize(
    ("curve", "expected"),
    [
        ([3, 3, 3, 3], "steady"),
        ([1, 2, 3, 4, 5], "speeds_up"),
        ([5, 4, 3, 2, 1], "slows_down"),
        ([0, 6, 0, 6, 0, 6, 0], "bursty"),
        ([4], "steady"),
        ([], "steady"),
    ],
)
def test_classify_acceleration(curve: list[float], expected: str) -> None:
    assert scene.classify_acceleration(curve) == expected


def test_pacing_curve_scales_a_partial_last_window() -> None:
    assert scene.pacing_curve([1, 2, 6, 11, 12], 12.5) == [2.0, 1.0, 4.0]  # 2 cuts in 2.5s
    assert scene.pacing_curve([1, 2, 6], 11.0) == [2.0, 1.0]  # 1s tail is dropped
    assert scene.pacing_curve([1.0], 3.0) == [1.67]  # a short video still gets one window


# ---------------------------------------------------------------- audio


def test_click_track_tempo_beats_and_loudness(clips: Path) -> None:
    result = audio.analyze_audio(clips / "music_120bpm_20s.wav")

    assert result.has_audio and result.music_present
    assert result.bpm == pytest.approx(CLICK_BPM, abs=2.0)
    assert len(result.beats_s) >= 30
    intervals = np.diff(result.beats_s)
    assert float(np.median(intervals)) == pytest.approx(60 / CLICK_BPM, abs=0.02)
    assert -60 < result.integrated_lufs < 0
    assert len(result.energy_curve) == 20 and max(result.energy_curve) == 1.0

    # Cuts placed on detected beats are on the beat; cuts placed between them are not.
    on_beat = result.beats_s[4:12:2]
    off_beat = [b + 0.25 for b in on_beat]
    assert audio.cut_on_beat_fraction(on_beat, result.beats_s) == 1.0
    assert audio.cut_on_beat_fraction(off_beat, result.beats_s) == 0.0
    assert audio.cut_on_beat_fraction(on_beat[:2] + off_beat[:2], result.beats_s) == 0.5


def test_steady_tone_is_not_music_and_silence_is_handled(clips: Path, tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    run_ffmpeg(analysis_wav_args(clips / "talking_head_10s.mp4", wav))
    tone = audio.analyze_audio(wav)
    assert tone.has_audio and not tone.music_present
    assert tone.bpm is None and tone.beats_s == []

    silent = tmp_path / "silent.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", str(silent)])
    quiet = audio.analyze_audio(silent)
    assert quiet.integrated_lufs == audio.SILENCE_LUFS and not quiet.music_present

    none = audio.silent_result(4.2)
    assert not none.has_audio and len(none.energy_curve) == 5


def test_cut_on_beat_fraction_edge_cases() -> None:
    assert audio.cut_on_beat_fraction([], [1.0]) is None
    assert audio.cut_on_beat_fraction([1.0], []) is None
    assert audio.cut_on_beat_fraction([1.07, 1.09, 2.0], [1.0, 2.05]) == pytest.approx(0.667)


# ---------------------------------------------------------------- speech


def _words(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in items]


def test_speech_stats_measures_wpm_over_speech_time_only() -> None:
    # 10 words in two bursts of 2s each, separated by a 6s b-roll gap, in a 12s video.
    first = [(f"w{i}", i * 0.4, i * 0.4 + 0.3) for i in range(5)]
    second = [(f"w{i}", 8 + i * 0.4, 8 + i * 0.4 + 0.3) for i in range(5)]
    stats = speech.speech_stats(_words(*first, *second), duration_s=12.0)

    assert stats.present and stats.word_count == 10
    # speech time = 10 words * 0.3s + 8 gaps of 0.1s; the 6.1s gap is not speech
    assert stats.coverage_pct == pytest.approx(3.8 / 12, abs=0.001)
    assert stats.wpm == pytest.approx(10 / (3.8 / 60), abs=0.5)
    assert stats.pause_ms_p50 == pytest.approx(100, abs=1)
    assert stats.pause_ms_p90 > 100  # pulled up by the long gap


def test_speech_stats_without_speech() -> None:
    stats = speech.speech_stats(_words(("hi", 0.0, 0.2)), duration_s=10.0)
    assert (stats.present, stats.wpm, stats.coverage_pct) == (False, 0.0, 0.0)
    assert speech.speech_stats([], 10.0).present is False


def test_filler_counting_distinguishes_filler_from_content_words() -> None:
    words = _words(
        ("Um,", 0.0, 0.2), ("I", 0.3, 0.4), ("like", 0.45, 0.6), ("pizza.", 0.65, 0.9),
        ("It's,", 1.0, 1.2), ("like,", 1.5, 1.7), ("really", 2.0, 2.3), ("good,", 2.35, 2.6),
        ("you", 2.7, 2.8), ("know.", 2.85, 3.0),
        ("So,", 3.5, 3.7), ("basically", 3.8, 4.2), ("so", 4.3, 4.4), ("good.", 4.45, 4.7),
    )  # fmt: skip
    # um, filler "like,", "you know", sentence-initial "So,", "basically"
    assert speech.count_fillers(words) == 5
    stats = speech.speech_stats(words, 5.0)
    assert stats.filler_rate == pytest.approx(5 * 100 / 14, abs=0.01)


# ---------------------------------------------------------------- color


def test_color_stats_separate_warm_cool_bright_and_dark() -> None:
    def solid(bgr: tuple[int, int, int]) -> np.ndarray:
        return np.full((96, 54, 3), bgr, dtype=np.uint8)

    luma_w, contrast_w, sat_w, _ = color.frame_stats(solid((255, 255, 255)))
    luma_k, _, _, _ = color.frame_stats(solid((0, 0, 0)))
    assert luma_w > 0.95 and luma_k < 0.05 and contrast_w == 0.0 and sat_w == 0.0

    *_, sat_orange, warmth_orange = color.frame_stats(solid((0, 140, 255)))
    *_, warmth_blue = color.frame_stats(solid((255, 80, 0)))
    assert sat_orange > 0.9 and warmth_orange > 0.3 and warmth_blue < -0.3

    half = solid((0, 0, 0))
    half[:48] = 255
    assert color.frame_stats(half)[1] == pytest.approx(0.5, abs=0.02)


def test_eq_params_are_neutral_at_baseline_and_clamped() -> None:
    neutral = color.eq_params(color.NEUTRAL_LUMA, color.NEUTRAL_CONTRAST, color.NEUTRAL_SATURATION)
    assert neutral == {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0}
    extreme = color.eq_params(1.0, 0.6, 1.0)
    assert extreme == {"brightness": 0.15, "contrast": 1.3, "saturation": 1.5, "gamma": 1.0}
    assert color.summarize([]).frames_sampled == 0


def test_analyze_color_on_clip_is_deterministic(clips: Path) -> None:
    first = color.analyze_color(clips / "vertical_hardcuts_15s.mp4", HARDCUT_DURATION_S)
    assert first.frames_sampled == 15
    assert first.saturation > 0.5  # saturated color cards
    assert first == color.analyze_color(clips / "vertical_hardcuts_15s.mp4", HARDCUT_DURATION_S)


# ---------------------------------------------------------------- visual


def _texture(seed: int = 7, size: tuple[int, int] = (540, 960)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = np.full((size[1], size[0], 3), 40, dtype=np.uint8)
    for _ in range(140):
        x, y = int(rng.integers(0, size[0])), int(rng.integers(0, size[1]))
        color_bgr = tuple(int(c) for c in rng.integers(60, 255, 3))
        if rng.random() < 0.5:
            cv2.circle(image, (x, y), int(rng.integers(8, 40)), color_bgr, -1)
        else:
            cv2.rectangle(
                image,
                (x, y),
                (x + int(rng.integers(15, 70)), y + int(rng.integers(15, 70))),
                color_bgr,
                -1,
            )
    return image


def _zoom(image: np.ndarray, scale: float) -> np.ndarray:
    h, w = image.shape[:2]
    cw, ch = round(w / scale), round(h / scale)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return cv2.resize(image[y0 : y0 + ch, x0 : x0 + cw], (w, h), interpolation=cv2.INTER_LINEAR)


@pytest.mark.parametrize("scale", [1.12, 1.2, 1.4])
def test_punch_in_scale_is_estimated(scale: float) -> None:
    base = _texture()
    assert visual.estimate_punch_in(base, _zoom(base, scale)) == pytest.approx(scale, abs=0.04)


def test_punch_in_is_not_reported_for_other_cuts() -> None:
    base = _texture()
    assert visual.estimate_punch_in(base, base) is None  # same framing: scale 1.0
    assert visual.estimate_punch_in(base, _texture(seed=99)) is None  # a different scene
    assert visual.estimate_punch_in(_zoom(base, 1.2), base) is None  # a pull-out
    flat = np.full_like(base, 128)
    assert visual.estimate_punch_in(flat, flat) is None  # nothing to match


def test_flow_magnitude_is_zero_when_static_and_grows_with_motion() -> None:
    base = _texture()
    shifted = np.roll(base, 12, axis=1)
    assert visual.flow_magnitude(base, base) < 0.05
    assert visual.flow_magnitude(base, shifted) > 1.0


def test_pick_frames_respects_the_frame_budget() -> None:
    def spans(n: int) -> list[ShotSpan]:
        return [ShotSpan(idx=i, start_s=i * 2.0, end_s=i * 2.0 + 2.0) for i in range(n)]

    few = visual.pick_frames(spans(3))
    assert [(f.shot_idx, f.t) for f in few] == [
        (0, 0.5),
        (0, 1.5),
        (1, 2.5),
        (1, 3.5),
        (2, 4.5),
        (2, 5.5),
    ]
    assert len(visual.pick_frames(spans(24))) == 48
    one_each = visual.pick_frames(spans(30))
    assert len(one_each) == 30 and one_each[0].t == 1.0
    many = visual.pick_frames(spans(100))
    assert len(many) <= 48 and many[0].shot_idx == 0 and many[-1].shot_idx == 99
    assert visual.pick_frames([]) == []


def test_contact_sheets_and_shot_measures_on_hardcut_clip(clips: Path) -> None:
    path = clips / "vertical_hardcuts_15s.mp4"
    shots = scene.detect_scenes(path, HARDCUT_DURATION_S, FPS).shots
    result, sheets = visual.analyze_visual(path, shots)

    assert len(result.frames) == 22 and result.sheet_count == len(sheets) == 2
    decoded = cv2.imdecode(np.frombuffer(sheets[0], np.uint8), cv2.IMREAD_COLOR)
    tile_w = round(visual.TILE_HEIGHT * 540 / 960)
    assert decoded.shape == (3 * visual.TILE_HEIGHT, 4 * tile_w, 3)
    # Tile 0 is the red first card (BGR), below its label.
    b, g, r = decoded[visual.TILE_HEIGHT // 2, tile_w // 2]
    assert r > 200 and g < 60 and b < 60

    assert [m.idx for m in result.shots] == list(range(len(shots)))
    assert all(m.motion_score < 0.05 for m in result.shots)  # solid cards do not move
    assert not any(m.punch_in for m in result.shots)  # and have no features to match
    assert visual.punch_in_summary(result.shots, HARDCUT_DURATION_S) == (None, 1.15)


def test_contact_sheet_is_sized_to_its_tiles() -> None:
    frame = np.full((96, 54, 3), 200, dtype=np.uint8)
    tile_w = round(visual.TILE_HEIGHT * 54 / 96)

    def sheet_shape(n: int) -> tuple[int, ...]:
        frames = [(visual.SheetFrame(shot_idx=i, t=float(i)), frame) for i in range(n)]
        sheets = visual.build_sheets(frames)
        return cv2.imdecode(np.frombuffer(sheets[-1], np.uint8), cv2.IMREAD_COLOR).shape

    assert sheet_shape(2) == (visual.TILE_HEIGHT, 2 * tile_w, 3)
    assert sheet_shape(5) == (2 * visual.TILE_HEIGHT, 4 * tile_w, 3)
    assert sheet_shape(12) == (3 * visual.TILE_HEIGHT, 4 * tile_w, 3)
    assert sheet_shape(13) == (visual.TILE_HEIGHT, tile_w, 3)  # second sheet holds one tile
    assert visual.build_sheets([]) == []


def test_punch_in_summary() -> None:
    measures = [
        visual.ShotMeasure(idx=0, motion_score=0, punch_in=False),
        visual.ShotMeasure(idx=1, motion_score=0, punch_in=True, punch_in_scale=1.2),
        visual.ShotMeasure(idx=2, motion_score=0, punch_in=True, punch_in_scale=1.1),
        visual.ShotMeasure(idx=3, motion_score=0, punch_in=True, punch_in_scale=1.3),
    ]
    assert visual.punch_in_summary(measures, 12.0) == (4.0, 1.2)


def test_frame_reader_clamps_out_of_range_times(clips: Path) -> None:
    with FrameReader(clips / "broll_5s.mp4") as reader:
        assert reader.fps == pytest.approx(FPS)
        assert reader.at(-1.0) is not None and reader.at(999.0) is not None
        assert reader.pair_at(1.0) is not None
