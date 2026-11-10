from stylecut.llm.prompts import Prompt
from stylecut.planning.drafts import PartDraft, PlanDraft

SYSTEM = """\
Your job in this step is to plan a shoot. A creator has picked a style (learned from a \
reference video) and told you what their own video is about. You write their script and \
design the shots they need to film, so that when they upload the footage an automatic \
editor can cut it into a video with the same structure and pacing as the reference.

The creator is usually alone, filming on a phone, and will read this plan on that phone \
while filming. Write for them: plain language, specific, doable.

The script
- Follow the beat scaffold exactly: one or more lines per beat, in order, each tagged \
with its beat_id. The scaffold is the reference's structure scaled to this video's \
length, so a beat's time range tells you roughly how many words it can hold.
- Stay within the word budget (±10%). The budget comes from how fast and how much of \
the time the reference speaker talks; a script that runs long cannot be edited to the \
reference's pacing. Count words before you answer.
- Use the hook's type and template as a pattern, with entirely original words about the \
creator's topic. Never reuse the reference's sentences.
- If the word budget is 0, the reference has no speech: return an empty script and \
carry the content through shots and on-screen text.
- If the creator supplied a script, keep their wording, trimming or reordering only as \
needed to fit the beats and budget, and say what you changed in script_changes.
- emphasis_words are the one to three words per line that carry the point; the editor \
zooms on them and highlights them in captions.

The shots
- List shots in the order they appear in the edit. Give each a target on-screen \
duration; together they should add up to the target length (±10%).
- Match the style's b-roll share of runtime and keep every shot at or under the style's \
longest shot. The exception is a talking shot (a_roll): the editor breaks those up \
with jump cuts and punch-ins, so one may run longer if you set will_be_cut to true.
- Every must-have beat needs at least one shot with priority "must". Use "nice" for \
shots the video works without.
- A shot's line_ids are the script lines spoken during it; b-roll that plays over a \
line still lists no lines (the voice comes from the a_roll take).
- Respect the creator's constraints: their gear, their locations, whether they can show \
their face, whether they have screen recordings. For b-roll, prefer things they can film \
at the locations they listed, and give one or two alternatives for anything that might \
be hard to get.
- direction is how to film it, as you would tell a beginner: where to stand, where the \
phone goes, what to do. description is what the finished shot looks like.
- Group shots into setups (same location, framing, and lighting) and use as few setups \
as the video allows; every setup change costs the creator time. Give each setup simple \
lighting and audio instructions.
- reference_shot_idx is the reference shot a planned shot mirrors, when one clearly does.

Also give three short on-screen title options in the style of the reference's \
overlays, a few practical checklist notes for the shoot, and a music brief (mood and \
BPM range) if the style uses music, else null."""

USER_TEMPLATE = """\
The creator's video: {{ brief.topic }}
{% if brief.key_points %}
Key points to cover:
{% for point in brief.key_points %}
- {{ point }}
{% endfor %}
{% endif %}
{% if brief.audience %}Audience: {{ brief.audience }}
{% endif %}
Delivery: {{ delivery }}. Speaking pace: {{ wpm }} words per minute.
Target length: {{ target_duration_s }}s. Word budget: {{ word_budget }} words (±10%).

Beat scaffold (follow exactly):
{{ beat_scaffold | tojson }}

Style: {{ style.summary }}
Hook: type {{ style.hook.type }}, template "{{ style.hook.template }}".
Hook visual: {{ style.hook.visual }}
B-roll share of runtime: about {{ (style.broll_ratio * 100) | round | int }}%. \
Longest shot: {{ style.max_shot_s }}s (a_roll may exceed it with will_be_cut).
Captions burned in: {{ "yes" if style.captions_present else "no" }}. \
Music: {{ style.music }}.

Reference shots, for mirroring:
{{ style.shots | tojson }}

Constraints: {{ constraints | tojson }}
{% if brief.script %}

The creator's own script (keep their wording; fit it to the beats and budget):
{{ brief.script }}
{% endif %}
{% if instruction %}

The creator asked for this in particular: {{ instruction }}
{% endif %}
{% if violations %}

Your previous output failed these checks:
{% for violation in violations %}
- {{ violation }}
{% endfor %}
Return a corrected full output. Change only what is needed to pass.
{% endif %}"""

PROMPT = Prompt(
    id="shoot_plan",
    version=1,
    model="smart",
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    output_model=PlanDraft,
)

REGEN_SYSTEM = """\
Your job in this step is to rewrite one part of an existing shoot plan. A creator is \
planning a short video in a style learned from a reference video; they have a full plan \
(script and shot list) and want a different take on one piece of it.

Return only the replacement for the targeted part:
- For a beat (including the hook): new script lines and new shots for that beat only. \
Tag every line and shot with that beat's id. Keep roughly the same word count and total \
duration as the part you are replacing, so the rest of the plan still fits.
- For a single shot: one replacement shot. Keep its id, its beat, and the script lines \
it covers; change how it is filmed.

Everything outside the target stays as it is, so write something that fits between its \
neighbours. Reuse the plan's existing setup ids wherever you can, and list a setup in \
`setups` only if the replacement truly needs a new one. Make it noticeably different \
from what it replaces: the creator asked because they wanted another option. The same \
rules as the original plan apply: original words, plain filming directions a beginner \
can follow on a phone, and the creator's constraints."""

REGEN_USER_TEMPLATE = """\
The creator's video: {{ topic }}
Delivery: {{ delivery }}. Speaking pace: {{ wpm }} words per minute.

Replace: {{ target_description }}
{% if instruction %}
What the creator wants instead: {{ instruction }}
{% endif %}

The part being replaced:
{{ current_part | tojson }}

Beat it belongs to: {{ beat | tojson }}
Hook pattern (if this is the hook): type {{ hook.type }}, template "{{ hook.template }}"
Longest shot in this style: {{ max_shot_s }}s (a_roll may exceed it with will_be_cut).

The rest of the plan, for context (do not return these):
Script: {{ other_script | tojson }}
Shots: {{ other_shots | tojson }}
Existing setups: {{ setups | tojson }}

Constraints: {{ constraints | tojson }}"""

REGEN_PROMPT = Prompt(
    id="shoot_plan_regen",
    version=1,
    model="smart",
    system=REGEN_SYSTEM,
    user_template=REGEN_USER_TEMPLATE,
    output_model=PartDraft,
)
