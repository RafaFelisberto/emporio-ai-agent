import tempfile
import unittest
from pathlib import Path
from app.agent import Agent, Session, redact
from app.settings import demo_dir
from app.storage import Store


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite")
        self.store.import_csv_dir(demo_dir())
        self.agent = Agent(self.store, "offline")
        self.session = Session()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_product_question(self):
        result = self.agent.reply("Quais violões disponíveis até R$ 1000?", self.session)
        self.assertIn("599,90", result)
        self.assertNotIn("Violão Antigo", result)
        self.assertNotIn("1.979,10", result)
        self.assertNotIn("Guitarra Estrela", result)

    def test_outside_scope(self):
        result = self.agent.reply("Vocês vendem palhetas?", self.session)
        self.assertIn("não acessórios", result)

    def test_order_requires_validation(self):
        self.assertIn("e-mail", self.agent.reply("Qual status do pedido 8?", self.session))
        self.assertEqual(self.agent.tool("get_order_status", {"order_id": 8}, self.session)["status"], "authorization_required")

    def test_valid_order_auth_and_redacted_session(self):
        self.agent.reply("Qual status do pedido 8?", self.session)
        result = self.agent.reply("Meu e-mail é cliente8@exemplo.example", self.session)
        self.assertIn("shipped", result)
        self.assertIn("BRDEMO12345BR", result)
        self.assertIn(8, self.session.verified_order_ids)
        self.assertNotIn("cliente8@exemplo.example", repr(self.session.history))
        self.assertEqual(self.agent.tool("get_order_status", {"order_id": 9}, self.session)["status"], "authorization_required")

    def test_email_redacted(self):
        self.assertNotIn("teste@dominio.com", redact("teste@dominio.com"))
        self.assertNotIn("(67) 99812-3456", redact("Meu telefone é (67) 99812-3456"))

    def test_no_false_authorization(self):
        self.agent.reply("Pedido 8: e-mail errado@exemplo.com", self.session)
        self.assertNotIn(8, self.session.verified_order_ids)

    def test_returns_no_fabricated_eligibility(self):
        result = self.agent.reply("Posso devolver minha compra online por arrependimento?", self.session)
        self.assertIn("7 dias", result)


if __name__ == "__main__":
    unittest.main()
