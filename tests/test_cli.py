from pathlib import Path
import tempfile

import unittest

from googlephotos_cleaner.cli import build_parser, parse_args

class MainFlowTests(unittest.TestCase):
    def test_main_writes_one_public_terminal_lifecycle(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass

        class Cleaner:
            last_outcome = type("Outcome", (), {"value": "pass_done"})()
            stop_requested = True
            def __init__(self, *args, **kwargs):
                self.diagnostic = kwargs["diagnostic"]
            def run(self):
                self.diagnostic.event("run_started", mode="dry-run")
                return 1

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                self.assertEqual(main.run(["--dry-run", "--max-batches", "1", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")]), 0)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        phases = [event["phase"] for event in events]
        self.assertEqual(phases.count("run_started"), 1)
        self.assertEqual(phases.count("cleaner_stopped"), 1)
        self.assertEqual(phases.count("run_finished"), 1)
        self.assertNotIn("cleaner_terminal_state", phases)
        stopped = next(event for event in events if event["phase"] == "cleaner_stopped")
        finished = next(event for event in events if event["phase"] == "run_finished")
        self.assertFalse(stopped["positive_feedback"])
        self.assertIsNone(stopped["feedback_source"])
        self.assertEqual(stopped["result"], "terminal_summary")
        self.assertFalse(finished["positive_feedback"])
        self.assertIsNone(finished["feedback_source"])
        self.assertEqual(finished["result"], "run_finished")
        self.assertTrue(stopped["stop_requested"])
        self.assertTrue(finished["stop_requested"])
        for event in (stopped, finished):
            self.assertIn("pid", event)
            self.assertIn("pending_path", event)
            self.assertIn("checkpoint_path", event)
            self.assertIn("outcome", event)
            self.assertIn("profile_dir", event)
            self.assertIn("profile_lock_path", event)

    def test_main_failure_terminal_events_have_non_proof_evidence(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass

        class Cleaner:
            last_outcome = type("Outcome", (), {"value": "destructive_ambiguous"})()
            stop_requested = True
            def __init__(self, *args, **kwargs):
                self.diagnostic = kwargs["diagnostic"]
            def run(self):
                raise RuntimeError("ambiguous")

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                self.assertEqual(main.run(["--dry-run", "--exit-on-error", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")]), 1)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        failed = next(event for event in events if event["phase"] == "run_failed")
        for event in (failed, next(event for event in events if event["phase"] == "cleaner_stopped"), next(event for event in events if event["phase"] == "run_finished")):
            self.assertIn("result", event)
            self.assertIn("positive_feedback", event)
            self.assertIn("feedback_source", event)
            self.assertFalse(event["positive_feedback"])
            self.assertIsNone(event["feedback_source"])

    def test_keyboard_interrupt_finalizes_terminal_checkpoint_context(self):
        import json
        import main
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            checkpoint = Path(tmp) / "checkpoint.json"
            with patch.object(main, "PlaywrightBrowser", side_effect=KeyboardInterrupt()):
                self.assertEqual(main.run(["--dry-run", "--log-file", str(log), "--checkpoint-file", str(checkpoint), "--profile-dir", str(Path(tmp) / "profile")]), 130)
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved["state"], "interrupted")
            self.assertEqual(saved["reason"], "keyboard_interrupt")
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]
            finished = next(event for event in events if event["phase"] == "run_finished")
            self.assertEqual(finished["result"], "run_finished")
            self.assertFalse(finished["positive_feedback"])
            self.assertIsNone(finished["feedback_source"])

    def test_close_failure_finalizes_checkpoint_and_non_proof_events(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                raise RuntimeError("close failed")

        class Cleaner:
            last_outcome = type("Outcome", (), {"value": "pass_done"})()
            stop_requested = True
            def __init__(self, *args, **kwargs):
                self.diagnostic = kwargs["diagnostic"]
            def run(self):
                self.diagnostic.event("run_started", mode="dry-run")
                return 1

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            checkpoint = Path(tmp) / "checkpoint.json"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                self.assertEqual(main.run(["--dry-run", "--max-batches", "1", "--log-file", str(log), "--checkpoint-file", str(checkpoint), "--profile-dir", str(Path(tmp) / "profile")]), 1)
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved["state"], "close_failed")
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]
            close_event = next(event for event in events if event["phase"] == "browser_close_failed")
            self.assertFalse(close_event["positive_feedback"])
            self.assertIsNone(close_event["feedback_source"])

    def test_main_run_finished_preserves_terminal_checkpoint_state(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass

        class Cleaner:
            last_outcome = type("Outcome", (), {"value": "pass_done"})()
            stop_requested = True
            def __init__(self, *args, **kwargs):
                self.diagnostic = kwargs["diagnostic"]
            def run(self):
                self.diagnostic.event("run_started", mode="dry-run")
                return 1

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            checkpoint = Path(tmp) / "checkpoint.json"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                self.assertEqual(main.run(["--dry-run", "--max-batches", "1", "--log-file", str(log), "--checkpoint-file", str(checkpoint), "--profile-dir", str(Path(tmp) / "profile")]), 0)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]
            finished = next(event for event in events if event["phase"] == "run_finished")
            self.assertEqual(finished["outcome"], "pass_done")
            self.assertFalse(checkpoint.exists())

    def test_main_writes_finished_outcome_on_keyboard_interrupt(self):
        import json
        import main
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", side_effect=KeyboardInterrupt()):
                self.assertEqual(main.run(["--dry-run", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")]), 130)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        finished = next(event for event in events if event["phase"] == "run_finished")
        self.assertEqual(finished["outcome"], "interrupted")
        self.assertTrue(all("html" not in event for event in events))

    def test_runtime_error_preserves_terminal_outcome_and_checkpoint_reason(self):
        import json
        import main
        from unittest.mock import patch
        from googlephotos_cleaner.automation import PassOutcome

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass

        class Cleaner:
            last_outcome = PassOutcome.PENDING_UNRESOLVED
            stop_requested = True
            def __init__(self, *args, **kwargs):
                self.diagnostic = kwargs["diagnostic"]
            def run(self):
                raise RuntimeError("pending reconciliation failed")

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            checkpoint = Path(tmp) / "checkpoint.json"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                self.assertEqual(main.run(["--dry-run", "--exit-on-error", "--log-file", str(log), "--checkpoint-file", str(checkpoint), "--profile-dir", str(Path(tmp) / "profile")]), 1)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]
            saved = json.loads(checkpoint.read_text())

        self.assertEqual(saved["state"], "pending")
        self.assertEqual(saved["reason"], "pending_reconciliation_failed")
        failed = next(event for event in events if event["phase"] == "run_failed")
        stopped = next(event for event in events if event["phase"] == "cleaner_stopped")
        finished = next(event for event in events if event["phase"] == "run_finished")
        self.assertEqual(failed["outcome"], "pending_unresolved")
        for event in (stopped, finished):
            self.assertEqual(event["outcome"], "pending_unresolved")
            self.assertEqual(event["checkpoint_state"], "pending")
            self.assertEqual(event["checkpoint_reason"], "pending_reconciliation_failed")

    def test_pending_reconcile_command_does_not_click_trash(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            last_feedback_source = None
            def close(self):
                pass
            def wait_until_authenticated(self):
                pass
            def target_exists(self, label):
                return True
            def wait_for_target_absence(self, label, timeout_ms):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            import json as json_module
            from googlephotos_cleaner.diagnostics import PendingActionStore
            pending_path = Path(tmp) / "pending-action.json"
            PendingActionStore(pending_path).save(label="pending day", kind="day", scroll_top=0)
            log = Path(tmp) / "run.log"
            checkpoint = Path(tmp) / "checkpoint.json"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()):
                self.assertEqual(main.run(["--reconcile-pending", "--exit-on-error", "--log-file", str(log), "--checkpoint-file", str(checkpoint), "--profile-dir", str(Path(tmp) / "profile")]), 0)
            events = [json_module.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        self.assertFalse(pending_path.exists())
        self.assertFalse(any(event["phase"] == "trash_click_started" for event in events))
        reconciled = next(event for event in events if event["phase"] == "pending_unresolved")
        self.assertFalse(reconciled["positive_feedback"])
        self.assertIsNone(reconciled["feedback_source"])

    def test_reconcile_pending_without_journal_is_safe_noop(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass
            def wait_until_authenticated(self):
                self.auth_calls = getattr(self, "auth_calls", 0) + 1

        with tempfile.TemporaryDirectory() as tmp:
            import json as json_module
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()):
                self.assertEqual(main.run(["--reconcile-pending", "--exit-on-error", "--log-file", str(log), "--checkpoint-file", str(Path(tmp) / "checkpoint.json"), "--profile-dir", str(Path(tmp) / "profile")]), 0)
            events = [json_module.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        self.assertEqual(sum(event["phase"] == "run_started" for event in events), 1)
        self.assertEqual(sum(event["phase"] == "cleaner_stopped" for event in events), 1)
        self.assertEqual(sum(event["phase"] == "run_finished" for event in events), 1)
        self.assertEqual(next(event for event in events if event["phase"] == "cleaner_stopped")["outcome"], "pass_done")

    def test_main_preserves_cleaner_ambiguous_outcome(self):
        import json
        import main
        from googlephotos_cleaner.automation import PassOutcome
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass

        class Cleaner:
            last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
            stop_requested = True
            def __init__(self, *args, **kwargs):
                pass
            def run(self):
                raise RuntimeError("ambiguous")

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                self.assertEqual(main.run(["--dry-run", "--exit-on-error", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")]), 1)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        finished = next(event for event in events if event["phase"] == "run_finished")
        stopped = next(event for event in events if event["phase"] == "cleaner_stopped")
        self.assertEqual(finished["outcome"], "destructive_ambiguous")
        self.assertEqual(stopped["outcome"], "destructive_ambiguous")
        self.assertEqual(sum(event["phase"] == "diagnostics_failed" for event in events), 1)

    def test_main_records_cleanup_status_when_browser_construction_fails(self):
        import json
        import main
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", side_effect=RuntimeError("boom")):
                self.assertEqual(main.run(["--dry-run", "--exit-on-error", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")]), 1)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        stopped = next(event for event in events if event["phase"] == "cleaner_stopped")
        finished = next(event for event in events if event["phase"] == "run_finished")
        self.assertEqual(stopped["browser_cleanup"], "not_started")
        self.assertEqual(finished["browser_cleanup"], "not_started")

    def test_main_records_cleanup_failure_in_terminal_events(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                raise RuntimeError("close boom")

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", side_effect=RuntimeError("run boom")):
                self.assertEqual(main.run(["--dry-run", "--exit-on-error", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")]), 1)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        for phase in ("cleaner_stopped", "run_finished"):
            event = next(event for event in events if event["phase"] == phase)
            self.assertEqual(event["browser_cleanup"], "failed")

    def test_main_writes_failed_terminal_lifecycle(self):
        import json
        import main
        from unittest.mock import patch

        class FailingBrowser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", side_effect=RuntimeError("boom")):
                self.assertEqual(main.run(["--dry-run", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")]), 1)
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        phases = [event["phase"] for event in events]
        self.assertIn("run_failed", phases)
        self.assertEqual(phases.count("cleaner_stopped"), 1)
        finished = next(event for event in events if event["phase"] == "run_finished")
        self.assertEqual(finished["outcome"], "failed")
        self.assertIn("browser_open", finished)
        self.assertIn("profile_dir", finished)
        self.assertEqual(phases.count("run_finished"), 1)

    def test_main_and_cleaner_emit_one_run_started(self):
        import json
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()
            def close(self):
                pass

        class Cleaner:
            last_outcome = type("Outcome", (), {"value": "pass_done"})()
            stop_requested = True
            def __init__(self, *args, **kwargs):
                self.diagnostic = kwargs["diagnostic"]
            def run(self):
                self.diagnostic.event("run_started", mode="dry-run")
                return 1

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                main.run(["--dry-run", "--max-batches", "1", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")])
            events = [json.loads(line) for line in log.with_name("run.jsonl").read_text().splitlines()]

        self.assertEqual(sum(event["phase"] == "run_started" for event in events), 1)

    def test_main_uses_one_cleaner_pass(self):
        import main
        from unittest.mock import patch

        class Browser:
            profile_dir = Path("profile")
            profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
            page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
            context = type("Context", (), {"pages": [page]})()

            def close(self):
                pass

        class Cleaner:
            last_outcome = type("Outcome", (), {"value": "pass_done"})()
            stop_requested = True

            def __init__(self, *args, **kwargs):
                self.calls = 0

            def run(self):
                self.calls += 1
                return 1

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=Browser()), patch.object(main, "Cleaner", Cleaner):
                result = main.run(["--dry-run", "--max-batches", "1", "--log-file", str(log), "--profile-dir", str(Path(tmp) / "profile")])

        self.assertEqual(result, 0)


class HandoffTests(unittest.TestCase):
    def test_handoff_has_current_status_block(self):
        handoff = Path(__file__).resolve().parents[1] / "HANDOFF-2026-08-24-googlephotos-scan.md"
        text = handoff.read_text(encoding="utf-8")

        self.assertIn("## Stato corrente", text)
        self.assertRegex(text, r"Current (?:worktree|main) commit: `[0-9a-f]+`")
        self.assertTrue("Nessun merge su `main`" in text or "Merge completato in `main`" in text)

class CliTests(unittest.TestCase):
    def test_parser_accepts_inactivity_timeout(self):
        args = parse_args(["--inactivity-timeout-seconds", "12"])
        self.assertEqual(args.inactivity_timeout_seconds, 12)

    def test_parser_accepts_cdp_url(self):
        args = parse_args(["--cdp-url", "http://127.0.0.1:9222"])
        self.assertEqual(args.cdp_url, "http://127.0.0.1:9222")

    def test_main_wires_browser_connection_and_timeout_options(self):
        import main
        from unittest.mock import Mock, patch

        browser = Mock()
        browser.profile_dir = Path("profile")
        browser.profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
        browser.page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
        browser.context = type("Context", (), {"pages": [browser.page]})()
        browser.close = Mock()
        cleaner = Mock()
        cleaner.last_outcome = type("Outcome", (), {"value": "pass_done"})()
        cleaner.stop_requested = True
        cleaner.run.return_value = 0

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=browser) as browser_factory, patch.object(main, "Cleaner", return_value=cleaner):
                result = main.run([
                    "--cdp-url", "http://127.0.0.1:9222",
                    "--inactivity-timeout-seconds", "12",
                    "--log-file", str(log),
                    "--profile-dir", str(Path(tmp) / "profile"),
                ])

        self.assertEqual(result, 0)
        self.assertEqual(browser_factory.call_args.kwargs["cdp_url"], "http://127.0.0.1:9222")
        self.assertEqual(browser_factory.call_args.kwargs["inactivity_timeout_seconds"], 12)

    def test_main_wires_authorization_and_pointer_options(self):
        import main
        from unittest.mock import Mock, patch

        browser = Mock()
        browser.profile_dir = Path("profile")
        browser.profile_lock = type("Lock", (), {"path": Path("profile/.lock"), "pid": 7, "acquired": True})()
        browser.page = type("Page", (), {"url": "https://photos.google.com/u/0/"})()
        browser.context = type("Context", (), {"pages": [browser.page]})()
        browser.close = Mock()
        cleaner = Mock()
        cleaner.last_outcome = type("Outcome", (), {"value": "pass_done"})()
        cleaner.stop_requested = True
        cleaner.run.return_value = 0

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with patch.object(main, "PlaywrightBrowser", return_value=browser) as browser_factory, patch.object(main, "Cleaner", return_value=cleaner) as cleaner_factory:
                result = main.run([
                    "--execute",
                    "--confirm-all-media-to-trash",
                    "--max-batches", "1",
                    "--pointer-pause-ms", "17",
                    "--pointer-max-steps", "3",
                    "--log-file", str(log),
                    "--profile-dir", str(Path(tmp) / "profile"),
                ])

        self.assertEqual(result, 0)
        self.assertEqual(browser_factory.call_args.kwargs["pointer_pause_ms"], 17)
        self.assertEqual(browser_factory.call_args.kwargs["pointer_max_steps"], 3)
        self.assertTrue(cleaner_factory.call_args.kwargs["execute"])
        self.assertTrue(cleaner_factory.call_args.kwargs["confirm_all_media_to_trash"])

    def test_parser_has_safe_defaults(self):
        args = parse_args([])

        self.assertTrue(args.dry_run)
        self.assertFalse(args.execute)
        self.assertFalse(args.confirm_all_media_to_trash)
        self.assertIsNone(args.max_batches)
        self.assertEqual(args.profile_dir, Path("data/browser-profile"))
        self.assertEqual(args.log_file, Path("data/run.log"))
        self.assertEqual(args.diagnostics_dir, Path("data/diagnostics"))
        self.assertEqual(args.checkpoint_file, Path("data/checkpoint.json"))
        self.assertEqual(args.max_retries, 2)
        self.assertFalse(args.exit_on_error)
        self.assertEqual(args.max_idle_scrolls, 5)
        self.assertEqual(args.selection_size, 1)
        self.assertFalse(args.media_first)
        self.assertEqual(args.scroll_step, 240)
        self.assertEqual(args.scroll_delay_ms, 1500)
        self.assertEqual(args.pending_action, "inspect")
        self.assertEqual(args.pending_timeout_ms, 30000)

    def test_parser_supports_diagnostic_runtime_context_defaults(self):
        args = parse_args([])

        self.assertEqual(args.diagnostics_dir, Path("data/diagnostics"))
        self.assertEqual(args.profile_dir, Path("data/browser-profile"))

    def test_parser_requires_explicit_destructive_authorization(self):
        with self.assertRaises(SystemExit):
            parse_args(["--execute"])
        with self.assertRaises(SystemExit):
            parse_args(["--confirm-all-media-to-trash"])

        args = parse_args(["--execute", "--confirm-all-media-to-trash"])
        self.assertTrue(args.execute)
        self.assertTrue(args.confirm_all_media_to_trash)
        self.assertFalse(args.dry_run)

    def test_parser_rejects_dry_run_with_destructive_authorization(self):
        with self.assertRaises(SystemExit):
            parse_args(
                ["--dry-run", "--execute", "--confirm-all-media-to-trash"]
            )

    def test_parser_supports_dry_run_and_batch_limit(self):
        args = parse_args(
            [
                "--dry-run",
                "--max-batches",
                "3",
                "--max-retries",
                "4",
                "--profile-dir",
                "custom/profile",
                "--diagnostics-dir",
                "custom/diagnostics",
                "--checkpoint-file",
                "custom/checkpoint.json",
            ]
        )

        self.assertTrue(args.dry_run)
        self.assertEqual(args.max_batches, 3)
        self.assertEqual(args.profile_dir, Path("custom/profile"))
        self.assertEqual(args.max_retries, 4)
        self.assertEqual(args.diagnostics_dir, Path("custom/diagnostics"))
        self.assertEqual(args.checkpoint_file, Path("custom/checkpoint.json"))

    def test_parser_supports_selection_size(self):
        args = parse_args(["--selection-size", "4"])
        self.assertEqual(args.selection_size, 4)

    def test_parser_supports_media_first_mode(self):
        args = parse_args(["--selection-size", "100", "--media-first"])
        self.assertEqual(args.selection_size, 100)
        self.assertTrue(args.media_first)

    def test_parser_supports_scroll_and_pointer_tuning(self):
        args = parse_args(
            [
                "--scroll-step",
                "180",
                "--scroll-delay-ms",
                "2000",
                "--pointer-pause-ms",
                "60",
                "--pointer-max-steps",
                "5",
            ]
        )
        self.assertEqual(args.scroll_step, 180)
        self.assertEqual(args.scroll_delay_ms, 2000)
        self.assertEqual(args.pointer_pause_ms, 60)
        self.assertEqual(args.pointer_max_steps, 5)

    def test_parser_supports_pending_policies(self):
        args = parse_args(["--pending-action", "inspect", "--pending-timeout-ms", "5000"])
        self.assertEqual(args.pending_action, "inspect")
        self.assertEqual(args.pending_timeout_ms, 5000)

    def test_parser_supports_idle_scroll_limit(self):
        args = parse_args(["--max-idle-scrolls", "7"])
        self.assertEqual(args.max_idle_scrolls, 7)

    def test_parser_supports_day_scan_attempt_limit(self):
        args = parse_args(["--max-day-scan-failures", "4"])
        self.assertEqual(args.max_day_scan_failures, 4)

    def test_parser_supports_exit_on_error(self):
        args = parse_args(["--exit-on-error"])
        self.assertTrue(args.exit_on_error)

    def test_parser_rejects_negative_retries(self):
        with self.assertRaises(SystemExit):
            parse_args(["--max-retries", "-1"])

    def test_parser_rejects_non_positive_batch_limit(self):
        with self.assertRaises(SystemExit):
            parse_args(["--max-batches", "0"])

    def test_help_is_available(self):
        parser = build_parser()

        self.assertIn("Google Photos", parser.description)


if __name__ == "__main__":
    unittest.main()
