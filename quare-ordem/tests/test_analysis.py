"""Metrics and statistics, validated on known inputs and on the fake LLM's planted primacy effect."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("statsmodels")

from quare_ordem import analysis
from quare_ordem.design import build_plan
from quare_ordem.llm import FakeBackend, LLMClient
from quare_ordem.runner import execute


def test_jaccard_and_holm():
    assert analysis.jaccard_distance({"a", "b"}, {"b", "c"}) == pytest.approx(2 / 3)
    assert analysis.jaccard_distance(set(), set()) == 0.0
    assert analysis.holm([0.01, 0.04, 0.03, math.nan]) == pytest.approx([0.03, 0.06, 0.06, math.nan], nan_ok=True)


def test_matched_text_distance_is_order_free_and_penalises_missing():
    vectors = analysis._tfidf(["encrypt user data", "log every access", "log every access", "encrypt user data"])
    assert analysis.matched_text_distance(vectors[:2], vectors[2:]) == pytest.approx(0.0, abs=1e-9)
    assert analysis.matched_text_distance(vectors[:2], vectors[2:3]) == pytest.approx(0.5, abs=1e-9)


def test_permanova_separates_groups_and_not_noise():
    rng = np.random.default_rng(0)
    points = np.concatenate([rng.normal(0, 1, (10, 2)), rng.normal(6, 1, (10, 2))])
    distance = np.linalg.norm(points[:, None] - points[None, :], axis=-1)
    groups = [0] * 10 + [1] * 10
    assert analysis.permanova(distance, groups, 199, 1)["p"] < 0.01
    shuffled = list(rng.permutation(groups))
    noise = np.linalg.norm(rng.normal(0, 1, (20, 2))[:, None] - rng.normal(0, 1, (20, 2))[None, :], axis=-1)
    noise = (noise + noise.T) / 2
    np.fill_diagonal(noise, 0)
    assert analysis.permanova(noise, shuffled, 199, 1)["p"] > 0.05


def test_detects_planted_primacy_without_false_u(tmp_path):
    client = LLMClient(backend=FakeBackend(), out_dir=tmp_path, budget_usd=float("inf"))
    report = execute(build_plan(cases=["AD"]), client, tmp_path)
    assert len(report.completed) == 50
    analysis.analyze(tmp_path, permutations=99)

    import pandas as pd

    agents = pd.read_csv(tmp_path / "analise" / "agents.csv")
    survival = agents.groupby("position")["survival"].mean()
    assert survival.is_monotonic_decreasing  # planted: 0.9, 0.8, 0.7, 0.6, 0.5
    tests = pd.read_csv(tmp_path / "analise" / "tests.csv").set_index("test")
    h1 = tests[tests.index.str.startswith("H1")].iloc[0]
    h2 = tests[tests.index.str.startswith("H2")].iloc[0]
    assert h1["p_holm"] < 0.01
    assert h2["p"] > 0.5  # the last speaker is the most penalised: no U
