import os
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import Mock

from googlephotos_cleaner.automation import Cleaner, CleanerError, DestructiveActionAmbiguous, PassOutcome
from googlephotos_cleaner.diagnostics import CheckpointStore, DiagnosticLog, PendingActionStore


def _test_pending() -> PendingActionStore:
    fd, raw_path = tempfile.mkstemp(prefix="googlephotos-test-pending-", suffix=".json")
    os.close(fd)
    path = Path(raw_path)
    path.unlink()
    store = PendingActionStore(path)
    store._test_cleanup = weakref.finalize(store, path.unlink, missing_ok=True)
    return store


class FakeBrowser:
    last_feedback_source = "browser_positive_feedback"

    def __init__(self, batches):
        self.batches = list(batches)
        self.days = []
        self.trashed = []
        self.authenticated = True

    def wait_until_authenticated(self):
        if not self.authenticated:
            raise CleanerError("Google Photos session is not authenticated")

    def select_visible_batch(self, batch_size, *, excluded_media_ids=()):
        if not self.batches:
            return []
        excluded = set(excluded_media_ids)
        return [media_id for media_id in self.batches.pop(0) if media_id not in excluded][:batch_size]

    def select_current_day(self):
        if not self.batches:
            return None
        item = self.batches.pop(0)
        if isinstance(item, tuple):
            day, _photos = item
        else:
            day = f"day-{len(self.days) + 1}"
        self.days.append(day)
        return day

    def move_selected_to_trash(self, media_ids):
        self.trashed.append(list(media_ids))

    def delete_selected_day(self):
        self.trashed.append(["day"])
        return True

    def target_exists(self, _label):
        return False

    def advance_timeline(self):
        return False

    def close(self):
        pass


class RecoverableBrowser(FakeBrowser):
    def __init__(self):
        super().__init__([["old-1"]])
        self.recover_calls = 0
        self.scan_calls = 0

    def select_visible_batch(self, batch_size, *, excluded_media_ids=()):
        self.scan_calls += 1
        if self.scan_calls == 1:
            raise TimeoutError("temporary timeout")
        return super().select_visible_batch(batch_size, excluded_media_ids=excluded_media_ids)

    def recover(self):
        self.recover_calls += 1


class AmbiguousBrowser(FakeBrowser):
    def move_selected_to_trash(self, media_ids):
        raise TimeoutError("result unknown after trash click")

    def recover(self):
        raise AssertionError("must not recover after destructive action")


class BrowserAdapterTests(unittest.TestCase):
    def test_cleaner_terminal_state_events_have_non_proof_fields(self):
        terminal_cases = [
            ("pending", {"pending_exists": True}),
            ("ambiguous", {"pending_exists": True}),
        ]
        for outcome, expected in terminal_cases:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id=f"terminal-{outcome}")
                cleaner = Cleaner(FakeBrowser([]), dry_run=True, diagnostic=diagnostic)
                cleaner.last_outcome = PassOutcome.PENDING_UNRESOLVED if outcome == "pending" else PassOutcome.DESTRUCTIVE_AMBIGUOUS
                cleaner.stop_requested = True
                cleaner._event("cleaner_terminal_state", "WARNING", outcome=outcome, stop_requested=True, **expected)
                events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
                terminal = events[-1]
                self.assertFalse(terminal["positive_feedback"])
                self.assertIsNone(terminal["feedback_source"])
                self.assertEqual(terminal["result"], "terminal_state")

    def test_cleaner_reentry_terminal_event_has_non_proof_fields(self):
        cleaner = Cleaner(FakeBrowser([]), dry_run=True)
        cleaner.last_outcome = PassOutcome.PASS_DONE

        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="reentry-evidence")
            cleaner.diagnostic = diagnostic
            cleaner.run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            terminal = next(event for event in events if event["phase"] == "cleaner_terminal_state")
            self.assertFalse(terminal["positive_feedback"])
            self.assertIsNone(terminal["feedback_source"])
            self.assertEqual(terminal["result"], "already_terminal")

    def test_fake_adapter_exposes_authentication_and_batch_operations(self):
        browser = FakeBrowser([["old-1", "old-2"]])

        browser.wait_until_authenticated()
        selected = browser.select_visible_batch(50)
        browser.move_selected_to_trash(selected)

        self.assertEqual(selected, ["old-1", "old-2"])
        self.assertEqual(browser.trashed, [["old-1", "old-2"]])

    def test_cleaner_default_is_non_destructive(self):
        browser = FakeBrowser([["photo-1"]])

        processed = Cleaner(browser, day_mode=False, max_batches=1).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.trashed, [])
        self.assertEqual(Cleaner(browser, dry_run=True).last_outcome, PassOutcome.CONTINUE)

    def test_cleaner_default_day_mode_is_non_destructive(self):
        browser = FakeBrowser([["day-1"]])

        processed = Cleaner(browser, day_mode=True, max_batches=1).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.trashed, [])

    def test_cleaner_requires_execute_and_confirmation_for_trash(self):
        browser = FakeBrowser([["photo-1"]])

        with self.assertRaises(CleanerError):
            Cleaner(
                browser, pending=_test_pending(),
                day_mode=False,
                dry_run=False,
                execute=True,
                confirm_all_media_to_trash=False,
            )

        with self.assertRaises(CleanerError):
            Cleaner(
                browser, pending=_test_pending(),
                day_mode=False,
                dry_run=False,
                execute=False,
                confirm_all_media_to_trash=True,
            )

    def test_pending_is_saved_before_destructive_browser_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")

            class PendingAwareBrowser(FakeBrowser):
                def move_selected_to_trash(self, media_ids):
                    self.pending_seen_before_click = pending.load()
                    super().move_selected_to_trash(media_ids)

            browser = PendingAwareBrowser([["photo-1"]])
            Cleaner(
                browser,
                day_mode=False,
                pending=pending,
                execute=True,
                confirm_all_media_to_trash=True,
                max_batches=1,
            ).run()

            self.assertIsNotNone(browser.pending_seen_before_click)
            self.assertEqual(browser.pending_seen_before_click["kind"], "media_batch")

    def test_cleaner_explicit_authorization_allows_trash(self):
        browser = FakeBrowser([["photo-1"]])

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            processed = Cleaner(
                browser,
                day_mode=False,
                dry_run=False,
                execute=True,
                confirm_all_media_to_trash=True,
                pending=pending,
                max_batches=1,
            ).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.trashed, [["photo-1"]])

    def test_cleaner_requires_durable_pending_store_for_destructive_mode(self):
        with self.assertRaises(CleanerError):
            Cleaner(
                FakeBrowser([["photo-1"]]),
                day_mode=False,
                execute=True,
                confirm_all_media_to_trash=True,
            )


    def test_malformed_pending_store_blocks_destructive_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.path.write_text("not-json", encoding="utf-8")
            browser = FakeBrowser([["photo-1"]])

            cleaner = Cleaner(
                browser,
                day_mode=False,
                execute=True,
                confirm_all_media_to_trash=True,
                pending=pending,
            )

            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)
            self.assertEqual(browser.trashed, [])
            self.assertTrue(pending.path.exists())

    def test_cleaner_does_not_retry_authentication(self):
        browser = FakeBrowser([])
        browser.authenticated = False
        browser.recover = lambda: self.fail("authentication must be manual")

        with self.assertRaises(CleanerError):
            Cleaner(browser, max_retries=4).run()

    def test_pending_checkpoint_is_discarded_by_inspect_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            checkpoint.save(batch=1, photos=2, state="pending", reason="reconciliation_unresolved", run_id="same-run")
            pending = PendingActionStore(Path(tmp) / "pending.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="same-run")
            browser = FakeBrowser([])
            cleaner = Cleaner(
                browser,
                checkpoint=checkpoint,
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="inspect",
                execute=True,
                confirm_all_media_to_trash=True,
            )

            self.assertEqual(cleaner.run(), 0)
            self.assertNotEqual(__import__("json").loads(checkpoint.path.read_text())["state"], "pending")
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            discarded = next(event for event in events if event["phase"] == "checkpoint_pending_discarded_after_timeout")
            self.assertEqual(discarded["result"], "discarded_without_reconciliation")

    def test_running_checkpoint_is_marked_stale_when_run_identity_is_not_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            checkpoint.save(batch=2, photos=3, state="running", reason="scan_started", run_id="different-run")
            diagnostic = DiagnosticLog(Path(tmp, "run.jsonl"), run_id="current-run")
            cleaner = Cleaner(FakeBrowser([]), day_mode=False, checkpoint=checkpoint, diagnostic=diagnostic)
            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome.value, "stop_safe")
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            stale = next(event for event in events if event["phase"] == "checkpoint_stale")
            self.assertEqual(stale["reason"], "run_identity_mismatch")
            self.assertFalse(stale["resumable"])

    def test_stale_running_checkpoint_is_discarded_explicitly_without_browser_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            checkpoint.save(batch=2, photos=3, state="running", reason="day_processed", run_id="different-run")
            diagnostic = DiagnosticLog(Path(tmp, "run.jsonl"), run_id="current-run")
            browser = FakeBrowser([[]])
            cleaner = Cleaner(
                browser,
                day_mode=False,
                checkpoint=checkpoint,
                pending=PendingActionStore(Path(tmp) / "pending.json"),
                diagnostic=diagnostic,
                pending_policy="discard",
                execute=True,
                confirm_all_media_to_trash=True,
            )

            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome.value, "pass_done")
            self.assertNotEqual(__import__("json").loads(checkpoint.path.read_text())["state"], "stale")
            self.assertEqual(browser.trashed, [])
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            discarded = next(event for event in events if event["phase"] == "checkpoint_discarded_manual")
            self.assertEqual(discarded["state"], "stale")
            self.assertEqual(discarded["result"], "discarded_without_reconciliation")

    def test_ambiguous_checkpoint_blocks_without_repeating_trash(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            checkpoint.save(
                batch=1,
                photos=2,
                state="ambiguous",
                reason="trash_result_unknown",
                run_id="same-run",
            )
            diagnostic = DiagnosticLog(Path(tmp, "run.jsonl"), run_id="same-run")
            browser = FakeBrowser([["photo-1"]])
            cleaner = Cleaner(browser, day_mode=False, checkpoint=checkpoint, diagnostic=diagnostic)

            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome, PassOutcome.DESTRUCTIVE_AMBIGUOUS)
            self.assertTrue(cleaner.stop_requested)
            self.assertEqual(browser.trashed, [])
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            blocked = next(event for event in events if event["phase"] == "checkpoint_unresolved")
            self.assertEqual(blocked["state"], "ambiguous")
            self.assertFalse(any(event["phase"] == "authenticated" for event in events))

    def test_scan_failure_saves_terminal_checkpoint_context(self):
        class FailedBrowser(FakeBrowser):
            def select_visible_batch(self, batch_size, *, excluded_media_ids=()):
                raise TimeoutError("scan timeout")

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="scan-failure-checkpoint")
            with self.assertRaises(CleanerError):
                Cleaner(FailedBrowser([]), day_mode=False, max_retries=0, checkpoint=checkpoint, diagnostic=diagnostic).run()
            saved = __import__("json").loads(checkpoint.path.read_text())
            self.assertEqual(saved["state"], "scan_failed")
            self.assertEqual(saved["reason"], "max_retries")
            self.assertEqual(saved["run_id"], "scan-failure-checkpoint")
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            failed = next(event for event in events if event["phase"] == "scan_failed")
            self.assertEqual(failed["result"], "scan_failed")
            self.assertFalse(failed["positive_feedback"])
            self.assertIsNone(failed["feedback_source"])

    def test_cleaner_reports_unauthenticated_session(self):
        browser = FakeBrowser([])
        browser.authenticated = False
        cleaner = Cleaner(browser, dry_run=True)

        with self.assertRaises(CleanerError):
            cleaner.run()

    def test_day_missing_completion_proof_preserves_pending_and_checkpoint(self):
        class NoSourceBrowser(FakeBrowser):
            last_feedback_source = None

        browser = NoSourceBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-proof-state")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(
                    browser,
                    day_mode=True,
                    diagnostic=diagnostic,
                    pending=pending,
                    checkpoint=checkpoint,
                    max_batches=1,
                    execute=True,
                    confirm_all_media_to_trash=True,
                ).run()

            self.assertIsNotNone(pending.load())
            import json
            self.assertEqual(json.loads(checkpoint.path.read_text())["state"], "ambiguous")

    def test_day_completion_with_missing_feedback_source_is_ambiguous(self):
        class NoSourceBrowser(FakeBrowser):
            last_feedback_source = None

        browser = NoSourceBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-source-required")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, pending=_test_pending(), day_mode=True, diagnostic=diagnostic, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        ambiguous = next(event for event in events if event["phase"] == "destructive_action_ambiguous")
        self.assertIn("feedback source", ambiguous["error_message"].lower())

    def test_day_completion_event_keeps_null_feedback_source_without_observer_proof(self):
        class SourceOnlyBrowser(FakeBrowser):
            last_feedback_source = None

        browser = SourceOnlyBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-source-null")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, pending=_test_pending(), day_mode=True, diagnostic=diagnostic, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()

    def test_day_completion_event_contains_observer_feedback_source(self):
        class DayBrowser(FakeBrowser):
            last_selection_kind = "day"
            last_feedback_source = "browser_positive_feedback"

        browser = DayBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-source")
            Cleaner(browser, pending=_test_pending(), day_mode=True, diagnostic=diagnostic, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        completed = next(event for event in events if event["phase"] == "day_trash_completed")
        self.assertTrue(completed["positive_feedback"])
        self.assertEqual(completed["feedback_source"], "browser_positive_feedback")

    def test_media_completion_event_uses_browser_feedback_source(self):
        class MediaBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"

        browser = MediaBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-source")
            Cleaner(browser, pending=_test_pending(), day_mode=False, diagnostic=diagnostic, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        completed = next(event for event in events if event["phase"] == "trash_completed")
        self.assertEqual(completed["feedback_source"], "browser_positive_feedback")

    def test_media_missing_completion_proof_preserves_pending_and_checkpoint(self):
        class NoSourceBrowser(FakeBrowser):
            last_feedback_source = None

        browser = NoSourceBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="proof-state")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(
                    browser,
                    day_mode=False,
                    diagnostic=diagnostic,
                    pending=pending,
                    checkpoint=checkpoint,
                    max_batches=1,
                    execute=True,
                    confirm_all_media_to_trash=True,
                ).run()

            self.assertIsNotNone(pending.load())
            import json
            self.assertEqual(json.loads(checkpoint.path.read_text())["state"], "ambiguous")

    def test_media_completion_with_missing_feedback_source_is_ambiguous(self):
        class NoSourceBrowser(FakeBrowser):
            last_feedback_source = None

        browser = NoSourceBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-source-required")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, pending=_test_pending(), day_mode=False, diagnostic=diagnostic, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        ambiguous = next(event for event in events if event["phase"] == "destructive_action_ambiguous")
        self.assertIn("feedback source", ambiguous["error_message"].lower())

    def test_media_completion_event_keeps_null_source_without_browser_proof(self):
        class SourceOnlyBrowser(FakeBrowser):
            last_feedback_source = None

        browser = SourceOnlyBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-source-null")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, pending=_test_pending(), day_mode=False, diagnostic=diagnostic, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()

    def test_trash_completion_event_contains_positive_feedback(self):
        browser = FakeBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="trash-proof")
            Cleaner(browser, pending=_test_pending(), day_mode=False, diagnostic=diagnostic, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        completed = next(event for event in events if event["phase"] == "trash_completed")
        self.assertTrue(completed["positive_feedback"])
        self.assertEqual(completed["result"], "confirmed")
        self.assertEqual(completed["feedback_source"], "browser_positive_feedback")

    def test_pending_observation_events_always_have_evidence_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-evidence-contract")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="inspect", execute=True, confirm_all_media_to_trash=True).run()
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            phases = {"pending_loaded", "pending_reconciliation_skipped", "pending_inspected", "cleaner_terminal_state"}
            for event in events:
                if event["phase"] in phases:
                    self.assertIn("result", event)
                    self.assertIn("positive_feedback", event)
                    self.assertIn("feedback_source", event)
                    self.assertFalse(event["positive_feedback"])
                    self.assertIsNone(event["feedback_source"])

    def test_unresolved_day_events_have_non_proof_evidence_fields(self):
        class PendingDayBrowser(FakeBrowser):
            def delete_selected_day(self):
                return False
            def wait_for_target_absence(self, _label, timeout_ms):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-pending-evidence")
            cleaner = Cleaner(
                PendingDayBrowser([("2 Aug", 1)]),
                pending=pending,
                checkpoint=checkpoint,
                diagnostic=diagnostic,
                max_batches=1,
            )
            cleaner.run()
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            for event in events:
                if event["phase"] in {"day_trash_pending", "day_trash_unresolved", "cleaner_terminal_state"}:
                    self.assertIn("result", event)
                    self.assertIn("positive_feedback", event)
                    self.assertIn("feedback_source", event)
                    self.assertFalse(event["positive_feedback"])
                    self.assertIsNone(event["feedback_source"])

    def test_destructive_ambiguous_event_has_non_proof_evidence_fields(self):
        class AmbiguousDayBrowser(FakeBrowser):
            last_feedback_source = None
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return True

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="destructive-ambiguous-evidence")
            cleaner = Cleaner(AmbiguousDayBrowser([("2 Aug", 1)]), execute=True, confirm_all_media_to_trash=True, pending=pending, diagnostic=diagnostic, max_batches=1)
            with self.assertRaises(DestructiveActionAmbiguous):
                cleaner.run()
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            event = next(event for event in events if event["phase"] == "destructive_action_ambiguous")
            self.assertEqual(event["result"], "ambiguous")
            self.assertFalse(event["positive_feedback"])
            self.assertIsNone(event["feedback_source"])

    def test_destructive_pending_event_has_non_proof_evidence_fields(self):
        class PendingDayBrowser(FakeBrowser):
            def delete_selected_day(self):
                raise TimeoutError("unknown result")

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="destructive-pending-evidence")
            cleaner = Cleaner(PendingDayBrowser([("2 Aug", 1)]), execute=True, confirm_all_media_to_trash=True, pending=pending, diagnostic=diagnostic, max_batches=1)
            cleaner.run()
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            event = next(event for event in events if event["phase"] == "destructive_action_pending")
            self.assertEqual(event["result"], "pending_reconciliation")
            self.assertFalse(event["positive_feedback"])
            self.assertIsNone(event["feedback_source"])

    def test_pending_reconciliation_event_has_positive_proof_fields(self):
        class ReconciledBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"
            def target_exists(self, _label):
                return False
            def wait_for_target_absence(self, _label, timeout_ms):
                return True

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-contract")
            # Directly exercise legacy reconciliation branch retained for old journals.
            cleaner = Cleaner(ReconciledBrowser([]), pending=pending, diagnostic=diagnostic)
            cleaner.pending_policy = "legacy"
            cleaner.run()
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            reconciled = next(event for event in events if event["phase"] == "pending_reconciled")
            self.assertTrue(reconciled["positive_feedback"])
            self.assertEqual(reconciled["feedback_source"], "browser_positive_feedback")
            self.assertEqual(reconciled["result"], "reconciled")

    def test_pending_inspect_event_has_non_proof_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-inspect-evidence")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="inspect", execute=True, confirm_all_media_to_trash=True).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            inspected = next(event for event in events if event["phase"] == "pending_inspected")
            self.assertFalse(inspected["positive_feedback"])
            self.assertIsNone(inspected["feedback_source"])
            self.assertEqual(inspected["result"], "reconciliation_attempted")

    def test_pending_inspect_timeout_does_not_replay_same_day_target(self):
        class TimeoutPendingBrowser(FakeBrowser):
            last_feedback_source = None

            def wait_for_target_absence(self, _label, timeout_ms):
                self.waited_timeout_ms = timeout_ms
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-no-replay")
            browser = TimeoutPendingBrowser([("day pending", 1), ("next day", 1)])
            cleaner = Cleaner(
                browser,
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="inspect",
                pending_timeout_ms=777,
                max_batches=1,
                execute=True,
                confirm_all_media_to_trash=True,
            )

            with self.assertRaises(DestructiveActionAmbiguous):
                cleaner.run()
            self.assertEqual(browser.days, ["day pending", "next day"])
            self.assertEqual(browser.trashed, [["day"]])
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            self.assertTrue(any(event["phase"] == "ambiguous_target_skipped" for event in events))

    def test_ambiguous_target_requests_one_bounded_timeline_advance(self):
        class StaleTargetBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"

            def __init__(self):
                super().__init__(["stale-day", "next-day"])
                self.advance_calls = 0

            def select_current_day(self):
                day = self.batches.pop(0)
                self.days.append(day)
                return day

            def advance_timeline(self):
                self.advance_calls += 1
                return True

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            browser = StaleTargetBrowser()
            cleaner = Cleaner(
                browser,
                pending=pending,
                max_batches=1,
                pending_policy="inspect",
                execute=True,
                confirm_all_media_to_trash=True,
            )
            cleaner._skipped_ambiguous_targets.add("stale-day")

            self.assertEqual(cleaner.run(), 1)
            self.assertEqual(browser.advance_calls, 1)
            self.assertEqual(browser.days, ["stale-day", "next-day"])
            self.assertEqual(browser.trashed, [["day"]])

    def test_pending_discard_policy_removes_pending_and_checkpoint_without_browser_reconciliation(self):
        class NoReconciliationBrowser(FakeBrowser):
            def wait_for_target_absence(self, *_args, **_kwargs):
                raise AssertionError("discard policy must not reconcile in browser")

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="ambiguous day", kind="day", scroll_top=0)
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            checkpoint.save(batch=1, photos=2, state="pending", reason="trash_result_pending")
            browser = NoReconciliationBrowser([])
            cleaner = Cleaner(
                browser,
                pending=pending,
                checkpoint=checkpoint,
                pending_policy="discard",
                execute=True,
                confirm_all_media_to_trash=True,
            )
            cleaner.reconcile_pending_only = True

            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PASS_DONE)
            self.assertIsNone(pending.load())
            self.assertIsNone(checkpoint.load())
            self.assertEqual(browser.trashed, [])

    def test_pending_inspect_timeout_discards_journal_and_continues_scan(self):
        class TimeoutPendingBrowser(FakeBrowser):
            last_feedback_source = None

            def wait_for_target_absence(self, _label, timeout_ms):
                self.waited_timeout_ms = timeout_ms
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-timeout-discard")
            browser = TimeoutPendingBrowser([("next day", 1)])
            browser.last_feedback_source = "browser_positive_feedback"
            cleaner = Cleaner(
                browser,
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="inspect",
                pending_timeout_ms=777,
                max_batches=1,
                execute=True,
                confirm_all_media_to_trash=True,
            )

            self.assertEqual(cleaner.run(), 1)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.waited_timeout_ms, 777)
            self.assertEqual(browser.trashed, [["day"]])
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            discarded = next(event for event in events if event["phase"] == "pending_discarded_after_timeout")
            self.assertEqual(discarded["target"], "day pending")
            self.assertEqual(discarded["result"], "discarded_without_reconciliation")
            self.assertFalse(discarded["positive_feedback"])
            self.assertFalse(any(event["phase"] == "pending_unresolved" for event in events))

    def test_pending_timeout_on_media_action_discards_journal_and_continues_scan(self):
        class TimeoutMediaBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"

            def move_selected_to_trash(self, media_ids):
                self.trashed.append(list(media_ids))
                raise TimeoutError("feedback timeout")

            def wait_for_target_absence(self, _label, timeout_ms):
                self.waited_timeout_ms = timeout_ms
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-timeout-discard")
            browser = TimeoutMediaBrowser([["first media"], ["second media"]])
            cleaner = Cleaner(
                browser,
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="inspect",
                pending_timeout_ms=444,
                max_batches=2,
                day_mode=False,
                execute=True,
                confirm_all_media_to_trash=True,
            )

            # Ambiguous media action itself remains fail-closed: only the
            # journal is discarded after the bounded timeout; no Trash retry.
            self.assertEqual(cleaner.run(), 0)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.waited_timeout_ms, 444)
            self.assertEqual(browser.trashed, [["first media"], ["second media"]])
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            self.assertTrue(any(event["phase"] == "pending_discarded_after_timeout" for event in events))

    def test_day_mode_fallback_passes_batch_limit_and_ambiguous_ids_to_adapter(self):
        class DayFallbackBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([["media-1", "media-2", "media-3"]])
                self.last_selection_kind = "media"
                self.last_batch_ids = []
                self.select_current_day_calls = []

            def select_current_day(self, *, batch_size=None, excluded_media_ids=()):
                self.select_current_day_calls.append((batch_size, set(excluded_media_ids)))
                excluded = set(excluded_media_ids)
                selected = [media_id for media_id in self.batches.pop(0) if media_id not in excluded][:batch_size]
                self.last_batch_ids = list(selected)
                if not selected:
                    self.last_selection_kind = None
                    return None
                self.last_selection_kind = "media"
                return f"batch:{len(selected)}"

            def delete_selected_day(self):
                self.trashed.append(list(self.last_batch_ids))
                raise TimeoutError("feedback timeout")

            def wait_for_target_absence(self, _label, timeout_ms):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-fallback-limit")
            browser = DayFallbackBrowser()
            cleaner = Cleaner(
                browser,
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="inspect",
                pending_timeout_ms=100,
                max_batches=1,
                day_mode=True,
                batch_size=2,
                execute=True,
                confirm_all_media_to_trash=True,
            )
            # Seed the replay tombstone as if the same batch had already ended
            # ambiguously in an earlier bounded attempt.
            cleaner._skipped_ambiguous_media_ids.add("media-1")

            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(browser.select_current_day_calls, [(2, {"media-1"})])
            self.assertEqual(browser.trashed, [["media-2", "media-3"]])
            self.assertEqual(browser.last_batch_ids, ["media-2", "media-3"])
            record = pending.load()
            self.assertIsNotNone(record)
            self.assertEqual(record["kind"], "media_batch")
            self.assertEqual(record["count"], 2)
            self.assertEqual(record["media_ids"], ["media-2", "media-3"])

    def test_ambiguous_media_batch_ids_are_not_selected_again(self):
        class ReplayAwareBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([["media-1", "media-2"], ["media-1", "media-2"]])
                self.last_batch_ids = []
                self.select_calls = []
                self.excluded_calls = []

            def select_visible_batch(self, batch_size, *, excluded_media_ids=()):
                batch = super().select_visible_batch(batch_size)
                batch = [media_id for media_id in batch if media_id not in set(excluded_media_ids)]
                self.last_batch_ids = list(batch)
                self.select_calls.append(list(batch))
                self.excluded_calls.append(set(excluded_media_ids))
                return batch

            def move_selected_to_trash(self, media_ids):
                self.trashed.append(list(media_ids))
                raise TimeoutError("feedback timeout")

            def wait_for_target_absence(self, _label, timeout_ms):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            browser = ReplayAwareBrowser()
            cleaner = Cleaner(
                browser,
                pending=pending,
                pending_policy="inspect",
                max_batches=2,
                day_mode=False,
                execute=True,
                confirm_all_media_to_trash=True,
            )

            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(browser.select_calls, [["media-1", "media-2"], []])
            self.assertEqual(browser.trashed, [["media-1", "media-2"]])

    def test_pending_timeout_on_day_action_discards_journal_and_continues_scan(self):
        class TimeoutDayBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"

            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False

            def wait_for_target_absence(self, _label, timeout_ms):
                self.waited_timeout_ms = timeout_ms
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-timeout-discard")
            browser = TimeoutDayBrowser([("first day", 1), ("second day", 1)])
            cleaner = Cleaner(
                browser,
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="inspect",
                pending_timeout_ms=555,
                max_batches=2,
                execute=True,
                confirm_all_media_to_trash=True,
                max_idle_scrolls=1,
            )

            # Neither uncertain action is counted as confirmed, but the pass
            # continues to the next visible day after each journal discard.
            self.assertEqual(cleaner.run(), 0)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.waited_timeout_ms, 555)
            self.assertEqual(browser.trashed, [["day"], ["day"]])
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            self.assertEqual(len([event for event in events if event["phase"] == "pending_discarded_after_timeout"]), 2)
            self.assertFalse(any(event["phase"] == "cleaner_terminal_state" for event in events))

    def test_cleaner_terminal_destructive_outcome_declares_no_positive_proof(self):
        class NoSourceBrowser(FakeBrowser):
            last_feedback_source = None

        browser = NoSourceBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="terminal-ambiguous-evidence")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, diagnostic=diagnostic, day_mode=False, max_batches=1).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            terminal = next(event for event in events if event["phase"] == "cleaner_terminal_state")
            self.assertEqual(terminal["outcome"], "destructive_ambiguous")
            self.assertFalse(terminal["positive_feedback"])
            self.assertIsNone(terminal["feedback_source"])

    def test_pending_loaded_event_declares_observation_not_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-loaded-evidence")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="block", execute=True, confirm_all_media_to_trash=True).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            loaded = next(event for event in events if event["phase"] == "pending_loaded")
            self.assertEqual(loaded["result"], "observed")
            self.assertFalse(loaded["positive_feedback"])
            self.assertIsNone(loaded["feedback_source"])

    def test_cleaner_terminal_pending_outcome_declares_no_positive_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="terminal-pending-evidence")
            cleaner = Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="block")
            cleaner.run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            terminal = next(event for event in events if event["phase"] == "cleaner_terminal_state")
            self.assertEqual(terminal["outcome"], "pending_unresolved")
            self.assertFalse(terminal["positive_feedback"])
            self.assertIsNone(terminal["feedback_source"])

    def test_pending_dry_run_event_has_non_proof_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-dry-evidence")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, dry_run=True).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            unresolved = next(event for event in events if event["phase"] == "pending_unresolved")
            self.assertFalse(unresolved["positive_feedback"])
            self.assertEqual(unresolved["result"], "policy_blocked_dry_run")

    def test_pending_reconciliation_does_not_clear_without_positive_source(self):
        class PendingBrowser(FakeBrowser):
            last_feedback_source = None
            def target_exists(self, _label):
                return False
            def wait_for_target_absence(self, _label, timeout_ms):
                return True

        browser = PendingBrowser([])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="Foto - pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-source")
            Cleaner(browser, pending=pending, diagnostic=diagnostic, pending_policy="block", execute=True, confirm_all_media_to_trash=True).run()

            self.assertIsNotNone(pending.load())
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            self.assertTrue(any(event["phase"] == "pending_unresolved" for event in events))

    def test_pending_block_event_has_non_proof_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-block-evidence")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="block", execute=True, confirm_all_media_to_trash=True).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            skipped = next(event for event in events if event["phase"] == "pending_reconciliation_skipped")
            self.assertFalse(skipped["positive_feedback"])
            self.assertEqual(skipped["result"], "not_attempted")

    def test_pending_block_records_reconciliation_was_not_attempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-skip")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="block", execute=True, confirm_all_media_to_trash=True).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            skipped = next(event for event in events if event["phase"] == "pending_reconciliation_skipped")
            self.assertEqual(skipped["reason"], "policy_blocks_automatic_reconciliation")
            self.assertIsNone(skipped["feedback_source"])

    def test_ambiguous_trash_event_includes_sanitized_error(self):
        browser = AmbiguousBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="ambiguous-proof")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, day_mode=False, diagnostic=diagnostic).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        ambiguous = next(event for event in events if event["phase"] == "destructive_action_ambiguous")
        self.assertEqual(ambiguous["error_message"], "result unknown after trash click")
        self.assertFalse(any(event["phase"] == "trash_completed" for event in events))

    def test_dry_run_does_not_move_photos(self):
        browser = FakeBrowser([["old-1"], ["old-2"]])

        processed = Cleaner(browser, dry_run=True, day_mode=False).run()

        self.assertEqual(processed, 2)
        self.assertEqual(browser.trashed, [])

    def test_day_scan_event_contains_attempt_and_target_context(self):
        class EventBrowser(FakeBrowser):
            scroll_step = 240
            scroll_delay_ms = 1500


        browser = EventBrowser([("2 Aug", 2)])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="scan-context")
            Cleaner(browser, day_mode=True, dry_run=True, max_batches=1, diagnostic=diagnostic).run()
            events = [
                __import__("json").loads(line)
                for line in Path(tmp, "run.jsonl").read_text().splitlines()
            ]

        day_scan = next(event for event in events if event["phase"] == "day_scan")
        self.assertEqual(day_scan["attempt"], 0)
        self.assertEqual(day_scan["day"], "2 Aug")
        started = next(event for event in events if event["phase"] == "run_started")
        self.assertEqual(started["mode"], "dry-run")
        self.assertEqual(started["scroll_step"], 240)
        self.assertEqual(started["pending_timeout_ms"], 30000)
        self.assertIn("uid", started)
        self.assertIn("username", started)
        self.assertEqual(started["max_idle_scrolls"], 5)

    def test_pass_done_is_terminal_without_second_run(self):
        browser = FakeBrowser([["old-1"]])
        cleaner = Cleaner(browser, dry_run=True, day_mode=False)

        first = cleaner.run()
        second = cleaner.run()

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(browser.batches, [])
        self.assertEqual(cleaner.last_outcome, PassOutcome.PASS_DONE)

    def test_run_started_contains_process_and_policy_context(self):
        browser = FakeBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="context")
            Cleaner(browser, dry_run=True, day_mode=False, max_batches=1, diagnostic=diagnostic).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        started = next(event for event in events if event["phase"] == "run_started")
        self.assertIn("pid", started)
        self.assertIn("ppid", started)
        self.assertEqual(started["pending_policy"], "block")
        self.assertEqual(started["pending_timeout_ms"], 30000)

    def test_reconciled_day_completion_propagates_positive_feedback_source(self):
        class ReconcileBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False
            def wait_for_target_absence(self, _label, timeout_ms):
                return True

        browser = ReconcileBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="reconcile-source-positive")
            Cleaner(browser, day_mode=True, diagnostic=diagnostic, pending=pending, max_batches=1, execute=True, confirm_all_media_to_trash=True).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        completed = next(event for event in events if event["phase"] == "day_trash_completed")
        self.assertEqual(completed["feedback_source"], "browser_positive_feedback")

    def test_reconciled_day_completion_requires_positive_feedback_source(self):
        class ReconcileBrowser(FakeBrowser):
            last_feedback_source = None
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False
            def wait_for_target_absence(self, _label, timeout_ms):
                return True

        browser = ReconcileBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="reconcile-source")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, execute=True, confirm_all_media_to_trash=True, day_mode=True, diagnostic=diagnostic, pending=pending, checkpoint=checkpoint, max_batches=1).run()

            self.assertIsNotNone(pending.load())
            import json
            self.assertEqual(json.loads(checkpoint.path.read_text())["state"], "ambiguous")

    def test_bounded_dry_run_checkpoint_is_terminal_and_contextual(self):
        browser = FakeBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="checkpoint-bounded")
            cleaner = Cleaner(browser, dry_run=True, day_mode=True, max_batches=1, checkpoint=checkpoint, diagnostic=diagnostic)
            self.assertEqual(cleaner.run(), 1)
            saved = __import__("json").loads(checkpoint.path.read_text())
            self.assertEqual(saved["state"], "bounded_stop")
            self.assertEqual(saved["reason"], "max_batches")
            self.assertEqual(saved["run_id"], "checkpoint-bounded")
            self.assertEqual(saved["pid"], __import__("os").getpid())

    def test_cleaner_blocks_legacy_running_checkpoint_without_resuming(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            checkpoint.path.write_text(__import__("json").dumps({"batch": 1, "photos": 1, "state": "running"}))
            browser = FakeBrowser([])
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="stale-checkpoint")
            cleaner = Cleaner(browser, dry_run=True, checkpoint=checkpoint, diagnostic=diagnostic)
            self.assertEqual(cleaner.run(), 0)
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            self.assertFalse(any(event["phase"] == "authenticated" for event in events))
            self.assertTrue(any(event["phase"] == "checkpoint_stale" for event in events))
            self.assertEqual(cleaner.last_outcome, PassOutcome.STOP_SAFE)

    def test_bounded_dry_run_day_pass_requests_stop(self):
        browser = FakeBrowser([("2 Aug", 1), ("1 Aug", 1)])

        cleaner = Cleaner(browser, dry_run=True, day_mode=True, max_batches=1)
        processed = cleaner.run()

        self.assertEqual(processed, 1)
        self.assertTrue(cleaner.stop_requested)
        self.assertEqual(cleaner.last_outcome, PassOutcome.BOUNDED_STOP)
        self.assertEqual(browser.trashed, [])

    def test_bounded_media_pass_requests_stop(self):
        browser = FakeBrowser([["photo-1"], ["photo-2"]])

        cleaner = Cleaner(browser, dry_run=True, day_mode=False, max_batches=1)
        processed = cleaner.run()

        self.assertEqual(processed, 1)
        self.assertTrue(cleaner.stop_requested)
        self.assertEqual(cleaner.last_outcome, PassOutcome.BOUNDED_STOP)
        self.assertEqual(browser.trashed, [])

    def test_cleaner_skips_stale_day_and_continues(self):
        class SkipStaleBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([("20 Jul", 2)])
                self.attempts = 0
                self.advance_count = 0

            def select_current_day(self):
                self.attempts += 1
                if self.attempts <= 3:
                    raise TimeoutError("stale control")
                return super().select_current_day()

            def recover(self):
                pass

            def advance_timeline(self):
                self.advance_count += 1
                return False

        browser = SkipStaleBrowser()
        processed = Cleaner(browser, pending=_test_pending(), day_mode=True, max_retries=1, execute=True, confirm_all_media_to_trash=True).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.advance_count, 2)
        self.assertEqual(browser.trashed, [["day"]])

    def test_cleaner_recovers_after_bounded_day_scan_failures(self):
        class RecoverAfterRoundBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([("recovered day", 1)])
                self.scan_attempts = 0
                self.recover_calls = 0
                self.reset_calls = 0

            def select_current_day(self):
                self.scan_attempts += 1
                if self.scan_attempts <= 2:
                    raise TimeoutError("virtualized control is unstable")
                return super().select_current_day()

            def recover(self):
                self.recover_calls += 1

            def reset_timeline_to_top(self):
                self.reset_calls += 1

        browser = RecoverAfterRoundBrowser()
        cleaner = Cleaner(
            browser,
            pending=_test_pending(),
            day_mode=True,
            max_retries=1,
            max_day_scan_failures=2,
            max_batches=1,
            execute=True,
            confirm_all_media_to_trash=True,
        )

        self.assertEqual(cleaner.run(), 1)
        self.assertEqual(browser.trashed, [["day"]])
        self.assertEqual(browser.reset_calls, 1)
        self.assertEqual(browser.recover_calls, 1)

    def test_cleaner_stops_after_bounded_day_scan_failures(self):
        class AlwaysStaleBrowser(FakeBrowser):
            def select_current_day(self):
                raise TimeoutError("stale day control")

            def recover(self):
                pass

        browser = AlwaysStaleBrowser([])
        processed = Cleaner(
            browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True,
            day_mode=True,
            max_retries=1,
            max_day_scan_failures=2,
        ).run()

        self.assertEqual(processed, 0)
        self.assertEqual(browser.trashed, [])

    def test_cleaner_marks_pass_stop_after_bounded_day_scan_failures(self):
        class AlwaysStaleBrowser(FakeBrowser):
            def select_current_day(self):
                raise TimeoutError("stale day control")

            def recover(self):
                pass

        browser = AlwaysStaleBrowser([])
        cleaner = Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, day_mode=True, max_retries=1, max_day_scan_failures=1)
        cleaner.run()

        self.assertTrue(cleaner.stop_requested)

    def test_cleaner_retries_day_selection_before_delete(self):
        class RetryDayBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([("12 Aug", 3)])
                self.attempts = 0
                self.recover_calls = 0

            def select_current_day(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise CleanerError("stale day control")
                return super().select_current_day()

            def recover(self):
                self.recover_calls += 1

        browser = RetryDayBrowser()
        processed = Cleaner(browser, pending=_test_pending(), day_mode=True, max_retries=1, execute=True, confirm_all_media_to_trash=True).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.recover_calls, 1)
        self.assertEqual(browser.trashed, [["day"]])

    def test_pending_reconciliation_positive_source_clears_journal(self):
        class ReconciledBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"
            def target_exists(self, _label):
                return False
            def wait_for_target_absence(self, _label, timeout_ms):
                return True

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            browser = ReconciledBrowser([])
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-positive")
            cleaner = Cleaner(browser, pending=pending, diagnostic=diagnostic, pending_policy="block")
            cleaner.run()
            self.assertIsNotNone(pending.load())
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            self.assertFalse(any(event["phase"] == "pending_reconciled" for event in events))
            self.assertTrue(any(event["phase"] == "pending_unresolved" for event in events))

    def test_legacy_pending_fallback_clears_with_positive_source(self):
        class FallbackBrowser(FakeBrowser):
            last_feedback_source = "browser_positive_feedback"
            def target_exists(self, _label):
                return True
            def wait_for_target_absence(self, _label, timeout_ms):
                return True

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            cleaner = Cleaner(FallbackBrowser([]), pending=pending)
            cleaner.pending_policy = "legacy"
            cleaner.run()
            self.assertIsNone(pending.load())

    def test_legacy_pending_fallback_does_not_clear_without_positive_source(self):
        class FallbackBrowser(FakeBrowser):
            last_feedback_source = None
            def target_exists(self, _label):
                return True
            def wait_for_target_absence(self, _label, timeout_ms):
                return True

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-fallback-source")
            cleaner = Cleaner(FallbackBrowser([]), pending=pending, diagnostic=diagnostic)
            cleaner.pending_policy = "legacy"
            cleaner.run()

            self.assertIsNotNone(pending.load())
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            unresolved = [event for event in events if event["phase"] == "pending_reconciled"]
            self.assertFalse(unresolved)
            self.assertTrue(any(event["phase"] == "pending_unresolved" for event in events))

    def test_pending_discard_is_explicit_and_not_reconciliation_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="pending-discard")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="discard").run()

            self.assertIsNone(pending.load())
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            discarded = next(event for event in events if event["phase"] == "pending_discarded_manual")
            self.assertEqual(discarded["policy"], "discard")
            self.assertFalse(discarded["positive_feedback"])
            self.assertIsNone(discarded["feedback_source"])
            self.assertFalse(any(event["phase"] == "pending_reconciled" for event in events))

    def test_pending_inspect_reconciles_positive_feedback_before_stopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            browser = FakeBrowser([("new day", 1)])
            browser.wait_for_target_absence = Mock(return_value=True)
            browser.last_feedback_source = "browser_positive_feedback"

            cleaner = Cleaner(
                browser,
                day_mode=True,
                pending=pending,
                pending_policy="inspect",
                execute=True,
                confirm_all_media_to_trash=True,
            )
            self.assertEqual(cleaner.run(), 1)
            self.assertEqual(cleaner.last_outcome, PassOutcome.STOP_SAFE)
            self.assertIsNone(pending.load())
            browser.wait_for_target_absence.assert_called_once_with("day pending", timeout_ms=30000)

    def test_pending_inspect_discards_after_timeout_and_continues_without_destructive_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            browser = FakeBrowser([("new day", 1)])

            cleaner = Cleaner(browser, day_mode=True, pending=pending, pending_policy="inspect")
            self.assertEqual(cleaner.run(), 1)
            self.assertEqual(browser.trashed, [])
            self.assertIsNone(pending.load())

    def test_pending_policy_block_does_not_call_retry_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            browser = FakeBrowser([("new day", 1)])
            browser.retry_pending_action = lambda _label: self.fail("automatic retry forbidden")

            cleaner = Cleaner(browser, day_mode=True, pending=pending, pending_policy="block")
            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)

    def test_pending_media_discard_event_is_not_reconciliation_proof(self):
        class MediaBrowser(FakeBrowser):
            last_feedback_source = None

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="batch:1", kind="media_batch", scroll_top=0, count=2)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-discard")
            Cleaner(
                MediaBrowser([]),
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="discard",
                discard_ambiguous_media_batches=True,
            ).run()

            self.assertIsNone(pending.load())
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            discarded = next(event for event in events if event["phase"] == "pending_discarded_manual")
            self.assertFalse(discarded["positive_feedback"])
            self.assertIsNone(discarded["feedback_source"])
            self.assertEqual(discarded["result"], "discarded_without_reconciliation")

    def test_pending_batch_discard_specific_event_contains_non_proof_fields(self):
        class MediaBrowser(FakeBrowser):
            last_feedback_source = None

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="batch:1", kind="media_batch", scroll_top=0, count=2)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-batch-discard")
            Cleaner(
                MediaBrowser([]),
                pending=pending,
                diagnostic=diagnostic,
                pending_policy="discard",
                discard_ambiguous_media_batches=True,
            ).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            discarded = next(event for event in events if event["phase"] == "pending_discarded_manual")
            self.assertFalse(discarded["positive_feedback"])
            self.assertIsNone(discarded["feedback_source"])
            self.assertEqual(discarded["result"], "discarded_without_reconciliation")

    def test_pending_media_unresolved_event_has_non_proof_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="batch:1", kind="media_batch", scroll_top=0, count=2)
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-unresolved")
            Cleaner(FakeBrowser([]), pending=pending, diagnostic=diagnostic, pending_policy="block", execute=True, confirm_all_media_to_trash=True).run()

            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            unresolved = next(event for event in events if event["phase"] == "pending_unresolved")
            self.assertFalse(unresolved["positive_feedback"])
            self.assertIsNone(unresolved["feedback_source"])
            self.assertEqual(unresolved["result"], "policy_blocked")

    def test_ambiguous_media_batch_is_journaled_and_blocks_followup_trash(self):
        class AmbiguousBatchBrowser(FakeBrowser):
            def move_selected_to_trash(self, _media_ids):
                raise TimeoutError("unknown batch result")

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            browser = AmbiguousBatchBrowser([["photo-1", "photo-2"]])
            cleaner = Cleaner(browser, execute=True, confirm_all_media_to_trash=True, day_mode=False, pending=pending)
            with self.assertRaises(DestructiveActionAmbiguous):
                cleaner.run()
            self.assertTrue(cleaner.stop_requested)
            record = pending.load()
            self.assertEqual(record["kind"], "media_batch")
            self.assertEqual(record["count"], 2)

            browser = FakeBrowser([["photo-3"]])
            self.assertEqual(Cleaner(browser, day_mode=False, pending=pending, execute=True, confirm_all_media_to_trash=True).run(), 0)
            self.assertEqual(browser.trashed, [])

    def test_ambiguous_media_batch_can_be_discarded_and_loop_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(
                label="batch:1",
                kind="media_batch",
                scroll_top=0,
                count=2,
                media_ids=["photo-1", "photo-2"],
            )
            browser = FakeBrowser([["photo-3"]])

            processed = Cleaner(
                browser,
                day_mode=False,
                pending=pending,
                discard_ambiguous_media_batches=True,
                pending_policy="discard",
                execute=True,
                confirm_all_media_to_trash=True,
            ).run()

            self.assertEqual(processed, 1)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.trashed, [["photo-3"]])

    def test_inspected_media_batch_timeout_discards_journal_and_continues(self):
        class TimeoutMediaBatchBrowser(FakeBrowser):
            last_feedback_source = None

            def wait_for_target_absence(self, _label, timeout_ms):
                self.waited_timeout_ms = timeout_ms
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(
                label="batch:1",
                kind="media_batch",
                scroll_top=0,
                count=2,
                media_ids=["photo-1", "photo-2"],
            )
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-batch-timeout-discard")
            checkpoint = CheckpointStore(Path(tmp) / "checkpoint.json")
            checkpoint.save = Mock(wraps=checkpoint.save)
            browser = TimeoutMediaBatchBrowser([["photo-3"]])

            processed = Cleaner(
                browser,
                day_mode=False,
                pending=pending,
                checkpoint=checkpoint,
                diagnostic=diagnostic,
                pending_policy="inspect",
                pending_timeout_ms=333,
                max_batches=1,
                execute=True,
                confirm_all_media_to_trash=True,
            ).run()

            self.assertEqual(processed, 0)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.waited_timeout_ms, 333)
            self.assertEqual(browser.trashed, [["photo-3"]])
            events = [__import__("json").loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]
            self.assertTrue(any(event["phase"] == "pending_discarded_after_timeout" for event in events))

    def test_cleaner_uses_selection_size_as_visible_batch_limit(self):
        browser = FakeBrowser([["photo-1", "photo-2", "photo-3"]])

        processed = Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, day_mode=False, batch_size=3).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.trashed, [["photo-1", "photo-2", "photo-3"]])

    def test_cleaner_advances_timeline_after_idle_scan_limit(self):
        class TimelineBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([("12 Aug", 3)])
                self.scan_count = 0
                self.advance_count = 0

            def select_current_day(self):
                self.scan_count += 1
                if self.scan_count <= 2:
                    return None
                return super().select_current_day()

            def advance_timeline(self):
                self.advance_count += 1
                return True

        browser = TimelineBrowser()
        processed = Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, day_mode=True, max_batches=1, max_idle_scrolls=2).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.advance_count, 2)

    def test_cleaner_scrolls_immediately_when_no_day_is_loaded(self):
        class TimelineBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([("12 Aug", 3)])
                self.scan_count = 0
                self.advance_count = 0

            def select_current_day(self):
                self.scan_count += 1
                if self.scan_count == 1:
                    return None
                return super().select_current_day()

            def advance_timeline(self):
                self.advance_count += 1
                return self.advance_count == 1

        browser = TimelineBrowser()
        processed = Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, day_mode=True, max_batches=1, max_idle_scrolls=2).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.advance_count, 1)

    def test_pending_reconciliation_receives_configured_timeout(self):
        class TimeoutSpyBrowser(FakeBrowser):
            def delete_selected_day(self):
                return False

            def wait_for_target_absence(self, _label, timeout_ms=30000):
                self.timeout_ms = timeout_ms
                return True

        browser = TimeoutSpyBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            processed = Cleaner(
                browser,
                day_mode=True,
                pending=pending,
                pending_timeout_ms=777,
                execute=True,
                confirm_all_media_to_trash=True,
            ).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.timeout_ms, 777)

    def test_pending_day_waits_for_absence_before_continuing(self):
        class DelayedAbsenceBrowser(FakeBrowser):
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False

            def wait_for_target_absence(self, label, *, timeout_ms):
                self.waited_label = label
                self.waited_timeout_ms = timeout_ms
                return True

        browser = DelayedAbsenceBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            cleaner = Cleaner(
                browser,
                day_mode=True,
                pending=pending,
                pending_timeout_ms=321,
                max_idle_scrolls=1,
                max_batches=1,
                execute=True,
                confirm_all_media_to_trash=True,
            )
            processed = cleaner.run()

            self.assertEqual(processed, 1)
            self.assertEqual(browser.waited_label, "2 Aug")
            self.assertEqual(browser.waited_timeout_ms, 321)
            self.assertEqual(browser.trashed, [["day"]])
            self.assertIsNone(pending.load())
            self.assertEqual(cleaner.last_outcome, PassOutcome.BOUNDED_STOP)
            self.assertTrue(cleaner.stop_requested)

    def test_pending_target_still_present_does_not_select_or_trash_again(self):
        class StillPresentBrowser(FakeBrowser):
            def target_exists(self, _label):
                return True

        browser = StillPresentBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Foto - 2 ago", kind="media", scroll_top=0)
            processed = Cleaner(browser, day_mode=True, pending=pending).run()

            self.assertEqual(processed, 0)
            self.assertEqual(browser.days, [])
            self.assertEqual(browser.trashed, [])
            self.assertIsNotNone(pending.load())

    def test_pending_present_target_without_feedback_stops_pass(self):
        class PresentWithoutFeedbackBrowser(FakeBrowser):
            def target_exists(self, _label):
                return True

            def wait_for_target_absence(self, _label, *, timeout_ms):
                return False

        browser = PresentWithoutFeedbackBrowser([])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Seleziona tutte le foto a partire da: 2 ago", kind="day", scroll_top=0)
            cleaner = Cleaner(browser, day_mode=True, pending=pending).run()

            self.assertEqual(cleaner, 0)
            self.assertIsNotNone(pending.load())

    def test_pending_present_target_never_retries_ambiguous_trash(self):
        class RetrySpyBrowser(FakeBrowser):
            def target_exists(self, _label):
                return True

            def retry_pending_action(self, _label):
                raise AssertionError("ambiguous Trash must not be retried automatically")

            def wait_for_target_absence(self, _label, *, timeout_ms):
                return False

        browser = RetrySpyBrowser([])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Seleziona tutte le foto a partire da: 2 ago", kind="day", scroll_top=0)
            processed = Cleaner(browser, day_mode=True, pending=pending).run()

            self.assertEqual(processed, 0)
            self.assertIsNotNone(pending.load())

    def test_pending_day_absent_after_single_click_is_completed_without_retry(self):
        class PendingThenAbsentBrowser(FakeBrowser):
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False

            def wait_for_target_absence(self, _label, timeout_ms=30000):
                return True

        browser = PendingThenAbsentBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            processed = Cleaner(
                browser,
                day_mode=True,
                pending=pending,
                max_idle_scrolls=1,
                execute=True,
                confirm_all_media_to_trash=True,
            ).run()

            self.assertEqual(processed, 1)
            self.assertEqual(browser.trashed, [["day"]])
            self.assertIsNone(pending.load())

    def test_dry_run_pending_does_not_poll_browser(self):
        class DryRunPollSpyBrowser(FakeBrowser):
            def wait_for_target_absence(self, _label):
                raise AssertionError("dry-run pending must not poll")

        browser = DryRunPollSpyBrowser([])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Foto - pending", kind="day", scroll_top=0)
            cleaner = Cleaner(browser, dry_run=True, pending=pending)

            self.assertEqual(cleaner.run(), 0)
            self.assertTrue(cleaner.stop_requested)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)
            self.assertIsNotNone(pending.load())

    def test_discard_policy_clears_pending_day_and_continues(self):
        browser = FakeBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Seleziona tutte le foto a partire da: 2 ago", kind="day", scroll_top=0)
            cleaner = Cleaner(
                browser,
                day_mode=True,
                pending=pending,
                pending_policy="discard",
                max_batches=1,
                dry_run=True,
            )

            self.assertEqual(cleaner.run(), 1)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.days, ["2 Aug"])
            self.assertEqual(cleaner.last_outcome, PassOutcome.BOUNDED_STOP)

    def test_block_pending_does_not_poll_browser(self):
        class PollSpyBrowser(FakeBrowser):
            def wait_for_target_absence(self, _label):
                raise AssertionError("block policy must not poll")

        browser = PollSpyBrowser([])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Foto - pending", kind="day", scroll_top=0)
            cleaner = Cleaner(browser, pending=pending)

            self.assertEqual(cleaner.run(), 0)
            self.assertTrue(cleaner.stop_requested)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)
            self.assertIsNotNone(pending.load())

    def test_pending_target_absent_without_feedback_stays_unresolved(self):
        class AbsentWithoutFeedbackBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([])
                self.wait_calls = 0

            def target_exists(self, _label):
                return False

            def wait_for_target_absence(self, _label):
                self.wait_calls += 1
                return False

        browser = AbsentWithoutFeedbackBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Foto - 2 ago", kind="day", scroll_top=200)
            cleaner = Cleaner(browser, day_mode=True, pending=pending, max_idle_scrolls=1)
            processed = cleaner.run()

            self.assertEqual(processed, 0)
            self.assertIsNotNone(pending.load())
            self.assertEqual(browser.wait_calls, 0)
            self.assertEqual(browser.trashed, [])
            self.assertTrue(cleaner.stop_requested)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)

    def test_single_media_fallback_is_journaled_as_media_action(self):
        class SingleMediaBrowser(FakeBrowser):
            def select_current_day(self):
                self.days.append("Foto - 2 ago")
                self.last_selection_kind = "media"
                return "Foto - 2 ago"

            def delete_selected_day(self):
                self.trashed.append(["media"])
                return False

            def wait_for_target_absence(self, _label):
                return False

        browser = SingleMediaBrowser([("Foto - 2 ago", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            cleaner = Cleaner(browser, execute=True, confirm_all_media_to_trash=True, day_mode=True, pending=pending, max_batches=1)
            cleaner.run()

            self.assertEqual(browser.trashed, [["media"]])
            self.assertEqual(pending.load()["kind"], "media_batch")
            self.assertEqual(pending.load()["count"], 0)
            self.assertEqual(pending.load()["media_ids"], [])

    def test_confirmed_day_action_resets_timeline_once(self):
        class UnresolvedDayBrowser(FakeBrowser):
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False

            def wait_for_target_absence(self, _label):
                return False

        browser = UnresolvedDayBrowser([("2 Aug", 1)])
        cleaner = Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, day_mode=True, max_idle_scrolls=1)
        cleaner.run()

        self.assertTrue(cleaner.stop_requested)
        self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)
        self.assertEqual(browser.trashed, [["day"]])

    def test_confirmed_day_action_resets_timeline_once(self):
        class ResetTrackingBrowser(FakeBrowser):
            def __init__(self):
                super().__init__([("2 Aug", 1)])
                self.reset_calls = 0

            def reset_timeline_to_top(self):
                self.reset_calls += 1

        browser = ResetTrackingBrowser()
        processed = Cleaner(browser, pending=_test_pending(), day_mode=True, max_idle_scrolls=1, execute=True, confirm_all_media_to_trash=True).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.reset_calls, 1)

    def test_cleaner_handles_adjacent_days_without_timeline_reset(self):
        browser = FakeBrowser([("2 Aug", 3), ("1 Aug", 2)])

        processed = Cleaner(browser, pending=_test_pending(), day_mode=True, max_idle_scrolls=1, execute=True, confirm_all_media_to_trash=True).run()

        self.assertEqual(processed, 2)
        self.assertEqual(browser.days, ["2 Aug", "1 Aug"])
        self.assertEqual(browser.trashed, [["day"], ["day"]])

    def test_cleaner_processes_days_without_selecting_tiles(self):
        browser = FakeBrowser([("12 Aug", 3), ("13 Aug", 2)])

        processed = Cleaner(browser, pending=_test_pending(), day_mode=True, max_idle_scrolls=1, execute=True, confirm_all_media_to_trash=True).run()

        self.assertEqual(processed, 2)
        self.assertEqual(browser.days, ["12 Aug", "13 Aug"])
        self.assertEqual(browser.trashed, [["day"], ["day"]])

    def test_max_batches_stops_after_limit(self):
        browser = FakeBrowser([["old-1"], ["old-2"], ["old-3"]])

        processed = Cleaner(browser, pending=_test_pending(), execute=True, confirm_all_media_to_trash=True, max_batches=2, day_mode=False).run()

        self.assertEqual(processed, 2)
        self.assertEqual(browser.trashed, [["old-1"], ["old-2"]])

    def test_empty_library_finishes_without_trash_action(self):
        browser = FakeBrowser([])

        processed = Cleaner(browser, max_idle_scrolls=1).run()

        self.assertEqual(processed, 0)
        self.assertEqual(browser.trashed, [])

    def test_retries_recoverable_scan_before_selection(self):
        browser = RecoverableBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="retry")
            processed = Cleaner(browser, max_retries=1, diagnostic=diagnostic, day_mode=False).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.recover_calls, 1)

    def test_never_retries_ambiguous_destructive_action(self):
        browser = AmbiguousBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="ambiguous")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, pending=_test_pending(), diagnostic=diagnostic, day_mode=False, execute=True, confirm_all_media_to_trash=True).run()

            events = Path(tmp, "run.jsonl").read_text()

        self.assertIn("destructive_action_ambiguous", events)
