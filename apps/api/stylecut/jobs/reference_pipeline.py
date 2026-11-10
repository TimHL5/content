"""The reference pipeline: one parent job from "here is a video" to "here is its style".

ingest_reference (io)
  -> make_proxy (cpu)
    -> [detect_scenes (cpu), analyze_audio (cpu), transcribe (gpu), analyze_color (cpu)]
      -> build_contact_sheets (cpu)
        -> vision_breakdown (llm)
          -> synthesize_profile (llm)
            -> cleanup_reference_media (io)
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from stylecut.db.models import Job, ReferenceVideo
from stylecut.jobs import analysis, ingest
from stylecut.jobs.base import Stage, idempotency_key, start_pipeline

PIPELINE_TYPE = "reference.analyze"
PIPELINE_STEP = "reference_analyze"
PIPELINE_VERSION = 1


def pipeline_key(reference_id: UUID) -> str:
    return idempotency_key(reference_id, PIPELINE_STEP, PIPELINE_VERSION)


def reference_stages() -> Sequence[Stage | Sequence[Stage]]:
    """(task, weight) per stage; weights are rough shares of wall-clock time."""
    return [
        (ingest.ingest_reference, 0.15),
        (ingest.make_proxy, 0.13),
        [
            (analysis.detect_scenes, 0.08),
            (analysis.analyze_audio, 0.08),
            (analysis.transcribe, 0.20),
            (analysis.analyze_color, 0.04),
        ],
        (analysis.build_contact_sheets, 0.08),
        (analysis.vision_breakdown, 0.11),
        (analysis.synthesize_profile, 0.11),
        (analysis.cleanup_reference_media, 0.02),
    ]


def start_reference_pipeline(session: Session, reference: ReferenceVideo) -> Job:
    return start_pipeline(
        session,
        type=PIPELINE_TYPE,
        owner_id=reference.owner_id,
        stages=reference_stages(),
        args={"reference_id": str(reference.id), "asset_id": str(reference.asset_id)},
        key=pipeline_key(reference.id),
    )
