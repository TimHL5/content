from stylecut.analysis.judgment import SynthesisOut
from stylecut.llm.prompts import Prompt

SYSTEM = """\
Your job in this step is to turn measurements of the reference video into the judgment \
parts of its style profile: how it hooks the viewer, how it is structured, and the \
editing habits an automatic editor should imitate.

You receive measured pacing, speech, audio, and color statistics, a shot table (measured \
timing and motion, plus shot types classified from frames in an earlier step), and a \
timestamped transcript. The transcript is evidence for structure and delivery only.

What to produce:

- beats: the narrative beats in order, covering the video from start to end without \
gaps. Start and end times should fall on shot boundaries from the shot table where the \
structure allows; code snaps them to the nearest cut afterwards. Give each beat a short \
id ("hook", "setup", "value_1", "payoff", "cta", ...), its function, and the technique \
it uses in words that would apply to any topic. Mark a beat must_have only if a video \
in this format would not work without it; a creator will be told to film every \
must-have beat.
- hook: the type of opening, a template of at most 15 words with <placeholders> that \
captures its pattern without reusing the original sentence, and what the hook looks \
like on screen.
- rules: what triggers zooms, whether silences are jump-cut out (very short measured \
pauses with many cuts suggest yes), which transitions appear, whether the ending loops \
back into the opening, and how text cards are used. The editor acts on these directly.
- audio_judgment: how dense sound effects are and which kinds, judged from onset peaks \
that speech and the beat grid do not explain; and the music's mood in a few words. \
Describe the mood only: never name or guess the track or artist. If measured \
music_present is false, music_mood is null.
- speech_judgment: delivery style and whether the voice is on camera, a voiceover, or \
mixed. If measured speech present is false, use delivery null and voice_type "none".
- color_look: a few words for the grade ("bright and punchy", "moody desaturated"), \
consistent with the measured color statistics.
- summary: two sentences a creator would recognize the format from.
- confidence: one value per block."""

USER_TEMPLATE = """\
Reference: {{ duration_s }}s, {{ aspect }}, from {{ platform }}.

Measured pacing:
{{ pacing | tojson }}

Measured speech statistics:
{{ speech | tojson }}

Measured audio:
{{ audio | tojson }}

Measured color:
{{ color | tojson }}

Shot table (timing, motion, and punch_in are measured; kind, framing, camera_motion, \
and description were classified from frames):
{{ shots | tojson }}

Captions and overlays seen in frames:
{{ visual | tojson }}

Transcript with timestamps (seconds):
{{ transcript if transcript else "(no speech detected)" }}"""

PROMPT = Prompt(
    id="style_synthesis",
    version=1,
    model="smart",
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    output_model=SynthesisOut,
)
