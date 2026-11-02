"""Speaking orders (Williams design) and the run plan."""

from __future__ import annotations

from dataclasses import dataclass

from quare_ordem import config


def williams_orders(n: int) -> list[list[int]]:
    """Williams design: every item appears equally often in every position and
    every ordered pair (a immediately before b) appears equally often.

    For odd n this needs 2n sequences: the n cyclic shifts of the base row plus
    their reversals.
    """

    base: list[int] = [0]
    low, high = 1, n - 1
    take_low = True
    while len(base) < n:
        if take_low:
            base.append(low)
            low += 1
        else:
            base.append(high)
            high -= 1
        take_low = not take_low

    rows = [[(item + shift) % n for item in base] for shift in range(n)]
    if n % 2 == 1:
        rows += [list(reversed(row)) for row in rows]
    return rows


def speaking_orders() -> list[tuple[str, ...]]:
    """The 10 agent speaking orders used in the experiment."""

    return [tuple(config.AGENTS[i] for i in row) for row in williams_orders(len(config.AGENTS))]


@dataclass(frozen=True)
class RunSpec:
    case: str
    order_index: int
    replica: int

    @property
    def run_id(self) -> str:
        return f"{self.case}-o{self.order_index:02d}-r{self.replica}"

    @property
    def order(self) -> tuple[str, ...]:
        return speaking_orders()[self.order_index]

    @property
    def seed(self) -> int:
        # Distinct per run, so no two runs share a cached LLM response.
        return 10_000 + 100 * self.order_index + self.replica


def build_plan(
    cases: tuple[str, ...] | list[str] = config.CASES,
    order_indices: list[int] | None = None,
    replicas: int = config.REPLICAS,
) -> list[RunSpec]:
    """Runs interleaved by replica, so a partial execution is still balanced."""

    if order_indices is None:
        order_indices = list(range(len(speaking_orders())))
    return [
        RunSpec(case=case, order_index=order_index, replica=replica)
        for replica in range(replicas)
        for case in cases
        for order_index in order_indices
    ]
