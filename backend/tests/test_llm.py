"""AnthropicLLM with a stub SDK client: request shape, parsing, refusals and the budget."""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm import AnthropicLLM, BudgetExceeded, FakeLLM, Image, LLMError, Text
from app.models import RequirementList
from tests.conftest import FIXTURES


class Answer(BaseModel):
    value: int


class StubMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(responses: list[Any]) -> tuple[Any, StubMessages]:
    messages = StubMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def _response(
    parsed: Any = None,
    *,
    stop_reason: str = "end_turn",
    content: list[Any] | None = None,
    tokens: tuple[int, int] = (100, 20),
) -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        parsed_output=parsed,
        content=content or [],
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


def _llm(settings: Settings, responses: list[Any]) -> tuple[AnthropicLLM, StubMessages]:
    client, messages = _client(responses)
    return AnthropicLLM(settings, client=client), messages


async def test_request_shape_and_result(settings: Settings) -> None:
    llm, messages = _llm(settings, [_response(Answer(value=3))])
    result = await llm.structured(
        step="s",
        system="sys",
        content=[Text("caption"), Image("image/png", b"\x89PNG")],
        output=Answer,
        tokens_used=0,
    )
    assert result.output.value == 3
    assert result.tokens == 120
    req = messages.requests[0]
    assert req["model"] == settings.anthropic_model
    assert req["output_format"] is Answer
    assert req["output_config"] == {"effort": "medium"}
    assert req["fallbacks"] == "default"
    assert "thinking" not in req and "temperature" not in req
    blocks = req["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["text", "image"]
    assert blocks[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "iVBORw=="}


async def test_text_block_is_found_after_thinking(settings: Settings) -> None:
    content = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text='{"value": 7}'),
    ]
    llm, _ = _llm(settings, [_response(None, content=content)])
    result = await llm.structured(step="s", system="", content=[], output=Answer, tokens_used=0)
    assert result.output.value == 7


async def test_refusal_and_truncation_fail_the_step(settings: Settings) -> None:
    llm, _ = _llm(settings, [_response(stop_reason="refusal")])
    with pytest.raises(LLMError, match="declined"):
        await llm.structured(step="s", system="", content=[], output=Answer, tokens_used=0)
    llm, _ = _llm(settings, [_response(stop_reason="max_tokens")])
    with pytest.raises(LLMError, match="cut off"):
        await llm.structured(step="s", system="", content=[], output=Answer, tokens_used=0)


async def test_validation_error_is_retried_once_with_the_error(settings: Settings) -> None:
    try:
        Answer.model_validate({"value": "x"})
    except ValidationError as e:
        invalid = e
    llm, messages = _llm(settings, [invalid, _response(Answer(value=1))])
    result = await llm.structured(step="s", system="", content=[], output=Answer, tokens_used=0)
    assert result.output.value == 1
    retry_blocks = messages.requests[1]["messages"][0]["content"]
    assert "did not pass validation" in retry_blocks[-1]["text"]

    llm, _ = _llm(settings, [invalid, invalid])
    with pytest.raises(LLMError, match="failed validation twice"):
        await llm.structured(step="s", system="", content=[], output=Answer, tokens_used=0)


async def test_budget_is_checked_before_calling(settings: Settings) -> None:
    llm, messages = _llm(settings, [_response(Answer(value=1))])
    with pytest.raises(BudgetExceeded):
        await llm.structured(
            step="s",
            system="",
            content=[],
            output=Answer,
            tokens_used=settings.max_llm_tokens_per_run,
        )
    assert messages.requests == []


async def test_fallback_can_be_turned_off(tmp_path: Any) -> None:
    from app.config import load_settings

    s = load_settings(data_dir=tmp_path, anthropic_refusal_fallback=False)
    llm, messages = _llm(s, [_response(Answer(value=1))])
    await llm.structured(step="s", system="", content=[], output=Answer, tokens_used=0)
    assert "fallbacks" not in messages.requests[0] and "betas" not in messages.requests[0]


async def test_fake_llm_replays_fixtures_and_counts_tokens() -> None:
    fake = FakeLLM(FIXTURES / "llm", limit=1_000_000)
    result = await fake.structured(
        step="extract_requirements",
        system="x" * 400,
        content=[Text("y" * 400)],
        output=RequirementList,
        tokens_used=0,
    )
    assert [r.id for r in result.output.requirements] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert result.tokens == 700
    with pytest.raises(LLMError, match="no recorded"):
        await fake.structured(step="nope", system="", content=[], output=Answer, tokens_used=0)
