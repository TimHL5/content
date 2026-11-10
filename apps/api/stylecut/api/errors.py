"""Error envelope: `{"error": {"code", "message", "hint"}}` on every non-2xx response."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stylecut.schemas.errors import ErrorBody, ErrorEnvelope

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.hint = hint


def not_found(resource: str) -> ApiError:
    code = resource.upper().replace(" ", "_")
    return ApiError(404, f"{code}_NOT_FOUND", f"{resource.capitalize()} not found.")


def _envelope(status_code: int, code: str, message: str, hint: str | None = None) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorBody(code=code, message=message, hint=hint))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def install_unhandled_error_middleware(app: FastAPI) -> None:
    """Turn unexpected exceptions into a 500 envelope.

    Must be added *before* the CORS middleware (so CORS wraps it). Starlette's own
    500 handler runs outside CORS, which makes browsers report a CORS failure
    instead of the real error.
    """

    @app.middleware("http")
    async def _unhandled(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return _envelope(500, "INTERNAL_ERROR", "Something went wrong on our side.")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message, exc.hint)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()))
        message = f"{where}: {first.get('msg', 'invalid request')}" if where else "Invalid request."
        return _envelope(422, "VALIDATION_ERROR", message)
