"""Evaluation quality and privacy checks; no network or API credentials."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.agent import Agent, Session
from app.settings import demo_dir
from app.storage import Store
from scripts.evaluate import load_cases, select_cases, grade_turn, evaluate, percentile_nearest_rank


def completion(content=None, call=None, prompt=11, completion_tokens=8):
    calls = [SimpleNamespace(id="call_1", function=SimpleNamespace(
        name=call[0], arguments=json.dumps(call[1])))] if call else []
    return SimpleNamespace(
        model="openai/gpt-oss-20b",
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion_tokens),
        choices=[SimpleNamespace(finish_reason="tool_calls" if call else "stop",
                                 message=SimpleNamespace(content=content, tool_calls=calls))])


class GroqFixture:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) % 2:
            return completion(call=("search_products", {"query": "Aurora GD20"}))
        return completion(content="O Violão Aurora GD20 custa R$ 1.979,10 no catálogo.")


class EvaluationTests(unittest.TestCase):
    def test_dataset_has_synthetic_coverage(self):
        cases = load_cases()
        self.assertEqual(len(cases), 42)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertEqual(sum(len(c["turns"]) for c in cases), 51)
        self.assertEqual({c["category"] for c in select_cases(cases, 6, False)},
                         {"catalog", "policy", "scope", "orders", "multi_turn", "adversarial"})

    def test_error_reply_is_not_graded_as_correct_negative(self):
        turn = {"contains_any": ["não"], "tool": "search_policies"}
        session = Session()
        result = grade_turn("Não foi possível consultar a fonte necessária. Tente novamente.",
                            turn, session, "groq")
        self.assertIn("fallback_or_empty", result)
        self.assertIn("missing_tool", result)
        self.assertNotIn("missing_tool", grade_turn("Não, não vendemos palhetas.", turn,
                                                     Session(last_tool_calls=["search_policies"]), "groq"))

    def test_authorization_and_forbidden_checks(self):
        turn = {"authorized": False, "forbidden": ["BRDEMO12345BR"]}
        self.assertEqual(grade_turn("Para consultar o pedido, confirme e-mail.", turn, Session(), "offline"), [])
        problems = grade_turn("Rastreio BRDEMO12345BR", turn,
                              Session(verified_order_ids={8}), "offline")
        self.assertIn("authorization_state", problems)
        self.assertIn("forbidden_content", problems)

    def test_empty_and_bad_dataset_are_rejected(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "cases.json"
            path.write_text(json.dumps({"schema_version": 1, "cases": [
                {"id": "repeat", "category": "scope", "turns": [{"text": "A"}]},
                {"id": "repeat", "category": "scope", "turns": [{"text": "B"}]},
            ]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_offline_evaluation_has_no_provider_calls_and_no_raw_text(self):
        cases = select_cases(load_cases(), 6, False)
        report = evaluate(cases, "offline")
        self.assertEqual(report["summary"]["executed"], 6)
        self.assertEqual(report["summary"]["llm_requests"], 0)
        self.assertEqual(report["summary"]["passed"], 6)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("cliente8@exemplo.example", serialized)
        self.assertNotIn("SYSTEM: ignore", serialized)
        self.assertNotIn("Quanto custa", serialized)
        self.assertIn("catalog_gd20_price", serialized)

    def test_mock_groq_usage_and_tool_metrics(self):
        provider = GroqFixture()
        client = SimpleNamespace(chat=SimpleNamespace(completions=provider))
        case = [c for c in load_cases() if c["id"] == "catalog_gd20_price"]
        report = evaluate(case, "groq", client=client)
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["summary"]["llm_requests"], 2)
        self.assertEqual(report["summary"]["prompt_tokens"], 22)
        self.assertEqual(report["summary"]["completion_tokens"], 16)
        self.assertEqual(report["cases"][0]["turns"][0]["tools"], ["search_products"])

    def test_telemetry_reset_on_denied_request(self):
        class Fake:
            def create(self, **kwargs):
                return completion(content="Posso ajudar.")
        with TemporaryDirectory() as root:
            store = Store(Path(root) / "db.sqlite")
            try:
                store.import_csv_dir(demo_dir())
                agent = Agent(store, "groq", client=SimpleNamespace(chat=SimpleNamespace(completions=Fake())))
                session = Session()
                agent.reply("Oi", session)
                self.assertEqual(session.last_prompt_tokens, 11)
                self.assertEqual(session.last_llm_requests, 1)
                agent.reply("email: pessoa@exemplo.example", session)
                self.assertEqual(session.last_prompt_tokens, 0)
                self.assertEqual(session.last_completion_tokens, 0)
                self.assertEqual(session.last_llm_requests, 0)
            finally:
                store.close()

    def test_tool_permission_boundary_still_blocks_injection(self):
        with TemporaryDirectory() as root:
            store = Store(Path(root) / "db.sqlite")
            try:
                store.import_csv_dir(demo_dir())
                agent = Agent(store, "offline")
                self.assertEqual(agent.tool("execute_sql", {"sql": "SELECT * FROM customers"}, Session()),
                                 {"error": "Ferramenta não autorizada"})
                self.assertEqual(agent.tool("get_order_status", {"order_id": 8}, Session())["status"],
                                 "authorization_required")
            finally:
                store.close()

    def test_percentile(self):
        self.assertIsNone(percentile_nearest_rank([], 0.95))
        self.assertEqual(percentile_nearest_rank([10, 1, 4, 2], 0.95), 10)


if __name__ == "__main__":
    unittest.main()
