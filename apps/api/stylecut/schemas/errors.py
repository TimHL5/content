from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str | None = None


class ErrorEnvelope(BaseModel):
    """Shape of every non-2xx API response (docs/API.md)."""

    error: ErrorBody
