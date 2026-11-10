"""Ingest failures the user can act on. Every one offers the upload fallback."""

from typing import Literal

IngestErrorCode = Literal[
    "INGEST_DISABLED",
    "INGEST_UNSUPPORTED_URL",
    "INGEST_PRIVATE_VIDEO",
    "INGEST_LOGIN_REQUIRED",
    "INGEST_REMOVED",
    "INGEST_REGION_LOCKED",
    "INGEST_TOO_LONG",
    "INGEST_TOO_LARGE",
    "INGEST_NOT_A_VIDEO",
    "INGEST_FAILED",
]

UPLOAD_HINT = "Upload the file instead."

_MESSAGES: dict[str, tuple[str, str]] = {
    "INGEST_DISABLED": ("Importing from a link is turned off.", UPLOAD_HINT),
    "INGEST_UNSUPPORTED_URL": (
        "That link isn't a YouTube Shorts, Instagram Reels, or TikTok video.",
        "Paste a link to a single video, or upload the file instead.",
    ),
    "INGEST_PRIVATE_VIDEO": ("That video is private.", UPLOAD_HINT),
    "INGEST_LOGIN_REQUIRED": ("That video can only be viewed when signed in.", UPLOAD_HINT),
    "INGEST_REMOVED": ("That video has been removed or doesn't exist.", "Check the link."),
    "INGEST_REGION_LOCKED": ("That video isn't available from our servers' region.", UPLOAD_HINT),
    "INGEST_TOO_LONG": (
        "That video is longer than 3 minutes.",
        "StyleCut works with short-form clips. Trim it and upload the file.",
    ),
    "INGEST_TOO_LARGE": (
        "That video is larger than 200 MB.",
        "Export a smaller copy and upload it.",
    ),
    "INGEST_NOT_A_VIDEO": ("That file doesn't contain a video.", "Upload an MP4, MOV, or WebM."),
    "INGEST_FAILED": ("We couldn't download that video.", UPLOAD_HINT),
}


class IngestError(Exception):
    def __init__(self, code: IngestErrorCode, detail: str | None = None) -> None:
        self.code: IngestErrorCode = code
        self.message, self.hint = _MESSAGES[code]
        self.detail = detail  # for logs only, never shown to the user
        self.user_message = self.message  # picked up by JobTask for job.error
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "hint": self.hint}


# Checked in order: the first phrase found in a downloader error message wins.
_DOWNLOADER_PATTERNS: tuple[tuple[tuple[str, ...], IngestErrorCode], ...] = (
    (("private",), "INGEST_PRIVATE_VIDEO"),
    (("login required", "log in", "sign in", "cookies", "age-restricted"), "INGEST_LOGIN_REQUIRED"),
    (
        ("not available in your country", "geo", "your region", "your location"),
        "INGEST_REGION_LOCKED",
    ),
    (
        ("removed", "unavailable", "does not exist", "not found", "404", "deleted", "no longer"),
        "INGEST_REMOVED",
    ),
    (("larger than max-filesize", "file is larger"), "INGEST_TOO_LARGE"),
    (("unsupported url",), "INGEST_UNSUPPORTED_URL"),
)


def classify_downloader_error(message: str) -> IngestErrorCode:
    lowered = message.lower()
    for phrases, code in _DOWNLOADER_PATTERNS:
        if any(phrase in lowered for phrase in phrases):
            return code
    return "INGEST_FAILED"
