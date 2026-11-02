"""Prompt builders.

Design constraints:
- Phase 1 requirements are always listed in the canonical agent order, so the
  speaking order is the only thing that differs between conditions.
- Agents are never told their speaking position.
- Debate messages are laid out as [shared system][shared context + transcript]
  [turn instruction], so consecutive turns share a growing prefix and benefit
  from OpenAI prompt caching.
"""

from __future__ import annotations

import json
from typing import Any

from quare_ordem import config

PHASE1_SYSTEM = (
    "You are {agent}, a quality-specialized requirements engineering agent in QUARE, "
    "a multi-agent framework for quality-aware requirements analysis. Your quality "
    "dimension is {concern_name}: {concern_scope}. You analyse project descriptions "
    "exclusively from this quality perspective and prioritise concerns that, if missed, "
    "would compromise {concern_name}. Always answer with a single JSON object."
)

PHASE1_USER = """PROJECT: {case_name} - {case_description}

PROJECT DESCRIPTION:
{requirement}

TASK: Think step by step. (1) Analyse the project description. (2) Identify the concerns
relevant to your quality dimension. (3) Formulate exactly {n} requirements that address them.
Each requirement must be a single "shall" statement with a measurable acceptance criterion
where possible (at most 40 words). Use KAOS levels: "strategic" (high-level objective),
"tactical" (system-level function) or "operational" (implementable action).

Return JSON: {{"requirements": [{{"text": "...", "kaos_level": "strategic|tactical|operational",
"rationale": "one sentence"}}]}} with exactly {n} items."""

DEBATE_SYSTEM = """You take part in QUARE Phase 2, a dialectical negotiation among five quality-specialized
agents (SafetyAgent, EfficiencyAgent, GreenAgent, TrustworthinessAgent, ResponsibilityAgent)
about the initial requirements of a software project. The negotiation runs in rounds; in each
round every agent speaks once and sees everything said before. Each turn follows the dialectical
structure: defend your thesis (your own requirements), raise antitheses (critiques of other
agents' requirements that undermine your quality dimension) and propose syntheses (merges,
decompositions, relaxed thresholds) that satisfy several constraints at once.

Conflict types: "resource" (qualities compete for finite resources, e.g. redundancy vs. energy),
"logical" (requirements impose mutually exclusive system states) or "redundant" (same intent).

Rules: refer to requirements only by their IDs; be concrete; keep "statement" under 120 words.
Always answer with a single JSON object with this schema:
{"statement": "your argument",
 "conflicts_raised": [{"ids": ["ID", "ID"], "type": "resource|logical|redundant", "description": "..."}],
 "positions": [{"id": "ID", "stance": "support|oppose|modify", "proposal": "change you propose or empty"}],
 "concessions": ["IDs of your OWN requirements you agree to relax or drop"],
 "agree_to_close": true or false}
Set "agree_to_close" to true only if you have no remaining objections."""

TURN_INSTRUCTION = """YOUR TURN. You are {agent}. Your quality dimension is {concern_name}: {concern_scope}.
Your own requirements are {own_ids}. This is round {round} of at most {max_rounds}.
{round_hint}
Answer with the JSON object only."""

ROUND_HINTS = {
    1: "Present your position: defend your requirements and raise the conflicts you see.",
    "later": "Respond to what the other agents said: hold, concede or propose syntheses.",
}

SYNTHESIS_INSTRUCTION = """YOU ARE THE ORCHESTRATOR AGENT. The negotiation has ended. Integrate the outcome
into the final requirement set, organised as a KAOS goal model with three levels
(strategic, tactical, operational). Rules:
- Base every decision on the initial requirements and on the negotiation transcript above.
- Every final requirement lists in "derived_from" the IDs of the initial requirements it keeps,
  merges or refines. A final requirement may derive from several agents' requirements.
- Every initial requirement that is not represented in any "derived_from" goes into "dropped".
- Account for EVERY initial requirement: "decisions" has exactly one entry per initial ID
  ({all_ids}), with "fate" "kept" (the final requirement "final" includes it in "derived_from")
  or "dropped" ("final" is null). Do not silently omit any initial requirement.
- For every conflict raised in the negotiation, record how it was resolved: outcome is one of
  "merged", "decomposed", "favored" (one agent's constraint prevails) or "unresolved";
  "favored_agent" names the prevailing agent or is null.
- Final requirement text: one "shall" statement, at most 40 words. "parent" is the id of a
  final requirement one level above, or null for strategic goals.

Return JSON:
{"requirements": [{"id": "F-01", "text": "...", "quality_axes": ["Safety|Efficiency|Sustainability|Trustworthiness|Responsibility"],
  "derived_from": ["ID"], "kaos_level": "strategic|tactical|operational", "parent": "F-xx or null"}],
 "conflict_resolutions": [{"ids": ["ID", "ID"], "outcome": "merged|decomposed|favored|unresolved",
  "favored_agent": "AgentName or null", "rationale": "one sentence"}],
 "dropped": [{"id": "ID", "reason": "one sentence"}],
 "decisions": [{"id": "ID", "fate": "kept|dropped", "final": "F-xx or null"}]}"""


def phase1_messages(case: dict[str, Any], agent: str) -> list[dict[str, str]]:
    concern_name, concern_scope = config.AGENT_CONCERN[agent]
    return [
        {
            "role": "system",
            "content": PHASE1_SYSTEM.format(
                agent=agent, concern_name=concern_name, concern_scope=concern_scope
            ),
        },
        {
            "role": "user",
            "content": PHASE1_USER.format(
                case_name=case["case_name"],
                case_description=case["case_description"],
                requirement=case["requirement"],
                n=config.REQS_PER_AGENT,
            ),
        },
    ]


def _context_block(
    case: dict[str, Any],
    phase1: dict[str, list[dict[str, Any]]],
    agents: tuple[str, ...] = config.AGENTS,
) -> str:
    lines = [
        f"PROJECT: {case['case_name']} - {case['case_description']}",
        "",
        "PROJECT DESCRIPTION:",
        case["requirement"],
        "",
        "INITIAL REQUIREMENTS (Phase 1):",
    ]
    for agent in agents:
        lines.append(f"[{agent}]")
        for item in phase1[agent]:
            lines.append(f"{item['id']} ({item['kaos_level']}): {item['text']}")
    return "\n".join(lines)


def _format_turn(turn: dict[str, Any]) -> str:
    structured = {
        key: turn[key]
        for key in ("conflicts_raised", "positions", "concessions", "agree_to_close")
    }
    return (
        f"[Round {turn['round']}] {turn['agent']}: {turn['statement']}\n"
        f"{json.dumps(structured, ensure_ascii=False)}"
    )


def _shared_prefix(
    case: dict[str, Any],
    phase1: dict[str, list[dict[str, Any]]],
    transcript: list[dict[str, Any]],
    agents: tuple[str, ...] = config.AGENTS,
) -> list[dict[str, str]]:
    body = _context_block(case, phase1, agents) + "\n\nNEGOTIATION TRANSCRIPT SO FAR:\n"
    body += "\n\n".join(_format_turn(turn) for turn in transcript) if transcript else "(empty)"
    return [
        {"role": "system", "content": DEBATE_SYSTEM},
        {"role": "user", "content": body},
    ]


def turn_messages(
    *,
    case: dict[str, Any],
    phase1: dict[str, list[dict[str, Any]]],
    transcript: list[dict[str, Any]],
    agent: str,
    round_number: int,
) -> list[dict[str, str]]:
    concern_name, concern_scope = config.AGENT_CONCERN[agent]
    instruction = TURN_INSTRUCTION.format(
        agent=agent,
        concern_name=concern_name,
        concern_scope=concern_scope,
        own_ids=", ".join(item["id"] for item in phase1[agent]),
        round=round_number,
        max_rounds=config.MAX_ROUNDS,
        round_hint=ROUND_HINTS[1] if round_number == 1 else ROUND_HINTS["later"],
    )
    return _shared_prefix(case, phase1, transcript) + [{"role": "user", "content": instruction}]


def synthesis_messages(
    *,
    case: dict[str, Any],
    phase1: dict[str, list[dict[str, Any]]],
    transcript: list[dict[str, Any]],
    agents: tuple[str, ...] = config.AGENTS,
) -> list[dict[str, str]]:
    # Canonical agent order, identical across speaking orders; `agents` changes it only in
    # the listing-order experiment (cli `lista`).
    all_ids = ", ".join(item["id"] for agent in agents for item in phase1[agent])
    return _shared_prefix(case, phase1, transcript, agents) + [
        {"role": "user", "content": SYNTHESIS_INSTRUCTION.replace("{all_ids}", all_ids)}
    ]


def ping_messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": 'Reply with the JSON object {"ok": true} and nothing else.'}]
