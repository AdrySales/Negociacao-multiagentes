"""Metrics and statistics for the speaking-order experiment. Reads saved runs; no API calls.

Discussion metrics: conflict agenda (Jaccard), who raises each conflict first, how much of the
agenda involves each agent's requirements, concessions.
Outcome metrics: survival of each agent's Phase 1 requirements by speaking position, share of the
final set, distance between final sets (traceability Jaccard and text similarity with optimal
one-to-one matching).
Statistics: PERMANOVA per case (between-order vs within-order variation), logistic regression of
requirement survival on position with run-clustered errors, Holm correction.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.optimize import linear_sum_assignment
from statsmodels.genmod.families import Binomial

from quare_ordem import config

PERMUTATION_SEED = 20261101
SHORT = {agent: config.AGENT_PREFIX[agent] for agent in config.AGENTS}


# ---------------------------------------------------------------------------
# Loading and per-run features
# ---------------------------------------------------------------------------


def load_runs(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Return the saved results and, per case, a map initial ID -> owning agent."""
    results = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run_dir / "results").glob("*.json"))
    ]
    owners: dict[str, dict[str, str]] = {}
    for path in sorted((run_dir / "phase1").glob("*.json")):
        phase1 = json.loads(path.read_text(encoding="utf-8"))
        owners[phase1["case"]] = {
            item["id"]: agent for agent, items in phase1["requirements"].items() for item in items
        }
    return results, owners


def kept_ids(result: dict[str, Any]) -> set[str]:
    return {item for req in result["synthesis"]["requirements"] for item in req["derived_from"]}


def conflict_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    """First appearance of every conflicting pair of initial requirements."""
    seen: dict[frozenset[str], dict[str, Any]] = {}
    for turn_index, turn in enumerate(result["transcript"], start=1):
        for conflict in turn["conflicts_raised"]:
            for pair in itertools.combinations(sorted(set(conflict["ids"])), 2):
                key = frozenset(pair)
                if key not in seen:
                    seen[key] = {
                        "pair": "|".join(pair),
                        "first_turn": turn_index,
                        "first_round": turn["round"],
                        "raiser": turn["agent"],
                        "raiser_position": turn["position"],
                        "type": conflict["type"],
                    }
    return list(seen.values())


def build_tables(
    results: list[dict[str, Any]], owners: dict[str, dict[str, str]]
) -> dict[str, pd.DataFrame]:
    run_rows, agent_rows, req_rows, conflict_rows = [], [], [], []
    for result in results:
        base = {
            "run_id": result["run_id"],
            "case": result["case"],
            "order_index": result["order_index"],
            "replica": result["replica"],
        }
        owner = owners[result["case"]]
        position = {agent: index for index, agent in enumerate(result["order"], start=1)}
        kept = kept_ids(result)
        unaccounted = set(result["synthesis"].get("unaccounted", []))
        finals = result["synthesis"]["requirements"]
        events = conflict_events(result)
        for event in events:
            conflict_rows.append({**base, **event})

        involvement = Counter()
        for event in events:
            for agent in {owner[item] for item in event["pair"].split("|")}:
                involvement[agent] += 1
        concessions = Counter()
        for turn in result["transcript"]:
            concessions[turn["agent"]] += len(turn["concessions"])
        first_raised = Counter(event["raiser"] for event in events)

        for agent in config.AGENTS:
            own = [item for item, who in owner.items() if who == agent]
            own_kept = [item for item in own if item in kept]
            agent_rows.append(
                {
                    **base,
                    "agent": agent,
                    "position": position[agent],
                    "initial": len(own),
                    "kept": len(own_kept),
                    "survival": len(own_kept) / len(own) if own else math.nan,
                    "final_share": (
                        sum(any(owner.get(i) == agent for i in req["derived_from"]) for req in finals)
                        / len(finals)
                    ),
                    "agenda_share": involvement[agent] / len(events) if events else math.nan,
                    "conflicts_first_raised": first_raised[agent],
                    "concessions": concessions[agent],
                }
            )
            for item in own:
                req_rows.append(
                    {
                        **base,
                        "req_id": item,
                        "agent": agent,
                        "position": position[agent],
                        "kept": int(item in kept),
                        "unaccounted": int(item in unaccounted),
                    }
                )

        first = min(events, key=lambda event: event["first_turn"]) if events else None
        run_rows.append(
            {
                **base,
                "order": "-".join(SHORT[agent] for agent in result["order"]),
                "rounds_played": result["rounds_played"],
                "closed_early": result["closed_early"],
                "n_final": len(finals),
                "n_kept_initial": len(kept),
                "n_dropped": len(result["synthesis"]["dropped"]),
                "n_unaccounted": len(unaccounted),
                "n_conflicts": len(events),
                "first_conflict_raiser_position": first["raiser_position"] if first else None,
                "synthesis_attempts": result["synthesis"].get("attempts", 1),
                "cost_usd": result["cost_usd"],
            }
        )
    return {
        "runs": pd.DataFrame(run_rows),
        "agents": pd.DataFrame(agent_rows),
        "requirements": pd.DataFrame(req_rows),
        "conflicts": pd.DataFrame(conflict_rows),
    }


# ---------------------------------------------------------------------------
# Distances between runs of the same case
# ---------------------------------------------------------------------------


def jaccard_distance(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return 1.0 - len(a & b) / len(a | b)


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by during for from in into is it its of on or shall should system "
    "that the their this to with within".split()
)


def _tfidf(texts: list[str]) -> np.ndarray:
    docs = [[t for t in _TOKEN.findall(text.lower()) if t not in _STOP] for text in texts]
    vocab = {term: i for i, term in enumerate(sorted({t for doc in docs for t in doc}))}
    counts = np.zeros((len(docs), len(vocab)))
    for row, doc in enumerate(docs):
        for term in doc:
            counts[row, vocab[term]] += 1
    df = (counts > 0).sum(axis=0)
    idf = np.log((1 + len(docs)) / (1 + df)) + 1
    weights = counts * idf
    norms = np.linalg.norm(weights, axis=1, keepdims=True)
    return weights / np.where(norms == 0, 1, norms)


def matched_text_distance(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """1 - (sum of similarities under the optimal one-to-one matching) / larger set size.

    Unmatched requirements count as similarity 0, so sets of different sizes are penalised.
    """
    similarity = vec_a @ vec_b.T
    rows, cols = linear_sum_assignment(-similarity)
    return 1.0 - similarity[rows, cols].sum() / max(len(vec_a), len(vec_b))


def case_distances(case_results: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    n = len(case_results)
    agendas = [{e["pair"] for e in conflict_events(r)} for r in case_results]
    traces = [kept_ids(r) for r in case_results]
    texts = [[req["text"] for req in r["synthesis"]["requirements"]] for r in case_results]
    vectors = _tfidf([t for group in texts for t in group])
    offsets = np.cumsum([0] + [len(group) for group in texts])
    blocks = [vectors[offsets[i] : offsets[i + 1]] for i in range(n)]

    out = {name: np.zeros((n, n)) for name in ("agenda", "traceability", "text")}
    for i, j in itertools.combinations(range(n), 2):
        values = {
            "agenda": jaccard_distance(agendas[i], agendas[j]),
            "traceability": jaccard_distance(traces[i], traces[j]),
            "text": matched_text_distance(blocks[i], blocks[j]),
        }
        for name, value in values.items():
            out[name][i, j] = out[name][j, i] = value
    return out


def permanova(distance: np.ndarray, groups: list[Any], permutations: int, seed: int) -> dict[str, float]:
    """One-way PERMANOVA (Anderson 2001): pseudo-F, permutation p-value and R^2."""
    labels = np.asarray(groups)
    n = len(labels)
    squared = distance**2
    total = squared[np.triu_indices(n, 1)].sum() / n

    def within(lab: np.ndarray) -> float:
        value = 0.0
        for group in np.unique(lab):
            idx = np.flatnonzero(lab == group)
            if len(idx) > 1:
                value += squared[np.ix_(idx, idx)][np.triu_indices(len(idx), 1)].sum() / len(idx)
        return value

    a = len(np.unique(labels))
    if a < 2 or n - a < 1 or total == 0:
        return {"pseudo_F": math.nan, "p": math.nan, "R2": math.nan}

    def pseudo_f(lab: np.ndarray) -> float:
        ssw = within(lab)
        return ((total - ssw) / (a - 1)) / (ssw / (n - a)) if ssw > 0 else math.inf

    observed = pseudo_f(labels)
    rng = np.random.default_rng(seed)
    hits = sum(pseudo_f(rng.permutation(labels)) >= observed for _ in range(permutations))
    return {
        "pseudo_F": observed,
        "p": (hits + 1) / (permutations + 1),
        "R2": (total - within(labels)) / total,
    }


def mean_within_between(distance: np.ndarray, groups: list[Any]) -> tuple[float, float]:
    labels = np.asarray(groups)
    same = labels[:, None] == labels[None, :]
    upper = np.triu(np.ones_like(distance, dtype=bool), 1)
    within = distance[upper & same]
    between = distance[upper & ~same]
    return (
        float(within.mean()) if within.size else math.nan,
        float(between.mean()) if between.size else math.nan,
    )


# ---------------------------------------------------------------------------
# Position effects
# ---------------------------------------------------------------------------


def _clustered_logit(formula: str, data: pd.DataFrame):
    groups = pd.factorize(data["run_id"])[0]
    return smf.glm(formula, data=data, family=Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": groups}
    )


def position_tests(requirements: pd.DataFrame) -> list[dict[str, Any]]:
    """Survival of each Phase 1 requirement vs. its owner's speaking position.

    Controls: agent and case fixed effects; standard errors clustered by run.
    H0 (robustness): position coefficients jointly zero.
    H1 (primacy): first position survives more than the middle positions 2-4 (one-sided).
    H2 (U-shape): the last position also survives more than the middle (one-sided); together
    with H1 this is the U. A quadratic term is not used because a linear decline in probability
    is already curved on the log-odds scale and would read as a spurious U.
    """
    data = requirements[requirements["unaccounted"] == 0].copy()
    if data["run_id"].nunique() < 2 or data["position"].nunique() < 2 or data["kept"].nunique() < 2:
        return []
    last = int(data["position"].max())
    data["first"] = (data["position"] == 1).astype(int)
    data["last"] = (data["position"] == last).astype(int)
    controls = "C(agent) + C(case)" if data["case"].nunique() > 1 else "C(agent)"

    def one_sided(fit, name: str) -> float:
        return float(fit.pvalues[name] / 2 if fit.tvalues[name] > 0 else 1 - fit.pvalues[name] / 2)

    tests = []
    try:
        full = _clustered_logit(f"kept ~ C(position) + {controls}", data)
        names = [name for name in full.params.index if name.startswith("C(position)")]
        wald = full.wald_test(" , ".join(f"{name} = 0" for name in names), scalar=True)
        tests.append({"test": "H0: posição não afeta a sobrevivência (Wald conjunto)",
                      "estimate": math.nan, "statistic": float(wald.statistic),
                      "p": float(wald.pvalue)})

        ends = _clustered_logit(f"kept ~ first + last + {controls}", data)
        tests.append({"test": "H1: 1ª posição sobrevive mais que as do meio (log-odds, unilateral)",
                      "estimate": float(ends.params["first"]), "statistic": float(ends.tvalues["first"]),
                      "p": one_sided(ends, "first")})
        tests.append({"test": "H2: última posição sobrevive mais que as do meio (log-odds, unilateral)",
                      "estimate": float(ends.params["last"]), "statistic": float(ends.tvalues["last"]),
                      "p": one_sided(ends, "last")})
    except (ValueError, np.linalg.LinAlgError) as exc:  # e.g. perfect separation on tiny data
        tests.append({"test": f"regressão não estimável: {exc}", "estimate": math.nan,
                      "statistic": math.nan, "p": math.nan})
    return tests


def agenda_tests(agents: pd.DataFrame) -> list[dict[str, Any]]:
    """Share of the conflict agenda involving each agent's requirements vs. speaking position.

    Linear model with agent and case fixed effects, errors clustered by run; runs without any
    conflict are excluded (the share is undefined there).
    """
    data = agents.dropna(subset=["agenda_share"])
    if data["run_id"].nunique() < 2 or data["position"].nunique() < 2:
        return []
    controls = "C(agent) + C(case)" if data["case"].nunique() > 1 else "C(agent)"
    groups = pd.factorize(data["run_id"])[0]
    fit = smf.ols(f"agenda_share ~ position + {controls}", data=data).fit(
        cov_type="cluster", cov_kwds={"groups": groups}
    )
    return [{"test": "Pauta: fatia da pauta muda com a posição (inclinação por posição)",
             "estimate": float(fit.params["position"]), "statistic": float(fit.tvalues["position"]),
             "p": float(fit.pvalues["position"])}]


def holm(pvalues: list[float]) -> list[float]:
    valid = [(p, i) for i, p in enumerate(pvalues) if not math.isnan(p)]
    adjusted = [math.nan] * len(pvalues)
    running = 0.0
    for rank, (p, index) in enumerate(sorted(valid)):
        running = max(running, min(1.0, (len(valid) - rank) * p))
        adjusted[index] = running
    return adjusted


def listing_analysis(run_dir: Path, original_dir: Path) -> Path:
    """Survival vs. the position of the owner's block in the requirement listing (cli `lista`).

    The listing rotation separates list position from agent identity, which the main
    experiment could not (the listing order was fixed). Logistic and linear probability models
    with agent, case and speaking-position fixed effects; errors clustered by run.
    """
    results, _ = load_runs(run_dir)
    if not results:
        raise FileNotFoundError(f"nenhum resultado em {run_dir / 'results'}")
    _, owners = load_runs(original_dir)  # the frozen Phase 1 lives with the original runs
    out_dir = run_dir / "analise"
    out_dir.mkdir(parents=True, exist_ok=True)
    requirements = build_tables(results, owners)["requirements"]
    listing = {r["run_id"]: r["listing_order"] for r in results}
    requirements["list_pos"] = [listing[run].index(agent) + 1
                                for run, agent in zip(requirements["run_id"], requirements["agent"])]
    requirements.to_csv(out_dir / "requirements.csv", index=False, encoding="utf-8")
    data = requirements[requirements["unaccounted"] == 0].copy()
    controls = "C(agent) + C(case) + C(position)"

    rows = []
    full = _clustered_logit(f"kept ~ C(list_pos) + {controls}", data)
    names = [n for n in full.params.index if n.startswith("C(list_pos)")]
    wald = full.wald_test(" , ".join(f"{n} = 0" for n in names), scalar=True)
    rows.append({"test": "posição na lista não afeta a sobrevivência (Wald conjunto)",
                 "estimate": math.nan, "statistic": float(wald.statistic), "p": float(wald.pvalue)})
    agent_names = [n for n in full.params.index if n.startswith("C(agent)")]
    wald = full.wald_test(" , ".join(f"{n} = 0" for n in agent_names), scalar=True)
    rows.append({"test": "agente não afeta a sobrevivência, dada a posição na lista (Wald conjunto)",
                 "estimate": math.nan, "statistic": float(wald.statistic), "p": float(wald.pvalue)})
    groups = pd.factorize(data["run_id"])[0]
    lpm = smf.ols(f"kept ~ C(list_pos) + {controls}", data=data).fit(
        cov_type="cluster", cov_kwds={"groups": groups})
    for name in [n for n in lpm.params.index if n.startswith("C(list_pos)")]:
        low, high = lpm.conf_int().loc[name]
        rows.append({"test": f"lista {name[-2]}ª vs 1ª (pontos percentuais, IC 95% "
                             f"{100 * low:.1f} a {100 * high:.1f})",
                     "estimate": 100 * float(lpm.params[name]), "statistic": float(lpm.tvalues[name]),
                     "p": float(lpm.pvalues[name])})
    tests = pd.DataFrame(rows)
    tests.to_csv(out_dir / "tests.csv", index=False, encoding="utf-8")

    original = pd.read_csv(original_dir / "analise" / "requirements.csv")
    by_agent = pd.DataFrame({
        "original (lista fixa)": original.groupby("agent")["kept"].mean(),
        "lista girada": data.groupby("agent")["kept"].mean(),
    }).reindex(list(config.AGENTS))
    by_list = data.pivot_table(index="agent", columns="list_pos", values="kept").reindex(
        list(config.AGENTS))
    by_list.columns = [f"lista {c}ª" for c in by_list.columns]
    lines = [
        f"# Experimento da lista girada ({len(results)} sínteses refeitas)", "",
        "## Sobrevivência por agente", "", _md_table(by_agent.reset_index()), "",
        "## Sobrevivência por posição na lista (todos os agentes)", "",
        _md_table(data.groupby("list_pos")["kept"].mean().rename("sobrevivência").reset_index()), "",
        "## Sobrevivência por agente e posição na lista", "", _md_table(by_list.reset_index()), "",
        "## Testes", "", _md_table(tests), "",
    ]
    report = out_dir / "resumo.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def analyze(run_dir: Path, permutations: int = 999) -> Path:
    results, owners = load_runs(run_dir)
    if not results:
        raise FileNotFoundError(f"nenhum resultado em {run_dir / 'results'}")
    out_dir = run_dir / "analise"
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = build_tables(results, owners)
    for name, frame in tables.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8")

    family: list[dict[str, Any]] = []
    distance_rows = []
    for case in sorted({r["case"] for r in results}):
        case_results = [r for r in results if r["case"] == case]
        groups = [r["order_index"] for r in case_results]
        for metric, matrix in case_distances(case_results).items():
            within, between = mean_within_between(matrix, groups)
            stats = permanova(matrix, groups, permutations, PERMUTATION_SEED)
            distance_rows.append({"case": case, "metric": metric, "runs": len(case_results),
                                  "mean_within_order": within, "mean_between_orders": between,
                                  **stats})
            family.append({"test": f"PERMANOVA {case} / {metric}", "estimate": stats["R2"],
                           "statistic": stats["pseudo_F"], "p": stats["p"]})
    family.extend(position_tests(tables["requirements"]))
    family.extend(agenda_tests(tables["agents"]))
    for row, adjusted in zip(family, holm([row["p"] for row in family])):
        row["p_holm"] = adjusted
    distances = pd.DataFrame(distance_rows)
    tests = pd.DataFrame(family)
    distances.to_csv(out_dir / "distances.csv", index=False, encoding="utf-8")
    tests.to_csv(out_dir / "tests.csv", index=False, encoding="utf-8")

    report = out_dir / "resumo.md"
    report.write_text(_report(tables, distances, tests, len(results)), encoding="utf-8")
    return report


def _fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, float):
        return "—" if math.isnan(value) else f"{value:.{digits}f}"
    return str(value)


def _md_table(frame: pd.DataFrame, digits: int = 3) -> str:
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "|".join("---" for _ in frame.columns) + "|"
    rows = ["| " + " | ".join(_fmt(v, digits) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, rule, *rows])


def _report(tables: dict[str, pd.DataFrame], distances: pd.DataFrame, tests: pd.DataFrame, n: int) -> str:
    runs, agents, conflicts = tables["runs"], tables["agents"], tables["conflicts"]
    by_position = (
        agents.groupby("position")[["survival", "final_share", "agenda_share", "conflicts_first_raised", "concessions"]]
        .mean()
        .reset_index()
        .rename(columns={"position": "posição", "survival": "sobrevivência", "final_share": "participação final",
                         "agenda_share": "fatia da pauta", "conflicts_first_raised": "conflitos que abriu",
                         "concessions": "concessões"})
    )
    by_case = agents.pivot_table(index="case", columns="position", values="survival", aggfunc="mean").reset_index()
    by_case.columns = ["caso", *[f"pos {c}" for c in by_case.columns[1:]]]
    by_agent = agents.pivot_table(index="agent", columns="position", values="survival", aggfunc="mean").reset_index()
    by_agent.columns = ["agente", *[f"pos {c}" for c in by_agent.columns[1:]]]
    raiser = (
        conflicts["raiser_position"].value_counts(normalize=True).sort_index().rename("fração").reset_index()
        .rename(columns={"raiser_position": "posição de quem abriu"})
        if not conflicts.empty else pd.DataFrame()
    )
    first_conflict = runs["first_conflict_raiser_position"].value_counts().sort_index()
    lines = [
        "# Resumo da análise",
        "",
        f"Execuções analisadas: **{n}**. Gasto somado dos resultados: US$ {runs['cost_usd'].sum():.4f}. "
        f"Rodadas jogadas (média): {runs['rounds_played'].mean():.2f}. Encerramento antecipado: "
        f"{int(runs['closed_early'].sum())}. Requisitos finais por execução (média): {runs['n_final'].mean():.1f}. "
        f"Requisitos omitidos pela síntese (média): {runs['n_unaccounted'].mean():.2f}. "
        f"Sínteses refeitas: {int((runs['synthesis_attempts'] > 1).sum())}.",
        "",
        "## 1. Efeito de posição (todas as execuções)",
        "",
        "Médias por posição de fala. *Sobrevivência*: fração dos 7 requisitos do agente que chegam ao "
        "resultado final. *Participação final*: fração dos requisitos finais derivados do agente. "
        "*Fatia da pauta*: fração dos conflitos que envolvem requisitos do agente.",
        "",
        _md_table(by_position),
        "",
        "### Sobrevivência por caso e posição",
        "",
        _md_table(by_case),
        "",
        "### Sobrevivência por agente e posição",
        "",
        _md_table(by_agent),
        "",
        "## 2. Quem pauta a discussão",
        "",
        "Posição de quem levantou primeiro cada conflito (fração de todos os conflitos):",
        "",
        _md_table(raiser) if not raiser.empty else "(sem conflitos)",
        "",
        "Posição de quem levantou o primeiro conflito de cada execução: "
        + ", ".join(f"pos {int(k)}: {v}" for k, v in first_conflict.items())
        + " (é esperado que seja quase sempre a posição 1, que fala antes; o indicador de pauta "
        "que importa é a *fatia da pauta* por posição, na seção 1).",
        "",
        "## 3. Quanto discussão e resultado mudam entre ordens",
        "",
        "Distâncias de 0 (idênticos) a 1. Se a ordem importa, a distância entre ordens diferentes supera a "
        "distância entre réplicas da mesma ordem (ruído do modelo). R² = fração da variação explicada pela ordem.",
        "",
        _md_table(distances.rename(columns={"case": "caso", "metric": "métrica", "runs": "execuções",
                                            "mean_within_order": "dist. mesma ordem",
                                            "mean_between_orders": "dist. ordens diferentes"})),
        "",
        "## 4. Testes (com correção de Holm sobre a família inteira)",
        "",
        _md_table(tests.rename(columns={"test": "teste", "estimate": "estimativa", "statistic": "estatística",
                                        "p_holm": "p (Holm)"}), digits=4),
        "",
    ]
    return "\n".join(lines)
