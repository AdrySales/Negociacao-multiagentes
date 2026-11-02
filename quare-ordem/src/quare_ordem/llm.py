"""LLM client with spending cap, disk cache, spend ledger and a strict retry policy.

Safety rules:
- Before every paid call, the worst-case cost (estimated input + full output cap)
  must fit under the budget, otherwise BudgetExceeded is raised and nothing is sent.
- Every response is cached on disk by request hash; re-running never pays twice.
- Every paid call is appended to the ledger, including truncated or unparsable ones.
- Only transient errors are retried (MAX_ATTEMPTS in total). Authentication,
  quota, permission and bad-request errors abort immediately.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from quare_ordem import config


class BudgetExceeded(Exception):
    """The next call could push spending over the budget."""


class FatalAPIError(Exception):
    """Error that retrying cannot fix (bad key, no credit, invalid request)."""


class TransientAPIError(Exception):
    """Error worth retrying (timeout, connection, rate limit, 5xx)."""


class TruncatedResponse(Exception):
    """The model hit max_tokens; the JSON is incomplete."""


class InvalidResponse(Exception):
    """The response is not usable JSON for the expected schema."""


@dataclass
class RawResponse:
    text: str
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    finish_reason: str
    model: str
    system_fingerprint: str | None


class Backend(Protocol):
    name: str

    def call(
        self,
        *,
        kind: str,
        messages: list[dict[str, str]],
        seed: int,
        max_tokens: int,
        meta: dict[str, Any],
    ) -> RawResponse: ...


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    """Conservative token estimate (English JSON averages ~4 chars per token)."""

    chars = sum(len(message["content"]) for message in messages)
    return int(chars / 3.5) + 20 * len(messages)


def call_cost(prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float:
    fresh = max(0, prompt_tokens - cached_tokens)
    return (
        fresh * config.PRICE_INPUT
        + cached_tokens * config.PRICE_CACHED_INPUT
        + completion_tokens * config.PRICE_OUTPUT
    ) / 1_000_000


class Ledger:
    """Append-only record of every paid call; the source of truth for spending."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._total = 0.0
        self._calls = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._total += float(json.loads(line)["cost_usd"])
                    self._calls += 1

    @property
    def total_usd(self) -> float:
        return self._total

    @property
    def calls(self) -> int:
        return self._calls

    def append(self, entry: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._total += float(entry["cost_usd"])
        self._calls += 1


class LLMClient:
    def __init__(
        self,
        *,
        backend: Backend,
        out_dir: Path,
        budget_usd: float,
        model: str = config.MODEL,
        temperature: float = config.TEMPERATURE,
        sleep: Any = time.sleep,
    ) -> None:
        self.backend = backend
        self.cache_dir = out_dir / "cache"
        self.ledger = Ledger(out_dir / "ledger.jsonl")
        self.budget_usd = budget_usd
        self.model = model
        self.temperature = temperature
        self.cache_hits = 0
        self._sleep = sleep

    def complete(
        self,
        *,
        kind: str,
        messages: list[dict[str, str]],
        seed: int,
        meta: dict[str, Any] | None = None,
        run_id: str = "",
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        max_tokens = max_tokens or config.MAX_TOKENS[kind]
        key = self._cache_key(messages=messages, seed=seed, max_tokens=max_tokens)
        cache_path = self.cache_dir / kind / f"{key}.json"
        if cache_path.exists():
            self.cache_hits += 1
            return json.loads(json.loads(cache_path.read_text(encoding="utf-8"))["text"])

        worst_case = (
            estimate_tokens(messages) * config.PRICE_INPUT + max_tokens * config.PRICE_OUTPUT
        ) / 1_000_000
        if self.ledger.total_usd + worst_case > self.budget_usd:
            raise BudgetExceeded(
                f"gasto atual US$ {self.ledger.total_usd:.4f} + pior caso desta chamada "
                f"US$ {worst_case:.4f} ultrapassa o teto de US$ {self.budget_usd:.2f}"
            )

        raw = self._call_with_retries(
            kind=kind, messages=messages, seed=seed, max_tokens=max_tokens, meta=meta or {}
        )
        cost = call_cost(raw.prompt_tokens, raw.cached_tokens, raw.completion_tokens)
        self.ledger.append(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "backend": self.backend.name,
                "run_id": run_id,
                "kind": kind,
                "model": raw.model,
                "system_fingerprint": raw.system_fingerprint,
                "prompt_tokens": raw.prompt_tokens,
                "cached_tokens": raw.cached_tokens,
                "completion_tokens": raw.completion_tokens,
                "finish_reason": raw.finish_reason,
                "cost_usd": cost,
                "cache_key": key,
            }
        )

        if raw.finish_reason == "length":
            # One retry with double the cap. The default cap stays in every other cache key,
            # so answers that fit are unaffected and nothing already cached is paid again.
            if max_tokens == config.MAX_TOKENS[kind]:
                return self.complete(kind=kind, messages=messages, seed=seed, meta=meta,
                                     run_id=run_id, max_tokens=2 * max_tokens)
            raise TruncatedResponse(f"{kind}: resposta cortada em {max_tokens} tokens")
        try:
            parsed = json.loads(raw.text)
        except json.JSONDecodeError as exc:
            raise InvalidResponse(f"{kind}: JSON inválido ({exc})") from exc
        if not isinstance(parsed, dict):
            raise InvalidResponse(f"{kind}: esperado um objeto JSON")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "kind": kind,
                    "seed": seed,
                    "messages": messages,
                    "text": raw.text,
                    "model": raw.model,
                    "system_fingerprint": raw.system_fingerprint,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        return parsed

    def _call_with_retries(self, **kwargs: Any) -> RawResponse:
        delays = (5, 20)
        for attempt in range(config.MAX_ATTEMPTS):
            try:
                return self.backend.call(**kwargs)
            except TransientAPIError:
                if attempt == config.MAX_ATTEMPTS - 1:
                    raise
                self._sleep(delays[min(attempt, len(delays) - 1)])
        raise AssertionError("unreachable")

    def _cache_key(self, *, messages: list[dict[str, str]], seed: int, max_tokens: int) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": self.temperature,
                "seed": seed,
                "max_tokens": max_tokens,
                "messages": messages,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------


def load_api_key(env_file: Path = config.PROJECT_ROOT / ".env") -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "OPENAI_API_KEY":
                key = value.strip().strip('"').strip("'")
    if not key or "coloque-sua-chave" in key:
        raise FatalAPIError(
            f"OPENAI_API_KEY não encontrada. Crie {env_file} com OPENAI_API_KEY=sk-..."
        )
    return key


class OpenAIBackend:
    name = "openai"

    def __init__(self, *, model: str = config.MODEL, temperature: float = config.TEMPERATURE):
        import openai

        self._openai = openai
        self.model = model
        self.temperature = temperature
        # The SDK's own retries are disabled; LLMClient owns the retry policy.
        self.client = openai.OpenAI(
            api_key=load_api_key(),
            timeout=config.REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def call(
        self,
        *,
        kind: str,
        messages: list[dict[str, str]],
        seed: int,
        max_tokens: int,
        meta: dict[str, Any],
    ) -> RawResponse:
        openai = self._openai
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                seed=seed,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except openai.RateLimitError as exc:
            if "insufficient_quota" in str(exc):
                raise FatalAPIError("crédito esgotado na OpenAI (insufficient_quota)") from exc
            raise TransientAPIError(str(exc)) from exc
        except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as exc:
            raise TransientAPIError(str(exc)) from exc
        except openai.APIError as exc:
            raise FatalAPIError(f"{type(exc).__name__}: {exc}") from exc

        choice = response.choices[0]
        usage = response.usage
        details = getattr(usage, "prompt_tokens_details", None)
        return RawResponse(
            text=choice.message.content or "",
            prompt_tokens=usage.prompt_tokens,
            cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
            completion_tokens=usage.completion_tokens,
            finish_reason=choice.finish_reason or "",
            model=response.model,
            system_fingerprint=getattr(response, "system_fingerprint", None),
        )

    def check_model(self) -> str:
        """Free call: confirms the key works and the snapshot is available."""

        try:
            return self.client.models.retrieve(self.model).id
        except self._openai.APIError as exc:
            raise FatalAPIError(f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# Fake backend for free end-to-end testing
# ---------------------------------------------------------------------------

_FILLER = (
    "considering the operational context, the stakeholders involved and the measurable "
    "acceptance criteria that an engineer would need to verify this behaviour in practice"
)


class FakeBackend:
    """Deterministic stand-in for the API.

    Produces schema-valid outputs of realistic length, so a dry run exercises the
    whole pipeline and its token counts approximate the real spend.
    """

    name = "fake"

    def __init__(self, *, fail_kinds: dict[str, list[Exception]] | None = None) -> None:
        # fail_kinds["turn"] = [TransientAPIError(), ...] raises these, in order, first.
        self.fail_kinds = fail_kinds or {}
        self.calls = 0

    def call(
        self,
        *,
        kind: str,
        messages: list[dict[str, str]],
        seed: int,
        max_tokens: int,
        meta: dict[str, Any],
    ) -> RawResponse:
        self.calls += 1
        pending = self.fail_kinds.get(kind)
        if pending:
            raise pending.pop(0)

        rng = random.Random(f"{seed}|{kind}|{meta.get('agent', '')}|{len(messages[-1]['content'])}")
        builder = {
            "ping": lambda: {"ok": True},
            "phase1": lambda: self._phase1(meta),
            "turn": lambda: self._turn(meta, rng),
            "synthesis": lambda: self._synthesis(meta, rng),
        }[kind]
        text = json.dumps(builder(), ensure_ascii=False)
        completion_tokens = int(len(text) / 4)
        prompt_tokens = int(sum(len(m["content"]) for m in messages) / 4)
        # Mimic OpenAI prompt caching: a long shared prefix is mostly cached.
        cached = int(prompt_tokens * 0.6) if kind == "turn" and prompt_tokens > 1024 else 0
        return RawResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached,
            completion_tokens=min(completion_tokens, max_tokens),
            finish_reason="length" if completion_tokens > max_tokens else "stop",
            model="fake-model",
            system_fingerprint="fake",
        )

    @staticmethod
    def _phase1(meta: dict[str, Any]) -> dict[str, Any]:
        agent = meta["agent"]
        levels = ["strategic", "tactical", "tactical", "operational", "operational", "operational", "operational"]
        return {
            "requirements": [
                {
                    "text": f"The system shall satisfy {agent} concern number {i + 1}, {_FILLER}.",
                    "kaos_level": levels[i % len(levels)],
                    "rationale": f"Derived from the project description for {agent}.",
                }
                for i in range(meta["n"])
            ]
        }

    @staticmethod
    def _turn(meta: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        own = meta["own_ids"]
        others = meta["other_ids"]
        target = rng.choice(others)
        return {
            "statement": (
                f"As {meta['agent']} I defend {own[0]} because it is essential, and I challenge "
                f"{target} since it competes for the same resources; {_FILLER}."
            ),
            "conflicts_raised": [
                {
                    "ids": [own[0], target],
                    "type": rng.choice(["resource", "logical", "redundant"]),
                    "description": f"{own[0]} and {target} impose incompatible constraints.",
                }
            ],
            "positions": [
                {"id": target, "stance": rng.choice(["support", "oppose", "modify"]),
                 "proposal": f"Relax {target} with a measurable threshold."},
            ],
            "concessions": [own[-1]] if rng.random() < 0.3 else [],
            "agree_to_close": meta["round"] >= 2 and rng.random() < 0.5,
        }

    @staticmethod
    def _synthesis(meta: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        ids = list(meta["all_ids"])
        # Planted primacy effect for validating the metrics: the agent at position p
        # (0-based) loses each requirement with probability 0.1 + 0.1 * p.
        drop_prob = {config.AGENT_PREFIX[agent]: 0.1 + 0.1 * position
                     for position, agent in enumerate(meta["order"])}
        dropped = [item for item in ids if rng.random() < drop_prob[item.split("-")[0]]]
        kept = [item for item in ids if item not in dropped]
        requirements = []
        for index in range(0, len(kept), 2):
            group = kept[index : index + 2]
            requirements.append(
                {
                    "id": f"F-{len(requirements) + 1:02d}",
                    "text": f"Integrated requirement covering {', '.join(group)}, {_FILLER}.",
                    "quality_axes": ["Safety"],
                    "derived_from": group,
                    "kaos_level": "operational",
                    "parent": None,
                }
            )
        return {
            "requirements": requirements,
            "conflict_resolutions": [
                {
                    "ids": dropped[:2],
                    "outcome": "favored",
                    "favored_agent": meta["order"][0],
                    "rationale": "Safety-critical constraint prevails.",
                }
            ],
            "dropped": [{"id": item, "reason": "Superseded by negotiated outcome."} for item in dropped],
        }
