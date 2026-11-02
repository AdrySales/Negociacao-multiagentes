"""Executes a run plan with resume, a circuit breaker and spending reports."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from quare_ordem import config
from quare_ordem.design import RunSpec
from quare_ordem.llm import BudgetExceeded, FatalAPIError, LLMClient
from quare_ordem.pipeline import ensure_phase1, result_path, run_debate, save_result


@dataclass
class RunReport:
    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    stop_reason: str = ""
    spent_usd: float = 0.0


def _log_failure(out_dir: Path, run_id: str, exc: BaseException) -> None:
    path = out_dir / "failures.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def execute(
    plan: list[RunSpec],
    client: LLMClient,
    out_dir: Path,
    *,
    max_failed_runs: int = config.MAX_FAILED_RUNS,
    echo=print,
) -> RunReport:
    report = RunReport()
    start_spend = client.ledger.total_usd
    phase1_cache: dict[str, dict] = {}

    for index, spec in enumerate(plan, start=1):
        if result_path(out_dir, spec).exists():
            report.skipped.append(spec.run_id)
            continue
        try:
            if spec.case not in phase1_cache:
                phase1_cache[spec.case] = ensure_phase1(spec.case, client, out_dir)
            result = run_debate(spec, phase1_cache[spec.case], client)
            save_result(out_dir, spec, result)
            report.completed.append(spec.run_id)
            echo(
                f"[{index}/{len(plan)}] {spec.run_id} ok  "
                f"rodadas={result['rounds_played']}  custo=US$ {result['cost_usd']:.4f}  "
                f"total=US$ {client.ledger.total_usd:.4f}"
            )
        except BudgetExceeded as exc:
            report.stop_reason = f"teto de gasto: {exc}"
            break
        except FatalAPIError as exc:
            _log_failure(out_dir, spec.run_id, exc)
            report.stop_reason = f"erro fatal da API: {exc}"
            break
        except Exception as exc:  # noqa: BLE001 - any other failure counts toward the breaker
            _log_failure(out_dir, spec.run_id, exc)
            report.failed.append(spec.run_id)
            echo(f"[{index}/{len(plan)}] {spec.run_id} FALHOU: {type(exc).__name__}: {exc}")
            if len(report.failed) >= max_failed_runs:
                report.stop_reason = (
                    f"{len(report.failed)} execuções falharam; parando para não gastar à toa "
                    f"(detalhes em {out_dir / 'failures.jsonl'})"
                )
                break

    report.spent_usd = client.ledger.total_usd - start_spend
    return report
