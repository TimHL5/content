# PRD — StyleCut

## Problem
Creators see a video format blow up and want to make their own version. Today that means rewatching it frame by frame to reverse-engineer the pacing, captions, zooms, and hook. Then they shoot without a plan, miss half the shots they need, and spend 2–4 hours editing a 30-second clip.

## Solution
1. **Copy the style**: paste a link, get the video's style as an editable profile.
2. **Plan the shoot**: get a script and a shot list that fit that style, in the order you should film it.
3. **Auto-edit**: upload footage, get a styled first cut, tweak, export.

## Target users
- **Solo creators / personal brands** (primary): phone-shot talking-head content plus b-roll; post 3–7×/week.
- **Small-business marketers**: need on-trend content without an editor.
- **Agencies / editors** (later): batch production for multiple clients with saved style libraries.

## Core user flows

### Flow A: Create a style
1. Paste URL (or upload) → progress shows "Downloading → Detecting cuts → Listening → Reading captions → Building style".
2. **Style Card**: hook type, pacing ("fast: 1.4s avg shot, speeds up after 10s"), caption look preview, zoom frequency, b-roll %, music energy, narrative beats on a timeline.
3. User edits anything ("make captions yellow", "slower pacing") and saves to their library.

### Flow B: Plan Mode
1. New project → pick a style → enter topic + key points (or paste a script) → target length.
2. Get a **Shoot Plan**:
   - Script split into beats (Hook / Setup / Value / Payoff / CTA) mapped to the reference's structure.
   - Shot list: each shot's purpose, line, framing, camera move, setting, lighting, number of takes, must-have vs nice-to-have.
   - **Shoot Checklist** in shoot order (grouped by setup) with a teleprompter.
3. Regenerate any beat or shot. Export PDF / share link.

### Flow C: Auto-edit
1. Upload all raw clips (any order, multiple takes).
2. **Coverage Check**: covered / weak / missing per shot → optional reshoot list.
3. Auto-assemble → preview in under 2 minutes.
4. Editor: fix captions, trims, swap takes, toggle zooms/SFX → re-render → export 1080×1920.

## MVP scope (Phases 0–5)
In: URL + upload ingest; StyleProfile; Plan Mode with checklist and teleprompter; auto-assembly with jump cuts, captions, punch-ins, b-roll insertion, music ducking, beat sync, and 9:16 reframe; preview and final render.
Out (until later): real-time browser preview, multi-user teams, direct posting to platforms, AI-generated b-roll, voice cloning.

## Non-goals
- Re-uploading or remixing other people's footage or audio. We copy **style**, never **content**.
- Long-form editing (>3 min).
- Being a full NLE. The editor stays limited to the tweaks people actually make.

## Success metrics
- **Time to first cut**: < 5 min from footage upload (p50).
- **Tweak count**: ≤ 5 manual edits before export (p50).
- **Style fidelity**: in blind tests, users match our output to its reference ≥ 70% of the time.
- **Plan follow-through**: ≥ 80% of must-have shots covered on first upload.
- **Cost**: < $0.40 compute per finished 30s clip (LLM + GPU).

## Key risks
| Risk | Mitigation |
|---|---|
| Platform downloads break / ToS | `IngestProvider` abstraction, upload fallback always works, reference media deleted after analysis |
| LLM hallucinating measurable facts | Deterministic extraction; LLM only fills judgment fields |
| Slow renders | Proxies, segment cache, GPU worker pool, preview presets |
| "Copied" output looks generic | Eval set + style-fidelity tests each phase |
| Music licensing | User uploads + royalty-free library only |
