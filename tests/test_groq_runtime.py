"""Regression tests for model transport options, error mapping and safe traces."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from app.agent import Agent, Session
from app.settings import demo_dir
from app.storage import Store


class FailingCompletion:
    def __init__(self, code):
        self.code = code

    def create(self, **kwargs):
        exc = RuntimeError("provider details must never appear in user response: sk_test_secret")
        exc.status_code = self.code
        raise exc


class SingleCompletion:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="Posso ajudar com instrumentos.", tool_calls=[]))])


class ScopeCompletion:
    """Fake provider honoring a forced policy lookup before a final answer."""

    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            call = SimpleNamespace(
                id="scope_1",
                function=SimpleNamespace(name="search_policies",
                                         arguments='{"topic":"scope"}'))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=None, tool_calls=[call]))])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="Não, a loja não vende palhetas avulsas. (Seção 1)",
            tool_calls=[]))])


class GroqRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite")
        self.store.import_csv_dir(demo_dir())

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def agent_with(self, completion):
        return Agent(self.store, provider="groq", client=SimpleNamespace(
            chat=SimpleNamespace(completions=completion)))

    def test_gpt_oss_runs_with_sequential_tool_calls(self):
        fake = SingleCompletion()
        session = Session()
        self.agent_with(fake).reply("Olá!", session)
        self.assertIs(fake.kwargs["parallel_tool_calls"], False)
        self.assertEqual(fake.kwargs["max_completion_tokens"], 1024)
        self.assertEqual(session.last_llm_requests, 1)
        self.assertEqual(session.last_tool_calls, [])

    def test_scope_is_forced_into_retrieval(self):
        fake = ScopeCompletion()
        session = Session()
        answer = self.agent_with(fake).reply("Vocês vendem palhetas avulsas?", session)
        self.assertIn("não", answer.casefold())
        self.assertEqual(
            fake.requests[0]["tool_choice"],
            {"type": "function", "function": {"name": "search_policies"}},
        )
        self.assertEqual(fake.requests[1]["tool_choice"], "auto")
        self.assertEqual(session.last_tool_calls, ["search_policies"])
        self.assertEqual(session.last_llm_requests, 2)
        self.assertIn("acessórios avulsos", fake.requests[1]["messages"][-1]["content"])

    def test_greeting_and_nylon_strings_do_not_force_scope(self):
        from app.agent import requires_scope_lookup
        self.assertFalse(requires_scope_lookup("Oi, tudo bem?"))
        self.assertFalse(requires_scope_lookup("Qual violão tem cordas de nylon?"))
        self.assertTrue(requires_scope_lookup("Vendem cordas avulsas?"))
        self.assertTrue(requires_scope_lookup("Vocês vendem palhetas avulsas?"))
        fake = SingleCompletion()
        self.agent_with(fake).reply("Oi!", Session())
        self.assertEqual(fake.kwargs["tool_choice"], "auto")

    def test_provider_errors_do_not_expose_secret_or_exception(self):
        messages = {401: "GROQ_API_KEY", 403: "GROQ_API_KEY", 429: "limite", 400: "Groq rejeitou", 503: "Não consegui"}
        for code, expected in messages.items():
            with self.subTest(code=code):
                session = Session()
                result = self.agent_with(FailingCompletion(code)).reply("Olá", session)
                self.assertIn(expected, result)
                self.assertNotIn("sk_test_secret", result)
                self.assertEqual(session.last_error_code, code)
                self.assertEqual(session.last_llm_requests, 1)


if __name__ == "__main__":
    unittest.main()
