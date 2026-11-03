"""Stability runner regression tests. No Groq token, API call or customer data."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.evaluate import load_cases, select_case_ids
from scripts.repeat_eval import repeat, summarize


CASES = ("catalog_gd20_price", "multi_catalog_price")


def synthetic_report(ids=CASES, *, requests=0, status=None, partial=False, passed=True):
    listed = ids[:1] if partial else ids
    return {
        "summary": {"passed": len(listed) if passed else 0,
                    "executed": len(listed), "llm_requests": requests,
                    "prompt_tokens": 12 if requests else None,
                    "completion_tokens": 8 if requests else None,
                    "p50_latency_ms": 10, "p95_latency_ms": 15},
        "cases": [{"id": ident, "category": "catalog", "passed": passed,
                   "completed": True,
                   "turns": [{"latency_ms": 10, "failures": [] if passed else ["provider_error"],
                              "fallback": "rate_limited" if status == 429 else None,
                              "status": status}]}
                  for ident in listed]
    }


class RepeatEvaluationTests(unittest.TestCase):
    def test_runs_three_times_offline_without_secrets(self):
        cases = select_case_ids(load_cases(), list(CASES))
        with TemporaryDirectory() as folder:
            target = Path(folder) / "stability"
            summary = repeat(cases, provider="offline", runs=3, cooldown=0,
                             between_runs=0, output_dir=target)
            self.assertEqual(summary["executed_runs"], 3)
            self.assertEqual(summary["complete_runs"], 3)
            self.assertEqual(summary["llm_requests"], 0)
            self.assertTrue(all(row["passed"] == 3 for row in summary["by_case"].values()))
            self.assertEqual(len(list(target.glob("*.json"))), 4)
            contents = "".join(path.read_text(encoding="utf-8") for path in target.glob("*.json"))
            self.assertNotIn("Quanto custa", contents)
            self.assertNotIn("cliente8@exemplo.example", contents)
            self.assertNotIn("BRDEMO12345BR", contents)

    def test_stops_after_rate_limit(self):
        cases = select_case_ids(load_cases(), list(CASES))
        calls = []
        def fake_evaluate(*args, **kwargs):
            calls.append(kwargs)
            return synthetic_report(requests=2, status=429, passed=False)
        with TemporaryDirectory() as folder:
            summary = repeat(cases, provider="groq", runs=3, output_dir=Path(folder),
                             evaluate_fn=fake_evaluate, sleep_fn=lambda _: None)
            self.assertEqual(len(calls), 1)
            self.assertEqual(summary["stop_reason"], "rate_limited")
            self.assertEqual(summary["executed_runs"], 1)
            self.assertEqual(summary["by_case"][CASES[0]]["missing"], 2)
            self.assertEqual(summary["by_case"][CASES[1]]["passed"], 0)

    def test_total_budget_checked_between_runs(self):
        cases = select_case_ids(load_cases(), list(CASES))
        calls = []
        def fake_evaluate(*args, **kwargs):
            calls.append(kwargs)
            return synthetic_report(requests=5)
        with TemporaryDirectory() as folder:
            summary = repeat(cases, provider="groq", runs=3,
                             max_total_requests=4, max_requests_per_run=12,
                             output_dir=Path(folder), evaluate_fn=fake_evaluate,
                             sleep_fn=lambda _: None)
            self.assertEqual(calls[0]["max_requests"], 4)
            self.assertEqual(len(calls), 1)
            self.assertEqual(summary["stop_reason"], "total_request_budget")
            self.assertEqual(summary["llm_requests"], 5)

    def test_partial_run_not_recorded_as_full_success(self):
        cases = select_case_ids(load_cases(), list(CASES))
        with TemporaryDirectory() as folder:
            summary = repeat(cases, provider="groq", runs=3,
                             output_dir=Path(folder), sleep_fn=lambda _: None,
                             evaluate_fn=lambda *args, **kwargs: synthetic_report(partial=True, requests=1))
            self.assertEqual(summary["stop_reason"], "partial_run_budget")
            self.assertEqual(summary["complete_runs"], 0)
            self.assertEqual(summary["by_case"][CASES[1]]["missing"], 3)

    def test_destination_collision_prevents_api_usage(self):
        cases = select_case_ids(load_cases(), list(CASES))
        with TemporaryDirectory() as folder:
            target = Path(folder) / "run_01.json"
            target.write_text("old report", encoding="utf-8")
            def should_not_run(*args, **kwargs):
                self.fail("would have called the provider before detecting file collision")
            with self.assertRaises(FileExistsError):
                repeat(cases, provider="groq", runs=3, output_dir=Path(folder),
                       evaluate_fn=should_not_run)
            self.assertEqual(target.read_text(encoding="utf-8"), "old report")

    def test_aggregate_pass_rates_are_not_inflated(self):
        summary = summarize([synthetic_report(passed=False), synthetic_report(passed=True)],
                            list(CASES), requested_runs=3, provider="offline",
                            stop_reason="test_stop")
        self.assertEqual(summary["by_case"][CASES[0]]["passed"], 1)
        self.assertEqual(summary["by_case"][CASES[0]]["failed"], 1)
        self.assertEqual(summary["by_case"][CASES[0]]["missing"], 1)
        self.assertEqual(summary["by_case"][CASES[0]]["pass_rate_pct"], 33.3)


if __name__ == "__main__":
    unittest.main()
