"""OpenAI error classification, exercised with the SDK's real exception classes (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from quare_ordem import prompts
from quare_ordem.llm import (
    FatalAPIError,
    LLMClient,
    OpenAIBackend,
    TransientAPIError,
    load_api_key,
)

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _status_error(cls, status, code):
    body = {"error": {"message": code, "code": code}}
    return cls(code, response=httpx.Response(status, request=REQUEST, json=body), body=body)


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    return OpenAIBackend()


def _raise(exc):
    def create(**_):
        raise exc

    return create


CALL = dict(kind="ping", messages=prompts.ping_messages(), seed=1, max_tokens=5, meta={})


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_status_error(openai.RateLimitError, 429, "insufficient_quota"), FatalAPIError),
        (_status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), TransientAPIError),
        (_status_error(openai.AuthenticationError, 401, "invalid_api_key"), FatalAPIError),
        (_status_error(openai.PermissionDeniedError, 403, "model_not_found"), FatalAPIError),
        (_status_error(openai.NotFoundError, 404, "model_not_found"), FatalAPIError),
        (_status_error(openai.BadRequestError, 400, "invalid_request"), FatalAPIError),
        (_status_error(openai.InternalServerError, 500, "server_error"), TransientAPIError),
        (openai.APITimeoutError(request=REQUEST), TransientAPIError),
        (openai.APIConnectionError(request=REQUEST), TransientAPIError),
    ],
)
def test_error_classification(backend, monkeypatch, exc, expected):
    monkeypatch.setattr(backend.client.chat.completions, "create", _raise(exc))
    with pytest.raises(expected):
        backend.call(**CALL)


def test_no_credit_stops_without_retry(backend, monkeypatch, tmp_path):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise _status_error(openai.RateLimitError, 429, "insufficient_quota")

    monkeypatch.setattr(backend.client.chat.completions, "create", create)
    client = LLMClient(backend=backend, out_dir=tmp_path, budget_usd=8, sleep=lambda _: None)
    with pytest.raises(FatalAPIError):
        client.complete(kind="ping", messages=prompts.ping_messages(), seed=1)
    assert len(calls) == 1


def test_request_parameters_and_usage_parsing(backend, monkeypatch, tmp_path):
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'),
                                     finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=10,
                                  prompt_tokens_details=SimpleNamespace(cached_tokens=1024)),
            model="gpt-4o-mini-2024-07-18",
            system_fingerprint="fp_x",
        )

    monkeypatch.setattr(backend.client.chat.completions, "create", create)
    client = LLMClient(backend=backend, out_dir=tmp_path, budget_usd=8)
    assert client.complete(kind="ping", messages=prompts.ping_messages(), seed=42) == {"ok": True}
    assert seen["model"] == "gpt-4o-mini-2024-07-18"
    assert seen["temperature"] == 0.7 and seen["seed"] == 42
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["max_completion_tokens"] == 20
    expected = ((2000 - 1024) * 0.15 + 1024 * 0.075 + 10 * 0.60) / 1_000_000
    assert client.ledger.total_usd == pytest.approx(expected)


def test_temperature_zero_reaches_the_request(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    backend = OpenAIBackend(temperature=0.0)
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None),
            model="gpt-4o-mini-2024-07-18", system_fingerprint="fp_x",
        )

    monkeypatch.setattr(backend.client.chat.completions, "create", create)
    client = LLMClient(backend=backend, out_dir=tmp_path, budget_usd=1, temperature=0.0)
    client.complete(kind="ping", messages=prompts.ping_messages(), seed=1)
    assert seen["temperature"] == 0.0


def test_sdk_retries_are_disabled(backend):
    assert backend.client.max_retries == 0


def test_missing_key_is_fatal(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(FatalAPIError):
        load_api_key(tmp_path / ".env")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-coloque-sua-chave-aqui\n")
    with pytest.raises(FatalAPIError):
        load_api_key(tmp_path / ".env")
    (tmp_path / ".env").write_text('OPENAI_API_KEY="sk-real"\n')
    assert load_api_key(tmp_path / ".env") == "sk-real"
