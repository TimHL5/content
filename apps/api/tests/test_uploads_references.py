import json
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from scripts.bootstrap_storage import lifecycle_rules
from stylecut.db.models import Asset, Job, ReferenceVideo
from stylecut.ingest.base import LocalFile, SourceMeta
from stylecut.ingest.errors import IngestError
from stylecut.jobs import ingest as ingest_jobs
from stylecut.jobs.events import channel
from stylecut.media.probe import probe
from stylecut.redis_client import get_redis
from stylecut.settings import get_settings
from stylecut.storage import keys, s3

API = "/api/v1"


def _put(url: str, data: bytes) -> str:
    """What the browser does: PUT one part to its presigned URL, read the ETag."""
    request = urllib.request.Request(url, data=data, method="PUT")
    with urllib.request.urlopen(request, timeout=30) as response:
        etag: str = response.headers["ETag"]
        return etag


def _upload(client: TestClient, path: Path, kind: str = "reference") -> dict[str, Any]:
    data = path.read_bytes()
    created = client.post(
        f"{API}/uploads",
        json={"filename": path.name, "size": len(data), "content_type": "video/mp4", "kind": kind},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    size = body["part_size"]
    parts = [
        {"part_number": p["part_number"], "etag": _put(p["url"], data[i * size : (i + 1) * size])}
        for i, p in enumerate(body["parts"])
    ]
    done = client.post(
        f"{API}/uploads/{body['asset_id']}/complete",
        json={"upload_id": body["upload_id"], "parts": parts},
    )
    assert done.status_code == 200, done.text
    return {**body, "asset": done.json()["asset"], "completed_parts": parts}


# ---------------------------------------------------------------- uploads


def test_multipart_upload_roundtrip(
    client: TestClient, clips: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1 MB source, 5 MB parts would be one part; force several to exercise multipart.
    # S3 requires every part but the last to be >= 5 MB, so build a 11 MB file.
    big = clips / "big.mp4"
    big.write_bytes((clips / "talking_head_10s.mp4").read_bytes() + b"\0" * (11 * 1024 * 1024))
    monkeypatch.setattr(get_settings(), "upload_part_bytes", 5 * 1024 * 1024)

    result = _upload(client, big)
    assert len(result["parts"]) == 3
    asset = result["asset"]
    assert (asset["kind"], asset["status"], asset["has_proxy"]) == ("reference", "ready", False)
    expires = datetime.fromisoformat(asset["expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(UTC) <= timedelta(hours=24)

    fetched = client.get(f"{API}/assets/{asset['id']}").json()
    assert fetched["proxy_url"] is None
    with urllib.request.urlopen(fetched["url"], timeout=30) as response:
        assert response.read() == big.read_bytes()

    # Completing twice is harmless (the browser may retry).
    again = client.post(
        f"{API}/uploads/{asset['id']}/complete",
        json={"upload_id": result["upload_id"], "parts": result["completed_parts"]},
    )
    assert again.status_code == 200 and again.json()["asset"]["status"] == "ready"


def test_upload_validation(client: TestClient) -> None:
    def create(**overrides: Any) -> Any:
        body = {
            "filename": "clip.mp4",
            "size": 1000,
            "content_type": "video/mp4",
            "kind": "reference",
        }
        return client.post(f"{API}/uploads", json={**body, **overrides})

    bad_type = create(filename="notes.exe")
    assert bad_type.status_code == 422
    assert bad_type.json()["error"]["code"] == "UPLOAD_UNSUPPORTED_TYPE"
    assert "MP4" in bad_type.json()["error"]["hint"]

    assert create(filename="song.mp3").json()["error"]["code"] == "UPLOAD_UNSUPPORTED_TYPE"
    assert create(filename="song.mp3", kind="music").status_code == 201

    too_big = create(size=get_settings().max_reference_bytes + 1)
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "UPLOAD_TOO_LARGE"

    assert create(size=0).status_code == 422
    assert create(kind="footage").status_code == 422  # footage uploads arrive in Phase 5


def test_complete_rejects_missing_parts_and_wrong_upload(client: TestClient) -> None:
    created = client.post(
        f"{API}/uploads",
        json={
            "filename": "clip.mp4",
            "size": 1000,
            "content_type": "video/mp4",
            "kind": "reference",
        },
    ).json()
    url = f"{API}/uploads/{created['asset_id']}/complete"

    wrong = client.post(url, json={"upload_id": "nope", "parts": [{"part_number": 1, "etag": "x"}]})
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (409, "UPLOAD_NOT_PENDING")

    missing = client.post(
        url,
        json={"upload_id": created["upload_id"], "parts": [{"part_number": 1, "etag": '"abc"'}]},
    )
    assert (missing.status_code, missing.json()["error"]["code"]) == (422, "UPLOAD_INCOMPLETE")

    unknown = client.post(
        f"{API}/uploads/{uuid4()}/complete",
        json={"upload_id": "x", "parts": [{"part_number": 1, "etag": "x"}]},
    )
    assert unknown.status_code == 404


def test_complete_rejects_a_truncated_upload(client: TestClient) -> None:
    created = client.post(
        f"{API}/uploads",
        json={
            "filename": "clip.mp4",
            "size": 1000,
            "content_type": "video/mp4",
            "kind": "reference",
        },
    ).json()
    etag = _put(created["parts"][0]["url"], b"x" * 400)  # declared 1000 bytes
    res = client.post(
        f"{API}/uploads/{created['asset_id']}/complete",
        json={"upload_id": created["upload_id"], "parts": [{"part_number": 1, "etag": etag}]},
    )
    assert (res.status_code, res.json()["error"]["code"]) == (422, "UPLOAD_SIZE_MISMATCH")
    assert client.get(f"{API}/assets/{created['asset_id']}").json()["asset"]["status"] == "failed"


def test_expired_asset_reports_expired_and_has_no_urls(
    client: TestClient, db: Session, user_id: UUID
) -> None:
    asset = Asset(
        owner_id=user_id,
        kind="reference",
        status="ready",
        s3_key="references/raw/gone.mp4",
        proxy_key="references/proxy/gone.mp4",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(asset)
    db.commit()
    body = client.get(f"{API}/assets/{asset.id}").json()
    assert (body["asset"]["status"], body["asset"]["has_proxy"]) == ("expired", False)
    assert body["url"] is None and body["proxy_url"] is None


# ---------------------------------------------------------------- storage lifecycle


def test_reference_media_expires_after_24h() -> None:
    applied = s3.get_s3_client().get_bucket_lifecycle_configuration(
        Bucket=get_settings().s3_bucket
    )["Rules"]
    expiring = {
        rule["Filter"]["Prefix"]: rule["Expiration"]["Days"]
        for rule in applied
        if "Expiration" in rule
    }
    assert expiring == {"references/raw/": 1, "references/proxy/": 1}
    assert len(applied) == len(lifecycle_rules())

    asset_id = uuid4()
    for key in (
        keys.reference_raw(asset_id, "mp4"),
        keys.reference_proxy(asset_id),
        keys.reference_speech(asset_id),
    ):
        assert key.startswith(tuple(expiring)), key
    # Derived data is kept.
    assert not keys.reference_derived(asset_id, "scenes").startswith(tuple(expiring))


# ---------------------------------------------------------------- references


def _follow(db: Session, accepted: dict[str, Any]) -> tuple[Job, ReferenceVideo, Asset]:
    db.expire_all()
    job = db.get(Job, UUID(accepted["job_id"]))
    reference = db.get(ReferenceVideo, UUID(accepted["resource_id"]))
    assert job is not None and reference is not None
    asset = db.get(Asset, reference.asset_id)
    assert asset is not None
    return job, reference, asset


def test_uploaded_reference_becomes_a_playable_proxy(
    client: TestClient, db: Session, clips: Path, eager: None
) -> None:
    uploaded = _upload(client, clips / "talking_head_10s.mp4")

    pubsub = get_redis().pubsub()
    pubsub.psubscribe("job:*")
    pubsub.get_message(timeout=1)
    res = client.post(f"{API}/references", json={"asset_id": uploaded["asset_id"]})
    assert res.status_code == 202, res.text
    job, reference, asset = _follow(db, res.json())

    assert (job.type, job.status, job.progress) == ("reference.ingest", "succeeded", 1.0)
    assert (reference.status, reference.platform, reference.error) == ("ingested", "upload", None)
    assert (asset.width, asset.height, asset.fps, asset.has_audio) == (540, 960, 30.0, True)
    assert asset.duration_s == pytest.approx(10.0, abs=0.1)
    assert asset.content_hash is not None and len(asset.content_hash) == 64
    assert asset.proxy_key == keys.reference_proxy(asset.id)

    # The parent job's events: one stream, progress never goes backwards, human step names.
    events = []
    while (message := pubsub.get_message(timeout=0.2)) is not None:
        if message["type"] == "pmessage" and message["channel"] == channel(job.id):
            events.append(json.loads(message["data"]))
    pubsub.close()
    progress = [e["progress"] for e in events]
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert events[-1]["status"] == "succeeded"
    steps = {e["step"] for e in events}
    assert {
        "Downloading",
        "Checking the video",
        "Making a preview copy",
        "Extracting audio",
    } <= steps
    assert [e["status"] for e in events].count("succeeded") == 1

    # The proxy is real, playable media at the documented spec.
    urls = client.get(f"{API}/assets/{asset.id}").json()
    assert urls["asset"]["has_proxy"] is True
    proxy = clips / "downloaded_proxy.mp4"
    urllib.request.urlretrieve(urls["proxy_url"], proxy)
    info = probe(proxy)
    assert (info.width, info.height, info.fps, info.video_codec) == (540, 960, 30.0, "h264")
    assert info.audio_streams[0].sample_rate == 48000
    assert s3.object_size(keys.reference_speech(asset.id)) > 0

    out = client.get(f"{API}/references/{reference.id}").json()
    assert (out["status"], out["job_id"], out["asset_id"]) == (
        "ingested",
        str(job.id),
        str(asset.id),
    )
    assert str(reference.id) in {r["id"] for r in client.get(f"{API}/references").json()}


class FakeProvider:
    name = "fake"

    def __init__(self, clip: Path | None = None, error: IngestError | None = None) -> None:
        self.clip, self.error = clip, error

    def can_handle(self, source: str) -> bool:
        return True

    def fetch(
        self, source: str, dest_dir: Path, on_progress: Any = None
    ) -> tuple[LocalFile, SourceMeta]:
        if self.error is not None:
            raise self.error
        assert self.clip is not None
        dest = dest_dir / "source.mp4"
        dest.write_bytes(self.clip.read_bytes())
        for fraction in (0.01, 0.011, 0.5, 1.0):
            on_progress(fraction)
        return LocalFile(dest, dest.stat().st_size), SourceMeta("tiktok", source)


def test_url_reference_is_downloaded_stored_and_proxied(
    client: TestClient, db: Session, clips: Path, eager: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fake_get_provider(source: str) -> FakeProvider:
        seen.append(source)
        return FakeProvider(clips / "broll_5s.mp4")

    monkeypatch.setattr(ingest_jobs, "get_provider", fake_get_provider)
    res = client.post(
        f"{API}/references",
        json={"url": "https://www.tiktok.com/@creator/video/7300000000000000000?lang=en"},
    )
    assert res.status_code == 202, res.text
    job, reference, asset = _follow(db, res.json())

    assert seen == ["https://www.tiktok.com/@creator/video/7300000000000000000"]
    assert (job.status, reference.status, reference.platform) == ("succeeded", "ingested", "tiktok")
    assert asset.s3_key == keys.reference_raw(asset.id, "mp4")
    assert (asset.status, asset.has_audio) == ("ready", False)
    assert s3.object_size(asset.s3_key) == (clips / "broll_5s.mp4").stat().st_size
    assert s3.object_size(keys.reference_proxy(asset.id)) > 0
    # No audio in the source: no speech file is produced.
    with pytest.raises(s3.ObjectNotFound):
        s3.object_size(keys.reference_speech(asset.id))
    assert asset.expires_at is not None


def test_failed_url_gives_a_clear_message_and_offers_upload(
    client: TestClient, db: Session, eager: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ingest_jobs,
        "get_provider",
        lambda _: FakeProvider(error=IngestError("INGEST_PRIVATE_VIDEO", detail="raw yt-dlp text")),
    )
    res = client.post(f"{API}/references", json={"url": "https://www.instagram.com/reel/Cabc123/"})
    job, reference, _ = _follow(db, res.json())

    assert (job.status, job.error) == ("failed", "That video is private.")
    assert reference.status == "failed"
    assert reference.error == {
        "code": "INGEST_PRIVATE_VIDEO",
        "message": "That video is private.",
        "hint": "Upload the file instead.",
    }
    out = client.get(f"{API}/references/{reference.id}").json()
    assert out["error"]["hint"] == "Upload the file instead."
    assert "raw yt-dlp text" not in json.dumps(out)


def test_too_long_and_non_video_uploads_fail_with_specific_codes(
    client: TestClient, db: Session, clips: Path, eager: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_reference_duration_s", 8.0)
    uploaded = _upload(client, clips / "talking_head_10s.mp4")
    res = client.post(f"{API}/references", json={"asset_id": uploaded["asset_id"]})
    _, reference, asset = _follow(db, res.json())
    assert reference.error is not None and reference.error["code"] == "INGEST_TOO_LONG"
    assert asset.proxy_key is None

    junk = clips / "junk.mp4"
    junk.write_bytes(b"this is not a video" * 100)
    uploaded = _upload(client, junk)
    res = client.post(f"{API}/references", json={"asset_id": uploaded["asset_id"]})
    _, reference, _ = _follow(db, res.json())
    assert reference.error is not None and reference.error["code"] == "INGEST_NOT_A_VIDEO"


def test_reference_request_validation(
    client: TestClient, db: Session, user_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    def post(body: dict[str, Any]) -> Any:
        return client.post(f"{API}/references", json=body)

    assert post({}).status_code == 422
    assert (
        post({"url": "https://www.youtube.com/shorts/a", "asset_id": str(uuid4())}).status_code
        == 422
    )

    bad = post({"url": "https://example.com/video.mp4"})
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "INGEST_UNSUPPORTED_URL")
    assert "upload" in bad.json()["error"]["hint"].lower()

    assert post({"asset_id": str(uuid4())}).status_code == 404

    pending = Asset(owner_id=user_id, kind="reference", status="uploading", s3_key="k")
    music = Asset(owner_id=user_id, kind="music", status="ready", s3_key="k2")
    db.add_all([pending, music])
    db.commit()
    assert post({"asset_id": str(pending.id)}).json()["error"]["code"] == "ASSET_NOT_READY"
    assert post({"asset_id": str(music.id)}).json()["error"]["code"] == "ASSET_WRONG_KIND"

    monkeypatch.setattr(get_settings(), "enable_url_ingest", False)
    off = post({"url": "https://www.youtube.com/shorts/abc"})
    assert (off.status_code, off.json()["error"]["code"]) == (403, "INGEST_DISABLED")
    assert off.json()["error"]["hint"] == "Upload the file instead."

    assert client.get(f"{API}/references/{uuid4()}").status_code == 404
