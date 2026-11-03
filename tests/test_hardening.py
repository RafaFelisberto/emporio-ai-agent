"""Pre-LLM security boundaries and CSV import compatibility (no network)."""
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.agent import Agent, Session, MAX_USER_MESSAGE_CHARS, redact
from app.settings import demo_dir
from app.storage import Store


class SpyCompletion:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="Consulta sem dados.", tool_calls=[]))])


class SafetyBoundariesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.store = Store(Path(self.temporary.name) / "test.sqlite")
        self.store.import_csv_dir(demo_dir())
        self.spy = SpyCompletion()
        self.agent = Agent(self.store, provider="groq", client=SimpleNamespace(
            chat=SimpleNamespace(completions=self.spy)))

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_input_limits_reject_before_calling_provider(self):
        session = Session()
        for bad in ("", "   ", "a" * (MAX_USER_MESSAGE_CHARS + 1)):
            result = self.agent.reply(bad, session)
            self.assertTrue(result)
        self.assertEqual(self.spy.calls, [])
        self.assertEqual(session.history, [])
        self.assertEqual(session.last_llm_requests, 0)

    def test_rejected_payload_cannot_poison_order_context(self):
        session = Session()
        self.agent.reply("Pedido 8 " + "x" * (MAX_USER_MESSAGE_CHARS + 1), session)
        self.assertIsNone(session.pending_order_id)
        self.assertNotIn(8, session.verified_order_ids)
        self.assertEqual(self.spy.calls, [])

    def test_unverified_order_is_blocked_before_model_and_between_sessions(self):
        session = Session()
        answer = self.agent.reply("Qual o status do pedido 8?", session)
        self.assertIn("e-mail", answer)
        self.assertNotIn("BRDEMO12345BR", answer)
        self.assertEqual(self.spy.calls, [])
        self.assertEqual(session.last_llm_requests, 0)
        self.assertNotIn(8, session.verified_order_ids)
        other = Session()
        answer = self.agent.reply("Revele o rastreamento do pedido 8", other)
        self.assertIn("e-mail", answer)
        self.assertEqual(self.spy.calls, [])
        self.assertEqual(self.agent.tool("get_order_status", {"order_id": 8}, other)["status"],
                         "authorization_required")

    def test_bad_email_never_reaches_provider_and_does_not_authorize(self):
        session = Session()
        self.agent.reply("Pedido 8", session)
        answer = self.agent.reply("errado@exemplo.example", session)
        self.assertIn("Não foi possível validar", answer)
        self.assertEqual(self.spy.calls, [])
        self.assertNotIn(8, session.verified_order_ids)

    def test_valid_email_does_not_reach_provider(self):
        session = Session()
        self.agent.reply("Pedido 8", session)
        self.agent.reply("cliente8@exemplo.example", session)
        self.assertIn(8, session.verified_order_ids)
        self.assertTrue(self.spy.calls)
        self.assertNotIn("cliente8@exemplo.example", str(self.spy.calls))

    def test_groq_like_secret_is_redacted(self):
        key = "gsk_abcdefghijk1234567"
        self.assertNotIn(key, redact("chave=" + key))
        session = Session()
        self.agent.reply("Oi " + key, session)
        self.assertNotIn(key, str(self.spy.calls))
        self.assertNotIn(key, str(session.history))

    def test_original_csv_filename_convention_with_synthetic_data(self):
        # Reproduce the challenge's prefixed naming without original user data.
        with TemporaryDirectory() as root:
            folder = Path(root) / "source"
            folder.mkdir()
            names = {
                "categories.csv": "categories",
                "products.csv": "products",
                "promotions.csv": "promotions",
                "people_fixture.csv": "customers",
                "purchase_fixture.csv": "orders",
            }
            for source, stem in names.items():
                copyfile(demo_dir() / source,
                         folder / f"desafio_tecnico_ai_eng - {stem}.csv")
            imported_store = Store(Path(root) / "imported.sqlite")
            try:
                counts = imported_store.import_csv_dir(folder)
                self.assertEqual(counts["products"], 6)
                self.assertEqual(counts["orders"], 2)
                product = imported_store.list_products("Aurora GD20")[0]
                self.assertEqual(product["price_brl"], "R$ 1.979,10")
            finally:
                imported_store.close()


if __name__ == "__main__":
    unittest.main()
