from uuid import UUID

from scripts.export_schemas import build_schema
from stylecut.schemas import EXPORTED_MODELS
from stylecut.storage import keys

A = UUID("11111111-1111-1111-1111-111111111111")
P = UUID("22222222-2222-2222-2222-222222222222")


def test_exported_schema_contains_every_registered_model() -> None:
    schema = build_schema()
    for model in EXPORTED_MODELS:
        assert model.__name__ in schema["$defs"]
    assert schema["$defs"]["JobEvent"]["properties"]["status"]["enum"] == [
        "queued",
        "running",
        "succeeded",
        "failed",
    ]
    assert build_schema() == schema  # deterministic


def test_storage_keys_follow_the_documented_layout() -> None:
    assert keys.reference_raw(A, ".MP4") == f"references/raw/{A}.mp4"
    assert keys.reference_proxy(A) == f"references/proxy/{A}.mp4"
    assert keys.reference_derived(A, "scenes") == f"references/derived/{A}/scenes.json"
    assert keys.reference_sheet(A, 2) == f"references/derived/{A}/sheets/2.jpg"
    assert keys.footage_original(P, A, "mov") == f"footage/{P}/{A}/original.mov"
    assert keys.footage_file(P, A, "proxy.mp4") == f"footage/{P}/{A}/proxy.mp4"
    assert keys.library_asset(P, "music", A, "mp3") == f"library/{P}/music/{A}.mp3"
    assert keys.render_segment(P, "abc") == f"renders/{P}/segments/abc.mp4"
    assert keys.render_output(A, "preview") == f"renders/{A}/preview.mp4"
    # Only raw and proxy reference media expire; derived data is kept.
    assert keys.reference_raw(A, "mp4").startswith(keys.EXPIRING_PREFIXES)
    assert not keys.reference_sheet(A, 0).startswith(keys.EXPIRING_PREFIXES)
