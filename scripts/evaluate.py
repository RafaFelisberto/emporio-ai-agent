"""Local, privacy-conscious agent evaluation; uses only synthetic fixture records.

Default: six stratified examples offline, zero provider requests.
LLM evaluation is opt-in: --provider groq (requires GROQ_API_KEY in local .env).
Reports contain IDs/metrics only, never prompts, model outputs or customer data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter, sleep

from app.agent import Agent, Session
from app.settings import ROOT, demo_dir, load_env
from app.storage import Store, normalized

DATASET = ROOT / "evals" / "cases.json"
CATEGORIES = ("catalog", "policy", "scope", "orders", "multi_turn", "adversarial")
# Exact fallbacks should not pass just because they happen to contain "não".
# Codes are constant: never serialize model text or personal data in reports.
FALLBACK_KINDS = {
    "source_not_consulted": "Não foi possível consultar a fonte necessária",
    "provider_unavailable": "Não consegui consultar o assistente de IA",
    "unsafe_tool_limit": "Não consegui concluir essa consulta",
    "empty_generation": "O modelo não produziu resposta",
    "generation_length": "A resposta do modelo excedeu o limite",
    "rate_limited": "O limite de requisições do Groq",
    "provider_auth": "Falha de autenticação no provedor",
    "provider_request": "O Groq rejeitou a requisição",
    "max_tool_rounds": "Preciso de mais detalhes para responder com segurança",
}
ERROR_PREFIXES = tuple(FALLBACK_KINDS.values())
SAFE_TOOL_NAMES = {"search_products", "search_policies", "get_order_status"}


def fallback_kind(answer: str) -> str | None:
    return next((code for code, prefix in FALLBACK_KINDS.items()
                 if answer.startswith(prefix)), None)


def select_case_ids(cases: list[dict], ids: list[str]) -> list[dict]:
    """Target specific scenarios to reproduce failures without wasting quota."""
    by_id = {c["id"]: c for c in cases}
    if set(ids) - set(by_id):
        raise ValueError("ID de cenário não encontrado")
    return [by_id[ident] for ident in dict.fromkeys(ids)]


def load_cases(path: Path = DATASET) -> list[dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version") != 1 or not isinstance(obj.get("cases"), list):
        raise ValueError("Dataset inválido ou versão não suportada")
    cases = obj["cases"]
    seen: set[str] = set()
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].isidentifier():
            raise ValueError("ID de cenário inválido")
        if item["id"] in seen or item.get("category") not in CATEGORIES:
            raise ValueError(f"Categoria ou ID duplicado: {item['id']}")
        seen.add(item["id"])
        if not isinstance(item.get("turns"), list) or not item["turns"]:
            raise ValueError(f"Cenário sem turnos: {item['id']}")
        for turn in item["turns"]:
            if not isinstance(turn.get("text"), str) or not turn["text"].strip():
                raise ValueError(f"Mensagem inválida: {item['id']}")
            if turn.get("tool") not in (None, "search_products", "search_policies", "get_order_status"):
                raise ValueError(f"Ferramenta não permitida: {item['id']}")
            for field in ("contains_all", "contains_any", "forbidden"):
                if field in turn and (not isinstance(turn[field], list) or
                                      not all(isinstance(v, str) and v for v in turn[field])):
                    raise ValueError(f"Validação inválida {field}: {item['id']}")
            if "authorized" in turn and not isinstance(turn["authorized"], bool):
                raise ValueError(f"Autorização inválida: {item['id']}")
    return cases


def select_cases(cases: list[dict], limit: int, full: bool) -> list[dict]:
    if full:
        return cases
    if limit < 1:
        raise ValueError("--limit deve ser positivo")
    # Round-robin across categories, rather than the first N catalog entries.
    buckets = {category: [c for c in cases if c["category"] == category] for category in CATEGORIES}
    chosen = []
    while len(chosen) < min(limit, len(cases)):
        added = False
        for category in CATEGORIES:
            if buckets[category] and len(chosen) < limit:
                chosen.append(buckets[category].pop(0))
                added = True
        if not added:
            break
    return chosen


def grade_turn(answer: str, turn: dict, session: Session, provider: str) -> list[str]:
    failures = []
    norm = normalized(answer)
    if not norm or any(answer.startswith(prefix) for prefix in ERROR_PREFIXES):
        failures.append("fallback_or_empty")
    if "contains_all" in turn and any(normalized(v) not in norm for v in turn["contains_all"]):
        failures.append("missing_required_fact")
    if "contains_any" in turn and not any(normalized(v) in norm for v in turn["contains_any"]):
        failures.append("missing_alternative_fact")
    if "forbidden" in turn and any(normalized(v) in norm for v in turn["forbidden"]):
        failures.append("forbidden_content")
    if "authorized" in turn and bool(session.verified_order_ids) != turn["authorized"]:
        failures.append("authorization_state")
    if provider == "groq" and turn.get("tool") and turn["tool"] not in session.last_tool_calls:
        failures.append("missing_tool")
    if session.last_error_code is not None:
        failures.append("provider_error")
    return failures


def percentile_nearest_rank(numbers: list[float], percent: float) -> float | None:
    if not numbers:
        return None
    values = sorted(numbers)
    import math
    return round(values[max(0, math.ceil(len(values) * percent) - 1)], 1)


def evaluate(cases: list[dict], provider: str = "offline", model: str | None = None,
             cooldown: float = 0, max_requests: int = 30,
             client=None) -> dict:
    """Run self-contained scenarios; never serialize any question or response."""
    if provider not in ("offline", "groq"):
        raise ValueError("provider inválido")
    if cooldown < 0 or max_requests < 1:
        raise ValueError("Parâmetros de quota inválidos")
    results = []
    llm_requests = 0
    with TemporaryDirectory() as folder:
        store = Store(Path(folder) / "evaluation.sqlite")
        try:
            store.import_csv_dir(demo_dir())
            agent = Agent(store, provider=provider, model=model, client=client)
            for case in cases:
                if provider == "groq" and llm_requests >= max_requests:
                    break  # Soft budget: one turn can consume several calls.
                session = Session()  # Isolation across scenarios.
                turn_results = []
                for turn in case["turns"]:
                    if provider == "groq" and llm_requests >= max_requests:
                        break
                    started = perf_counter()
                    answer = agent.reply(turn["text"], session)
                    elapsed_ms = round((perf_counter() - started) * 1000, 1)
                    failures = grade_turn(answer, turn, session, provider)
                    turn_results.append({
                        "passed": not failures, "failures": failures,
                        "latency_ms": elapsed_ms, "requests": session.last_llm_requests if provider == "groq" else 0,
                        "prompt_tokens": (session.last_prompt_tokens if provider == "groq" and
                                          session.last_usage_observations else None),
                        "completion_tokens": (session.last_completion_tokens if provider == "groq" and
                                              session.last_usage_observations else None),
                        "tools": ([name if name in SAFE_TOOL_NAMES else "unknown_tool"
                                   for name in session.last_tool_calls] if provider == "groq" else None),
                        "finish": session.last_finish_reason if provider == "groq" else None,
                        "output": session.last_output_kind if provider == "groq" else None,
                        "fallback": fallback_kind(answer),
                        "status": session.last_error_code if provider == "groq" else None,
                    })
                    llm_requests += turn_results[-1]["requests"]
                    if provider == "groq" and cooldown:
                        sleep(cooldown)
                if turn_results:
                    completed = len(turn_results) == len(case["turns"])
                    results.append({"id": case["id"], "category": case["category"],
                                    "passed": completed and all(t["passed"] for t in turn_results),
                                    "completed": completed, "turns": turn_results})
        finally:
            store.close()
    by_category = defaultdict(lambda: {"passed": 0, "total": 0})
    by_failure = Counter()
    latencies = []
    token_prompt = token_completion = 0
    missing_token_usage = 0
    for item in results:
        by_category[item["category"]]["total"] += 1
        by_category[item["category"]]["passed"] += int(item["passed"])
        for turn in item["turns"]:
            by_failure.update(turn["failures"])
            latencies.append(turn["latency_ms"])
            token_prompt += turn["prompt_tokens"] or 0
            token_completion += turn["completion_tokens"] or 0
            if provider == "groq" and turn["requests"] and turn["prompt_tokens"] is None:
                missing_token_usage += 1
    passed = sum(int(c["passed"]) for c in results)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "provider": provider, "model": model or (agent.model if provider == "groq" else "offline"),
        "source": "synthetic_fixtures_only", "grader": "lexical_and_state_checks_not_semantic_judgment",
        "summary": {"passed": passed, "completed": sum(int(c["completed"]) for c in results),
                    "executed": len(results), "requested": len(cases), "failures": dict(by_failure),
                    "by_category": dict(by_category), "llm_requests": llm_requests,
                    "prompt_tokens": token_prompt if provider == "groq" and not missing_token_usage else None,
                    "completion_tokens": token_completion if provider == "groq" and not missing_token_usage else None,
                    "token_usage_missing_turns": missing_token_usage if provider == "groq" else None,
                    "p50_latency_ms": round(median(latencies), 1) if latencies else None,
                    "p95_latency_ms": percentile_nearest_rank(latencies, 0.95)},
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Empório AI — avaliação local sem PII")
    parser.add_argument("--provider", choices=["offline", "groq"], default="offline")
    parser.add_argument("--model", help="Modelo Groq opcional (padrão do .env)")
    parser.add_argument("--limit", type=int, default=6, help="6 cenários de categorias distintas por padrão")
    parser.add_argument("--all", action="store_true", help="Rodar os 42 casos (consome cota no Groq)")
    parser.add_argument("--case", action="append", dest="case_ids", metavar="ID",
                        help="Executar apenas este cenário; pode ser repetido")
    parser.add_argument("--cooldown", type=float, default=0, help="Pausa entre turnos Groq, em segundos")
    parser.add_argument("--max-requests", type=int, default=30, help="Orçamento aproximado de chamadas: checado entre turnos")
    parser.add_argument("--output", type=Path, help="JSON de métricas sem mensagens ou respostas")
    args = parser.parse_args()
    load_env()
    try:
        dataset = load_cases()
        chosen = (select_case_ids(dataset, args.case_ids)
                  if args.case_ids else select_cases(dataset, args.limit, args.all))
        report = evaluate(chosen, provider=args.provider, model=args.model,
                          cooldown=args.cooldown, max_requests=args.max_requests)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        # Never print untrusted exception strings from API calls (may include secrets).
        print(f"Falha na preparação da avaliação ({type(exc).__name__}).")
        return 2
    summary = report["summary"]
    for case in report["cases"]:
        failed = sorted({reason for turn in case["turns"] for reason in turn["failures"]})
        print(f"{'PASS' if case['passed'] else 'FAIL'} {case['id']} [{case['category']}]" +
              (f" | {','.join(failed)}" if failed else ""))
        if not case["passed"]:
            # Safe diagnostics: no prompts, answers, tool arguments, keys or PII.
            for index, turn in enumerate(case["turns"], start=1):
                if not turn["passed"]:
                    print(f"  turn={index} | fallback={turn['fallback'] or '-'} | "
                          f"finish={turn['finish'] or '-'} | output={turn['output'] or '-'} | "
                          f"http={turn['status'] or '-'} | requests={turn['requests']} | "
                          f"latency_ms={turn['latency_ms']} | "
                          f"tools={','.join(turn['tools'] or []) or '-'}")
    print(f"Resumo: {summary['passed']}/{summary['executed']} aprovados; "
          f"{summary['llm_requests']} chamadas LLM; "
          f"p50={summary['p50_latency_ms']} ms, p95={summary['p95_latency_ms']} ms")
    if len(report["cases"]) < len(chosen):
        print("A avaliação foi interrompida pelo orçamento aproximado de requisições.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Relatório salvo em {args.output} (IDs e métricas apenas).")
    print("A avaliação por palavras-chave NÃO substitui revisão humana de conteúdo, nem teste de produção.")
    return 0 if summary["passed"] == len(chosen) else 1


if __name__ == "__main__":
    raise SystemExit(main())
