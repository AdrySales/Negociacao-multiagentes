"""Experiment constants. Everything that defines the experimental conditions lives here."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = PROJECT_ROOT / "data" / "cases"
RUNS_DIR = PROJECT_ROOT / "runs"

# Same snapshot as the QUARE paper (Section IV-B).
MODEL = "gpt-4o-mini-2024-07-18"
TEMPERATURE = 0.7

CASES = ("AD", "ATM", "Library", "RollCall", "Bookkeeping")

# Agents and quality concerns from QUARE Table I. The tuple order is only the
# canonical index used to build the Williams design; it is never a speaking order.
AGENTS = (
    "SafetyAgent",
    "EfficiencyAgent",
    "GreenAgent",
    "TrustworthinessAgent",
    "ResponsibilityAgent",
)
AGENT_PREFIX = {
    "SafetyAgent": "SAF",
    "EfficiencyAgent": "EFF",
    "GreenAgent": "GRN",
    "TrustworthinessAgent": "TRU",
    "ResponsibilityAgent": "RES",
}
AGENT_CONCERN = {
    "SafetyAgent": (
        "Safety & Reliability",
        "hazard identification and mitigation, fault tolerance, safe degradation",
    ),
    "EfficiencyAgent": (
        "Performance Efficiency",
        "resource optimization, latency, throughput, responsiveness",
    ),
    "GreenAgent": (
        "Sustainability",
        "energy efficiency, carbon footprint, lifecycle resource impact",
    ),
    "TrustworthinessAgent": (
        "Security & Privacy",
        "data protection, access control, integrity, auditability",
    ),
    "ResponsibilityAgent": (
        "Ethical & Compliance",
        "regulatory compliance, accountability, fairness, social responsibility",
    ),
}

# Every agent produces exactly this many Phase 1 requirements, so that the speaking
# order is the only asymmetry between agents (QUARE reports 35 = 5 x 7).
REQS_PER_AGENT = 7

# QUARE caps negotiation at 3 rounds (Section III-C).
MAX_ROUNDS = 3

REPLICAS = 5
PHASE1_SEED = 7

# Output token caps per call kind. A truncated answer is treated as an error.
MAX_TOKENS = {
    "ping": 20,
    "phase1": 1500,
    "turn": 800,
    "synthesis": 4500,
}

# USD per 1M tokens for gpt-4o-mini (check https://platform.openai.com/docs/pricing).
PRICE_INPUT = 0.15
PRICE_CACHED_INPUT = 0.075
PRICE_OUTPUT = 0.60

# Hard spending cap enforced by the client, below the US$ 10 of credit.
DEFAULT_BUDGET_USD = 8.0

# Runner stops after this many failed runs in total.
MAX_FAILED_RUNS = 3

REQUEST_TIMEOUT_SECONDS = 90
MAX_ATTEMPTS = 3
