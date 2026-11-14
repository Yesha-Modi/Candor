"""Talk to a language model.

Written as an interface rather than a function because Week 3 compares four
providers. Adding Groq or Ollama later means writing one more class, not
rewriting the agent.
"""

import os
import time
from typing import Protocol

from dotenv import load_dotenv

from agent.schema import AgentResponse

load_dotenv()

TIMEOUT_MS = 30_000
API_VERSION = "v1beta"
MAX_OUTPUT_TOKENS = 2048

# 503 "high demand" is normal on a free tier. Retry it, with a bound you can
# compute: 4 attempts x 30s, plus ~19s of backoff, is under 2m20s worst case.
RETRY_ATTEMPTS = 4
RETRY_CODES = [408, 429, 500, 502, 503, 504]


class Provider(Protocol):
    name: str

    def generate(self, prompt: str) -> tuple[AgentResponse, dict]:
        """Return the parsed response and metadata about the call."""
        ...


class GeminiProvider:
    """Google AI Studio. Free tier, no card required."""

    def __init__(self, model: str = "gemini-3.8-flash") -> None:
        from google import genai
        from google.genai import types

        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Put it in a .env file at the project root:\n"
                "    GEMINI_API_KEY=your-key-here\n"
                "Get one free at https://aistudio.google.com/apikey"
            )

        self.client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                api_version=API_VERSION,
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(
                    attempts=RETRY_ATTEMPTS,
                    initial_delay=2.0,
                    max_delay=20.0,
                    http_status_codes=RETRY_CODES,
                ),
            ),
        )
        self.model = model
        self.name = f"gemini/{model}"

    def generate(self, prompt: str) -> tuple[AgentResponse, dict]:
        started = time.perf_counter()

        try:
            raw = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": AgentResponse.model_json_schema(),
                    "automatic_continuation": False,
                    "max_output_tokens": MAX_OUTPUT_TOKENS,
                },
            )
        except Exception as e:
            code = getattr(e, "code", None)
            if code in RETRY_CODES:
                hint = (
                    f"The model is busy, not broken -- this is the free tier under "
                    f"load. {RETRY_ATTEMPTS} attempts already failed, so wait a few "
                    f"minutes and run the same command again."
                )
            else:
                hint = (
                    "If this is a model-not-found error, run list_models.py. It "
                    "lists each API version separately, and a model present in one "
                    "version is not necessarily present in the other."
                )
            raise RuntimeError(
                f"Call to {self.name} on API version {API_VERSION} failed after "
                f"{time.perf_counter() - started:.0f}s: {type(e).__name__}: {e}\n"
                f"{hint}"
            ) from e

        seconds = time.perf_counter() - started

        finish = None
        if raw.candidates:
            finish = getattr(raw.candidates[0], "finish_reason", None)
            finish = getattr(finish, "name", finish)

        if not raw.text:
            raise RuntimeError(
                f"{self.name} returned no text (finish_reason={finish}). "
                f"If that says MAX_TOKENS, raise MAX_OUTPUT_TOKENS in provider.py."
            )

        try:
            response = AgentResponse.model_validate_json(raw.text)
        except Exception as e:
            raise RuntimeError(
                f"{self.name} returned text that is not a valid AgentResponse "
                f"(finish_reason={finish}): {type(e).__name__}: {e}\n"
                f"First 300 characters of what came back:\n{raw.text[:300]}"
            ) from e

        usage = getattr(raw, "usage_metadata", None)
        meta = {
            "provider": self.name,
            "seconds": round(seconds, 2),
            "prompt_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "finish_reason": finish,
        }
        return response, meta


PROVIDERS = {
    "gemini": GeminiProvider,
}


def get_provider(name: str = "gemini", **kwargs) -> Provider:
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider '{name}'. Available: {list(PROVIDERS)}")
    return PROVIDERS[name](**kwargs)