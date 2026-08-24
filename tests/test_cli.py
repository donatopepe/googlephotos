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
                pass
            def run(self):
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
        for event in (stopped, finished):
            self.assertIn("pid", event)
            self.assertIn("pending_path", event)
            self.assertIn("checkpoint_path", event)
            self.assertIn("outcome", event)
            self.assertIn("profile_dir", event)
            self.assertIn("profile_lock_path", event)

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
    def test_handoff_records_current_terminal_commit(self):
        handoff = Path("/home/public/googlephotos/HANDOFF-2026-08-24-googlephotos-scan.md")
        text = handoff.read_text(encoding="utf-8")

        self.assertIn("237122e", text)
        self.assertIn("Nessun merge su `main`", text)

class CliTests(unittest.TestCase):
    def test_parser_has_safe_defaults(self):
        args = parse_args([])

        self.assertFalse(args.dry_run)
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
        self.assertEqual(args.pending_action, "block")
        self.assertEqual(args.pending_timeout_ms, 30000)

    def test_parser_supports_diagnostic_runtime_context_defaults(self):
        args = parse_args([])

        self.assertEqual(args.diagnostics_dir, Path("data/diagnostics"))
        self.assertEqual(args.profile_dir, Path("data/browser-profile"))

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

    def test_parser_supports_scroll_tuning(self):
        args = parse_args(["--scroll-step", "180", "--scroll-delay-ms", "2000"])
        self.assertEqual(args.scroll_step, 180)
        self.assertEqual(args.scroll_delay_ms, 2000)

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
