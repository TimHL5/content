# Open Questions

Claude: append questions here when a spec is ambiguous. Format:
`- [ ] (phase N, date) Question — option chosen for now — why`

- [ ] (phase 2) Ship Demucs voice/music separation in v1 or keep it optional? — Optional, behind `ENABLE_DEMUCS` — adds ~20s GPU per clip.
- [ ] (phase 5) Starter royalty-free music/SFX pack: which source and license? — Placeholder: generated test tones until a licensed pack is chosen.
- [ ] (phase 7) Auth provider: Clerk vs Supabase Auth — decide before Phase 7.
- [ ] (phase 2/3, 2026-11-10) Reference with no speech (`speech.present=false`) gives a word budget of 0. What should Plan Mode produce for music-only styles? — Undecided; generate a shot list with an empty script and on-screen text only — keeps ShootPlan schema intact.
- [ ] (phase 4, 2026-11-10) MediaPipe has no dependable linux/arm64 wheel, and local dev is Docker on Apple Silicon. — Decide in Phase 4: run the worker as `linux/amd64` or fall back to OpenCV face detection.
- [ ] (phase 2, 2026-11-10) The "<90s on a GPU worker" target cannot be measured on the dev machine (no NVIDIA GPU). — Measure CPU time locally with `WHISPER_MODEL=small`; verify the GPU number on the first deployed worker.
- [ ] (phase 7, 2026-11-10) Separate DB role for the yt-dlp `io` worker (ARCHITECTURE.md Security). — Deferred to deploy; single role in local dev.
- [ ] (phase 0, 2026-11-10) Stack pins Next.js 15 while a newer major exists. — Stay on 15 as decided in CLAUDE.md.
- [ ] (phase 1, 2026-11-10) Phase 1 "Done when" names a TikTok URL; live ingest was verified with a YouTube URL only (no TikTok/Instagram link was available to test). — Paste one of each on the New style page to confirm; both platforms often need cookies or block datacenter IPs, which surfaces as `INGEST_LOGIN_REQUIRED`/`INGEST_FAILED` with the upload fallback.
- [ ] (phase 7, 2026-11-10) Browser uploads need bucket CORS that allows PUT from the web origin and exposes `ETag`. Local MinIO allows this by default. — Add an explicit CORS rule when choosing the production S3 provider.
- [ ] (phase 2, 2026-11-10) Pipelines run stages one after another. The analysis DAG needs a parallel stage (scenes, audio, speech, color). — Extend `start_pipeline` stages to groups in Phase 2.
- [ ] (phase 2, 2026-11-10) The LLM path has never run against the real API: no `ANTHROPIC_API_KEY` was available. The client is written to the documented `messages.parse` surface and tested with a fake client; `tests/llm_cassettes/` are hand-written, not recordings. — Add a key, run `make eval`, fix anything the real API rejects, and replace the cassettes with recorded outputs.
- [ ] (phase 2, 2026-11-10) Phase 2 "Done when" (8/10 eval clips judged accurate; <90s on a GPU worker) is unjudged: `eval/` holds one test clip and there is no GPU here. — Add ~10 reference clips and run `make eval`.
- [ ] (phase 2, 2026-11-10) Refusal fallbacks for the LLM calls are not enabled; a refusal fails the reference with `LLM_REFUSED`. — Decide whether to opt into server-side fallbacks once the real path is exercised.
- [ ] (phase 2, 2026-11-10) `music_present` uses one threshold tuned on three clips (click track, tone, speech). Speech over quiet music may be misread. — Tune on the eval set; Demucs would make this robust.
- [ ] (phase 2, 2026-11-10) Source aspect is the nearest of 9:16, 1:1, 4:5, 16:9, so a 4:3 reference reports 1:1. — Fine for short-form; add 4:3 only if references need it.
- [ ] (phase 2, 2026-11-10) Three libraries are pinned because newer builds crash (SIGILL) on linux/arm64 under Docker Desktop, which advertises SVE2 it cannot execute: `opencv<5`, `onnxruntime<1.23`, and `NUMBA_CPU_NAME=generic`. — Revisit on the production (x86/GPU) image; the pins are harmless there but may be unnecessary.
- [ ] (phase 3, 2026-11-10) Plan generation and regeneration have never run against the real API (no key). Tests replay hand-written drafts from `tests/llm_cassettes/`. — With a key: create a project, check the plan arrives in under 20s (the Phase 3 bar) and that the script fits the word budget without the repair pass.
- [ ] (phase 3, 2026-11-10) Checklist ticks live in the browser's local storage, per project and plan version. They are not shared between devices and reset when a new plan version is written. — Simplest thing that works on set; move to the server if creators plan on one device and film on another.
- [ ] (phase 3, 2026-11-10) The spec's Shots tab shows the matching reference contact-sheet tile ("like this"). Not built: sheets are stored whole, not per tile. — Store per-shot tiles in Phase 2's sheet builder if this proves useful.
- [ ] (phase 3, 2026-11-10) Share links never expire and expose the plan to anyone holding the link, until revoked. — Fine for single-user; add expiry with auth in Phase 7.
- [ ] (phase 3, 2026-11-10) Coverage Check (PLAN_MODE_SPEC) is scheduled with footage in Phase 5, not built here.
