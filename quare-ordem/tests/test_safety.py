"""Tests for everything that could waste money: budget, cache, retries, resume, breaker."""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest

from quare_ordem import config, prompts
from quare_ordem.design import RunSpec, build_plan, speaking_orders, williams_orders
from quare_ordem.llm import (
    BudgetExceeded,
    FakeBackend,
    FatalAPIError,
    InvalidResponse,
    LLMClient,
    RawResponse,
    TransientAPIError,
    TruncatedResponse,
)
from quare_ordem.pipeline import ensure_phase1, load_case
from quare_ordem.runner import execute


def make_client(tmp_path, backend=None, budget=float("inf")):
    return LLMClient(
        backend=backend or FakeBackend(), out_dir=tmp_path, budget_usd=budget, sleep=lambda _: None
    )


PING = prompts.ping_messages()


# --- design -----------------------------------------------------------------


def test_williams_design_is_balanced():
    rows = williams_orders(5)
    assert len(rows) == 10
    assert all(sorted(row) == list(range(5)) for row in rows)
    for position in range(5):
        assert Counter(row[position] for row in rows) == {agent: 2 for agent in range(5)}
    adjacent = Counter((row[i], row[i + 1]) for row in rows for i in range(4))
    assert len(adjacent) == 20 and set(adjacent.values()) == {2}


def test_plan_size_and_unique_seeds():
    plan = build_plan()
    assert len(plan) == 5 * 10 * config.REPLICAS
    assert len({spec.run_id for spec in plan}) == len(plan)
    assert len({spec.seed for spec in plan if spec.case == "AD"}) == 10 * config.REPLICAS


def test_every_agent_speaks_first_in_two_orders():
    firsts = Counter(order[0] for order in speaking_orders())
    assert firsts == {agent: 2 for agent in config.AGENTS}


# --- budget, cache, ledger --------------------------------------------------


def test_budget_blocks_call_before_sending(tmp_path):
    backend = FakeBackend()
    client = make_client(tmp_path, backend, budget=0.0000001)
    with pytest.raises(BudgetExceeded):
        client.complete(kind="ping", messages=PING, seed=1)
    assert backend.calls == 0
    assert client.ledger.total_usd == 0


def test_budget_counts_previous_spend_from_ledger_file(tmp_path):
    (tmp_path / "ledger.jsonl").write_text(json.dumps({"cost_usd": 7.999}) + "\n")
    backend = FakeBackend()
    client = make_client(tmp_path, backend, budget=8.0)
    case = load_case("AD")
    with pytest.raises(BudgetExceeded):
        client.complete(
            kind="phase1",
            messages=prompts.phase1_messages(case, "SafetyAgent"),
            seed=1,
            meta={"agent": "SafetyAgent", "n": 7},
        )
    assert backend.calls == 0


def test_cache_prevents_paying_twice(tmp_path):
    backend = FakeBackend()
    client = make_client(tmp_path, backend)
    first = client.complete(kind="ping", messages=PING, seed=1)
    spent = client.ledger.total_usd
    second = make_client(tmp_path, backend).complete(kind="ping", messages=PING, seed=1)
    assert first == second
    assert backend.calls == 1
    assert make_client(tmp_path, backend).ledger.total_usd == spent


# --- retry policy -----------------------------------------------------------


def test_transient_errors_are_retried_then_succeed(tmp_path):
    backend = FakeBackend(fail_kinds={"ping": [TransientAPIError(), TransientAPIError()]})
    assert make_client(tmp_path, backend).complete(kind="ping", messages=PING, seed=1) == {"ok": True}
    assert backend.calls == 3


def test_transient_errors_give_up_after_max_attempts(tmp_path):
    backend = FakeBackend(fail_kinds={"ping": [TransientAPIError()] * 5})
    with pytest.raises(TransientAPIError):
        make_client(tmp_path, backend).complete(kind="ping", messages=PING, seed=1)
    assert backend.calls == config.MAX_ATTEMPTS


def test_fatal_errors_are_not_retried(tmp_path):
    backend = FakeBackend(fail_kinds={"ping": [FatalAPIError("no credit")]})
    with pytest.raises(FatalAPIError):
        make_client(tmp_path, backend).complete(kind="ping", messages=PING, seed=1)
    assert backend.calls == 1


class TruncatingBackend(FakeBackend):
    def call(self, **kwargs):
        self.calls += 1
        return RawResponse('{"ok": tr', 100, 0, 5, "length", "fake", None)


def test_truncated_response_is_charged_and_not_cached(tmp_path):
    backend = TruncatingBackend()
    client = make_client(tmp_path, backend)
    with pytest.raises(TruncatedResponse):
        client.complete(kind="ping", messages=PING, seed=1)
    # One retry with double the cap, then give up: two paid calls, nothing cached.
    assert backend.calls == 2
    assert client.ledger.calls == 2
    assert not (tmp_path / "cache").exists()


# --- prompts ----------------------------------------------------------------


def test_prompts_never_reveal_speaking_position(tmp_path):
    phase1 = ensure_phase1("ATM", make_client(tmp_path), tmp_path)
    case = load_case("ATM")
    for agent in config.AGENTS:
        text = json.dumps(
            prompts.turn_messages(case=case, phase1=phase1, transcript=[], agent=agent, round_number=1)
        ).lower()
        assert not re.search(
            r"speaking (order|position)|position \d|speak(s|ing)? (first|last)|"
            r"you are the (first|second|third|fourth|last)",
            text,
        )


def test_shared_context_is_identical_across_orders(tmp_path):
    """Before anyone speaks, every order sees exactly the same context."""

    phase1 = ensure_phase1("ATM", make_client(tmp_path), tmp_path)
    case = load_case("ATM")
    prefixes = {
        json.dumps(prompts.turn_messages(case=case, phase1=phase1, transcript=[], agent=order[0],
                                         round_number=1)[:2])
        for order in speaking_orders()
    }
    assert len(prefixes) == 1


# --- runner -----------------------------------------------------------------


def test_dry_run_completes_and_resume_costs_nothing(tmp_path):
    plan = build_plan(cases=["Library"], order_indices=[0, 1], replicas=2)
    backend = FakeBackend()
    client = make_client(tmp_path, backend)
    report = execute(plan, client, tmp_path, echo=lambda *_: None)
    assert len(report.completed) == 4 and not report.failed and not report.stop_reason

    result = json.loads((tmp_path / "results" / f"{plan[0].run_id}.json").read_text())
    assert [turn["agent"] for turn in result["transcript"][:5]] == list(plan[0].order)
    assert result["synthesis"]["requirements"]

    calls_before = backend.calls
    report = execute(plan, make_client(tmp_path, backend), tmp_path, echo=lambda *_: None)
    assert len(report.skipped) == 4 and backend.calls == calls_before


class BrokenSynthesisBackend(FakeBackend):
    def call(self, **kwargs):
        if kwargs["kind"] == "synthesis":
            self.calls += 1
            return RawResponse('{"requirements": []}', 100, 0, 5, "stop", "fake", None)
        return super().call(**kwargs)


def test_circuit_breaker_stops_after_repeated_failures(tmp_path):
    plan = build_plan(cases=["Library"], replicas=1)
    backend = BrokenSynthesisBackend()
    report = execute(plan, make_client(tmp_path, backend), tmp_path, echo=lambda *_: None)
    assert len(report.failed) == config.MAX_FAILED_RUNS
    assert "falharam" in report.stop_reason
    assert len((tmp_path / "failures.jsonl").read_text().splitlines()) == config.MAX_FAILED_RUNS


def test_runner_stops_cleanly_at_budget(tmp_path):
    plan = build_plan(cases=["Library"], replicas=1)
    client = make_client(tmp_path, budget=0.01)
    report = execute(plan, client, tmp_path, echo=lambda *_: None)
    assert report.stop_reason.startswith("teto de gasto")
    assert client.ledger.total_usd <= 0.01


def test_fatal_error_stops_runner_immediately(tmp_path):
    backend = FakeBackend(fail_kinds={"phase1": [FatalAPIError("bad key")]})
    plan = build_plan(cases=["Library"], replicas=1)
    report = execute(plan, make_client(tmp_path, backend), tmp_path, echo=lambda *_: None)
    assert report.stop_reason.startswith("erro fatal")
    assert backend.calls == 1


def test_phase1_is_frozen_and_reused(tmp_path):
    backend = FakeBackend()
    first = ensure_phase1("RollCall", make_client(tmp_path, backend), tmp_path)
    calls = backend.calls
    assert ensure_phase1("RollCall", make_client(tmp_path, backend), tmp_path) == first
    assert backend.calls == calls
    assert all(len(items) == config.REQS_PER_AGENT for items in first.values())


def test_invalid_turn_raises():
    from quare_ordem.pipeline import normalize_turn

    with pytest.raises(InvalidResponse):
        normalize_turn({"statement": ""}, {"SAF-01"})
    turn = normalize_turn(
        {"statement": "x", "conflicts_raised": [{"ids": ["SAF-01", "ZZZ-9"], "type": "LOGICAL"}],
         "agree_to_close": "true"},
        {"SAF-01"},
    )
    assert turn["conflicts_raised"][0] == {"ids": ["SAF-01"], "type": "logical", "description": ""}
    assert turn["unknown_ids"] == ["ZZZ-9"]
    assert turn["agree_to_close"] is False  # only a real JSON boolean counts


def test_listing_rotations_are_balanced_and_change_only_the_listing():
    from collections import Counter

    from quare_ordem import prompts
    from quare_ordem.cli import listing_rotation

    rotations = [listing_rotation(o, r) for o in range(10) for r in range(5)]
    for position in range(len(config.AGENTS)):
        assert Counter(rot[position] for rot in rotations) == {a: 10 for a in config.AGENTS}

    phase1 = {a: [{"id": f"{config.AGENT_PREFIX[a]}-01", "kaos_level": "tactical", "text": "x"}]
              for a in config.AGENTS}
    case = {"case_name": "C", "case_description": "d", "requirement": "r"}
    canonical = prompts.synthesis_messages(case=case, phase1=phase1, transcript=[])
    assert prompts.synthesis_messages(case=case, phase1=phase1, transcript=[],
                                      agents=config.AGENTS) == canonical
    rotated = prompts.synthesis_messages(case=case, phase1=phase1, transcript=[],
                                         agents=listing_rotation(2, 0))
    body = rotated[1]["content"]
    assert body.index("[GreenAgent]") < body.index("[SafetyAgent]")
    assert rotated[-1]["content"].index("GRN-01") < rotated[-1]["content"].index("SAF-01")
