"""Repeat a small, synthetic evaluation to measure intermittent agent failures.

Groq is explicitly opt-in. All reports store IDs and metrics, never messages,
raw completions, API keys or tool arguments. No background execution or network
access is needed for offline mode and unit tests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
from time import sleep

from app.settings import ROOT, load_env
from scripts.evaluate import (evaluate, load_cases, percentile_nearest_rank,
                              select_case_ids)

DEFAULT_CASES = ("catalog_gd20_price", "multi_catalog_price")
STOP_HTTP = {401: "provider_auth", 403: "provider_auth", 429: "rate_limited"}


def summarize(reports: list[dict], ids: list[str], requested_runs: int,
              provider: str, stop_reason: str | None) -> dict:
    """Count failures by attempt, not just success among completed cases."""
    by_case = {case_id: {"passed": 0, "failed": 0, "missing": 0,
                         "evaluated": 0, "failures": {}, "fallbacks": {}}
               for case_id in ids}
    all_latencies: list[float] = []
    failure_counter: Counter[str] = Counter()
    fallback_counter: Counter[str] = Counter()
    total_requests = 0
    total_prompt = 0
    total_completion = 0
    token_coverage = True
    run_summaries = []
    complete_runs = 0
    for idx, report in enumerate(reports, start=1):
        cases = {item["id"]: item for item in report["cases"]}
        all_present = all(case_id in cases and cases[case_id]["completed"] for case_id in ids)
        complete_runs += int(all_present)
        metrics = report["summary"]
        total_requests += metrics["llm_requests"]
        if provider == "groq":
            if metrics.get("prompt_tokens") is None or metrics.get("completion_tokens") is None:
                token_coverage = False
            else:
                total_prompt += metrics["prompt_tokens"]
                total_completion += metrics["completion_tokens"]
        run_summaries.append({"run": idx, "passed": metrics["passed"],
                              "executed": metrics["executed"],
                              "complete": all_present,
                              "llm_requests": metrics["llm_requests"],
                              "p50_latency_ms": metrics["p50_latency_ms"],
                              "p95_latency_ms": metrics["p95_latency_ms"],
                              "results_file": f"run_{idx:02}.json"})
        for case_id in ids:
            row = by_case[case_id]
            case = cases.get(case_id)
            if case is None or not case["completed"]:
                row["missing"] += 1
            if case is None:
                continue
            row["evaluated"] += 1
            row["passed" if case["passed"] else "failed"] += 1
            for turn in case["turns"]:
                all_latencies.append(turn["latency_ms"])
                failure_counter.update(turn["failures"])
                row["failures"] = dict(Counter(row["failures"]) + Counter(turn["failures"]))
                if turn.get("fallback"):
                    fallback_counter.update([turn["fallback"]])
                    row["fallbacks"] = dict(Counter(row["fallbacks"]) + Counter([turn["fallback"]]))
    # Runs that stopped before an entire scenario count as missing, not passing.
    for row in by_case.values():
        row["missing"] += requested_runs - len(reports)
        row["pass_rate_pct"] = round(100 * row["passed"] / requested_runs, 1)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "synthetic_fixtures_only",
        "scoring": "lexical_and_state_checks_not_semantic_judgment",
        "provider": provider,
        "case_ids": list(ids),
        "requested_runs": requested_runs,
        "executed_runs": len(reports),
        "complete_runs": complete_runs,
        "stop_reason": stop_reason,
        "llm_requests": total_requests,
        "prompt_tokens": total_prompt if provider == "groq" and token_coverage else None,
        "completion_tokens": total_completion if provider == "groq" and token_coverage else None,
        "p50_latency_ms": round(median(all_latencies), 1) if all_latencies else None,
        "p95_latency_ms": percentile_nearest_rank(all_latencies, 0.95),
        "failure_counts": dict(failure_counter),
        "fallback_counts": dict(fallback_counter),
        "by_case": by_case,
        "runs": run_summaries,
        "limitations": "Small non-random sample; passage does not prove production reliability or security."
    }


def repeat(cases: list[dict], *, provider: str = "offline", runs: int = 3,
           cooldown: float = 2.0, between_runs: float = 5.0,
           max_requests_per_run: int = 12, max_total_requests: int = 36,
           output_dir: Path, model: str | None = None,
           evaluate_fn=evaluate, sleep_fn=sleep) -> dict:
    """Run sequentially, stop on rate/auth errors, and persist safe reports."""
    if provider not in ("offline", "groq") or not 1 <= runs <= 20:
        raise ValueError("Provedor ou número de repetições inválidos")
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Cenários duplicados ou ausentes")
    if min(cooldown, between_runs) < 0 or min(max_requests_per_run, max_total_requests) < 1:
        raise ValueError("Quota ou intervalos inválidos")
    output_dir = Path(output_dir)
    target_files = [output_dir / f"run_{i:02}.json" for i in range(1, runs + 1)]
    target_files.append(output_dir / "summary.json")
    if any(p.exists() for p in target_files):
        raise FileExistsError("O diretório já contém resultados; use um destino novo")
    output_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict] = []
    spent = 0
    stop_reason = None
    for i in range(runs):
        if provider == "groq" and spent >= max_total_requests:
            stop_reason = "total_request_budget"
            break
        budget = (min(max_requests_per_run, max_total_requests - spent)
                  if provider == "groq" else max_requests_per_run)
        report = evaluate_fn(cases, provider=provider, model=model,
                             cooldown=(cooldown if provider == "groq" else 0),
                             max_requests=budget)
        reports.append(report)
        spent += report["summary"]["llm_requests"]
        (output_dir / f"run_{i+1:02}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Execução {i+1}/{runs}: {report['summary']['passed']}/{len(cases)} cenários "
              f"| chamadas={report['summary']['llm_requests']}")
        statuses = {t.get("status") for c in report["cases"] for t in c["turns"]}
        if 429 in statuses:
            stop_reason = STOP_HTTP[429]
        elif 401 in statuses or 403 in statuses:
            stop_reason = STOP_HTTP[401]
        elif len(report["cases"]) < len(cases) or any(not c["completed"] for c in report["cases"]):
            stop_reason = "partial_run_budget"
        if stop_reason:
            break
        if provider == "groq" and i < runs-1 and between_runs:
            sleep_fn(between_runs)
    summary = summarize(reports, [c["id"] for c in cases], runs, provider, stop_reason)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case_id, values in summary["by_case"].items():
        print(f"{case_id}: {values['passed']}/{runs} aprovados "
              f"({values['pass_rate_pct']}%); falhas={values['failed']}; ausentes={values['missing']}")
    print(f"Resumo: {summary['executed_runs']}/{runs} execuções; "
          f"{summary['llm_requests']} chamadas; p50={summary['p50_latency_ms']} ms; "
          f"p95={summary['p95_latency_ms']} ms; parada={stop_reason or '-'}")
    print(f"Arquivos locais em: {output_dir} (sem perguntas ou respostas)")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Empório AI — estabilidade de avaliações sintéticas")
    parser.add_argument("--provider", choices=("offline", "groq"), default="offline")
    parser.add_argument("--model", help="Modelo opcional; por padrão usa o .env")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case", action="append", dest="case_ids", metavar="ID",
                        help="Repetível; por padrão são os dois casos que falharam")
    parser.add_argument("--cooldown", type=float, default=2)
    parser.add_argument("--between-runs", type=float, default=5)
    parser.add_argument("--max-requests-per-run", type=int, default=12,
                        help="Orçamento aproximado verificado entre turnos")
    parser.add_argument("--max-total-requests", type=int, default=36,
                        help="Orçamento total aproximado; não impõe corte no loop interno")
    parser.add_argument("--output-dir", type=Path,
                        help="Diretório novo para JSONs locais; padrão com timestamp")
    args = parser.parse_args()
    load_env()
    destination = args.output_dir or (ROOT / "evals" / "results" / "stability" /
                                      datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    try:
        cases = select_case_ids(load_cases(), args.case_ids or list(DEFAULT_CASES))
        summary = repeat(cases, provider=args.provider, runs=args.runs,
                         cooldown=args.cooldown, between_runs=args.between_runs,
                         max_requests_per_run=args.max_requests_per_run,
                         max_total_requests=args.max_total_requests,
                         output_dir=destination, model=args.model)
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, OSError) as exc:
        # Never print provider exception details or local secret paths.
        print(f"Falha no preparo/execução da avaliação ({type(exc).__name__}).")
        return 2
    return 0 if summary["complete_runs"] == args.runs and all(
        value["passed"] == args.runs for value in summary["by_case"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
