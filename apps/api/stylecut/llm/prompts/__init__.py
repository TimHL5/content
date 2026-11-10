"""Prompt registry (docs/PROMPTS.md).

One module per prompt, each exposing `PROMPT`. Bump `version` on ANY change to a
prompt's text or output model: it busts the cache and shows up in `llm_calls`.
"""

from dataclasses import dataclass
from typing import Any, Literal

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel

ModelTier = Literal["smart", "fast"]

PREAMBLE = """\
You are one component of StyleCut, a tool that helps creators make short-form vertical \
videos. StyleCut studies a reference video to learn how it is made (pacing, captions, \
framing, structure) so the creator can film and edit their own, original video the same \
way. The reference's footage, audio, and wording are never reused; only its style is.

Two things follow from that, and they apply to everything you write:

- Describe style, structure, and technique, not content. Descriptions and templates must \
make sense for a video about a completely different topic. Do not quote the reference's \
sentences; short fill-in-the-blank patterns with <placeholders> are fine.
- Values marked as measured were computed by code from the video itself and are ground \
truth. Use them as evidence. Do not re-estimate or contradict them.

Your output is consumed by code and by an automatic editor, so prefer concrete, \
checkable statements over impressions. When the evidence for a judgment is weak, pick \
the most conservative option and give that block a lower confidence (0 to 1) so the \
creator knows to double-check it."""

_env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
_env.policies["json.dumps_kwargs"] = {"sort_keys": True, "ensure_ascii": False}


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    model: ModelTier
    system: str
    user_template: str
    output_model: type[BaseModel]

    @property
    def full_system(self) -> str:
        return f"{PREAMBLE}\n\n{self.system}"

    def render(self, inputs: dict[str, Any]) -> str:
        return _env.from_string(self.user_template).render(**inputs).strip()
