import json
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stylecut.analysis import judgment, speech, synthesis
from stylecut.analysis.scene import build_scene_result
from stylecut.analysis.speech import Transcript, Word
from stylecut.db.models import Asset, Job, LlmCache, LlmCall, ReferenceVideo, StyleProfileRow
from stylecut.jobs.base import start_pipeline
from stylecut.jobs.demo import demo_sleep
from stylecut.jobs.events import channel
from stylecut.llm import client as llm_client
from stylecut.llm.client import LlmError, call_structured, cost_usd
from stylecut.llm.prompts import style_synthesis, visual_breakdown
from stylecut.media.fixtures import HARDCUT_DURATION_S, HARDCUT_TIMES_S
from stylecut.redis_client import get_redis
from stylecut.schemas.style_profile import (
    JsonPointerError,
    StyleProfile,
    apply_overrides,
)
from stylecut.storage import keys, s3
from tests.test_uploads_references import _follow, _upload

API = "/api/v1"
CASSETTES = Path(__file__).parent / "llm_cassettes"


def cassette(prompt: Any, name: str = "hardcuts") -> dict[str, Any]:
    path = CASSETTES / f"{prompt.PROMPT.id}_v{prompt.PROMPT.version}" / f"{name}.json"
    data: dict[str, Any] = json.loads(path.read_text())
    return data


class FakeAnthropic:
    """Replays cassettes through the same `messages.parse` surface the client uses."""

    def __init__(self, responses: dict[str, list[Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = responses or {}
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        model: type[BaseModel] = kwargs["output_format"]
        queued = self._responses.get(model.__name__)
        if queued:
            item = queued.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        prompt = visual_breakdown if model is judgment.VisualBreakdown else style_synthesis
        return _response(model.model_validate(cassette(prompt)))


def _response(parsed: Any, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        parsed_output=parsed,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1500, output_tokens=500),
    )


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch, db: Session) -> FakeAnthropic:
    db.query(LlmCache).delete()
    db.commit()
    fake = FakeAnthropic()
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    return fake


@pytest.fixture
def canned_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whisper is not run in tests (model download); its output is replaced."""
    words = [
        Word(text=f"word{i}", start=round(0.2 + i * 0.3, 3), end=round(0.4 + i * 0.3, 3))
        for i in range(40)
    ]
    monkeypatch.setattr(
        speech, "transcribe", lambda _: Transcript(language="en", text="canned", words=words)
    )


# ---------------------------------------------------------------- full pipeline


def test_reference_becomes_a_style_profile(
    client: TestClient, db: Session, clips: Path, eager: None,
    fake_llm: FakeAnthropic, canned_speech: None,
) -> None:  # fmt: skip
    uploaded = _upload(client, clips / "vertical_hardcuts_15s.mp4")
    pubsub = get_redis().pubsub()
    pubsub.psubscribe("job:*")
    pubsub.get_message(timeout=1)

    res = client.post(f"{API}/references", json={"asset_id": uploaded["asset_id"]})
    assert res.status_code == 202, res.text
    job, reference, asset = _follow(db, res.json())
    assert (job.status, job.error, reference.status) == ("succeeded", None, "ready")

    # One parent stream; progress never goes backwards; the PRD's step names appear.
    events = []
    while (message := pubsub.get_message(timeout=0.2)) is not None:
        if message["type"] == "pmessage" and message["channel"] == channel(job.id):
            events.append(json.loads(message["data"]))
    pubsub.close()
    progress = [e["progress"] for e in events]
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert {
        "Detecting cuts", "Listening to the audio", "Transcribing speech", "Reading colors",
        "Picking frames", "Reading captions and shots", "Building the style", "Cleaning up",
    } <= {e["step"] for e in events}  # fmt: skip

    out = client.get(f"{API}/references/{reference.id}").json()
    profile_id = out["style_profile_id"]
    assert profile_id is not None
    body = client.get(f"{API}/style-profiles/{profile_id}").json()
    profile = StyleProfile.model_validate(body["profile"])

    # [D] fields come from code: measured on the clip, whatever the cassettes say.
    assert profile.schema_version == 1 and str(profile.id) == profile_id
    assert (profile.source.platform, profile.source.aspect, profile.source.fps) == (
        "upload",
        "9:16",
        30.0,
    )
    assert profile.source.duration_s == pytest.approx(HARDCUT_DURATION_S, abs=0.1)
    assert profile.pacing.shot_count == len(HARDCUT_TIMES_S) + 1
    assert [s.start_s for s in profile.shots[1:]] == pytest.approx(HARDCUT_TIMES_S, abs=0.04)
    assert profile.pacing.cuts_per_5s == [3.0, 4.0, 3.0]
    assert profile.pacing.cut_on_beat_pct is None  # a steady tone is not music
    assert profile.audio.music_present is False and profile.audio.bpm is None
    assert profile.audio.music_mood is None  # the cassette claims a mood; there is no music
    assert profile.speech.present and profile.speech.wpm > 100
    assert profile.rules.punch_in_every_s is None and profile.rules.punch_in_scale == 1.15
    assert profile.rules.broll_ratio == pytest.approx(3.5 / 15, abs=0.01)  # shots 3 and 4
    assert profile.hook.duration_s == pytest.approx(2.5, abs=0.04)  # the hook beat, snapped

    # [J] fields come from the cassettes, normalized.
    assert [s.kind for s in profile.shots][:5] == ["a_roll", "a_roll", "a_roll", "b_roll", "screen"]
    captions = profile.captions
    assert (captions.preset, captions.font_family) == ("bold_pop", "Montserrat ExtraBold")
    assert (captions.words_per_chunk, captions.position_y_pct) == ((1, 3), 1.0)
    assert (captions.fill, captions.stroke, captions.highlight_color) == (
        "#FFFFFF",
        None,
        "#FFE600",
    )
    assert [(b.id, b.start_s, b.end_s) for b in profile.beats] == [
        ("hook", 0.0, pytest.approx(2.5, abs=0.04)),
        ("value", pytest.approx(2.5, abs=0.04), pytest.approx(11.0, abs=0.04)),
        ("cta", pytest.approx(11.0, abs=0.04), pytest.approx(15.0, abs=0.04)),
    ]
    assert [s.beat_id for s in profile.shots] == ["hook"] * 2 + ["value"] * 6 + ["cta"] * 3
    assert profile.rules.zoom_on == ["emphasis_word", "new_point"]
    assert profile.rules.transitions == ["hard_cut"]
    assert profile.audio.sfx_types == ["pop"]
    assert profile.overlays[0].start_s == 0.0
    assert profile.confidence["captions"] == 1.0 and profile.confidence["beats"] == 0.7

    # The LLM saw contact sheets and measurements, never the video; both calls were logged.
    vision_call, synthesis_call = fake_llm.calls
    assert vision_call["model"] == "claude-sonnet-5-5"
    blocks = vision_call["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["image", "image", "text"]
    assert "Measured shot table" in blocks[-1]["text"]
    assert "word0 word1" in synthesis_call["messages"][0]["content"][-1]["text"]
    assert "tool_choice" not in vision_call
    logged = db.scalars(select(LlmCall).where(LlmCall.job_id.in_(_child_ids(db, job)))).all()
    assert sorted(c.prompt_id for c in logged) == ["style_synthesis", "visual_breakdown"]
    assert all(c.cost_usd == cost_usd("claude-sonnet-5-5", 1500, 500) for c in logged)

    # Reference media is gone; derived data and contact sheets stay.
    db.refresh(asset)
    assert (asset.status, asset.proxy_key) == ("expired", None)
    for key in (
        keys.reference_raw(asset.id, "mp4"),
        keys.reference_proxy(asset.id),
        keys.reference_speech(asset.id),
    ):
        with pytest.raises(s3.ObjectNotFound):
            s3.object_size(key)
    assert s3.object_size(keys.reference_derived(asset.id, "scenes")) > 0
    assert len(body["sheet_urls"]) == 2
    with urllib.request.urlopen(body["sheet_urls"][0], timeout=30) as response:
        assert response.read()[:3] == b"\xff\xd8\xff"  # JPEG

    listed = client.get(f"{API}/style-profiles").json()
    mine = next(p for p in listed if p["id"] == profile_id)
    assert (mine["shot_count"], mine["hook_type"], mine["platform"]) == (11, "bold_claim", "upload")


def _child_ids(db: Session, parent: Job) -> list[UUID]:
    return list(db.scalars(select(Job.id).where(Job.parent_id == parent.id)))


def test_analysis_without_an_api_key_fails_clearly_and_keeps_the_media(
    client: TestClient, db: Session, clips: Path, eager: None, canned_speech: None
) -> None:
    db.query(LlmCache).delete()
    db.commit()
    uploaded = _upload(client, clips / "broll_5s.mp4")
    res = client.post(f"{API}/references", json={"asset_id": uploaded["asset_id"]})
    job, reference, asset = _follow(db, res.json())

    assert (job.status, job.error) == ("failed", "Style analysis needs an Anthropic API key.")
    assert reference.status == "failed"
    assert reference.error is not None and reference.error["code"] == "LLM_NOT_CONFIGURED"
    assert "ANTHROPIC_API_KEY" in reference.error["hint"]
    # Nothing was cleaned up, so a retry after adding the key can reuse the proxy.
    assert asset.status == "ready" and asset.proxy_key is not None
    assert s3.object_size(asset.proxy_key) > 0
    assert client.get(f"{API}/references/{reference.id}").json()["style_profile_id"] is None


# ---------------------------------------------------------------- pipelines


def _children(db: Session, parent: Job) -> list[Job]:
    order = [s["job_id"] for group in parent.input["groups"] for s in group]
    rows = {str(j.id): j for j in db.scalars(select(Job).where(Job.parent_id == parent.id))}
    return [rows[i] for i in order]


def test_pipeline_runs_groups_in_order_and_finishes_once(
    db: Session, user_id: UUID, eager: None
) -> None:
    pubsub = get_redis().pubsub()
    pubsub.psubscribe("job:*")
    pubsub.get_message(timeout=1)
    parent = start_pipeline(
        db,
        type="test.pipeline",
        owner_id=user_id,
        stages=[(demo_sleep, 1.0), [(demo_sleep, 1.0), (demo_sleep, 2.0)], (demo_sleep, 1.0)],
        args={"seconds": 0, "steps": 2},
    )
    db.refresh(parent)
    assert (parent.status, parent.progress, parent.input["current"]) == ("succeeded", 1.0, 2)
    children = _children(db, parent)
    assert [c.status for c in children] == ["succeeded"] * 4
    assert [len(g) for g in parent.input["groups"]] == [1, 2, 1]

    events = []
    while (message := pubsub.get_message(timeout=0.2)) is not None:
        if message["type"] == "pmessage" and message["channel"] == channel(parent.id):
            events.append(json.loads(message["data"]))
    pubsub.close()
    progress = [e["progress"] for e in events]
    assert progress == sorted(progress)
    assert [e["status"] for e in events].count("succeeded") == 1
    # After the first stage (weight 1 of 5) the parent is at 20%.
    assert any(p == pytest.approx(0.2) for p in progress)


def test_pipeline_stops_when_a_stage_fails_and_restarts_on_the_same_key(
    db: Session, user_id: UUID, eager: None
) -> None:
    key = f"{uuid4()}:test:1"
    stages = [(demo_sleep, 1.0), [(demo_sleep, 1.0), (demo_sleep, 1.0)], (demo_sleep, 1.0)]
    parent = start_pipeline(
        db, type="test.pipeline", owner_id=user_id, stages=stages,
        args={"seconds": 0, "steps": 1, "fail": True}, key=key,
    )  # fmt: skip
    db.refresh(parent)
    assert (parent.status, parent.error) == ("failed", "RuntimeError: demo failure requested")
    assert [c.status for c in _children(db, parent)] == ["failed", "queued", "queued", "queued"]

    again = start_pipeline(
        db, type="test.pipeline", owner_id=user_id, stages=stages,
        args={"seconds": 0, "steps": 1}, key=key,
    )  # fmt: skip
    db.refresh(again)
    assert again.id == parent.id and again.status == "succeeded" and again.error is None
    assert db.scalar(select(func.count()).select_from(Job).where(Job.parent_id == parent.id)) == 4

    same = start_pipeline(
        db, type="test.pipeline", owner_id=user_id, stages=stages, args={}, key=key
    )
    assert same.id == parent.id  # already succeeded: nothing new is started

    with pytest.raises(ValueError):
        start_pipeline(db, type="t", owner_id=user_id, stages=[], args={})


# ---------------------------------------------------------------- llm client


def _vision_inputs() -> dict[str, Any]:
    return {
        "duration_s": 15.0, "aspect": "9:16", "sheet_count": 1, "frame_count": 2,
        "shots": [{"idx": 0, "start_s": 0, "end_s": 15, "motion_score": 0.1, "punch_in": False}],
        "caption_presets": ["bold_pop"], "fonts": ["Anton"],
    }  # fmt: skip


def _call(db: Session, **kwargs: Any) -> judgment.VisualBreakdown:
    return call_structured(
        visual_breakdown.PROMPT, _vision_inputs(), judgment.VisualBreakdown,
        session=db, images=[b"\xff\xd8\xff fake jpeg"], **kwargs,
    )  # fmt: skip


def test_llm_results_are_cached_by_content(db: Session, fake_llm: FakeAnthropic) -> None:
    before = db.scalar(select(func.count()).select_from(LlmCall)) or 0
    first = _call(db)
    second = _call(db)
    assert first == second and len(fake_llm.calls) == 1
    calls = db.scalars(select(LlmCall).order_by(LlmCall.created_at.desc()).limit(2)).all()
    assert (db.scalar(select(func.count()).select_from(LlmCall)) or 0) == before + 2
    assert sorted(c.cache_hit for c in calls) == [False, True]
    assert next(c for c in calls if c.cache_hit).cost_usd == 0.0
    live = next(c for c in calls if not c.cache_hit)
    assert (live.prompt_id, live.prompt_version, live.input_tokens, live.output_tokens) == (
        "visual_breakdown", 1, 1500, 500,
    )  # fmt: skip

    # A different image is a different request.
    call_structured(
        visual_breakdown.PROMPT, _vision_inputs(), judgment.VisualBreakdown,
        session=db, images=[b"another image"],
    )  # fmt: skip
    assert len(fake_llm.calls) == 2


def test_llm_retries_once_with_the_validation_error(db: Session, fake_llm: FakeAnthropic) -> None:
    try:
        judgment.VisualBreakdown.model_validate({"shots": "nope"})
    except ValidationError as exc:
        invalid = exc
    fake_llm._responses["VisualBreakdown"] = [invalid]
    result = _call(db)
    assert isinstance(result, judgment.VisualBreakdown) and len(fake_llm.calls) == 2
    retry_text = fake_llm.calls[1]["messages"][0]["content"][-1]["text"]
    assert "failed these checks" in retry_text and "shots" in retry_text

    db.query(LlmCache).delete()
    db.commit()
    fake_llm._responses["VisualBreakdown"] = [invalid, invalid]
    with pytest.raises(LlmError) as excinfo:
        _call(db)
    assert excinfo.value.code == "LLM_INVALID_OUTPUT" and len(fake_llm.calls) == 4


def test_llm_refusal_truncation_and_missing_key(
    db: Session, fake_llm: FakeAnthropic, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm._responses["VisualBreakdown"] = [_response(None, "refusal")]
    with pytest.raises(LlmError) as excinfo:
        _call(db)
    assert excinfo.value.code == "LLM_REFUSED"

    fake_llm._responses["VisualBreakdown"] = [_response(None, "max_tokens")]
    with pytest.raises(LlmError) as excinfo:
        _call(db)
    assert excinfo.value.code == "LLM_OUTPUT_TRUNCATED"
    assert db.scalar(select(func.count()).select_from(LlmCache)) == 0  # failures are not cached

    monkeypatch.undo()
    with pytest.raises(LlmError) as excinfo:
        llm_client.get_client()
    assert excinfo.value.code == "LLM_NOT_CONFIGURED"


def test_cost_and_prompt_contract() -> None:
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 100_000) == 3.0
    assert cost_usd("claude-haiku-5-5", 2_000_000, 0) == 0.2
    assert cost_usd("unknown-model", 10, 10) == 0.0

    for prompt in (visual_breakdown.PROMPT, style_synthesis.PROMPT):
        assert "ground truth" in prompt.full_system and prompt.version >= 1
    with pytest.raises(TypeError):
        call_structured(visual_breakdown.PROMPT, {}, judgment.SynthesisOut, session=None)  # type: ignore[arg-type]


def test_llm_output_models_have_no_measured_fields() -> None:
    """Rule 2: the LLM cannot set anything code measures, because no field exists for it."""

    def field_names(model: type[BaseModel], seen: set[str] | None = None) -> set[str]:
        names: set[str] = set() if seen is None else seen
        for name, info in model.model_fields.items():
            names.add(name)
            for arg in [info.annotation, *getattr(info.annotation, "__args__", ())]:
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    field_names(arg, names)
        return names

    measured = {
        "bpm", "integrated_lufs", "wpm", "pause_ms_p50", "pause_ms_p90", "filler_rate",
        "coverage_pct", "shot_count", "shot_len_s", "cuts_per_5s", "max_shot_s",
        "cut_on_beat_pct", "motion_score", "punch_in", "punch_in_scale", "punch_in_every_s",
        "broll_ratio", "luma_mean", "contrast", "saturation", "warmth", "eq", "energy_curve",
        "drops_s", "music_present", "duration_s", "fps", "acceleration",
    }  # fmt: skip
    assert not (field_names(judgment.SynthesisOut) & measured)
    # Overlay time ranges are judgment; nothing else in the vision output is measured.
    assert not (field_names(judgment.VisualBreakdown) & measured)


# ---------------------------------------------------------------- assembly helpers


def test_normalize_beats_snaps_sorts_and_deduplicates() -> None:
    scene = build_scene_result([2.0, 5.0], duration_s=10.0, fps=30.0)

    def beat(id_: str, start: float, end: float) -> judgment.BeatJudgment:
        return judgment.BeatJudgment(
            id=id_, function="value", start_s=start, end_s=end, technique="t", must_have=False
        )

    beats = synthesis.normalize_beats(
        [beat("b", 5.2, 12.0), beat("a", -1.0, 1.8), beat("a", 2.1, 4.75), beat("", 7.0, 7.0)],
        scene,
    )
    assert [(b.id, b.start_s, b.end_s) for b in beats] == [
        ("a", 0.0, 2.0),
        ("a_2", 2.0, 5.0),  # 4.75 snaps to the cut at 5.0
        ("b", 5.0, 10.0),
    ]


def test_nearest_aspect_and_transcript_lines() -> None:
    assert synthesis.nearest_aspect(540, 960) == "9:16"
    assert synthesis.nearest_aspect(1080, 1350) == "4:5"
    assert synthesis.nearest_aspect(1000, 1000) == "1:1"
    assert synthesis.nearest_aspect(1920, 1080) == "16:9"
    assert synthesis.nearest_aspect(None, None) == "9:16"

    transcript = Transcript(
        text="",
        words=[
            Word(text="Stop", start=0.2, end=0.5),
            Word(text="scrolling.", start=0.55, end=1.0),
            Word(text="Here's", start=2.4, end=2.7),
            Word(text="why.", start=2.75, end=3.0),
        ],  # fmt: skip
    )
    assert synthesis.transcript_lines(transcript) == "[0.2] Stop scrolling.\n[2.4] Here's why."
    assert synthesis.transcript_lines(Transcript(text="", words=[])) == ""


def test_apply_overrides() -> None:
    data = {"captions": {"fill": "#FFFFFF", "words_per_chunk": [1, 3]}, "beats": [{"id": "hook"}]}
    result = apply_overrides(
        data, {"/captions/fill": "#000000", "/captions/words_per_chunk/1": 4, "/beats/0/id": "x"}
    )
    assert result == {
        "captions": {"fill": "#000000", "words_per_chunk": [1, 4]},
        "beats": [{"id": "x"}],
    }
    assert data["captions"]["fill"] == "#FFFFFF"  # the input is not mutated

    for bad in ("/captions/nope", "/beats/3/id", "captions/fill", "/", "/captions/fill/deeper"):
        with pytest.raises(JsonPointerError):
            apply_overrides(data, {bad: 1})


# ---------------------------------------------------------------- style profile API


@pytest.fixture
def profile_row(db: Session, user_id: UUID) -> StyleProfileRow:
    scene = build_scene_result(list(HARDCUT_TIMES_S), HARDCUT_DURATION_S, 30.0)
    from stylecut.analysis.audio import silent_result
    from stylecut.analysis.color import summarize
    from stylecut.analysis.visual import ShotMeasure, VisualResult

    profile_id = uuid4()
    profile = synthesis.assemble_profile(
        profile_id=profile_id,
        name="Test style",
        source=synthesis.SourceInfo(platform="upload", duration_s=15.0, aspect="9:16", fps=30.0),
        scene=scene,
        audio=silent_result(15.0),
        speech=speech.speech_stats([], 15.0),
        color=summarize([]),
        visual=VisualResult(
            frames=[],
            sheet_count=0,
            shots=[ShotMeasure(idx=s.idx, motion_score=0.0, punch_in=False) for s in scene.shots],
        ),  # fmt: skip
        breakdown=judgment.VisualBreakdown.model_validate(cassette(visual_breakdown)),
        synthesis=judgment.SynthesisOut.model_validate(cassette(style_synthesis)),
    )
    row = StyleProfileRow(
        id=profile_id, owner_id=user_id, name="Test style", schema_version=1,
        data=profile.model_dump(mode="json"),
    )  # fmt: skip
    db.add(row)
    db.commit()
    return row


def test_profile_edits_are_overrides_on_top_of_the_analysis(
    client: TestClient, db: Session, profile_row: StyleProfileRow
) -> None:
    url = f"{API}/style-profiles/{profile_row.id}"
    original = client.get(url).json()
    assert original["profile"]["captions"]["highlight_color"] == "#FFE600"
    assert original["profile"]["speech"]["voice_type"] == "none"  # no speech was measured
    assert original["overrides"] == {} and original["sheet_urls"] == []

    patched = client.patch(
        url,
        json={
            "name": "  Punchy finance  ",
            "overrides": {"/captions/highlight_color": "#00FF88", "/pacing/max_shot_s": 2.5},
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == body["profile"]["name"] == "Punchy finance"
    assert body["profile"]["captions"]["highlight_color"] == "#00FF88"
    assert body["profile"]["pacing"]["max_shot_s"] == 2.5
    assert body["overrides"] == {"/captions/highlight_color": "#00FF88", "/pacing/max_shot_s": 2.5}

    # The analyzed values are untouched underneath, and null restores one.
    db.refresh(profile_row)
    assert profile_row.data["captions"]["highlight_color"] == "#FFE600"
    restored = client.patch(url, json={"overrides": {"/captions/highlight_color": None}}).json()
    assert restored["profile"]["captions"]["highlight_color"] == "#FFE600"
    assert restored["overrides"] == {"/pacing/max_shot_s": 2.5}


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"/captions/nope": 1}, "OVERRIDE_INVALID_PATH"),
        ({"/captions/case": "shouting"}, "OVERRIDE_INVALID_VALUE"),
        ({"/captions/position_y_pct": 62}, "OVERRIDE_INVALID_VALUE"),
        ({"/id": str(uuid4())}, "OVERRIDE_PROTECTED"),
        ({"/source/duration_s": 1}, "OVERRIDE_PROTECTED"),
        ({"/schema_version": 2}, "OVERRIDE_PROTECTED"),
    ],
)
def test_invalid_overrides_are_rejected_and_not_stored(
    client: TestClient,
    db: Session,
    profile_row: StyleProfileRow,
    overrides: dict[str, Any],
    code: str,
) -> None:
    res = client.patch(f"{API}/style-profiles/{profile_row.id}", json={"overrides": overrides})
    assert (res.status_code, res.json()["error"]["code"]) == (422, code)
    db.refresh(profile_row)
    assert profile_row.data["user_overrides"] == {}


def test_delete_and_not_found(client: TestClient, profile_row: StyleProfileRow) -> None:
    url = f"{API}/style-profiles/{profile_row.id}"
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert (
        client.patch(url, json={"name": "x"}).json()["error"]["code"] == "STYLE_PROFILE_NOT_FOUND"
    )
    assert client.get(f"{API}/style-profiles/{uuid4()}").status_code == 404


def test_reference_rows_cascade(db: Session, user_id: UUID) -> None:
    asset = Asset(owner_id=user_id, kind="reference", s3_key="k", status="ready")
    db.add(asset)
    db.flush()
    db.add(ReferenceVideo(owner_id=user_id, asset_id=asset.id, platform="upload"))
    db.commit()
    db.delete(asset)
    db.commit()
    assert (
        db.scalar(
            select(func.count())
            .select_from(ReferenceVideo)
            .where(ReferenceVideo.asset_id == asset.id)
        )
        == 0
    )
