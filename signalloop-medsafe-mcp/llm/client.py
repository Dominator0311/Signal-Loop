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
from typing import TypeVar, Type

from google import genai
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


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

        try:
            # Wrap synchronous SDK call to avoid blocking the async event loop
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=prompt,
                config=config,
            )

            if not response.text:
                raise RuntimeError("Gemini returned empty response")

            return output_model.model_validate_json(response.text)

        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
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

        try:
            # Wrap synchronous SDK call to avoid blocking the async event loop
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=prompt,
                config=config if config else None,
            )
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini text generation failed: {e}")
            raise RuntimeError(f"LLM generation failed: {e}") from e


# Module-level singleton (lazy initialization)
_gemini_client: GeminiClient | None = None


def get_gemini_client() -> GeminiClient:
    """Get or create the singleton Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
