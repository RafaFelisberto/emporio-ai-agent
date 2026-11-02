"""CLI; supports synthetic demo and private challenge CSV imports."""
from __future__ import annotations

import argparse
import os
from .agent import Agent, Session
from .settings import db_path, demo_dir, load_env
from .storage import Store


def main() -> None:
    parser = argparse.ArgumentParser(description="Empório da Música — AI Engineer Challenge")
    parser.add_argument("--provider", choices=["offline", "groq"], help="Default from AGENT_PROVIDER (offline)")
    parser.add_argument("--import-dir", help="Import official CSV locally (never commit them)")
    parser.add_argument("--db", help="SQLite file path")
    parser.add_argument("--message", help="One-shot question (otherwise interactive CLI)")
    args = parser.parse_args()
    load_env()
    provider = args.provider or os.getenv("AGENT_PROVIDER", "offline")
    db = args.db or db_path()
    store = Store(db)
    try:
        if args.import_dir:
            counts = store.import_csv_dir(args.import_dir)
            print("Importação local:", ", ".join(f"{k}={v}" for k,v in counts.items()))
        elif not store.con.execute("SELECT 1 FROM products LIMIT 1").fetchone():
            store.import_csv_dir(demo_dir())
            print("Modo de dados: catálogo sintético de demonstração.")
        agent = Agent(store, provider=provider)
        session = Session()
        if args.message:
            print(agent.reply(args.message, session))
            return
        print(f"Empório AI | provedor={provider} | 'sair' para encerrar")
        while True:
            try:
                question = input("Você> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if question.casefold() in ("sair", "exit", "quit"):
                break
            if question:
                print("Agente>", agent.reply(question, session))
    finally:
        store.close()


if __name__ == "__main__":
    main()
