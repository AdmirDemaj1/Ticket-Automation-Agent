"""LLM layer: structured outputs from Claude, with a per-run token budget.

- `AnthropicLLM` calls the Anthropic SDK directly (no LangChain wrapper). It uses
  `beta.messages.parse` with a Pydantic output model, adaptive thinking (the default on
  current models, so no `thinking` or `temperature` is sent), `output_config.effort`, and the
  server-side refusal fallback. Transient errors are retried by the SDK (3 tries in total).
- `FakeLLM` replays recorded JSON responses from `fixtures/llm/<step>.json`, so the app and
  the tests run with no API key.

Prompts and responses are never logged above DEBUG.
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import Settings

log = logging.getLogger("app.llm")

MAX_OUTPUT_TOKENS = 16_000


class LLMError(Exception):
    """An LLM step failed. The message is safe to show to the user."""


class BudgetExceeded(LLMError):
    pass


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Image:
    media_type: str
    data: bytes


Part = Text | Image


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    tokens: int


class LLM(Protocol):
    async def structured[T: BaseModel](
        self,
        *,
        step: str,
        system: str,
        content: list[Part],
        output: type[T],
        tokens_used: int,
    ) -> LLMResult[T]:
        """Run one structured call. Raises BudgetExceeded before calling when over budget."""
        ...


def check_budget(tokens_used: int, limit: int) -> None:
    if tokens_used >= limit:
        raise BudgetExceeded(
            f"Token budget reached ({tokens_used:,} of {limit:,} tokens used). "
            "Raise MAX_LLM_TOKENS_PER_RUN or use a shorter transcript or fewer files."
        )


# ---------- Anthropic ----------


class AnthropicLLM:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if client is None:
            key = settings.anthropic_api_key
            if key is None or not key.get_secret_value().strip():
                raise LLMError("ANTHROPIC_API_KEY is not set")
            client = anthropic.AsyncAnthropic(api_key=key.get_secret_value(), max_retries=2)
        self.client = client
        self.model = settings.anthropic_model
        self.effort = settings.anthropic_effort
        self.fallback = settings.anthropic_refusal_fallback
        self.limit = settings.max_llm_tokens_per_run

    async def structured[T: BaseModel](
        self,
        *,
        step: str,
        system: str,
        content: list[Part],
        output: type[T],
        tokens_used: int,
    ) -> LLMResult[T]:
        blocks = [_to_block(p) for p in content]
        spent = 0
        error: str | None = None
        for attempt in (1, 2):
            check_budget(tokens_used + spent, self.limit)
            request = blocks
            if error is not None:
                request = [
                    *blocks,
                    {
                        "type": "text",
                        "text": "Your previous answer did not pass validation: "
                        f"{error}\nReturn a corrected answer.",
                    },
                ]
            try:
                # The SDK validates against `output` inside parse(), so a ValidationError
                # can come from the call itself or from our own fallback parsing.
                response = await self._call(step, system, request, output)
                spent += _usage_tokens(response)
                parsed = _parsed(step, response, output)
            except ValidationError as e:
                error = _short_validation_error(e)
                log.warning("%s: output failed validation (attempt %d)", step, attempt)
                continue
            return LLMResult(output=parsed, tokens=spent)
        raise LLMError(f"{step}: Claude's answer failed validation twice ({error})")

    async def _call(
        self, step: str, system: str, blocks: list[dict[str, Any]], output: type[BaseModel]
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": blocks}],
            "output_format": output,
            "output_config": {"effort": self.effort},
        }
        if self.fallback:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        try:
            return await self.client.beta.messages.parse(**kwargs)
        except ValidationError:
            raise
        except anthropic.AuthenticationError as e:
            raise LLMError("The Anthropic API key was rejected") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError("The Anthropic API key may not use this model or feature") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"{step}: Claude rejected the request ({_api_message(e)})") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"{step}: rate limited by the Anthropic API; retry later") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"{step}: Anthropic API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"{step}: could not reach the Anthropic API") from e


def _to_block(part: Part) -> dict[str, Any]:
    if isinstance(part, Text):
        return {"type": "text", "text": part.text}
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": part.media_type,
            "data": base64.b64encode(part.data).decode("ascii"),
        },
    }


def _parsed[T: BaseModel](step: str, response: Any, output: type[T]) -> T:
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        raise LLMError(
            f"{step}: Claude declined this request"
            + (f" (category: {category})" if category else "")
        )
    if response.stop_reason == "max_tokens":
        raise LLMError(f"{step}: Claude's answer was cut off at the output token limit")
    parsed = getattr(response, "parsed_output", None)
    if isinstance(parsed, output):
        return parsed
    # Select by block type, never by position: thinking blocks may come first.
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise LLMError(f"{step}: Claude returned no answer")
    return output.model_validate_json(text)


def _usage_tokens(response: Any) -> int:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0
    total = 0
    for name in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = getattr(usage, name, None)
        if isinstance(value, int):
            total += value
    return total


def _short_validation_error(e: ValidationError) -> str:
    parts = []
    for err in e.errors(include_input=False, include_url=False)[:5]:
        loc = ".".join(str(p) for p in err["loc"])
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def _api_message(e: anthropic.APIStatusError) -> str:
    body = e.body if isinstance(e.body, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    message = err.get("message") if isinstance(err, dict) else None
    return str(message)[:300] if message else f"HTTP {e.status_code}"


# ---------- Fake ----------


@dataclass
class FakeCall:
    step: str
    system: str
    content: list[Part]


@dataclass
class FakeLLM:
    """Replays `<responses_dir>/<step>.json`. `overrides` win over files (for tests)."""

    responses_dir: Path
    limit: int = 300_000
    overrides: dict[str, Any] = field(default_factory=dict)
    calls: list[FakeCall] = field(default_factory=list)

    async def structured[T: BaseModel](
        self,
        *,
        step: str,
        system: str,
        content: list[Part],
        output: type[T],
        tokens_used: int,
    ) -> LLMResult[T]:
        check_budget(tokens_used, self.limit)
        self.calls.append(FakeCall(step=step, system=system, content=list(content)))
        if step in self.overrides:
            data = self.overrides[step]
        else:
            path = self.responses_dir / f"{step}.json"
            if not path.is_file():
                raise LLMError(f"{step}: no recorded fake response at {path.name}")
            data = json.loads(path.read_text("utf-8"))
        if isinstance(data, Exception):
            raise data
        try:
            parsed = output.model_validate(data)
        except ValidationError as e:
            raise LLMError(f"{step}: recorded fake response is invalid") from e
        chars = len(system) + sum(len(p.text) for p in content if isinstance(p, Text))
        images = sum(1 for p in content if isinstance(p, Image))
        return LLMResult(output=parsed, tokens=chars // 4 + images * 1_600 + 500)


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings)
    return FakeLLM(settings.fake_llm_dir, limit=settings.max_llm_tokens_per_run)
