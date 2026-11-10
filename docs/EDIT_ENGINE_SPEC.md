# Edit Engine Spec (v1)

Two halves:
- **Assembly** (`edit/`): footage + ShootPlan + StyleProfile → **Timeline**. Uses judgment (some LLM).
- **Renderer** (`render/`): Timeline → MP4. Pure and deterministic.

## Timeline schema

Times are in seconds on the **output** timeline unless they're named `src_*`.

```python
class Transform(BaseModel):
    crop: tuple[float,float,float,float] | None   # x,y,w,h normalized 0–1 on source (reframe)
    scale: float = 1.0                            # punch-in (applied after crop)
    scale_to: float | None = None                 # if set, ease from scale→scale_to over clip (slow push)
    anchor: tuple[float,float] = (0.5,0.4)        # zoom center, normalized (default: face-ish)
    flip_h: bool = False

class VideoClip(BaseModel):
    id: str
    asset_id: UUID
    src_in: float; src_out: float
    start: float                                  # output time
    transform: Transform = Transform()
    shot_id: str | None                           # ShootPlan link
    role: Literal["a_roll","b_roll","screen","text_card","other"]  # reaction/product/pov shots map to b_roll
    transition_in: Literal["cut","fade","whip","zoom","slide"] = "cut"
    transition_s: float = 0.0

class CaptionWord(BaseModel):
    text: str; start: float; end: float
    emphasis: bool = False
    emoji: str | None = None

class CaptionChunk(BaseModel):
    id: str
    words: list[CaptionWord]

class CaptionTrack(BaseModel):
    style: CaptionStyle                           # same model as StyleProfile.captions
    chunks: list[CaptionChunk]

class TimelineOverlay(BaseModel):   # distinct from StyleProfile.Overlay
    id: str
    kind: Literal["text","emoji","image","progress_bar"]
    start: float; end: float
    content: str                                  # text, emoji, or asset_id
    position: tuple[float,float]                  # normalized center
    style: dict[str, Any] = {}
    animation: Literal["none","pop","fade","slide_up"] = "pop"

class AudioClip(BaseModel):
    id: str
    asset_id: UUID
    src_in: float; src_out: float
    start: float
    gain_db: float = 0.0
    fade_in_s: float = 0.0; fade_out_s: float = 0.0

class AudioTracks(BaseModel):
    voice: list[AudioClip]                        # from the selected a_roll takes; continues under b-roll cutaways
    music: list[AudioClip]
    sfx: list[AudioClip]
    duck_music_db: float = -12                    # under voice
    target_lufs: float = -14

class Timeline(BaseModel):
    schema_version: Literal[1] = 1
    id: UUID; project_id: UUID; version: int; parent_id: UUID | None
    created_by: Literal["auto","user"]
    width: int = 1080; height: int = 1920; fps: int = 30
    duration: float
    video: list[VideoClip]                        # single primary track, no overlaps except during transitions
    captions: CaptionTrack | None
    overlays: list[TimelineOverlay]
    audio: AudioTracks
    color: dict[str, float]                       # ffmpeg eq params
    allow_gap: bool = False                       # hand-written/test timelines may leave black gaps
    warnings: list[str] = []                      # "Hook is 4.8s; reference is 2.6s"
```

**Invariant checks** (`edit/validate.py`, run after every pass and before render): clips sorted, no gaps (unless `allow_gap`), `src_out > src_in`, all asset ids exist, captions inside duration, duration equals the last clip's end.

## Transition vocabulary
One mapping, applied by the `map_to_plan` pass (profile → timeline) and `render/concat.py` (timeline → ffmpeg):

| `StyleProfile.rules.transitions` | `VideoClip.transition_in` | ffmpeg `xfade` transition |
|---|---|---|
| `hard_cut` | `cut` | none (concat) |
| `fade` | `fade` | `fade` |
| `whip` | `whip` | `slideleft` (short, 0.15–0.2s) |
| `zoom` | `zoom` | `zoomin` |
| — | `slide` | `slideleft` |
| `glitch` | `cut` + warning | none in v1 |

## TimelineOps (editor edits)
`PATCH /timelines/{id}` with a list of ops creates a new version:
`trim_clip{clip_id, src_in?, src_out?}`, `move_clip{clip_id, index}`, `delete_clip`, `swap_take{clip_id, asset_id, src_in, src_out}`, `set_transform{clip_id, …}`, `edit_caption{chunk_id, words}`, `restyle_captions{style}`, `add_overlay`, `remove_overlay`, `add_sfx`, `set_music{asset_id, gain_db}`.
Ops apply in `edit/ops.py`. Re-run `ripple` (re-time downstream clips, captions, and voice audio) and validation after applying.

## Assembly pipeline (`edit/pipeline.py`)

| # | Pass | Type | What it does |
|---|---|---|---|
| 1 | `coverage` | det + LLM(fast) | Map clips → shots (see PLAN_MODE_SPEC) |
| 2 | `select_takes` | det + LLM | Score takes: fluency (no restart words), filler count, audio RMS stability, face present, blur. LLM (`take_ranking`) breaks ties on delivery energy. Pick a winner per line. |
| 3 | `jump_cuts` | det | Inside each chosen take, cut silences > `max(pause_ms_p90, 250ms)` and filler words. Leave `pause_ms_p50` of air. Snap cut points to word boundaries ±30ms. |
| 4 | `map_to_plan` | det | Lay clips in ShootPlan edit order. a_roll carries voice; b_roll gets placed over a_roll lines it was planned for (J-cut: voice continues). |
| 5 | `reframe` | det | Face track → crop for 9:16 (keep face center at y≈0.38, x≈0.5). Source already 9:16 → crop `None`. |
| 6 | `pacing` | det | Any a_roll run > `max_shot_s` gets split with a punch-in (alternate scale 1.0 ↔ `punch_in_scale`) or a planned b-roll cutaway. Target the profile's `shot_len_s.median`. |
| 7 | `emphasis` | LLM | `emphasis_picker` chooses words for punch-ins, caption highlight, emoji, and SFX, constrained by `rules.punch_in_every_s` and `sfx_density`. |
| 8 | `beat_sync` | det | If music: shift cut points to the nearest beat within ±80ms when the shift doesn't land mid-word. Report the achieved `cut_on_beat_pct`. |
| 9 | `captions` | det | Chunk words per `words_per_chunk` (break on punctuation and pauses > 300ms; never split a number from its unit), apply case and emphasis. |
| 10 | `audio_plan` | det | Voice clips come from the selected a_roll takes, independent of what the video track shows (voice continues under b-roll). Music: pick a library track by BPM/mood closest to the profile, start on a downbeat, fade out the last 1s. SFX: whoosh on whip transitions, pop on emphasis punch-ins (per density). |
| 11 | `hook_check` | det | Warn if the first beat > 1.5× reference hook length or the first cut lands after 3s. |
| 12 | `loop_end` | det | If `rules.loop_ending`, trim the tail so the last word flows into the first frame (cut on an incomplete sentence if the script was written for it). |

Every pass appends to `timeline.warnings` instead of failing when it can't satisfy a rule.

## Renderer (`render/`)

Render as **segments → concat → finishing pass**. Easier to debug and cache than one giant `filter_complex`.

### 1. Segments (`segments.py`)
For each VideoClip, build one ffmpeg invocation:
```
-ss {src_in} -to {src_out} -i {proxy_or_original}
-vf "crop=…,scale=W*s:H*s,crop=W:H:x:y,eq=…,fps=30,format=yuv420p,setsar=1"
-an -c:v libx264 -preset veryfast -crf 18 (final) / -crf 26 (preview)
```
- `scale_to` (slow push-in): use `zoompan` with `z='lerp'` over the clip's frame count, or `scale` with a `t`-based expression. Pick one and snapshot-test it.
- Segment cache key: `sha256(clip json + asset content hash + preset + renderer_version)`.

### 2. Concat (`concat.py`)
- All cuts hard → concat demuxer (`-f concat -c copy`).
- Any transitions → `xfade` filter chain between the affected neighbors only (re-encode only those pairs).

### 3. Finishing (`finish.py`)
One pass:
- `subtitles=captions.ass:fontsdir=assets/fonts`
- overlays via `overlay` / `drawtext` with `enable='between(t,a,b)'`
- audio graph: voice `concat` → `asplit`; music `sidechaincompress` keyed by voice (threshold 0.05, ratio 8, release 250ms, makeup per `duck_music_db`); SFX `adelay` + `amix`; then `loudnorm=I=-14:TP=-1:LRA=11`
- Output: H.264 High, yuv420p, 30fps, AAC 192k, `+faststart`.

### Captions → ASS (`captions.py`)
- PlayResX=1080, PlayResY=1920. Style from `CaptionStyle` (font, size from preset table, outline=stroke_px, shadow, alignment from `position_y_pct` (0–1) → `MarginV = round((1 - position_y_pct) × 1920)` with bottom-center alignment).
- **Word highlight**: for each chunk, emit one Dialogue event per word span. All words in the chunk are drawn, and the active word gets `{\c&HBBGGRR&}` (color), `{\3c}` with box (box), or `{\fscx115\fscy115}` (scale).
- **Pop animation**: `{\t(0,80,\fscx110\fscy110)\t(80,160,\fscx100\fscy100)}` at chunk start.
- Emoji: render from a bundled emoji font (Noto Color Emoji; check libass support in your build, else pre-render PNGs and use overlays).

### Presets
| preset | res | crf | source |
|---|---|---|---|
| preview | 540×960 | 26 | proxies |
| final | 1080×1920 | 18 | originals |

## Tests
- `tests/render/test_golden.py`: three hand-written timelines over the fixtures (hard cuts only; punch-ins + captions; music ducking + SFX + xfade). Assert duration ±1 frame, resolution, perceptual hash of frames at listed timestamps (tolerance), and LUFS ±1.
- `tests/edit/test_passes.py`: each pass on small synthetic Timelines, checking invariants and expected cut points.
- Snapshot tests of generated ffmpeg arg lists.
