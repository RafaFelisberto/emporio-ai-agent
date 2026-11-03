"""A small, redacted real-API smoke test. Run only with your own Groq API key.

Usage: python -m scripts.live_smoke

Uses synthetic fixtures in a temporary database; no raw customer exports.
Only prints case labels, tool names and pass/fail, never questions, API keys,
model responses, or customer identifiers. Manual conversational QA is still needed.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from tempfile import TemporaryDirectory
from pathlib import Path

from app.agent import Agent, Session
from app.settings import demo_dir, load_env
from app.storage import Store


@dataclass(frozen=True)
class Check:
    name: str
    question: str
    tool: str
    expected: tuple[str, ...]


CASES = (
    Check("catalog_price", "Quanto custa o Violão Aurora GD20?", "search_products", ("1.979,10",)),
    Check("returns_policy", "Qual o prazo de arrependimento de uma compra online?", "search_policies", ("7 dias",)),
    Check("scope", "Vocês vendem palhetas avulsas?", "search_policies", ("não",)),
)


def run() -> int:
    load_env()
    if not os.environ.get("GROQ_API_KEY"):
        print("ERRO: GROQ_API_KEY não encontrada. Configure .env local e não compartilhe a chave.")
        return 2

    with TemporaryDirectory() as temp:
        store = Store(Path(temp) / "evaluation.sqlite")
        try:
            store.import_csv_dir(demo_dir())
            agent = Agent(store, provider="groq")
            failed = 0
            for case in CASES:
                session = Session()
                answer = agent.reply(case.question, session).casefold()
                tool_ok = case.tool in session.last_tool_calls
                facts_ok = all(term.casefold() in answer for term in case.expected)
                passed = tool_ok and facts_ok and session.last_error_code is None
                failed += not passed
                print(f"{'PASS' if passed else 'FAIL'} {case.name} | "
                      f"tools={','.join(session.last_tool_calls) or '-'} | "
                      f"requests={session.last_llm_requests} | tool_check={tool_ok} | "
                      f"fact_check={facts_ok} | status={session.last_error_code or '-'}")
            print(f"Total: {len(CASES) - failed}/{len(CASES)} checks automáticos aprovados")
            print("Obs.: checks por palavras-chave não substituem avaliação semântica nem testes de segurança.")
            return 1 if failed else 0
        finally:
            store.close()


if __name__ == "__main__":
    raise SystemExit(run())
