"""No real Groq token is required: exercise the exact orchestration contract."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from app.agent import Agent, Session
from app.settings import demo_dir
from app.storage import Store


def response(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_call(name, arguments):
    return SimpleNamespace(id="tool_1", function=SimpleNamespace(name=name, arguments=arguments))


class FakeCompletion:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) % 2:
            return response(SimpleNamespace(content=None, tool_calls=[tool_call(
                "search_products", '{"query":"Aurora GD20"}')]))
        tool_result = self.requests[-1]["messages"][-1]["content"]
        if "1.979,10" not in tool_result:
            raise AssertionError("Agent failed to pass database data back into LLM")
        return response(SimpleNamespace(content="O GD20 custa R$ 1.979,10.", tool_calls=None))


class ModelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite")
        self.store.import_csv_dir(demo_dir())
        self.mock = FakeCompletion()
        self.agent = Agent(self.store, provider="groq", client=SimpleNamespace(
            chat=SimpleNamespace(completions=self.mock)))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_groq_contract_and_db_grounding(self):
        answer = self.agent.reply("Quanto custa o Aurora GD20?", Session())
        self.assertIn("1.979,10", answer)
        self.assertEqual(len(self.mock.requests), 2)
        self.assertEqual(self.mock.requests[1]["messages"][-1]["role"], "tool")

    def test_model_cannot_read_unverified_order(self):
        session = Session()
        self.assertEqual(self.agent.tool("get_order_status", {"order_id": 8}, session)["status"], "authorization_required")
        self.assertEqual(self.agent.tool("get_order_status", {"order_id": 9}, session)["status"], "authorization_required")

    def test_email_never_forwarded_to_model(self):
        session = Session()
        self.agent.reply("Status do pedido 8? Meu email é cliente8@exemplo.example", session)
        for request in self.mock.requests:
            self.assertNotIn("cliente8@exemplo.example", str(request))


if __name__ == "__main__":
    unittest.main()
