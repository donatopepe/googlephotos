import tempfile
import unittest
from pathlib import Path

from googlephotos_cleaner.automation import Cleaner, CleanerError, DestructiveActionAmbiguous, PassOutcome
from googlephotos_cleaner.diagnostics import CheckpointStore, DiagnosticLog, PendingActionStore


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

    def select_visible_batch(self, batch_size):
        if not self.batches:
            return []
        return self.batches.pop(0)[:batch_size]

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

    def select_visible_batch(self, batch_size):
        self.scan_calls += 1
        if self.scan_calls == 1:
            raise TimeoutError("temporary timeout")
        return super().select_visible_batch(batch_size)

    def recover(self):
        self.recover_calls += 1


class AmbiguousBrowser(FakeBrowser):
    def move_selected_to_trash(self, media_ids):
        raise TimeoutError("result unknown after trash click")

    def recover(self):
        raise AssertionError("must not recover after destructive action")


class BrowserAdapterTests(unittest.TestCase):
    def test_fake_adapter_exposes_authentication_and_batch_operations(self):
        browser = FakeBrowser([["old-1", "old-2"]])

        browser.wait_until_authenticated()
        selected = browser.select_visible_batch(50)
        browser.move_selected_to_trash(selected)

        self.assertEqual(selected, ["old-1", "old-2"])
        self.assertEqual(browser.trashed, [["old-1", "old-2"]])

    def test_cleaner_does_not_retry_authentication(self):
        browser = FakeBrowser([])
        browser.authenticated = False
        browser.recover = lambda: self.fail("authentication must be manual")

        with self.assertRaises(CleanerError):
            Cleaner(browser, max_retries=4).run()

    def test_cleaner_reports_unauthenticated_session(self):
        browser = FakeBrowser([])
        browser.authenticated = False
        cleaner = Cleaner(browser, dry_run=True)

        with self.assertRaises(CleanerError):
            cleaner.run()

    def test_day_completion_with_missing_feedback_source_is_ambiguous(self):
        class NoSourceBrowser(FakeBrowser):
            last_feedback_source = None

        browser = NoSourceBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-source-required")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, day_mode=True, diagnostic=diagnostic, max_batches=1).run()
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
                Cleaner(browser, day_mode=True, diagnostic=diagnostic, max_batches=1).run()

    def test_day_completion_event_contains_observer_feedback_source(self):
        class DayBrowser(FakeBrowser):
            last_selection_kind = "day"
            last_feedback_source = "browser_positive_feedback"

        browser = DayBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="day-source")
            Cleaner(browser, day_mode=True, diagnostic=diagnostic, max_batches=1).run()
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
            Cleaner(browser, day_mode=False, diagnostic=diagnostic, max_batches=1).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        completed = next(event for event in events if event["phase"] == "trash_completed")
        self.assertEqual(completed["feedback_source"], "browser_positive_feedback")

    def test_media_completion_with_missing_feedback_source_is_ambiguous(self):
        class NoSourceBrowser(FakeBrowser):
            last_feedback_source = None

        browser = NoSourceBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="media-source-required")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, day_mode=False, diagnostic=diagnostic, max_batches=1).run()
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
                Cleaner(browser, day_mode=False, diagnostic=diagnostic, max_batches=1).run()

    def test_trash_completion_event_contains_positive_feedback(self):
        browser = FakeBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="trash-proof")
            Cleaner(browser, day_mode=False, diagnostic=diagnostic, max_batches=1).run()
            import json
            events = [json.loads(line) for line in Path(tmp, "run.jsonl").read_text().splitlines()]

        completed = next(event for event in events if event["phase"] == "trash_completed")
        self.assertTrue(completed["positive_feedback"])
        self.assertEqual(completed["result"], "confirmed")
        self.assertEqual(completed["feedback_source"], "browser_positive_feedback")

    def test_ambiguous_trash_event_includes_sanitized_error(self):
        browser = AmbiguousBrowser([["old-1"]])
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = DiagnosticLog(Path(tmp) / "run.jsonl", run_id="ambiguous-proof")
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, day_mode=False, diagnostic=diagnostic).run()
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
        cleaner = Cleaner(browser, dry_run=True, day_mode=False, max_batches=1)

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

    def test_bounded_dry_run_day_pass_requests_stop(self):
        browser = FakeBrowser([("2 Aug", 1), ("1 Aug", 1)])

        cleaner = Cleaner(browser, dry_run=True, day_mode=True, max_batches=1)
        processed = cleaner.run()

        self.assertEqual(processed, 1)
        self.assertTrue(cleaner.stop_requested)
        self.assertEqual(browser.trashed, [])

    def test_bounded_media_pass_requests_stop(self):
        browser = FakeBrowser([["photo-1"], ["photo-2"]])

        cleaner = Cleaner(browser, dry_run=True, day_mode=False, max_batches=1)
        processed = cleaner.run()

        self.assertEqual(processed, 1)
        self.assertTrue(cleaner.stop_requested)
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
        processed = Cleaner(browser, day_mode=True, max_retries=1).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.advance_count, 2)
        self.assertEqual(browser.trashed, [["day"]])

    def test_cleaner_stops_after_bounded_day_scan_failures(self):
        class AlwaysStaleBrowser(FakeBrowser):
            def select_current_day(self):
                raise TimeoutError("stale day control")

            def recover(self):
                pass

        browser = AlwaysStaleBrowser([])
        processed = Cleaner(
            browser,
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
        cleaner = Cleaner(browser, day_mode=True, max_retries=1, max_day_scan_failures=1)
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
        processed = Cleaner(browser, day_mode=True, max_retries=1).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.recover_calls, 1)
        self.assertEqual(browser.trashed, [["day"]])

    def test_pending_inspect_stops_without_retrying_destructive_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            browser = FakeBrowser([("new day", 1)])

            cleaner = Cleaner(browser, day_mode=True, pending=pending, pending_policy="inspect")
            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)
            self.assertEqual(browser.trashed, [])
            self.assertIsNotNone(pending.load())

    def test_pending_policy_block_does_not_call_retry_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            pending.save(label="day pending", kind="day", scroll_top=0)
            browser = FakeBrowser([("new day", 1)])
            browser.retry_pending_action = lambda _label: self.fail("automatic retry forbidden")

            cleaner = Cleaner(browser, day_mode=True, pending=pending, pending_policy="block")
            self.assertEqual(cleaner.run(), 0)
            self.assertEqual(cleaner.last_outcome, PassOutcome.PENDING_UNRESOLVED)

    def test_ambiguous_media_batch_is_journaled_and_blocks_followup_trash(self):
        class AmbiguousBatchBrowser(FakeBrowser):
            def move_selected_to_trash(self, _media_ids):
                raise TimeoutError("unknown batch result")

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            browser = AmbiguousBatchBrowser([["photo-1", "photo-2"]])
            cleaner = Cleaner(browser, day_mode=False, pending=pending)
            with self.assertRaises(DestructiveActionAmbiguous):
                cleaner.run()
            self.assertTrue(cleaner.stop_requested)
            record = pending.load()
            self.assertEqual(record["kind"], "media_batch")
            self.assertEqual(record["count"], 2)

            browser = FakeBrowser([["photo-3"]])
            self.assertEqual(Cleaner(browser, day_mode=False, pending=pending).run(), 0)
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
            ).run()

            self.assertEqual(processed, 1)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.trashed, [["photo-3"]])

    def test_cleaner_uses_selection_size_as_visible_batch_limit(self):
        browser = FakeBrowser([["photo-1", "photo-2", "photo-3"]])

        processed = Cleaner(browser, day_mode=False, batch_size=3).run()

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
        processed = Cleaner(browser, day_mode=True, max_batches=1, max_idle_scrolls=2).run()

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
        processed = Cleaner(browser, day_mode=True, max_batches=1, max_idle_scrolls=2).run()

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
            processed = Cleaner(
                browser,
                day_mode=True,
                pending=pending,
                pending_timeout_ms=321,
                max_idle_scrolls=1,
            ).run()

            self.assertEqual(processed, 1)
            self.assertEqual(browser.waited_label, "2 Aug")
            self.assertEqual(browser.waited_timeout_ms, 321)
            self.assertEqual(browser.trashed, [["day"]])
            self.assertIsNone(pending.load())

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
                browser, day_mode=True, pending=pending, max_idle_scrolls=1
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
            self.assertEqual(cleaner.last_outcome, PassOutcome.PASS_DONE)

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
            cleaner = Cleaner(browser, day_mode=True, pending=pending, max_batches=1)
            cleaner.run()

            self.assertEqual(browser.trashed, [["media"]])
            self.assertEqual(pending.load()["kind"], "media")

    def test_confirmed_day_action_resets_timeline_once(self):
        class UnresolvedDayBrowser(FakeBrowser):
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False

            def wait_for_target_absence(self, _label):
                return False

        browser = UnresolvedDayBrowser([("2 Aug", 1)])
        cleaner = Cleaner(browser, day_mode=True, max_idle_scrolls=1)
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
        processed = Cleaner(browser, day_mode=True, max_idle_scrolls=1).run()

        self.assertEqual(processed, 1)
        self.assertEqual(browser.reset_calls, 1)

    def test_cleaner_handles_adjacent_days_without_timeline_reset(self):
        browser = FakeBrowser([("2 Aug", 3), ("1 Aug", 2)])

        processed = Cleaner(browser, day_mode=True, max_idle_scrolls=1).run()

        self.assertEqual(processed, 2)
        self.assertEqual(browser.days, ["2 Aug", "1 Aug"])
        self.assertEqual(browser.trashed, [["day"], ["day"]])

    def test_cleaner_processes_days_without_selecting_tiles(self):
        browser = FakeBrowser([("12 Aug", 3), ("13 Aug", 2)])

        processed = Cleaner(browser, day_mode=True, max_idle_scrolls=1).run()

        self.assertEqual(processed, 2)
        self.assertEqual(browser.days, ["12 Aug", "13 Aug"])
        self.assertEqual(browser.trashed, [["day"], ["day"]])

    def test_max_batches_stops_after_limit(self):
        browser = FakeBrowser([["old-1"], ["old-2"], ["old-3"]])

        processed = Cleaner(browser, max_batches=2, day_mode=False).run()

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
                Cleaner(browser, diagnostic=diagnostic, day_mode=False).run()

            events = Path(tmp, "run.jsonl").read_text()

        self.assertIn("destructive_action_ambiguous", events)
