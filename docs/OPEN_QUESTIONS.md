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
