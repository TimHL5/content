import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stylecut.db.models import LlmCache, Project, ShootPlanRow, StyleProfileRow
from stylecut.llm import client as llm_client
from stylecut.planning import budget, generate, order
from stylecut.planning.drafts import PartDraft, PlanDraft
from stylecut.planning.pdf import render_plan_pdf
from stylecut.planning.validate import broll_share, downgrade_camera_moves, validate_plan
from stylecut.schemas.shoot_plan import Constraints, ProjectBrief, ShootPlan
from stylecut.schemas.style_profile import StyleProfile

API = "/api/v1"
CASSETTES = Path(__file__).parent / "llm_cassettes"


def cassette(folder: str, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CASSETTES / folder / f"{name}.json").read_text())
    return data


def make_profile(**speech: Any) -> StyleProfile:
    """A 15s talking style: hook 0-2.5, value 2.5-11, cta 11-15; 180 wpm, 90% speech;
    23% b-roll; longest shot 2s."""
    stats = {"mean": 1.4, "median": 1.3, "p10": 1.0, "p90": 2.0, "min": 1.0, "max": 2.0}
    return StyleProfile.model_validate(
        {
            "id": str(uuid4()),
            "name": "Fast finance tip",
            "source": {"platform": "upload", "duration_s": 15.0, "aspect": "9:16", "fps": 30.0},
            "summary": "Rapid talking head with b-roll cutaways.",
            "pacing": {"shot_count": 11, "shot_len_s": stats, "cuts_per_5s": [3, 4, 3],
                       "acceleration": "steady", "max_shot_s": 2.0, "cut_on_beat_pct": None},
            "shots": [{"idx": 0, "start_s": 0, "end_s": 2.5, "kind": "a_roll", "framing": "cu",
                       "camera_motion": "static", "punch_in": False, "motion_score": 0.1,
                       "description": "person speaking to camera", "beat_id": "hook"}],
            "captions": {"present": True, "preset": "bold_pop", "font_family": "Anton", "case": "upper",
                         "words_per_chunk": [1, 3], "lines": 1, "position_y_pct": 0.6, "fill": "#FFFFFF",
                         "stroke": "#000000", "stroke_px": 6, "shadow": True, "highlight": "color",
                         "highlight_color": "#FFE600", "emoji": "none", "animation": "pop"},
            "overlays": [],
            "speech": {"present": True, "coverage_pct": 0.9, "wpm": 180, "pause_ms_p50": 120,
                       "pause_ms_p90": 260, "filler_rate": 0.0, "delivery": "energetic",
                       "voice_type": "on_camera", **speech},
            "audio": {"integrated_lufs": -14.0, "music_present": False, "bpm": None, "energy_curve": [1.0],
                      "drops_s": [], "sfx_density": "low", "sfx_types": [], "music_mood": None},
            "color": {"luma_mean": 0.5, "contrast": 0.2, "saturation": 0.4, "warmth": 0.0,
                      "eq": {"brightness": 0, "contrast": 1, "saturation": 1, "gamma": 1}, "look": "bright"},
            "hook": {"type": "bold_claim", "duration_s": 2.5, "template": "Stop <thing> if you want <outcome>",
                     "visual": "close-up"},
            "beats": [
                {"id": "hook", "function": "hook", "start_s": 0, "end_s": 2.5, "technique": "bold claim", "must_have": True},
                {"id": "value", "function": "value", "start_s": 2.5, "end_s": 11, "technique": "numbered tips", "must_have": True},
                {"id": "cta", "function": "cta", "start_s": 11, "end_s": 15, "technique": "follow ask", "must_have": False},
            ],
            "rules": {"punch_in_every_s": 2.0, "punch_in_scale": 1.15, "zoom_on": ["emphasis_word"],
                      "broll_ratio": 0.233, "jump_cut_silences": True, "transitions": ["hard_cut"],
                      "loop_ending": False, "text_card_usage": "none"},
            "confidence": {"beats": 0.8},
        }
    )  # fmt: skip


BRIEF = ProjectBrief(
    topic="3 mistakes first-time renters make", key_points=["negotiate", "split bills"]
)


def good_plan(profile: StyleProfile, brief: ProjectBrief = BRIEF) -> ShootPlan:
    draft = PlanDraft.model_validate(cassette("shoot_plan_v1", "good"))
    return generate.finalize(draft, project_id=uuid4(), profile=profile, brief=brief)


class FakeAnthropic:
    """Replays queued cassettes per output model through `messages.parse`."""

    def __init__(self, **queues: list[dict[str, Any]]) -> None:
        self.queues = queues
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        model: type[BaseModel] = kwargs["output_format"]
        queue = self.queues[model.__name__]
        data = queue.pop(0) if len(queue) > 1 else queue[0]
        return SimpleNamespace(
            parsed_output=model.model_validate(data),
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=2000, output_tokens=900),
        )

    def prompt_text(self, index: int) -> str:
        text: str = self.calls[index]["messages"][0]["content"][-1]["text"]
        return text


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch, db: Session) -> FakeAnthropic:
    db.query(LlmCache).delete()
    db.commit()
    fake = FakeAnthropic(
        PlanDraft=[cassette("shoot_plan_v1", "good")],
        PartDraft=[cassette("shoot_plan_regen_v1", "hook")],
    )
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    return fake


# ---------------------------------------------------------------- budget


def test_word_budget_and_target_duration() -> None:
    profile = make_profile()
    assert budget.target_duration(BRIEF, profile) == 15.0  # defaults to the reference's length
    assert budget.target_duration(ProjectBrief(topic="t", target_duration_s=30), profile) == 30.0
    # 15s x 90% speech x 180 wpm / 60
    assert budget.word_budget(15.0, profile) == 40
    assert budget.word_budget(30.0, profile) == 81
    assert budget.word_budget(15.0, make_profile(present=False, wpm=0, coverage_pct=0)) == 0
    assert budget.speaking_wpm(make_profile(present=False, wpm=0)) == budget.FALLBACK_WPM


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Stop wasting money on rent.", 5),
        ("It's $1,200 a month, don't sign yet!", 7),
        ("  spaced   out \n words ", 3),
        ("", 0),
        ("state-of-the-art 4K", 2),
    ],
)
def test_count_words(text: str, expected: int) -> None:
    assert budget.count_words(text) == expected


def test_scale_beats_keeps_the_hook_absolute_and_scales_the_rest() -> None:
    profile = make_profile()
    doubled = budget.scale_beats(profile, 30.0)
    assert [(b.id, b.start_s, b.end_s) for b in doubled] == [
        ("hook", 0.0, 2.5),  # not 5.0: a hook that scales stops being a hook
        ("value", 2.5, 21.2),  # 27.5s shared 8.5 : 4
        ("cta", 21.2, 30.0),
    ]
    same = budget.scale_beats(profile, 15.0)
    assert [(b.start_s, b.end_s) for b in same] == [(0.0, 2.5), (2.5, 11.0), (11.0, 15.0)]

    long_hook = profile.model_copy(
        update={"beats": [profile.beats[0].model_copy(update={"end_s": 9.0}), *profile.beats[1:]]}
    )
    assert budget.scale_beats(long_hook, 15.0)[0].end_s == 4.0  # clamped to 4s
    assert budget.scale_beats(profile.model_copy(update={"beats": []}), 15.0) == []


# ---------------------------------------------------------------- finalize, order, validate


def test_finalize_computes_everything_code_owns() -> None:
    profile = make_profile()
    plan = good_plan(profile)

    assert (plan.target_duration_s, plan.word_budget, plan.style_profile_id) == (
        15.0,
        40,
        profile.id,
    )
    assert plan.warnings == []
    assert len(plan.title_options) == 3  # a fourth option is dropped
    # 10 words at 180 wpm
    assert [line.est_duration_s for line in plan.script] == [3.33] * 4

    by_id = {s.id: s for s in plan.shots}
    assert by_id["S1"].takes == 3  # hook
    assert by_id["S2"].takes == 2 and by_id["S4"].takes == 2  # must a_roll
    assert by_id["S3"].takes == 1 and by_id["S6"].takes == 2
    assert by_id["S2"].record_s == 6.0  # 2x on-screen
    assert by_id["S5"].record_s == 3.0  # 1.5s of b-roll still records 3s

    # No gimbal in the brief: the tracking move is downgraded, with a note for the creator.
    assert by_id["S3"].camera_motion == "handheld"
    assert "No gimbal" in by_id["S3"].direction

    # Talking setup first; the hook is filmed last within it; then the b-roll setup.
    assert plan.shoot_order == ["S2", "S4", "S6", "S1", "S3", "S5"]
    assert broll_share(plan) == pytest.approx(3.5 / 15)


def test_gimbal_moves_are_kept_when_the_creator_has_one() -> None:
    brief = BRIEF.model_copy(update={"constraints": Constraints(gear=["phone", "gimbal"])})
    plan = good_plan(make_profile(), brief)
    assert next(s for s in plan.shots if s.id == "S3").camera_motion == "tracking"
    assert downgrade_camera_moves(plan.shots, brief.constraints) == plan.shots


def test_validator_reports_each_broken_rule() -> None:
    profile = make_profile()
    draft = PlanDraft.model_validate(cassette("shoot_plan_v1", "bad"))
    plan = generate.finalize(draft, project_id=uuid4(), profile=profile, brief=BRIEF)
    text = "\n".join(plan.warnings)
    assert re.search(r"Script is 6\d words; the budget is 40", text)
    assert "Must-have beat 'value' has no must-priority shot" in text
    assert "Shots total 19.5s; the target is 15.0s" in text
    assert "B-roll is 41% of runtime; the style uses about 23%" in text
    assert "Shot S5 runs 6.0s; the style's longest shot is 2.0s" in text
    assert len(plan.warnings) == 5


def test_validator_enforces_references_and_constraints() -> None:
    profile = make_profile()
    plan = good_plan(profile)
    assert validate_plan(plan, profile, Constraints()) == []

    no_face = validate_plan(plan, profile, Constraints(can_show_face=False))
    assert len(no_face) == 4 and all("face" in v for v in no_face)
    assert validate_plan(plan, profile, Constraints(max_setups=1)) == [
        "The plan uses 2 setups; the brief allows 1."
    ]

    broken = plan.model_copy(
        update={
            "shots": [
                plan.shots[0].model_copy(
                    update={"line_ids": ["L99"], "setup_id": "nowhere", "beat_id": "intro"}
                ),
                plan.shots[0].model_copy(update={"kind": "screen"}),
                *plan.shots[2:],
            ]
        }
    )
    text = "\n".join(validate_plan(broken, profile, Constraints()))
    for expected in (
        "Duplicate shot ids: S1",
        "Shot S1 uses unknown beat 'intro'",
        "Shot S1 uses unknown setup 'nowhere'",
        "Shot S1 refers to missing script lines: L99",
        "need screen recordings",
    ):
        assert expected in text

    silent = make_profile(present=False, wpm=0, coverage_pct=0)
    spoken = generate.finalize(
        PlanDraft.model_validate(cassette("shoot_plan_v1", "good")),
        project_id=uuid4(), profile=silent, brief=BRIEF,
    )  # fmt: skip
    assert spoken.word_budget == 0
    assert any("no speech" in w for w in spoken.warnings)


def test_shoot_order_is_stable_for_pure_broll() -> None:
    plan = good_plan(make_profile())
    broll_only = [s for s in plan.shots if s.kind == "b_roll"]
    assert order.shoot_order(broll_only, plan.script, {"hook"}) == ["S3", "S5"]
    assert order.shoot_order([], [], set()) == []


# ---------------------------------------------------------------- generation


def test_generate_repairs_once_with_the_violations(db: Session, llm: FakeAnthropic) -> None:
    llm.queues["PlanDraft"] = [cassette("shoot_plan_v1", "bad"), cassette("shoot_plan_v1", "good")]
    profile = make_profile()
    plan = generate.generate_plan(
        project_id=uuid4(), profile=profile, brief=BRIEF, session=db, instruction="keep it punchy"
    )
    assert plan.warnings == [] and len(llm.calls) == 2

    first, second = llm.prompt_text(0), llm.prompt_text(1)
    assert "Word budget: 40 words" in first and "3 mistakes first-time renters make" in first
    assert "keep it punchy" in first and "- negotiate" in first
    assert '"id": "hook"' in first and "about 23%" in first
    assert "failed these checks" not in first
    assert "failed these checks" in second and "Must-have beat" in second
    assert llm.calls[0]["model"] == "claude-sonnet-5-5"


def test_generate_keeps_a_plan_that_cannot_be_repaired(db: Session, llm: FakeAnthropic) -> None:
    llm.queues["PlanDraft"] = [cassette("shoot_plan_v1", "bad")]
    plan = generate.generate_plan(
        project_id=uuid4(), profile=make_profile(), brief=BRIEF, session=db
    )
    assert len(llm.calls) == 2  # one repair attempt, then stop
    assert len(plan.warnings) == 5 and len(plan.shots) == 6


def test_regenerating_the_hook_changes_only_the_hook(db: Session, llm: FakeAnthropic) -> None:
    profile = make_profile()
    before = good_plan(profile)
    after = generate.regenerate_part(
        plan=before, profile=profile, brief=BRIEF, scope="hook", target_id=None,
        instruction="more dramatic", session=db,
    )  # fmt: skip

    old_hook_line = next(x for x in before.script if x.beat_id == "hook")
    new_hook_line = next(x for x in after.script if x.beat_id == "hook")
    assert new_hook_line.text.startswith("Your rent is quietly") and new_hook_line.id == "L5"
    assert old_hook_line.id not in {x.id for x in after.script}
    # Everything outside the hook is byte-for-byte what it was.
    assert [x for x in after.script if x.beat_id != "hook"] == [
        x for x in before.script if x.beat_id != "hook"
    ]

    def untouched(p: ShootPlan) -> list[dict[str, Any]]:
        return [s.model_dump(exclude={"takes", "record_s"}) for s in p.shots if s.beat_id != "hook"]

    assert untouched(after) == untouched(before)
    # The replacement sits where the hook was, is tagged with the right beat, and is re-derived.
    assert after.script[0].id == "L5" and after.shots[0].id == "S7"
    assert (after.shots[0].beat_id, after.shots[0].line_ids, after.shots[0].takes) == (
        "hook",
        ["L5"],
        3,
    )
    assert after.shoot_order[-3] == "S7" and after.warnings == []
    assert "more dramatic" in llm.prompt_text(0) and "Stop wasting money" in llm.prompt_text(0)


def test_regenerating_one_shot_keeps_its_id_and_lines(db: Session, llm: FakeAnthropic) -> None:
    llm.queues["PartDraft"] = [cassette("shoot_plan_regen_v1", "shot")]
    profile = make_profile()
    before = good_plan(profile)
    after = generate.regenerate_part(
        plan=before, profile=profile, brief=BRIEF, scope="shot", target_id="S5",
        instruction=None, session=db,
    )  # fmt: skip
    new = next(s for s in after.shots if s.id == "S5")
    assert (new.beat_id, new.line_ids, new.setup_id) == ("value", [], "street")
    assert new.description == "walking past apartment buildings"
    assert [s.id for s in after.shots] == [s.id for s in before.shots]
    assert after.script == before.script
    assert {s.id for s in after.setups} == {"desk", "table", "street"}


def test_regenerate_rejects_unknown_targets() -> None:
    profile = make_profile()
    plan = good_plan(profile)
    assert generate.resolve_target(plan, profile, "hook", None) == ("beat", "hook")
    assert generate.resolve_target(plan, profile, "beat", "value") == ("beat", "value")
    for scope, target in (("beat", "nope"), ("shot", "S99"), ("shot", None)):
        with pytest.raises(generate.PlanError) as excinfo:
            generate.resolve_target(plan, profile, scope, target)  # type: ignore[arg-type]
        assert excinfo.value.code == "PLAN_TARGET_NOT_FOUND"
    no_hook = profile.model_copy(update={"beats": profile.beats[1:]})
    with pytest.raises(generate.PlanError):
        generate.resolve_target(plan, no_hook, "hook", None)


def test_plan_draft_models_have_no_code_owned_fields() -> None:
    owned = {
        "est_duration_s",
        "record_s",
        "takes",
        "shoot_order",
        "word_budget",
        "target_duration_s",
        "warnings",
    }
    names = set(PlanDraft.model_fields) | set(PartDraft.model_fields)
    for model in (PlanDraft, PartDraft):
        for field in ("script", "shots"):
            inner = model.model_fields[field].annotation.__args__[0]  # type: ignore[union-attr]
            names |= set(inner.model_fields)
    assert not (names & owned)


# ---------------------------------------------------------------- pdf


def test_pdf_has_a_script_page_and_one_page_per_setup() -> None:
    plan = good_plan(make_profile())
    pdf = render_plan_pdf(
        "Renter <mistakes> & more", plan, {"hook": "Hook", "value": "Value", "cta": "CTA"}
    )
    assert pdf[:5] == b"%PDF-"
    assert len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf)) == 1 + len(plan.setups)

    empty = plan.model_copy(update={"script": [], "title_options": [], "checklist_notes": []})
    assert render_plan_pdf("Silent", empty, {})[:5] == b"%PDF-"


# ---------------------------------------------------------------- API


@pytest.fixture
def style(db: Session, user_id: UUID) -> StyleProfileRow:
    profile = make_profile()
    row = StyleProfileRow(
        id=profile.id, owner_id=user_id, name=profile.name, schema_version=1,
        data=profile.model_dump(mode="json"),
    )  # fmt: skip
    db.add(row)
    db.commit()
    return row


def _create(client: TestClient, style: StyleProfileRow, **brief: Any) -> dict[str, Any]:
    res = client.post(
        f"{API}/projects",
        json={
            "style_profile_id": str(style.id),
            "title": "Renter mistakes",
            "brief": {"topic": "3 mistakes first-time renters make", **brief},
        },
    )
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def test_project_crud(client: TestClient, style: StyleProfileRow) -> None:
    project = _create(client, style, key_points=["negotiate"])
    assert (project["status"], project["style_name"], project["has_plan"]) == (
        "planning",
        "Fast finance tip",
        False,
    )
    assert project["brief"]["constraints"]["gear"] == ["phone"]  # defaults filled in
    url = f"{API}/projects/{project['id']}"

    assert project["id"] in {p["id"] for p in client.get(f"{API}/projects").json()}
    patched = client.patch(
        url, json={"title": "  New title ", "brief": {"topic": "t", "target_duration_s": 30}}
    )
    assert (patched.json()["title"], patched.json()["brief"]["target_duration_s"]) == (
        "New title",
        30,
    )

    assert client.get(f"{url}/shoot-plan").json()["error"]["code"] == "PLAN_NOT_FOUND"
    assert client.post(f"{url}/share").status_code == 404  # nothing to share yet

    bad = client.post(
        f"{API}/projects",
        json={"style_profile_id": str(uuid4()), "title": "x", "brief": {"topic": "t"}},
    )
    assert bad.status_code == 404
    assert (
        client.post(
            f"{API}/projects",
            json={"style_profile_id": str(style.id), "title": "x", "brief": {"topic": ""}},
        ).status_code
        == 422
    )

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_plan_mode_end_to_end(
    client: TestClient, db: Session, style: StyleProfileRow, eager: None, llm: FakeAnthropic
) -> None:
    project = _create(client, style)
    url = f"{API}/projects/{project['id']}"

    accepted = client.post(f"{url}/shoot-plan")
    assert accepted.status_code == 202
    job = client.get(f"{API}/jobs/{accepted.json()['job_id']}").json()
    assert (job["status"], job["type"], job["output"]["version"]) == (
        "succeeded",
        "llm.generate_shoot_plan",
        1,
    )
    assert client.get(url).json()["has_plan"] is True
    assert client.get(url).json()["plan_job_id"] == accepted.json()["job_id"]

    out = client.get(f"{url}/shoot-plan").json()
    assert (out["version"], out["word_count"], out["title"]) == (1, 40, "Renter mistakes")
    assert out["style"] == {
        "name": "Fast finance tip", "wpm": 180, "max_shot_s": 2.0,
        "beats": [
            {"id": "hook", "function": "hook", "must_have": True},
            {"id": "value", "function": "value", "must_have": True},
            {"id": "cta", "function": "cta", "must_have": False},
        ],
    }  # fmt: skip
    plan = ShootPlan.model_validate(out["plan"])
    assert plan.warnings == [] and plan.shoot_order[0] == "S2"

    # Manual edits: a longer line breaks the budget and shows up as a warning, not an error.
    edited = client.patch(
        f"{url}/shoot-plan",
        json={
            "lines": [
                {"id": "L1", "text": "Stop   wasting money on rent, " + "seriously " * 12 + "stop."}
            ],
            "shots": [{"id": "S5", "priority": "must", "description": "bills fanned out"}],
            "shot_order": ["S1", "S3", "S2", "S4", "S5", "S6"],
        },
    ).json()
    assert edited["version"] == 1 and edited["word_count"] == 48
    assert [s["id"] for s in edited["plan"]["shots"]][:3] == ["S1", "S3", "S2"]
    assert (
        next(s for s in edited["plan"]["shots"] if s["id"] == "S5")["description"]
        == "bills fanned out"
    )
    assert any("Script is 48 words" in w for w in edited["plan"]["warnings"])
    assert "  " not in edited["plan"]["script"][0]["text"]

    for body, code in (
        ({"lines": [{"id": "L9", "text": "x"}]}, "PLAN_UNKNOWN_LINE"),
        ({"shots": [{"id": "S9", "priority": "must"}]}, "PLAN_UNKNOWN_SHOT"),
        ({"shot_order": ["S1", "S2"]}, "PLAN_BAD_ORDER"),
    ):
        assert client.patch(f"{url}/shoot-plan", json=body).json()["error"]["code"] == code

    # Regenerating the hook makes version 2 and keeps version 1.
    regen = client.post(
        f"{url}/shoot-plan/regenerate", json={"scope": "hook", "instruction": "bolder"}
    )
    assert regen.status_code == 202
    second = client.get(f"{url}/shoot-plan").json()
    assert second["version"] == 2
    assert second["plan"]["script"][0]["text"].startswith("Your rent is quietly")
    versions = db.execute(
        select(ShootPlanRow.version, ShootPlanRow.is_current)
        .where(ShootPlanRow.project_id == UUID(project["id"]))
        .order_by(ShootPlanRow.version)
    ).all()
    assert [tuple(v) for v in versions] == [(1, False), (2, True)]

    missing = client.post(
        f"{url}/shoot-plan/regenerate", json={"scope": "shot", "target_id": "S99"}
    )
    assert (missing.status_code, missing.json()["error"]["code"]) == (422, "PLAN_TARGET_NOT_FOUND")

    pdf = client.get(f"{url}/shoot-plan.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-" and "Renter mistakes" in pdf.headers["content-disposition"]


def test_share_link_is_public_read_only_and_revocable(
    client: TestClient, db: Session, style: StyleProfileRow, eager: None, llm: FakeAnthropic
) -> None:
    project = _create(client, style)
    url = f"{API}/projects/{project['id']}"
    client.post(f"{url}/shoot-plan")

    share = client.post(f"{url}/share").json()
    assert share["path"] == f"/share/{share['token']}" and len(share["token"]) >= 24
    assert client.post(f"{url}/share").json()["token"] == share["token"]  # stable

    public = client.get(f"{API}/share/{share['token']}")
    assert public.status_code == 200
    body = public.json()
    assert body["title"] == "Renter mistakes" and len(body["plan"]["shots"]) == 6
    assert "owner" not in json.dumps(body) and "brief" not in body
    assert client.get(f"{API}/share/{share['token']}/shoot-plan.pdf").content[:5] == b"%PDF-"

    for token in ("x", "a" * 32, share["token"][:-1] + "_"):
        assert client.get(f"{API}/share/{token}").status_code == 404
    assert client.patch(f"{API}/share/{share['token']}", json={}).status_code == 405

    assert client.delete(f"{url}/share").status_code == 204
    assert client.get(f"{API}/share/{share['token']}").status_code == 404


def test_plan_job_fails_clearly_without_a_key_or_a_style(
    client: TestClient, db: Session, style: StyleProfileRow, eager: None
) -> None:
    db.query(LlmCache).delete()
    db.commit()
    project = _create(client, style)
    url = f"{API}/projects/{project['id']}"

    accepted = client.post(f"{url}/shoot-plan").json()
    job = client.get(f"{API}/jobs/{accepted['job_id']}").json()
    assert (job["status"], job["error"]) == ("failed", "Style analysis needs an Anthropic API key.")
    assert client.get(url).json()["has_plan"] is False

    db.delete(db.get(StyleProfileRow, style.id))
    db.commit()
    gone = client.post(f"{url}/shoot-plan")
    assert (gone.status_code, gone.json()["error"]["code"]) == (409, "PROJECT_STYLE_MISSING")
    assert client.get(url).json()["style_name"] is None
    assert (
        db.scalar(
            select(func.count()).select_from(Project).where(Project.id == UUID(project["id"]))
        )
        == 1
    )
