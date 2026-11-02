"""Frozen Phase 1, sequential debate (Phase 2) and orchestrator synthesis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quare_ordem import config, prompts
from quare_ordem.design import RunSpec
from quare_ordem.llm import InvalidResponse, LLMClient

KAOS_LEVELS = {"strategic", "tactical", "operational"}
CONFLICT_TYPES = {"resource", "logical", "redundant"}
STANCES = {"support", "oppose", "modify"}
OUTCOMES = {"merged", "decomposed", "favored", "unresolved"}

# Phase 1 is retried with a new seed when the answer does not have exactly
# REQS_PER_AGENT usable items.
PHASE1_ATTEMPTS = 3

# The synthesis must account for every initial requirement (kept or dropped). Up to this
# many silent omissions are tolerated and recorded; more triggers a retry with a new seed.
MAX_UNACCOUNTED = 3
SYNTHESIS_ATTEMPTS = 5


def load_case(name: str) -> dict[str, Any]:
    return json.loads((config.CASES_DIR / f"{name}_input.json").read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Phase 1 (generated once per case, then frozen)
# ---------------------------------------------------------------------------


def ensure_phase1(case_name: str, client: LLMClient, out_dir: Path) -> dict[str, list[dict[str, Any]]]:
    path = out_dir / "phase1" / f"{case_name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["requirements"]

    case = load_case(case_name)
    requirements: dict[str, list[dict[str, Any]]] = {}
    for agent in config.AGENTS:
        requirements[agent] = _phase1_for_agent(case, agent, client)

    _write_json(
        path,
        {
            "case": case_name,
            "model": client.model,
            "temperature": client.temperature,
            "created": datetime.now(timezone.utc).isoformat(),
            "requirements": requirements,
        },
    )
    return requirements


def _phase1_for_agent(case: dict[str, Any], agent: str, client: LLMClient) -> list[dict[str, Any]]:
    prefix = config.AGENT_PREFIX[agent]
    last_error = ""
    for attempt in range(PHASE1_ATTEMPTS):
        raw = client.complete(
            kind="phase1",
            messages=prompts.phase1_messages(case, agent),
            seed=config.PHASE1_SEED + attempt,
            meta={"agent": agent, "n": config.REQS_PER_AGENT},
            run_id=f"phase1-{case['case_name']}",
        )
        items = [
            item
            for item in raw.get("requirements", [])
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]
        if len(items) < config.REQS_PER_AGENT:
            last_error = f"{agent} devolveu {len(items)} requisitos"
            continue
        return [
            {
                "id": f"{prefix}-{index + 1:02d}",
                "agent": agent,
                "text": str(item["text"]).strip(),
                "kaos_level": str(item.get("kaos_level", "")).strip().lower()
                if str(item.get("kaos_level", "")).strip().lower() in KAOS_LEVELS
                else "operational",
                "rationale": str(item.get("rationale", "")).strip(),
            }
            for index, item in enumerate(items[: config.REQS_PER_AGENT])
        ]
    raise InvalidResponse(f"Fase 1 falhou após {PHASE1_ATTEMPTS} tentativas: {last_error}")


# ---------------------------------------------------------------------------
# Debate and synthesis
# ---------------------------------------------------------------------------


def _id_list(value: Any, known: set[str], unknown: list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item).strip()
        if text in known:
            result.append(text)
        elif text:
            unknown.append(text)
    return result


def normalize_turn(raw: dict[str, Any], known: set[str]) -> dict[str, Any]:
    unknown: list[str] = []
    conflicts = []
    for item in raw.get("conflicts_raised", []) or []:
        if not isinstance(item, dict):
            continue
        ids = _id_list(item.get("ids"), known, unknown)
        if not ids:
            continue
        kind = str(item.get("type", "")).strip().lower()
        conflicts.append(
            {
                "ids": ids,
                "type": kind if kind in CONFLICT_TYPES else "unspecified",
                "description": str(item.get("description", "")).strip(),
            }
        )
    positions = []
    for item in raw.get("positions", []) or []:
        if not isinstance(item, dict):
            continue
        ids = _id_list([item.get("id")], known, unknown)
        if not ids:
            continue
        stance = str(item.get("stance", "")).strip().lower()
        positions.append(
            {
                "id": ids[0],
                "stance": stance if stance in STANCES else "unspecified",
                "proposal": str(item.get("proposal", "")).strip(),
            }
        )
    statement = str(raw.get("statement", "")).strip()
    if not statement:
        raise InvalidResponse("turno sem 'statement'")
    return {
        "statement": statement,
        "conflicts_raised": conflicts,
        "positions": positions,
        "concessions": _id_list(raw.get("concessions"), known, unknown),
        "agree_to_close": raw.get("agree_to_close") is True,
        "unknown_ids": unknown,
    }


def normalize_synthesis(raw: dict[str, Any], known: set[str]) -> dict[str, Any]:
    unknown: list[str] = []
    requirements = []
    for index, item in enumerate(raw.get("requirements", []) or []):
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        level = str(item.get("kaos_level", "")).strip().lower()
        parent = item.get("parent")
        requirements.append(
            {
                "id": str(item.get("id") or f"F-{index + 1:02d}").strip(),
                "text": str(item["text"]).strip(),
                "quality_axes": [str(axis) for axis in item.get("quality_axes", []) or []],
                "derived_from": _id_list(item.get("derived_from"), known, unknown),
                "kaos_level": level if level in KAOS_LEVELS else "unspecified",
                "parent": str(parent).strip() if parent not in (None, "", "null") else None,
            }
        )
    if not requirements:
        raise InvalidResponse("síntese sem requisitos finais")

    resolutions = []
    for item in raw.get("conflict_resolutions", []) or []:
        if not isinstance(item, dict):
            continue
        outcome = str(item.get("outcome", "")).strip().lower()
        favored = item.get("favored_agent")
        resolutions.append(
            {
                "ids": _id_list(item.get("ids"), known, unknown),
                "outcome": outcome if outcome in OUTCOMES else "unspecified",
                "favored_agent": favored if favored in config.AGENTS else None,
                "rationale": str(item.get("rationale", "")).strip(),
            }
        )
    dropped = []
    for item in raw.get("dropped", []) or []:
        if isinstance(item, dict):
            ids = _id_list([item.get("id")], known, unknown)
            if ids:
                dropped.append({"id": ids[0], "reason": str(item.get("reason", "")).strip()})

    # Reconcile the per-ID "decisions" ledger with derived_from / dropped.
    by_final = {req["id"]: req for req in requirements}
    for item in raw.get("decisions", []) or []:
        if not isinstance(item, dict):
            continue
        ids = _id_list([item.get("id")], known, unknown)
        if not ids:
            continue
        fate = str(item.get("fate", "")).strip().lower()
        target = by_final.get(str(item.get("final") or "").strip())
        if fate == "kept" and target is not None and ids[0] not in target["derived_from"]:
            target["derived_from"].append(ids[0])
        elif fate == "dropped" and ids[0] not in {d["id"] for d in dropped}:
            dropped.append({"id": ids[0], "reason": ""})
    derived = {item for req in requirements for item in req["derived_from"]}
    dropped = [d for d in dropped if d["id"] not in derived]
    unaccounted = sorted(known - derived - {d["id"] for d in dropped})
    if len(unaccounted) > MAX_UNACCOUNTED:
        raise InvalidResponse(f"síntese omitiu {len(unaccounted)} requisitos iniciais")
    return {
        "requirements": requirements,
        "conflict_resolutions": resolutions,
        "dropped": dropped,
        "unaccounted": unaccounted,
        "unknown_ids": unknown,
    }


def run_debate(
    spec: RunSpec,
    phase1: dict[str, list[dict[str, Any]]],
    client: LLMClient,
) -> dict[str, Any]:
    case = load_case(spec.case)
    known = {item["id"] for items in phase1.values() for item in items}
    all_ids = [item["id"] for agent in config.AGENTS for item in phase1[agent]]
    started = datetime.now(timezone.utc).isoformat()
    spend_before = client.ledger.total_usd

    transcript: list[dict[str, Any]] = []
    closed_early = False
    for round_number in range(1, config.MAX_ROUNDS + 1):
        votes = []
        for position, agent in enumerate(spec.order, start=1):
            own_ids = [item["id"] for item in phase1[agent]]
            raw = client.complete(
                kind="turn",
                messages=prompts.turn_messages(
                    case=case,
                    phase1=phase1,
                    transcript=transcript,
                    agent=agent,
                    round_number=round_number,
                ),
                seed=spec.seed,
                meta={
                    "agent": agent,
                    "round": round_number,
                    "own_ids": own_ids,
                    "other_ids": [item for item in all_ids if item not in own_ids],
                },
                run_id=spec.run_id,
            )
            turn = normalize_turn(raw, known)
            turn.update({"round": round_number, "position": position, "agent": agent})
            transcript.append(turn)
            votes.append(turn["agree_to_close"])
        # Early stop only from round 2 on, so every agent hears every other at least once.
        if round_number >= 2 and all(votes):
            closed_early = round_number < config.MAX_ROUNDS
            break

    synthesis = synthesize(
        case=case, phase1=phase1, transcript=transcript, client=client,
        seed=spec.seed, order=spec.order, run_id=spec.run_id,
    )

    return {
        "run_id": spec.run_id,
        "case": spec.case,
        "order_index": spec.order_index,
        "order": list(spec.order),
        "replica": spec.replica,
        "seed": spec.seed,
        "model": client.model,
        "temperature": client.temperature,
        "backend": client.backend.name,
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "rounds_played": transcript[-1]["round"],
        "closed_early": closed_early,
        "cost_usd": round(client.ledger.total_usd - spend_before, 6),
        "transcript": transcript,
        "synthesis": synthesis,
    }


def synthesize(
    *,
    case: dict[str, Any],
    phase1: dict[str, list[dict[str, Any]]],
    transcript: list[dict[str, Any]],
    client: LLMClient,
    seed: int,
    order: tuple[str, ...] | list[str],
    run_id: str,
    agents: tuple[str, ...] = config.AGENTS,
) -> dict[str, Any]:
    """Orchestrator synthesis; `agents` is the order in which initial requirements are listed."""
    known = {item["id"] for items in phase1.values() for item in items}
    all_ids = [item["id"] for agent in agents for item in phase1[agent]]
    for attempt in range(SYNTHESIS_ATTEMPTS):
        raw_synthesis = client.complete(
            kind="synthesis",
            messages=prompts.synthesis_messages(
                case=case, phase1=phase1, transcript=transcript, agents=agents
            ),
            seed=seed + 1_000_000 * attempt,
            meta={"all_ids": all_ids, "order": list(order)},
            run_id=run_id,
        )
        try:
            synthesis = normalize_synthesis(raw_synthesis, known)
            break
        except InvalidResponse:
            if attempt == SYNTHESIS_ATTEMPTS - 1:
                raise
    synthesis["attempts"] = attempt + 1
    return synthesis


def result_path(out_dir: Path, spec: RunSpec) -> Path:
    return out_dir / "results" / f"{spec.run_id}.json"


def save_result(out_dir: Path, spec: RunSpec, result: dict[str, Any]) -> None:
    _write_json(result_path(out_dir, spec), result)
