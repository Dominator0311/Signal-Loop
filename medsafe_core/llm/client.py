"""
Gemini LLM client wrapper.

Provides structured generation using Pydantic models as output schemas.
Handles API errors and response validation.

Uses the google-genai SDK with structured output (response_json_schema).

IMPORTANT: The Gemini SDK's generate_content() is SYNCHRONOUS. In our async
FastAPI context, we MUST wrap calls with asyncio.to_thread() to avoid blocking
the event loop. This is critical for a server handling concurrent requests.
"""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar, Type

from google import genai
from pydantic import BaseModel

from medsafe_core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

# Retryable error patterns (lowercase, matched against str(exception)).
# 503/UNAVAILABLE = Google model overloaded, transient.
# 429/RESOURCE_EXHAUSTED = rate-limit hit, usually transient.
# 504/DEADLINE_EXCEEDED = upstream timeout, transient.
# Connection/timeout errors = network transient.
_RETRYABLE_PATTERNS = (
    "503",
    "unavailable",
    "429",
    "resource_exhausted",
    "504",
    "deadline_exceeded",
    "timeout",
    "connection",
)
_RETRY_BACKOFF_SECONDS = (1.0, 3.0, 7.0)  # delays before attempts 2, 3, 4


async def _call_with_retry(call_fn: Callable[[], Awaitable[R]], *, max_attempts: int = 3) -> R:
    """
    Retry an async Gemini call on transient errors with exponential backoff.

    Retryable: 503, 429, 504, connection/timeout errors.
    Non-retryable: 400 (bad request), 401/403 (auth), etc. — fail fast.
    """
    last_exception: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await call_fn()
        except Exception as e:
            last_exception = e
            err_lower = str(e).lower()
            is_retryable = any(p in err_lower for p in _RETRYABLE_PATTERNS)
            if not is_retryable or attempt == max_attempts - 1:
                raise
            delay = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning(
                f"Gemini call failed (attempt {attempt + 1}/{max_attempts}): {e}. "
                f"Retrying in {delay}s..."
            )
            await asyncio.sleep(delay)
    # Defensive — the loop should always return or raise above.
    assert last_exception is not None
    raise last_exception


class GeminiClient:
    """Wrapper around the Google Gemini API for structured generation."""

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY not set — LLM calls will fail")
            self._client = None
        else:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def generate_structured(
        self,
        prompt: str,
        output_model: Type[T],
        system_instruction: str | None = None,
    ) -> T:
        """
        Generate structured output conforming to a Pydantic model.

        Args:
            prompt: The user/task prompt
            output_model: Pydantic model class defining the output schema
            system_instruction: Optional system-level instruction

        Returns:
            Validated instance of output_model

        Raises:
            ValueError: If LLM client is not configured
            RuntimeError: If generation or parsing fails
        """
        if self._client is None:
            raise ValueError(
                "Gemini client not initialized. Set GEMINI_API_KEY environment variable."
            )

        config = {
            "response_mime_type": "application/json",
            "response_json_schema": output_model.model_json_schema(),
        }

        if system_instruction:
            config["system_instruction"] = system_instruction

        async def _invoke():
            # Wrap synchronous SDK call to avoid blocking the async event loop
            return await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=prompt,
                config=config,
            )

        try:
            response = await _call_with_retry(_invoke)

            if not response.text:
                raise RuntimeError("Gemini returned empty response")

            return output_model.model_validate_json(response.text)

        except Exception as e:
            logger.error(f"Gemini generation failed after retries: {e}")
            raise RuntimeError(f"LLM generation failed: {e}") from e

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        """
        Generate unstructured text response.

        Used when structured output is not needed (e.g., narrative generation
        where the output is a single prose string).
        """
        if self._client is None:
            raise ValueError(
                "Gemini client not initialized. Set GEMINI_API_KEY environment variable."
            )

        config = {}
        if system_instruction:
            config["system_instruction"] = system_instruction

        async def _invoke():
            # Wrap synchronous SDK call to avoid blocking the async event loop
            return await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=prompt,
                config=config if config else None,
            )

        try:
            response = await _call_with_retry(_invoke)
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini text generation failed after retries: {e}")
            raise RuntimeError(f"LLM generation failed: {e}") from e


# Module-level singleton (lazy initialization)
_gemini_client: GeminiClient | None = None


def get_gemini_client() -> GeminiClient:
    """Get or create the singleton Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
