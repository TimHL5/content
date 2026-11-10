# StyleProfile Spec (v1)

The StyleProfile is the app's core asset: a reference video's "style DNA" in a form the planner and editor can act on.
Each field is tagged **[D]** (deterministic: computed by code, LLM must not change it) or **[J]** (judgment: produced by the LLM from evidence).

**Units:** every `*_pct` and `*_ratio` field is a fraction in 0–1 (`Field(ge=0, le=1)`), never 0–100. Times are seconds unless the name ends in `_ms`.

## Schema (Pydantic, abbreviated)

```python
class Stats(BaseModel):
    mean: float; median: float; p10: float; p90: float; min: float; max: float

class SourceInfo(BaseModel):
    platform: Literal["tiktok","instagram","youtube","upload"]
    url: str | None
    duration_s: float                       # [D]
    aspect: Literal["9:16","1:1","4:5","16:9"]  # [D]
    fps: float                              # [D]

class Pacing(BaseModel):                    # all [D]
    shot_count: int
    shot_len_s: Stats                       # mean, median, p10, p90, min, max
    cuts_per_5s: list[float]                # pacing curve
    acceleration: Literal["steady","speeds_up","slows_down","bursty"]  # [D] from slope of curve
    max_shot_s: float                       # rule used by pacing pass (= p90, clamped 1.5–6s)
    cut_on_beat_pct: float | None           # fraction (0–1) of cuts within ±80ms of a beat

class Shot(BaseModel):
    idx: int
    start_s: float; end_s: float            # [D]
    kind: Literal["a_roll","b_roll","screen","text_card","reaction","product","pov","other"]  # [J]
    framing: Literal["ecu","cu","mcu","ms","ws","overhead","pov","screen"]                   # [J]
    camera_motion: Literal["static","handheld","push_in","pull_out","pan","whip","tracking"] # [J], informed by flow score [D]
    punch_in: bool                          # [D] detected scale jump vs previous shot
    motion_score: float                     # [D]
    description: str                        # [J] short, content-agnostic ("person at desk speaking to camera")
    beat_id: str | None                     # [D] the beat whose time range contains the shot's midpoint

class CaptionStyle(BaseModel):              # [J] from vision, mapped to our presets
    present: bool
    preset: str                             # nearest bundled preset id, e.g. "bold_pop", "clean_subtle", "boxed"
    font_family: str                        # closest bundled OFL font, e.g. "Montserrat ExtraBold"
    case: Literal["upper","lower","sentence","title"]
    words_per_chunk: tuple[int,int]         # e.g. (1,3)
    lines: Literal[1,2]
    position_y_pct: float                   # 0=top, 1=bottom (center of caption block)
    fill: str; stroke: str | None; stroke_px: int; shadow: bool
    highlight: Literal["none","color","box","scale"]
    highlight_color: str | None
    emoji: Literal["none","sparse","frequent"]
    animation: Literal["none","pop","fade","typewriter","bounce"]

class Overlay(BaseModel):                   # [J]
    kind: Literal["title","label","arrow","emoji","progress_bar","sticker","other"]
    start_s: float; end_s: float
    position: Literal["top","center","bottom","follow"]
    text_example: str | None                # paraphrased pattern, e.g. "<number> things …"

class Speech(BaseModel):                    # [D]
    present: bool
    coverage_pct: float                     # fraction (0–1) of runtime with speech
    wpm: float
    pause_ms_p50: float; pause_ms_p90: float
    filler_rate: float                      # fillers per 100 words
    delivery: Literal["energetic","conversational","calm","deadpan","whisper"] | None  # [J]
    voice_type: Literal["on_camera","voiceover","mixed","none"]                        # [J]

class Audio(BaseModel):                     # [D] unless noted
    integrated_lufs: float
    music_present: bool
    bpm: float | None
    energy_curve: list[float]               # RMS per second, normalized
    drops_s: list[float]                    # large onset peaks
    sfx_density: Literal["none","low","medium","high"]   # [J] from onset peaks not explained by speech/beats
    sfx_types: list[Literal["whoosh","pop","ding","riser","bass_hit","click","record_scratch"]]  # [J]
    music_mood: str | None                  # [J] "upbeat lo-fi", "dramatic cinematic" — NEVER the track name

class Color(BaseModel):                     # [D]
    luma_mean: float; contrast: float; saturation: float; warmth: float
    eq: dict[str, float]                    # ffmpeg eq params: brightness, contrast, saturation, gamma
    look: str                               # [J] "bright and punchy", "moody desaturated"

class Beat(BaseModel):                      # [J]
    id: str                                 # "hook", "setup", "value_1", "twist", "payoff", "cta", "loop"
    function: Literal["hook","context","tension","value","proof","twist","payoff","cta","loop"]
    start_s: float; end_s: float
    technique: str                          # "bold claim + visual pattern-interrupt"
    must_have: bool

class Hook(BaseModel):                      # [J]
    type: Literal["bold_claim","question","pov","list_tease","result_first","controversy","visual_shock","story_open","challenge"]
    duration_s: float                       # [D] length of the hook beat
    template: str                           # content-agnostic: "Stop doing <common thing> if you want <outcome>"
    visual: str                             # "extreme close-up, text overlay filling top third"

class EditingRules(BaseModel):              # [J] unless tagged [D]; [D] fields are computed by code from the classified shots and never output by the LLM
    punch_in_every_s: float | None          # [D] duration / number of detected punch-ins
    punch_in_scale: float                   # [D] median detected scale, default 1.15
    zoom_on: list[Literal["emphasis_word","new_point","joke","number"]]
    broll_ratio: float                      # [D] share of runtime that is b_roll/screen/product
    jump_cut_silences: bool
    transitions: list[Literal["hard_cut","whip","zoom","fade","glitch"]]
    loop_ending: bool                       # ending flows back into the start
    text_card_usage: Literal["none","intro","sections","frequent"]

class StyleProfile(BaseModel):
    schema_version: Literal[1] = 1
    id: UUID; name: str
    source: SourceInfo
    summary: str                            # [J] 2 sentences, human-readable
    pacing: Pacing
    shots: list[Shot]
    captions: CaptionStyle
    overlays: list[Overlay]
    speech: Speech
    audio: Audio
    color: Color
    hook: Hook
    beats: list[Beat]
    rules: EditingRules
    confidence: dict[str, float]            # 0–1 per [J] block: {"captions":0.9,"beats":0.7,…}
    user_overrides: dict[str, Any] = {}     # JSON-pointer → value; applied on read
```

## Extraction methods

| Field | Method |
|---|---|
| cuts / shots | PySceneDetect `ContentDetector(threshold=27)`; if <2 cuts in >10s, retry `AdaptiveDetector`. Merge cuts <0.15s apart. |
| pacing curve | Count cuts per 5s window. `acceleration` = sign of linear-fit slope (±0.15 threshold) or "bursty" if CV > 0.6. |
| punch_in | ORB feature match between last frame of shot N and first frame of shot N+1. Estimated scale 1.05–1.6 with matching inliers counts as a punch-in. |
| motion_score | Mean Farneback optical-flow magnitude on 4 sampled frame pairs per shot. |
| BPM / beats | `librosa.beat.beat_track` on the full mix (hop 256 at 22.05 kHz); BPM is 60 / median inter-beat interval. Demucs stem separation is still optional and not yet wired in. |
| music_present | Pulse clarity: normalized autocorrelation of the onset envelope at one beat period, ≥ 0.25, and only when the audio has real onsets (peak onset strength ≥ 1.0; a steady tone has none and would otherwise score on codec noise). Measured clarity: click track 0.97, speech-only clip 0.01. When false, `bpm`, `cut_on_beat_pct`, and `music_mood` are null. |
| cut_on_beat_pct | Fraction of cuts within ±80ms of a beat. |
| LUFS | pyloudnorm on the full mix. |
| speech | faster-whisper `word_timestamps=True`, VAD on. Speech time = word durations plus gaps ≤ 0.7s; WPM is computed over speech time only and `coverage_pct` = speech time / duration. `like`/`so` count as fillers only when set off by a comma or pause. Fillers: {um, uh, like (as filler), you know, so, basically}. |
| color | Sample 1 frame/sec → LAB means. `eq` derived by mapping deltas from a neutral baseline (document constants in `analysis/color.py`). |
| captions, shot kind, overlays | Contact sheets → `visual_breakdown` prompt. Fonts are mapped to the nearest bundled preset; we never claim an exact font. |
| hook, beats, rules, summary | `style_synthesis` prompt over all deterministic JSON + transcript + vision output. |

## Contact sheets
- 2 frames per shot (25% and 75% of shot duration), max 48 frames.
- Up to 3×4 tiles per sheet (the sheet is sized to the tiles it holds), each tile 360px tall, with a label `#shot_idx t=12.4s` burned in.
- More than 24 shots: one frame per shot (50%). More than 48: an even sample of 48 shots; unsampled shots get kind `other`.
- Send all sheets in one vision call when possible (≤ 4 sheets).

## Example (truncated)

```json
{
  "schema_version": 1,
  "name": "Fast-talk finance tip",
  "source": {"platform":"tiktok","duration_s":34.2,"aspect":"9:16","fps":30},
  "summary": "Rapid-fire talking head with punch-ins every ~2s and bold yellow word-highlight captions. Opens with a bold claim, delivers three numbered tips, ends with a loop back to the hook.",
  "pacing": {"shot_count":19,"shot_len_s":{"mean":1.8,"median":1.6,"p10":0.8,"p90":3.1,"min":0.5,"max":4.0},
             "cuts_per_5s":[4,3,3,2,3,3,4],"acceleration":"steady","max_shot_s":3.1,"cut_on_beat_pct":0.42},
  "captions": {"present":true,"preset":"bold_pop","font_family":"Montserrat ExtraBold","case":"upper",
               "words_per_chunk":[1,3],"lines":1,"position_y_pct":0.62,"fill":"#FFFFFF","stroke":"#000000",
               "stroke_px":6,"shadow":true,"highlight":"color","highlight_color":"#FFE600","emoji":"sparse","animation":"pop"},
  "speech": {"present":true,"coverage_pct":0.93,"wpm":192,"pause_ms_p50":120,"pause_ms_p90":260,"filler_rate":0.4,
             "delivery":"energetic","voice_type":"on_camera"},
  "hook": {"type":"bold_claim","duration_s":2.6,"template":"You're losing money every month if you still <common habit>.",
           "visual":"ECU, slight push-in, caption centered"},
  "beats": [
    {"id":"hook","function":"hook","start_s":0,"end_s":2.6,"technique":"bold claim + ECU","must_have":true},
    {"id":"value_1","function":"value","start_s":2.6,"end_s":11.0,"technique":"numbered tip + b-roll proof","must_have":true},
    {"id":"cta","function":"cta","start_s":30.1,"end_s":34.2,"technique":"follow ask that loops into hook","must_have":false}
  ],
  "rules": {"punch_in_every_s":2.1,"punch_in_scale":1.18,"zoom_on":["emphasis_word","new_point"],"broll_ratio":0.22,
            "jump_cut_silences":true,"transitions":["hard_cut","whip"],"loop_ending":true,"text_card_usage":"sections"}
}
```

## Blending (Phase 7)
Average numeric [D] fields weighted by user-chosen weights; take [J] categorical fields from the highest-weight reference; re-run `style_synthesis` in "blend" mode for beats, hook, and rules.
