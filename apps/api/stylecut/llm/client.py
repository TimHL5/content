"""The only place that calls the LLM.

`call_structured` renders a prompt from the registry, asks for output constrained to the
prompt's Pydantic model (structured outputs via `messages.parse`), validates it, retries
once with the validation errors, caches by content hash, and logs every call (including
cache hits) to `llm_calls`.

Note: the models in use reject forced tool choice, so structured outputs replace the
"single forced tool" approach the original spec described. The guarantee is the same:
the response always matches the schema.
"""

import base64
import hashlib
import json
import logging
import time
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from stylecut.db.models import LlmCache, LlmCall
from stylecut.llm.prompts import Prompt
from stylecut.settings import get_settings

logger = logging.getLogger(__name__)

MAX_TOKENS = 16000

# USD per million tokens (input, output). Used for cost tracking only.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}


class LlmError(Exception):
    """A failure the user can understand. `code` is stable; `user_message` is shown."""

    def __init__(self, code: str, user_message: str, hint: str | None = None) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.hint = hint

    def as_dict(self) -> dict[str, str | None]:
        return {"code": self.code, "message": self.user_message, "hint": self.hint}


def not_configured() -> LlmError:
    return LlmError(
        "LLM_NOT_CONFIGURED",
        "Style analysis needs an Anthropic API key.",
        "Set ANTHROPIC_API_KEY in .env and restart the workers.",
    )


def get_client() -> Any:
    """Tests replace this function to supply recorded responses."""
    key = get_settings().anthropic_api_key
    if key is None or not key.get_secret_value():
        raise not_configured()
    import anthropic

    return anthropic.Anthropic(api_key=key.get_secret_value())


def resolve_model(prompt: Prompt) -> str:
    settings = get_settings()
    return settings.llm_model_smart if prompt.model == "smart" else settings.llm_model_fast


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


def cache_key(prompt: Prompt, model: str, user_text: str, images: Sequence[bytes]) -> str:
    digest = hashlib.sha256()
    for part in (prompt.id, str(prompt.version), model, prompt.full_system, user_text):
        digest.update(part.encode())
        digest.update(b"\x00")
    for image in images:
        digest.update(hashlib.sha256(image).digest())
    return digest.hexdigest()


def _log(
    session: Session, prompt: Prompt, model: str, job_id: UUID | None, *,
    input_tokens: int = 0, output_tokens: int = 0, latency_ms: int = 0, cache_hit: bool = False,
) -> None:  # fmt: skip
    session.add(
        LlmCall(
            job_id=job_id,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=0.0 if cache_hit else cost_usd(model, input_tokens, output_tokens),
            cache_hit=cache_hit,
        )
    )
    session.commit()
    logger.info(
        "llm call prompt=%s v%d model=%s in=%d out=%d ms=%d cache_hit=%s",
        prompt.id, prompt.version, model, input_tokens, output_tokens, latency_ms, cache_hit,
    )  # fmt: skip


def _request(client: Any, prompt: Prompt, model: str, user_text: str, images: Sequence[bytes]):  # type: ignore[no-untyped-def]
    import anthropic

    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(image).decode("ascii"),
            },
        }
        for image in images
    ]
    content.append({"type": "text", "text": user_text})
    try:
        return client.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=prompt.full_system,
            messages=[{"role": "user", "content": content}],
            output_format=prompt.output_model,
        )
    except anthropic.AuthenticationError:
        raise LlmError(
            "LLM_AUTH_FAILED",
            "The Anthropic API key was rejected.",
            "Check ANTHROPIC_API_KEY in .env.",
        ) from None
    except anthropic.RateLimitError:
        raise LlmError(
            "LLM_RATE_LIMITED", "The AI service is busy right now.", "Try again in a minute."
        ) from None
    except anthropic.APIStatusError as exc:
        raise LlmError(
            "LLM_REQUEST_FAILED",
            f"The AI service returned an error ({exc.status_code}).",
            "Try again. If it keeps happening, check the model names in .env.",
        ) from None
    except anthropic.APIConnectionError:
        raise LlmError(
            "LLM_UNREACHABLE", "Couldn't reach the AI service.", "Check the network and try again."
        ) from None


def call_structured[T: BaseModel](
    prompt: Prompt,
    inputs: dict[str, Any],
    output_model: type[T],
    *,
    session: Session,
    images: Sequence[bytes] = (),
    job_id: UUID | None = None,
) -> T:
    if output_model is not prompt.output_model:
        raise TypeError(f"{prompt.id} produces {prompt.output_model.__name__}")
    model = resolve_model(prompt)
    user_text = prompt.render(inputs)
    key = cache_key(prompt, model, user_text, images)

    cached = session.scalar(select(LlmCache.output).where(LlmCache.key == key))
    if cached is not None:
        _log(session, prompt, model, job_id, cache_hit=True)
        return output_model.model_validate(cached)

    client = get_client()
    text = user_text
    last_error: str | None = None
    for attempt in (1, 2):
        started = time.perf_counter()
        parsed: BaseModel | None = None
        try:
            response = _request(client, prompt, model, text, images)
            parsed = response.parsed_output
        except ValidationError as exc:
            # Client-side validation of the returned JSON failed inside the SDK.
            last_error = str(exc)
            response = None
        latency_ms = round((time.perf_counter() - started) * 1000)

        if response is not None:
            usage = response.usage
            _log(
                session, prompt, model, job_id,
                input_tokens=int(usage.input_tokens), output_tokens=int(usage.output_tokens),
                latency_ms=latency_ms,
            )  # fmt: skip
            if response.stop_reason == "refusal":
                raise LlmError(
                    "LLM_REFUSED",
                    "The AI model declined to analyze this video.",
                    "Try a different reference video.",
                )
            if response.stop_reason == "max_tokens":
                raise LlmError(
                    "LLM_OUTPUT_TRUNCATED",
                    "The analysis was cut off before it finished.",
                    "Try again.",
                )
            if parsed is not None:
                try:
                    result = output_model.model_validate(parsed.model_dump())
                except ValidationError as exc:
                    last_error = str(exc)
                else:
                    session.add(LlmCache(key=key, output=json.loads(result.model_dump_json())))
                    session.commit()
                    return result
            elif last_error is None:
                last_error = "the response contained no structured output"

        if attempt == 1:
            text = (
                f"{user_text}\n\nYour previous output failed these checks:\n{last_error}\n"
                "Return a corrected full output. Change only what is needed to pass."
            )
    raise LlmError(
        "LLM_INVALID_OUTPUT", "The analysis came back in an unexpected shape.", "Try again."
    )
