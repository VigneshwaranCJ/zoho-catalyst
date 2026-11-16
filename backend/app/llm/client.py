"""Thin wrapper around the official Anthropic SDK (`anthropic` 2.x).

Why a wrapper:
  * one place for model names, timeouts, retries, refusal handling
  * token usage + cost recorded for every call (cost controls, analytics)
  * tests can substitute a fake implementing the same `structured()` method

Structured outputs: `client.beta.messages.parse(..., output_format=Model)`
constrains Claude's reply to the JSON schema of a Pydantic model and returns
a validated instance (`response.parsed_output`).

Refusal fallbacks: for Sonnet/Opus we enable the server-side fallback
(`fallbacks="default"`, beta `server-side-fallback-2026-07-01`): if the model
declines for safety reasons, the API re-runs the request on a suitable model
inside the same call. Haiku has no server-side fallback.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("llm")

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high", "xhigh", "max"]

# USD per million tokens: (input, output, cache read). Anthropic list prices,
# November 2026 (re-check https://www.anthropic.com/pricing before budgeting).
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
}
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """User-safe message describing why the AI step failed."""


class LLMNotConfiguredError(LLMError):
    pass


class LLMRefusalError(LLMError):
    pass


class LLMTruncatedError(LLMError):
    pass


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, int] = field(default_factory=dict)

    def add(self, model: str, usage: Any) -> None:
        inp = int(getattr(usage, "input_tokens", 0) or 0)
        out = int(getattr(usage, "output_tokens", 0) or 0)
        cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        price_in, price_out, price_cached = PRICES.get(model, PRICES["claude-sonnet-5-5"])
        self.calls += 1
        self.input_tokens += inp
        self.output_tokens += out
        self.cache_read_tokens += cached
        self.cost_usd += (inp * price_in + out * price_out + cached * price_cached) / 1_000_000
        self.by_model[model] = self.by_model.get(model, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cost_usd": round(self.cost_usd, 5),
            "by_model": self.by_model,
        }


class StructuredLLM(Protocol):
    async def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        output_model: type[T],
        usage: Usage,
        max_tokens: int = 16000,
        effort: Effort = "medium",
    ) -> T: ...


class AnthropicLLM:
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        key = api_key or (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )
        if not key:
            raise LLMNotConfiguredError(
                "AI generation is not configured. Set ANTHROPIC_API_KEY in .env."
            )
        # The SDK retries 408/409/429/5xx and connection errors itself (2 retries).
        self.client = anthropic.AsyncAnthropic(api_key=key, timeout=600.0, max_retries=2)

    async def structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        output_model: type[T],
        usage: Usage,
        max_tokens: int = 16000,
        effort: Effort = "medium",
    ) -> T:
        kwargs: dict[str, Any] = {}
        if model in FALLBACK_MODELS:
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            response = await self.client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output_model,
                output_config={"effort": effort},
                **kwargs,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMNotConfiguredError("The Anthropic API key was rejected.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("The AI service is busy (rate limit). The job will retry.") from exc
        except anthropic.APIStatusError as exc:
            log.error("llm_api_error", status=exc.status_code, request_id=exc.request_id)
            raise LLMError(f"The AI service returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service.") from exc

        usage.add(response.model or model, response.usage)
        log.info(
            "llm_call",
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            request_id=getattr(response, "_request_id", None),
        )
        if response.stop_reason == "refusal":
            raise LLMRefusalError("The AI declined to process this content.")
        if response.stop_reason == "max_tokens":
            raise LLMTruncatedError("The AI response was cut off (document section too long).")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("The AI response could not be read as structured data.")
        return parsed


@lru_cache
def get_llm() -> StructuredLLM:
    return AnthropicLLM()
