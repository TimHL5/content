from stylecut.analysis.judgment import VisualBreakdown
from stylecut.llm.prompts import Prompt

SYSTEM = """\
Your job in this step is to look at frames from the reference video and describe what \
the camera and the on-screen graphics are doing.

You will see contact sheets: grids of frames sampled from the video. Every tile has a \
label in its top-left corner, "#<shot index> t=<seconds>", telling you which shot it \
belongs to and when it occurs. Most shots have two tiles (early and late in the shot); \
comparing them shows whether the camera or the subject moved.

For each shot in the measured shot table, classify:
- kind: a_roll is a person speaking to camera; b_roll is illustrative footage without \
the speaker addressing the lens; screen is a screen recording or app demo; text_card is \
mostly text on a plain or blurred background; reaction, product, and pov as named. Use \
"other" when a shot does not fit or you cannot see it.
- framing: from extreme close-up (ecu) to wide shot (ws), or overhead, pov, screen.
- camera_motion: use the measured motion_score as evidence alongside the tiles. Below \
about 0.5 the frame is essentially static; above about 2.5 there is strong movement. \
A measured punch_in of true means this shot is the previous shot's framing zoomed in, \
which is an editing choice, not a camera move.
- description: at most 12 words, about what kind of shot it is, not what it is about \
("person at desk speaking to camera", not the topic they discuss).

Shots with no tile on the sheets were not sampled; give them kind "other", your best \
guess for the rest, and let that lower the shots confidence.

Then describe the burned-in captions (subtitle-style text that tracks speech), if any. \
Choose the nearest preset and font from the lists you are given; these are the only \
ones our renderer has, so an approximate match from the list is more useful than an \
exact name that is not on it. Report colors as #RRGGBB. position_y_pct is the vertical \
center of the caption block as a fraction of frame height (0 = top, 1 = bottom). If the \
video has no captions, set present to false and fill the remaining caption fields with \
the first preset's typical values.

Finally, list recurring on-screen overlays that are not captions (titles, labels, \
arrows, stickers, progress bars) with approximate time ranges, and note the setting in \
a sentence."""

USER_TEMPLATE = """\
Contact sheets of a {{ duration_s }}s {{ aspect }} video are attached \
({{ sheet_count }} sheet{{ "s" if sheet_count != 1 else "" }}, {{ frame_count }} frames).

Measured shot table:
{{ shots | tojson }}

Caption presets available: {{ caption_presets | tojson }}
Fonts available: {{ fonts | tojson }}

Return one entry in `shots` for every idx in the shot table."""

PROMPT = Prompt(
    id="visual_breakdown",
    version=1,
    model="smart",
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    output_model=VisualBreakdown,
)
