"""Command line interface.

  quare-ordem ordens              mostra as 10 ordens de fala
  quare-ordem simular             experimento completo com LLM falso (grátis)
  quare-ordem checar              testa chave e modelo (custo ~US$ 0,00001)
  quare-ordem piloto              2 execuções reais no caso AD
  quare-ordem rodar [--confirmo]  experimento completo real (pede --confirmo para começar)
  quare-ordem status              gasto e progresso da execução real
  quare-ordem temp0 [--confirmo]  experimento complementar com temperatura 0 (runs/temp0)
  quare-ordem lista [--confirmo]  refaz só a síntese de runs/real com a lista de requisitos girada
  quare-ordem analisar            métricas e testes sobre runs/real (grátis; --temp0, --simulacao)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time

from quare_ordem import config
from quare_ordem.design import build_plan, speaking_orders
from quare_ordem.llm import (
    FakeBackend,
    FatalAPIError,
    InvalidResponse,
    LLMClient,
    OpenAIBackend,
    TransientAPIError,
    TruncatedResponse,
)
from quare_ordem.pipeline import result_path
from quare_ordem.runner import execute

REAL_DIR = config.RUNS_DIR / "real"
DRY_DIR = config.RUNS_DIR / "simulacao"
TEMP0_DIR = config.RUNS_DIR / "temp0"
PILOT_PLAN = dict(cases=["AD"], order_indices=[0, 5], replicas=1)

# Complementary experiment: same frozen Phase 1, same orders and seeds, debate at temperature 0.
TEMP0_PLAN = dict(cases=config.CASES, replicas=2)
TEMP0_BUDGET_USD = 1.5  # own ledger; real (~US$ 2.60) + this stays far below the US$ 10 credit

# Listing-order experiment: the debates of runs/real are kept and only the synthesis is redone,
# with the initial requirements listed in one of 5 rotations of the canonical agent order (each
# agent once in each list position). Rotation = (order_index + replica) % 5 balances rotations
# within every case and speaking order. A new seed makes rotation 0 a fresh control sample.
LISTA_DIR = config.RUNS_DIR / "lista"
LISTA_BUDGET_USD = 1.0
LISTA_SEED_OFFSET = 7_000_000


def listing_rotation(order_index: int, replica: int) -> tuple[str, ...]:
    shift = (order_index + replica) % len(config.AGENTS)
    return config.AGENTS[shift:] + config.AGENTS[:shift]


def _real_client(budget: float) -> LLMClient:
    return LLMClient(backend=OpenAIBackend(), out_dir=REAL_DIR, budget_usd=budget)


def _print_report(report, client: LLMClient) -> None:
    print()
    print(f"concluídas agora: {len(report.completed)}  já existentes: {len(report.skipped)}  "
          f"falhas: {len(report.failed)}")
    print(f"gasto nesta execução: US$ {report.spent_usd:.4f}  "
          f"gasto acumulado: US$ {client.ledger.total_usd:.4f} de US$ {client.budget_usd:.2f}")
    if report.stop_reason:
        print(f"PAROU: {report.stop_reason}")


def cmd_ordens(_: argparse.Namespace) -> int:
    for index, order in enumerate(speaking_orders()):
        print(f"o{index:02d}: " + " -> ".join(order))
    return 0


def cmd_simular(args: argparse.Namespace) -> int:
    if DRY_DIR.exists():
        shutil.rmtree(DRY_DIR)
    client = LLMClient(backend=FakeBackend(), out_dir=DRY_DIR, budget_usd=float("inf"))
    plan = build_plan()
    report = execute(plan, client, DRY_DIR, echo=(print if args.verbose else lambda *_: None))
    _print_report(report, client)
    print()
    print(f"execuções planejadas: {len(plan)}  chamadas ao LLM: {client.ledger.calls}")
    print(f"custo projetado para a rodada real (estimado pelo tamanho dos prompts): "
          f"US$ {client.ledger.total_usd:.2f}")
    print("Obs.: o LLM falso fala menos que o real; confirme o custo com o piloto.")
    return 0 if not report.failed and not report.stop_reason else 1


def cmd_checar(args: argparse.Namespace) -> int:
    from quare_ordem import prompts

    try:
        client = _real_client(args.teto)
        model_id = client.backend.check_model()
        print(f"chave OK; modelo disponível: {model_id}")
        reply = client.complete(kind="ping", messages=prompts.ping_messages(), seed=int(time.time()))
    except (FatalAPIError, TruncatedResponse, InvalidResponse, TransientAPIError) as exc:
        print(f"ERRO: {type(exc).__name__}: {exc}")
        return 1
    print(f"resposta do modelo: {reply}")
    print(f"gasto acumulado: US$ {client.ledger.total_usd:.6f}")
    return 0


def cmd_piloto(args: argparse.Namespace) -> int:
    try:
        client = _real_client(args.teto)
    except FatalAPIError as exc:
        print(f"ERRO: {exc}")
        return 1
    report = execute(build_plan(**PILOT_PLAN), client, REAL_DIR)
    _print_report(report, client)
    if report.completed or report.skipped:
        print()
        print(_estimate(client))
    return 0 if not report.failed and not report.stop_reason else 1


def _estimate(client: LLMClient) -> str:
    # Sum every paid call per pilot run from the ledger: a result file's cost_usd misses calls
    # that were served from the cache when the run was redone.
    per_run_id: dict[str, float] = {}
    ledger_path = REAL_DIR / "ledger.jsonl"
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                per_run_id[entry["run_id"]] = per_run_id.get(entry["run_id"], 0.0) + entry["cost_usd"]
    costs = [
        per_run_id[spec.run_id]
        for spec in build_plan(**PILOT_PLAN)
        if result_path(REAL_DIR, spec).exists() and spec.run_id in per_run_id
    ]
    if not costs:
        return "sem piloto concluído; rode `quare-ordem piloto` antes."
    per_run = max(costs)  # AD is the longest case, so this is conservative
    remaining = [spec for spec in build_plan() if not result_path(REAL_DIR, spec).exists()]
    projected = per_run * len(remaining) + 0.02 * len(config.CASES)
    return (
        f"custo por execução no piloto (AD, o caso mais longo): US$ {per_run:.4f}\n"
        f"execuções restantes: {len(remaining)}  projeção conservadora: US$ {projected:.2f}\n"
        f"já gasto: US$ {client.ledger.total_usd:.4f}  teto: US$ {client.budget_usd:.2f}"
    )


def cmd_rodar(args: argparse.Namespace) -> int:
    try:
        client = _real_client(args.teto)
    except FatalAPIError as exc:
        print(f"ERRO: {exc}")
        return 1
    print(_estimate(client))
    if not args.confirmo:
        print()
        print("Nada foi enviado. Para começar de fato: quare-ordem rodar --confirmo")
        return 0
    report = execute(build_plan(), client, REAL_DIR)
    _print_report(report, client)
    return 0 if not report.failed and not report.stop_reason else 1


def cmd_status(_: argparse.Namespace) -> int:
    from quare_ordem.llm import Ledger

    ledger = Ledger(REAL_DIR / "ledger.jsonl")
    plan = build_plan()
    done = sum(1 for spec in plan if result_path(REAL_DIR, spec).exists())
    failures = REAL_DIR / "failures.jsonl"
    n_failures = len(failures.read_text(encoding="utf-8").splitlines()) if failures.exists() else 0
    print(f"execuções concluídas: {done}/{len(plan)}")
    print(f"chamadas pagas: {ledger.calls}  gasto: US$ {ledger.total_usd:.4f}")
    print(f"falhas registradas: {n_failures}")
    return 0


def cmd_temp0(args: argparse.Namespace) -> int:
    phase1_src = REAL_DIR / "phase1"
    missing = [case for case in config.CASES if not (phase1_src / f"{case}.json").exists()]
    if missing:
        print(f"ERRO: falta a Fase 1 congelada da rodada principal para {missing}")
        return 1
    plan = build_plan(**TEMP0_PLAN)
    remaining = [spec for spec in plan if not result_path(TEMP0_DIR, spec).exists()]
    print(f"temperatura 0: {len(plan)} execuções ({len(remaining)} restantes), "
          f"projeção ~US$ {0.0115 * len(remaining):.2f}, teto próprio US$ {args.teto:.2f}")
    if not args.confirmo:
        print("Nada foi enviado. Para começar de fato: quare-ordem temp0 --confirmo")
        return 0
    (TEMP0_DIR / "phase1").mkdir(parents=True, exist_ok=True)
    for case in config.CASES:
        target = TEMP0_DIR / "phase1" / f"{case}.json"
        if not target.exists():
            shutil.copyfile(phase1_src / f"{case}.json", target)
    try:
        client = LLMClient(backend=OpenAIBackend(temperature=0.0), out_dir=TEMP0_DIR,
                           budget_usd=args.teto, temperature=0.0)
    except FatalAPIError as exc:
        print(f"ERRO: {exc}")
        return 1
    report = execute(plan, client, TEMP0_DIR)
    _print_report(report, client)
    return 0 if not report.failed and not report.stop_reason else 1


def cmd_lista(args: argparse.Namespace) -> int:
    from quare_ordem.llm import BudgetExceeded
    from quare_ordem.pipeline import _write_json, load_case, synthesize

    sources = sorted((REAL_DIR / "results").glob("*.json"))
    remaining = [path for path in sources if not (LISTA_DIR / "results" / path.name).exists()]
    print(f"lista girada: {len(sources)} sínteses ({len(remaining)} restantes), "
          f"projeção ~US$ {0.0025 * len(remaining):.2f}, teto próprio US$ {args.teto:.2f}")
    if not args.confirmo:
        print("Nada foi enviado. Para começar de fato: quare-ordem lista --confirmo")
        return 0
    try:
        client = LLMClient(backend=OpenAIBackend(), out_dir=LISTA_DIR, budget_usd=args.teto)
    except FatalAPIError as exc:
        print(f"ERRO: {exc}")
        return 1
    phase1 = {case: json.loads((REAL_DIR / "phase1" / f"{case}.json").read_text(encoding="utf-8"))
              ["requirements"] for case in config.CASES}
    failed = 0
    for index, path in enumerate(remaining, start=1):
        source = json.loads(path.read_text(encoding="utf-8"))
        agents = listing_rotation(source["order_index"], source["replica"])
        before = client.ledger.total_usd
        try:
            synthesis = synthesize(
                case=load_case(source["case"]), phase1=phase1[source["case"]],
                transcript=source["transcript"], client=client,
                seed=source["seed"] + LISTA_SEED_OFFSET, order=source["order"],
                run_id=source["run_id"], agents=agents,
            )
        except BudgetExceeded as exc:
            print(f"PAROU: teto de gasto: {exc}")
            return 1
        except FatalAPIError as exc:
            print(f"PAROU: erro fatal da API: {exc}")
            return 1
        except Exception as exc:  # noqa: BLE001 - counts toward the breaker
            failed += 1
            print(f"[{index}/{len(remaining)}] {source['run_id']} FALHOU: {type(exc).__name__}: {exc}")
            if failed >= config.MAX_FAILED_RUNS:
                print(f"PAROU: {failed} falhas")
                return 1
            continue
        result = {**source, "listing_order": list(agents), "synthesis": synthesis,
                  "original_synthesis_cost_usd": source["cost_usd"],
                  "cost_usd": round(client.ledger.total_usd - before, 6)}
        _write_json(LISTA_DIR / "results" / path.name, result)
        print(f"[{index}/{len(remaining)}] {source['run_id']} ok  lista={'-'.join(a[:3] for a in agents)}  "
              f"total=US$ {client.ledger.total_usd:.4f}", flush=True)
    print(f"gasto: US$ {client.ledger.total_usd:.4f} de US$ {client.budget_usd:.2f}")
    return 0


def cmd_analisar(args: argparse.Namespace) -> int:
    from quare_ordem.analysis import analyze, listing_analysis  # needs the "metrics" extra

    if args.lista:
        try:
            report = listing_analysis(LISTA_DIR, REAL_DIR)
        except FileNotFoundError as exc:
            print(f"ERRO: {exc}")
            return 1
        print(report.read_text(encoding="utf-8"))
        return 0
    run_dir = DRY_DIR if args.simulacao else TEMP0_DIR if args.temp0 else REAL_DIR
    try:
        report = analyze(run_dir, permutations=args.permutacoes)
    except FileNotFoundError as exc:
        print(f"ERRO: {exc}")
        return 1
    print(report.read_text(encoding="utf-8"))
    print(f"tabelas e resumo salvos em {report.parent}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quare-ordem", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ordens").set_defaults(func=cmd_ordens)
    simular = sub.add_parser("simular")
    simular.add_argument("-v", "--verbose", action="store_true")
    simular.set_defaults(func=cmd_simular)
    for name, func in (("checar", cmd_checar), ("piloto", cmd_piloto), ("rodar", cmd_rodar)):
        command = sub.add_parser(name)
        command.add_argument("--teto", type=float, default=config.DEFAULT_BUDGET_USD,
                             help="teto de gasto acumulado em US$ (padrão: %(default)s)")
        if name == "rodar":
            command.add_argument("--confirmo", action="store_true", help="confirma o envio")
        command.set_defaults(func=func)
    sub.add_parser("status").set_defaults(func=cmd_status)
    analisar = sub.add_parser("analisar")
    analisar.add_argument("--simulacao", action="store_true", help="analisa runs/simulacao")
    analisar.add_argument("--temp0", action="store_true", help="analisa runs/temp0")
    analisar.add_argument("--lista", action="store_true", help="analisa runs/lista (lista girada)")
    temp0 = sub.add_parser("temp0")
    temp0.add_argument("--teto", type=float, default=TEMP0_BUDGET_USD)
    temp0.add_argument("--confirmo", action="store_true", help="confirma o envio")
    temp0.set_defaults(func=cmd_temp0)
    lista = sub.add_parser("lista")
    lista.add_argument("--teto", type=float, default=LISTA_BUDGET_USD)
    lista.add_argument("--confirmo", action="store_true", help="confirma o envio")
    lista.set_defaults(func=cmd_lista)
    analisar.add_argument("--permutacoes", type=int, default=999)
    analisar.set_defaults(func=cmd_analisar)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
