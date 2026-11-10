# PLAN.md — StyleCut Build Plan

Each phase ends with something demoable. Each task is sized for about one Claude Code session.
Check boxes as tasks complete. **Current phase: 1**

---

## Phase 0 — Scaffolding
**Goal:** `make dev` boots every service. A health page shows API, DB, Redis, and S3 all green.

- [x] Monorepo layout per CLAUDE.md. Makefile with all targets (stubs OK).
- [x] docker-compose: postgres, redis, minio (+ bucket bootstrap), api, worker (all queues), web.
- [x] FastAPI app with `/health` checking DB, Redis, and S3. Settings via pydantic-settings.
- [x] SQLAlchemy + Alembic setup. First migration: `users`, `assets`, `jobs` (see DATA_MODEL.md).
- [x] Celery app with `io`/`cpu`/`gpu`/`llm` queues. Job base class that writes status/progress to `jobs` and publishes progress to Redis.
- [x] SSE endpoint `GET /jobs/{id}/events`.
- [x] Next.js app shell: sidebar (Styles, Projects), health page, TanStack Query, generated-types import path.
- [x] `make types` pipeline (pydantic → JSON Schema → `json-schema-to-typescript`).
- [x] `make fixtures`: generate synthetic clips with ffmpeg lavfi: `talking_head_10s.mp4` (testsrc2 + sine), `broll_5s.mp4`, `music_120bpm_20s.wav` (click track), `vertical_hardcuts_15s.mp4` (color-card cuts at known timestamps).
- [x] CI (GitHub Actions): lint, test, build web.

**Done when:** fresh clone → `make dev` → health page all green; CI passes.

---

## Phase 1 — Ingest
**Goal:** the user pastes a URL or uploads a file and gets a normalized, playable proxy with metadata.

- [x] Presigned multipart upload flow (`POST /uploads` → browser → S3 → `POST /uploads/{id}/complete`).
- [x] `IngestProvider` interface (`can_handle(url)`, `fetch(url) -> LocalFile + SourceMeta`). Implement `UploadProvider` and `YtDlpProvider` (YouTube Shorts, Instagram Reels, TikTok). Feature flag `ENABLE_URL_INGEST`.
- [x] URL normalization and platform detection. Friendly errors for private, removed, region-locked, or too-long (>3 min) videos.
- [x] `media.probe()` (ffprobe → duration, w/h, fps, rotation, audio streams).
- [ ] Proxy transcode: 540p H.264 (`-preset veryfast`), CFR 30fps, AAC 48k; plus a 16k mono WAV for speech.
- [ ] S3 lifecycle rule: `references/raw/*` expires in 24h.
- [ ] Web: "New Style" page with URL paste box and drag-and-drop, live job progress, proxy player.

**Done when:** a TikTok URL and an uploaded MP4 both produce a playable proxy within 30s for a 30s clip (target <15s, see ARCHITECTURE.md); failed URLs show a clear message and offer upload.

---

## Phase 2 — Style Analysis → StyleProfile
**Goal:** every reference produces a validated StyleProfile JSON and a readable "Style Card" UI.
Spec: `docs/STYLE_PROFILE_SPEC.md`

- [ ] Pydantic `StyleProfile` v1 + `make types`.
- [ ] `analysis/scene.py`: PySceneDetect (ContentDetector, AdaptiveDetector fallback) → cuts, shot durations, stats, and pacing curve (cuts per 5s window). Unit test against `vertical_hardcuts_15s.mp4` (±1 frame).
- [ ] `analysis/audio.py`: loudness (pyloudnorm), BPM and beat grid (librosa), onset peaks, cut-to-beat alignment %. Test with the click track.
- [ ] `analysis/speech.py`: faster-whisper with word timestamps → transcript, WPM, pause distribution, filler rate, speech coverage %.
- [ ] `analysis/visual.py`: pick 2 frames/shot (max 48) → build 3×4 contact sheets with burned-in timestamps and shot ids. Optical-flow motion score per shot. Punch-in detection (scale change between consecutive shots with the same subject).
- [ ] `analysis/color.py`: mean luma, contrast, saturation, warmth (LAB b*) → `color` block + approximate `eq` filter params.
- [ ] `analysis/vision_llm.py`: contact sheets → Claude vision (prompt `visual_breakdown`) → per-shot type, caption style, overlays, setting, b-roll flag.
- [ ] `analysis/synthesis.py`: merge all signals → `style_synthesis` prompt → StyleProfile (narrative beats, hook type, editing rules). Deterministic fields are copied from code output, never invented by the LLM.
- [ ] Celery DAG: `ingest → proxy → [scene, audio, speech, color] → visual → vision_llm → synthesis → cleanup` (see ARCHITECTURE.md) with fan-out where possible.
- [ ] Web: Style Card page with pacing curve chart, shot-length histogram, caption preview (rendered with our bundled fonts), hook/beat timeline, and editable fields (PATCH profile).
- [ ] `make eval`: run on `eval/*.mp4`, write profiles to `eval/out/`, print a summary table.

**Done when:** 8/10 eval clips produce profiles you judge as accurate on pacing, caption style, and hook type; analysis of a 30s clip finishes in <90s on a GPU worker.

---

## Phase 3 — Plan Mode
**Goal:** the user picks a style, describes their video, and gets a shoot-ready plan they can follow on their phone.
Spec: `docs/PLAN_MODE_SPEC.md`

- [ ] Pydantic `ProjectBrief`, `ShootPlan` v1 + types.
- [ ] Projects CRUD (`projects` table, brief form: topic, key points, optional script, target length, constraints).
- [ ] Word-budget calculator: `target_duration × profile.speech.wpm` minus non-speech beats.
- [ ] `planning/generate.py`: `shoot_plan` prompt → ShootPlan. Validate that beat timings sum to the target ±10% and that every must-have beat from the profile has ≥1 shot. Repair loop on failure.
- [ ] Shoot-order optimizer: group shots by `setup_id` (location+framing+lighting) so the creator changes setups as rarely as possible.
- [ ] Regenerate a single shot or beat ("give me another hook").
- [ ] Web (mobile-first): Script view, Shot List (edit order), Shoot Checklist (shoot order, tap to check off), and Teleprompter (scrolling at target WPM, mirrored option).
- [ ] Export the plan as PDF and a shareable read-only link.

**Done when:** from a profile and a one-line topic, the plan generates in <20s, the script fits the word budget, and the checklist works one-handed on a phone.

---

## Phase 4 — Edit Engine v1 (renderer first, no AI)
**Goal:** a hand-written Timeline JSON renders correctly. This is the foundation for everything after it.
Spec: `docs/EDIT_ENGINE_SPEC.md`

- [ ] Pydantic `Timeline` v1 + types.
- [ ] `render/segments.py`: each video clip → normalized intermediate (1080×1920 or 540×960 preview, 30fps, yuv420p) with trim, reframe crop, scale/punch-in, and eq.
- [ ] `render/concat.py`: concat demuxer for segments, with hard cuts and a small set of transitions (`xfade`: fade, slideleft, zoomin) when specified.
- [ ] `render/captions.py`: Timeline captions → ASS file. Word-highlight via one Dialogue event per active word. Bundled OFL fonts in `assets/fonts/`.
- [ ] `render/overlays.py`: text, emoji, and image overlays with enable windows.
- [ ] `render/audio.py`: voice track concat, music with sidechain ducking under voice, SFX at timestamps, loudnorm I=-14 LUFS TP=-1.
- [ ] `render/reframe.py`: MediaPipe face detection on sampled frames → smoothed crop window per segment (static crop per segment in v1).
- [ ] Golden tests: 3 hand-written timelines over fixtures → assert duration, resolution, caption frame hashes, and audio LUFS within ±1.
- [ ] `POST /timelines/{id}/render` with `preview` and `final` presets.

**Done when:** golden tests pass and a hand-written timeline renders a 30s preview in <20s and a final in <60s on the dev machine.

---

## Phase 5 — Auto-Assembly
**Goal:** upload raw footage → get a styled first cut automatically.

- [ ] Footage upload into a project. Per clip: proxy, transcript with word timings, face track, quality metrics (audio level, blur score, filler count).
- [ ] Coverage Check: map clips to shot ids (transcript-to-script alignment plus `coverage_classify` vision prompt for b-roll). UI shows ✅ covered / ⚠️ weak / ❌ missing, plus a "reshoot list".
- [ ] Take selection: for each script line, rank takes (fluency, fillers, energy, delivery via `take_ranking` prompt); pick the best.
- [ ] Jump-cut pass: remove silences > profile threshold and filler words; keep breaths to `profile.speech.pause_ms_p50`.
- [ ] Pacing pass: enforce `profile.pacing` shot-length distribution by inserting b-roll or punch-ins where an A-roll stretch exceeds `max_shot_s`.
- [ ] Emphasis pass: `emphasis_picker` prompt chooses words for punch-ins, caption color, and SFX according to profile rules.
- [ ] Beat-sync pass (if music): snap cuts to the nearest beat within ±80ms without cutting mid-word.
- [ ] Caption build from word timings using profile chunking rules.
- [ ] Music and SFX: user library plus a starter royalty-free pack; pick by BPM/energy closest to the profile.
- [ ] Hook check: the first 3s must contain the hook beat; warn if not.
- [ ] `POST /projects/{id}/assemble` → Timeline v1 (`created_by=auto`) → auto preview render.

**Done when:** from the Phase 3 plan plus self-shot footage, auto-assembly yields a cut you'd post with ≤5 manual tweaks.

---

## Phase 6 — Editor
**Goal:** fast manual tweaks without leaving the app.

- [ ] Timeline UI: clip strip with thumbnails, trim handles, reorder, delete, swap take.
- [ ] Caption editor: edit text and timing inline, restyle (preset or custom), toggle word highlight.
- [ ] Zoom/SFX/overlay toggles per segment.
- [ ] Edits are expressed as `TimelineOp`s (PATCH with ops) → new Timeline version (`parent_id`). Undo/redo via version history.
- [ ] Incremental preview: re-render only changed segments (segment cache keyed by hash).
- [ ] "Apply a different style" to the same footage → re-assemble.

**Done when:** a typical tweak (caption fix + one trim) shows an updated preview in <8s.

---

## Phase 7 — Ship
- [ ] Auth (Clerk or Supabase Auth); replace `DEV_USER_ID`. Row-level ownership checks on every query.
- [ ] Usage limits and cost tracking per user (LLM tokens, GPU minutes, storage).
- [ ] Export presets (TikTok, Reels, Shorts: same 9:16 with platform-safe caption zones), plus SRT export.
- [ ] Style library: save, rename, duplicate; blend 2–3 references into one profile.
- [ ] Observability: Sentry, structured logs, job dashboards (Flower).
- [ ] Deploy: web on Vercel; API and workers on a container host with a GPU worker pool; managed Postgres, Redis, and S3.
- [ ] Billing (Stripe) if launching publicly.

---

## Later / ideas
- Real-time browser preview (WebCodecs or Remotion player) instead of server preview renders.
- Dynamic reframe (per-frame crop path) and subject cutout.
- AI b-roll suggestions from stock libraries (Pexels API).
- Trend radar: track which styles are rising.
- Voiceover mode (script → TTS → b-roll-only edit).

---

## Decisions log
<!-- Claude: append one line per non-obvious decision: date — decision — why -->
- 2026-11-10 — Project root is the repo root; `skills/` is gitignored — matches CLAUDE.md paths; skills are unrelated to StyleCut.
- 2026-11-10 — Segment cache keyed by project (`renders/{project_id}/segments/`), not timeline — each edit creates a new timeline id, so a per-timeline cache would never hit.
- 2026-11-10 — Table `reference_videos` instead of `references` — reserved word in Postgres.
- 2026-11-10 — All `*_pct`/`*_ratio` fields are 0–1 fractions, including `position_y_pct` — the spec mixed 0–1 and 0–100.
- 2026-11-10 — Added `Timeline.allow_gap`, a single transition mapping table (`glitch` → cut + warning in v1), removed unused `Confidence` model — the specs referenced things that did not exist or disagreed.
- 2026-11-10 — Job idempotency key generalized to `(subject_id, step, step_version)`, nullable — plan/assemble/render jobs have no asset.
- 2026-11-10 — Added `projects.share_token`, `GET /share/{token}`, `GET /health`, `GET /assets/{id}`, list endpoints for references/projects, `DELETE /projects/{id}` — needed by UI flows already in PLAN.md.
- 2026-11-10 — Voice track is built from selected a_roll takes, not mirrored from the video track — required for J-cuts under b-roll.
- 2026-11-10 — Host needs only Docker; `make` targets run in containers. Python deps via uv (`apps/api/uv.lock`), JS via pnpm workspaces — the dev machine has no Python 3.12/ffmpeg, and this keeps local and CI identical.
- 2026-11-10 — MinIO image is `cgr.dev/chainguard/minio:latest`; bucket bootstrap is `scripts/bootstrap_storage.py` (compose service `storage-init`) — `minio/minio` and `minio/mc` are no longer on Docker Hub. Chainguard's free tier only offers `latest`, so the tag is unpinned.
- 2026-11-10 — Sync SQLAlchemy (psycopg 3) in API and workers; async Redis only inside the SSE endpoint — one DB access style everywhere; Celery is sync anyway.
- 2026-11-10 — A task's queue is the prefix of its name (`io.`/`cpu.`/`gpu.`/`llm.`); unprefixed tasks go to `cpu` — routing can't drift from naming.
- 2026-11-10 — Jobs are started only through `jobs.base.enqueue()` (row first, then send); `JobTask` passes the job's `input` as kwargs and sets `typing = False` so Celery doesn't reject the `job_id` kwarg.
- 2026-11-10 — SSE stream re-reads the job row if no event arrives for 10s — ends the stream when a worker dies without publishing.
- 2026-11-10 — `ENABLE_DEV_ROUTES` + `POST /api/v1/dev/demo-job` (`cpu.demo_sleep`) and a "Run test job" button on the System page — lets Phase 0 demo queue → worker → progress → SSE before any real job exists. Off by default.
- 2026-11-10 — Health is served at `/api/v1/health` and unversioned `/health` (container healthchecks). Failed checks report only the exception class name — messages can contain hosts or credentials.
- 2026-11-10 — Status/kind columns are `varchar` + CHECK constraints, not Postgres enums — adding a value is a one-line migration.
- 2026-11-10 — Tests use real Postgres/Redis/MinIO: database `stylecut_test` (recreated per run) and Redis db 15 — no mocks to drift, dev data untouched. A test asserts the hand-written migration matches the models.
- 2026-11-10 — `make types` emits one `schemas.json` and one `generated/index.ts` from the models listed in `stylecut/schemas/__init__.py::EXPORTED_MODELS`; both are committed and CI fails if they are stale.
- 2026-11-10 — Fixture clips are 540×960 (proxy size) and gitignored; `stylecut/media/fixtures.py` exports the known cut times and BPM for Phase 2 tests.
- 2026-11-10 — Dev migrations run automatically when the `api` container starts — required for "fresh clone → make dev → green".
- 2026-11-10 — shadcn/ui components (`card`, `badge`, `button`) are written in the shadcn conventions with `components.json` in place, so `shadcn add` works for later components.
- 2026-11-10 — New libraries. API: fastapi, uvicorn, pydantic-settings, sqlalchemy, alembic, psycopg, celery, redis, boto3, sse-starlette; dev: pytest, httpx, ruff, mypy. Web: next 15, react 19, @tanstack/react-query, tailwindcss 4, class-variance-authority, clsx, tailwind-merge, lucide-react, vitest, json-schema-to-typescript — all named in or implied by the stack in CLAUDE.md except sse-starlette (SSE responses with keep-alive pings) and boto3 (S3 client).
