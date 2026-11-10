"""Deterministic S3 key builders (docs/ARCHITECTURE.md, "Storage layout").

A re-run of any job writes to the same key, so it overwrites cleanly.
"""

from typing import Literal
from uuid import UUID

DerivedArtifact = Literal["scenes", "audio", "transcript", "color"]
RenderPreset = Literal["preview", "final"]

# Everything under these prefixes expires after 24h (S3 lifecycle rule, Phase 1).
EXPIRING_PREFIXES = ("references/raw/", "references/proxy/")


def _ext(ext: str) -> str:
    return ext.lower().lstrip(".")


def reference_raw(asset_id: UUID, ext: str) -> str:
    return f"references/raw/{asset_id}.{_ext(ext)}"


def reference_proxy(asset_id: UUID) -> str:
    return f"references/proxy/{asset_id}.mp4"


def reference_derived(asset_id: UUID, artifact: DerivedArtifact) -> str:
    return f"references/derived/{asset_id}/{artifact}.json"


def reference_sheet(asset_id: UUID, n: int) -> str:
    return f"references/derived/{asset_id}/sheets/{n}.jpg"


def footage_original(project_id: UUID, asset_id: UUID, ext: str) -> str:
    return f"footage/{project_id}/{asset_id}/original.{_ext(ext)}"


def footage_file(
    project_id: UUID,
    asset_id: UUID,
    name: Literal["proxy.mp4", "speech.wav", "transcript.json", "faces.json"],
) -> str:
    return f"footage/{project_id}/{asset_id}/{name}"


def library_asset(user_id: UUID, kind: Literal["music", "sfx"], asset_id: UUID, ext: str) -> str:
    return f"library/{user_id}/{kind}/{asset_id}.{_ext(ext)}"


def render_segment(project_id: UUID, segment_hash: str) -> str:
    """Segment cache, shared by every timeline version of a project."""
    return f"renders/{project_id}/segments/{segment_hash}.mp4"


def render_output(timeline_id: UUID, preset: RenderPreset) -> str:
    return f"renders/{timeline_id}/{preset}.mp4"
