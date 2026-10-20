#!/usr/bin/env python3
"""Offline tests for peerreview.py. Nothing here touches the network.

Every test runs with PEERREVIEW_HOME pointed at a temp dir and `request`
replaced by a stub that fails the test if called, so a test that would spend
money, or write to a real ledger, can't.

    python3 -m unittest discover -s plugins/peerreview/tests
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "peerreview" / "scripts"))
import peerreview as pr  # noqa: E402

MODEL = "lab/model-a"
# $1 per million in, $10 per million out.
PRICES = {MODEL: (1e-6, 1e-5), "lab/cheap": (1e-8, 1e-7)}


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        old = os.environ.get("PEERREVIEW_HOME")
        os.environ["PEERREVIEW_HOME"] = str(self.dir / "home")
        self.addCleanup(self._restore_env, old)
        os.environ.pop("PEERREVIEW_MODEL", None)
        old_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = "test-key-not-real"
        self.addCleanup(self._restore_key, old_key)

        self.calls = []
        self.real_model_prices = pr.model_prices
        self._patch("request", self._forbidden)
        self._patch("model_prices", lambda refresh=True: dict(PRICES))
        self._patch("balance", lambda: None)

    def _restore_env(self, old):
        if old is None:
            os.environ.pop("PEERREVIEW_HOME", None)
        else:
            os.environ["PEERREVIEW_HOME"] = old

    def _restore_key(self, old):
        if old is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = old

    def _patch(self, name, value):
        real = getattr(pr, name)
        setattr(pr, name, value)
        self.addCleanup(setattr, pr, name, real)

    def _forbidden(self, path, payload=None):
        self.fail(f"a test reached the network: {path}")

    def fake_review(self, prompt_tokens=1000, completion_tokens=500, text="FINDINGS"):
        def review(model, prompt, max_tokens):
            self.calls.append((model, prompt, max_tokens))
            return text, {"prompt_tokens": prompt_tokens,
                          "completion_tokens": completion_tokens}
        self._patch("review", review)

    def doc(self, body="A short document. 2 + 2 = 5.\n", name="doc.md"):
        p = self.dir / name
        p.write_text(body, encoding="utf-8")
        return p

    def jar(self, **fields):
        b = pr.default_budget()
        b.update(fields)
        pr.config_dir().mkdir(parents=True, exist_ok=True)
        pr.write_budget(b)
        return b

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = pr.main([str(a) for a in argv])
        return rc, out.getvalue(), err.getvalue()


class Defaults(Sandbox):
    def test_the_defaults_are_the_published_ones(self):
        self.assertEqual(pr.DEFAULT_MODEL, "openai/gpt-5.1")
        self.assertEqual(pr.DEFAULT_JAR, 2.00)
        self.assertEqual(pr.DEFAULT_CEILING, 0.50)

    def test_config_lives_under_peerreview_home(self):
        self.assertEqual(pr.budget_file(), self.dir / "home" / "budget.json")
        self.assertEqual(pr.ledger_file(), self.dir / "home" / "ledger.jsonl")

    def test_without_peerreview_home_it_uses_xdg(self):
        os.environ.pop("PEERREVIEW_HOME")
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(self.dir / "xdg")
        try:
            self.assertEqual(pr.config_dir(), self.dir / "xdg" / "peerreview")
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME")
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    def test_with_no_model_set_it_uses_the_default(self):
        self.jar()
        self._patch("model_prices", lambda refresh=True: {pr.DEFAULT_MODEL: PRICES[MODEL]})
        self.fake_review()
        rc, _, _ = self.run_main(self.doc())
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls[0][0], pr.DEFAULT_MODEL)

    def test_the_environment_overrides_the_default_model(self):
        self.jar()
        os.environ["PEERREVIEW_MODEL"] = MODEL
        self.addCleanup(os.environ.pop, "PEERREVIEW_MODEL", None)
        self.fake_review()
        self.run_main(self.doc())
        self.assertEqual(self.calls[0][0], MODEL)


class Rubric(Sandbox):
    def test_it_forbids_a_clean_review(self):
        self.assertIn("looks good, minor suggestions", pr.DEFAULT_RUBRIC)

    def test_it_bans_grading_unverifiable_claims(self):
        self.assertIn("UNVERIFIABLE HERE", pr.DEFAULT_RUBRIC)

    def test_it_requires_reading_the_whole_document_first(self):
        self.assertIn("READ THE WHOLE DOCUMENT", pr.DEFAULT_RUBRIC)

    def test_the_document_goes_last_and_context_is_marked(self):
        p = pr.build_prompt("DOC BODY", "d.md", "RUBRIC", [("ref.md", "REF BODY")])
        self.assertTrue(p.rstrip().endswith("--- END DOCUMENT ---"))
        self.assertLess(p.index("REF BODY"), p.index("DOC BODY"))
        self.assertIn("Do not review it", p)

    def test_review_sends_a_low_temperature_completion(self):
        sent = {}
        self._patch("request", lambda path, payload=None: (
            sent.update(path=path, payload=payload)
            or {"choices": [{"message": {"content": "ok"}}], "usage": {}}))
        pr.review(MODEL, "hi", 100)
        self.assertEqual(sent["path"], "/chat/completions")
        self.assertEqual(sent["payload"]["temperature"], 0.2)


class Cost(Sandbox):
    def test_prices_input_and_the_full_output_cap(self):
        cost, in_tokens = pr.estimate_cost(MODEL, "x" * 4000, 1000, PRICES)
        self.assertEqual(in_tokens, 1000)
        self.assertAlmostEqual(cost, 1000 * 1e-6 + 1000 * 1e-5)

    def test_an_unknown_model_is_none_not_zero(self):
        cost, _ = pr.estimate_cost("lab/unknown", "x", 10, PRICES)
        self.assertIsNone(cost)

    def test_a_malformed_models_response_falls_back_instead_of_crashing(self):
        pr.config_dir().mkdir(parents=True)
        pr.price_cache().write_text(json.dumps({MODEL: [1, 2]}))
        self._patch("request", lambda path, payload=None: {"data": "not a list"})
        self.assertEqual(self.real_model_prices(), {MODEL: (1, 2)})


class Ledger(Sandbox):
    def test_appends_one_line_per_call(self):
        pr.append_ledger({"model": MODEL, "cost": 0.01})
        pr.append_ledger({"model": MODEL, "cost": 0.02})
        self.assertEqual(len(pr.read_ledger()), 2)

    def test_a_torn_line_loses_one_row_not_the_history(self):
        pr.append_ledger({"model": MODEL, "cost": 0.01})
        with pr.ledger_file().open("a") as fh:
            fh.write('{"model": "torn\n')
        pr.append_ledger({"model": MODEL, "cost": 0.02})
        self.assertEqual(len(pr.read_ledger()), 2)

    def test_an_unwritable_ledger_warns_and_does_not_raise(self):
        err = io.StringIO()
        with redirect_stderr(err):
            blocker = self.dir / "blocker"
            blocker.write_text("a file where a directory should be")
            pr.append_ledger({"x": 1}, blocker / "ledger.jsonl")
        self.assertIn("warning", err.getvalue())

    def test_unpriced_calls_are_declared_not_hidden(self):
        text = pr.summarize_ledger([{"model": MODEL, "cost": None}])
        self.assertIn("no price on file", text)


class BudgetJar(Sandbox):
    def test_first_run_creates_the_default_jar_and_says_so(self):
        self.fake_review()
        rc, _, err = self.run_main(self.doc(), "--model", MODEL)
        self.assertEqual(rc, 0)
        self.assertIn("Created a budget jar", err)
        self.assertEqual(pr.load_budget()["jar"], 2.00)

    def test_an_unreadable_jar_refuses_and_sends_nothing(self):
        pr.config_dir().mkdir(parents=True)
        pr.budget_file().write_text("{not json")
        self.fake_review()
        rc, _, err = self.run_main(self.doc(), "--model", MODEL)
        self.assertEqual(rc, 1)
        self.assertIn("unreadable", err)
        self.assertEqual(self.calls, [])

    def test_an_unreadable_jar_is_not_replaced_with_a_fresh_one(self):
        pr.config_dir().mkdir(parents=True)
        pr.budget_file().write_text("{not json")
        self.fake_review()
        self.run_main(self.doc(), "--model", MODEL)
        self.assertEqual(pr.budget_file().read_text(), "{not json")

    def test_a_bad_field_refuses(self):
        for bad in (-1, "2", True, None):
            pr.config_dir().mkdir(parents=True, exist_ok=True)
            pr.budget_file().write_text(json.dumps({"jar": bad, "ceiling": 0.5, "spent": 0}))
            with self.assertRaises(pr.Refused):
                pr.load_budget()

    def test_over_the_ceiling_stops_and_sends_nothing(self):
        self.jar(ceiling=0.001)
        self.fake_review()
        rc, _, err = self.run_main(self.doc(), "--model", MODEL)
        self.assertEqual(rc, 1)
        self.assertIn("per-call ceiling", err)
        self.assertEqual(self.calls, [])

    def test_over_what_is_left_stops_and_sends_nothing(self):
        self.jar(spent=1.999)
        self.fake_review()
        rc, _, err = self.run_main(self.doc(), "--model", MODEL)
        self.assertEqual(rc, 1)
        self.assertIn("Not enough left", err)
        self.assertEqual(self.calls, [])

    def test_an_unpriced_model_never_auto_spends(self):
        self.jar()
        self.fake_review()
        rc, _, err = self.run_main(self.doc(), "--model", "lab/unknown")
        self.assertEqual(rc, 1)
        self.assertIn("can't be costed", err)
        self.assertEqual(self.calls, [])

    def test_the_upper_bound_is_debited_before_the_call(self):
        self.jar()
        seen = {}
        def review(model, prompt, max_tokens):
            seen["spent_during_call"] = pr.load_budget()["spent"]
            return "ok", {"prompt_tokens": 10, "completion_tokens": 10}
        self._patch("review", review)
        self.run_main(self.doc(), "--model", MODEL, "--max-tokens", 1000)
        self.assertGreaterEqual(seen["spent_during_call"], 1000 * 1e-5)

    def test_settling_charges_actual_tokens_not_the_cap(self):
        self.jar()
        self.fake_review(prompt_tokens=1000, completion_tokens=500)
        self.run_main(self.doc(), "--model", MODEL, "--max-tokens", 8000)
        self.assertAlmostEqual(pr.load_budget()["spent"], 1000 * 1e-6 + 500 * 1e-5, places=6)

    def test_the_jar_and_the_ledger_agree_after_calls(self):
        self.jar()
        self.fake_review(prompt_tokens=1234, completion_tokens=567)
        for _ in range(3):
            self.run_main(self.doc(), "--model", MODEL)
        ledger = sum(r["cost"] for r in pr.read_ledger())
        self.assertAlmostEqual(pr.load_budget()["spent"], ledger, places=6)
        self.assertNotIn("disagree", pr.format_budget(pr.load_budget(), pr.read_ledger()))

    def test_a_real_mismatch_is_reported(self):
        self.jar(spent=0.5)
        pr.append_ledger({"at": "9999", "model": MODEL, "cost": 0.1})
        self.assertIn("disagree", pr.format_budget(pr.load_budget(), pr.read_ledger()))

    def test_approve_lets_one_over_ceiling_call_through_and_records_it(self):
        self.jar(ceiling=0.001)
        self.fake_review()
        rc, _, err = self.run_main(self.doc(), "--model", MODEL, "--approve")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(pr.read_ledger()), 1)

    def test_init_budget_will_not_overwrite_a_jar_with_spend(self):
        self.jar(spent=1.0)
        rc, _, err = self.run_main("--init-budget")
        self.assertEqual(rc, 1)
        self.assertEqual(pr.load_budget()["spent"], 1.0)


class Plan(Sandbox):
    def test_plan_sends_nothing_and_writes_no_ledger(self):
        self.jar()
        self.fake_review()
        rc, out, _ = self.run_main(self.doc(), "--model", MODEL, "--plan")
        self.assertEqual(rc, 0)
        self.assertIn("nothing has been sent", out)
        self.assertEqual(self.calls, [])
        self.assertEqual(pr.read_ledger(), [])
        self.assertEqual(pr.load_budget()["spent"], 0.0)

    def test_plan_warns_when_the_run_would_stop(self):
        self.jar(ceiling=0.001)
        _, out, _ = self.run_main(self.doc(), "--model", MODEL, "--plan")
        self.assertIn("WILL STOP", out)

    def test_plan_does_not_cry_wolf(self):
        self.jar()
        _, out, _ = self.run_main(self.doc(), "--model", MODEL, "--plan")
        self.assertNotIn("WILL STOP", out)
        self.assertNotIn("SWEEP", out)

    def test_an_unaffordable_account_is_called_out(self):
        self.jar()
        self._patch("balance", lambda: 0.0001)
        _, out, _ = self.run_main(self.doc(), "--model", MODEL, "--plan")
        self.assertIn("will reject", out)


class ContentSweep(Sandbox):
    def test_catches_secrets_and_account_shapes(self):
        # Built from pieces so this file doesn't trip a repo secret scanner.
        planted = "\n".join([
            "key " + "sk-" + "a" * 20,
            "aws " + "AKIA" + "A" * 16,
            "mail " + "someone" + "@" + "example.org",
            "call " + "(555) 555" + "-0142",
            "card " + "4" * 16,
        ])
        labels = {h[0] for h in pr.sweep_prompt(planted)}
        self.assertTrue({"OpenAI/OpenRouter key", "AWS access key", "email address",
                         "phone number", "account/card number"} <= labels)

    def test_a_hit_reports_its_line(self):
        hits = pr.sweep_prompt("a\nb\nmail " + "x" + "@" + "example.org")
        self.assertEqual(hits[0][2], 3)

    def test_ordinary_prose_with_numbers_is_clean(self):
        self.assertEqual(pr.sweep_prompt(
            "MTTR fell from 240 to 90 minutes across 1,204 incidents in 2026."), [])

    def test_a_hit_refuses_and_leaves_the_jar_untouched(self):
        self.jar()
        self.fake_review()
        rc, _, err = self.run_main(self.doc("contact " + "a" + "@" + "example.org"),
                                   "--model", MODEL)
        self.assertEqual(rc, 1)
        self.assertIn("Nothing was sent", err)
        self.assertEqual(self.calls, [])
        self.assertEqual(pr.load_budget()["spent"], 0.0)

    def test_approve_lets_a_sweep_hit_through(self):
        self.jar()
        self.fake_review()
        rc, _, _ = self.run_main(self.doc("contact " + "a" + "@" + "example.org"),
                                 "--model", MODEL, "--approve")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 1)


class Output(Sandbox):
    def test_output_flag_writes_to_disk_and_keeps_stdout_clean(self):
        self.jar()
        self.fake_review(text="THE FINDINGS")
        out_path = self.dir / "out.md"
        rc, out, _ = self.run_main(self.doc(), "--model", MODEL, "-o", out_path)
        self.assertEqual(rc, 0)
        self.assertIn("THE FINDINGS", out_path.read_text())
        self.assertNotIn("THE FINDINGS", out)

    def test_without_output_the_findings_go_to_stdout(self):
        self.jar()
        self.fake_review(text="THE FINDINGS")
        _, out, _ = self.run_main(self.doc(), "--model", MODEL)
        self.assertIn("THE FINDINGS", out)

    def test_no_key_says_so_instead_of_blaming_the_model(self):
        os.environ.pop("OPENROUTER_API_KEY")
        self.fake_review()
        rc, out, err = self.run_main(self.doc(), "--model", MODEL, "--plan")
        self.assertEqual(rc, 1)
        self.assertIn("No OPENROUTER_API_KEY", err)
        self.assertEqual(self.calls, [])

    def test_offline_plan_works_without_a_key(self):
        os.environ.pop("OPENROUTER_API_KEY")
        self.jar()
        rc, out, _ = self.run_main(self.doc(), "--model", MODEL, "--plan", "--offline")
        self.assertEqual(rc, 0)
        self.assertIn("nothing has been sent", out)

    def test_a_missing_document_is_refused(self):
        rc, _, err = self.run_main(self.dir / "nope.md")
        self.assertEqual(rc, 1)
        self.assertIn("Not a file", err)


if __name__ == "__main__":
    unittest.main()
