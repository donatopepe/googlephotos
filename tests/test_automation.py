import tempfile
import unittest
from pathlib import Path

from googlephotos_cleaner.automation import Cleaner, CleanerError, DestructiveActionAmbiguous
from googlephotos_cleaner.diagnostics import CheckpointStore, DiagnosticLog, PendingActionStore


class FakeBrowser:
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

    def test_dry_run_does_not_move_photos(self):
        browser = FakeBrowser([["old-1"], ["old-2"]])

        processed = Cleaner(browser, dry_run=True, day_mode=False).run()

        self.assertEqual(processed, 2)
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
        self.assertEqual(browser.advance_count, 1)
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

    def test_ambiguous_media_batch_is_journaled_and_blocks_followup_trash(self):
        class AmbiguousBatchBrowser(FakeBrowser):
            def move_selected_to_trash(self, _media_ids):
                raise TimeoutError("unknown batch result")

        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending.json")
            browser = AmbiguousBatchBrowser([["photo-1", "photo-2"]])
            with self.assertRaises(DestructiveActionAmbiguous):
                Cleaner(browser, day_mode=False, pending=pending).run()
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
        self.assertEqual(browser.advance_count, 1)

    def test_cleaner_waits_without_scrolling_when_no_target_is_loaded(self):
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
        self.assertEqual(browser.advance_count, 0)

    def test_pending_day_waits_for_absence_before_continuing(self):
        class DelayedAbsenceBrowser(FakeBrowser):
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False

            def wait_for_target_absence(self, label):
                self.waited_label = label
                return True

        browser = DelayedAbsenceBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            processed = Cleaner(browser, day_mode=True, pending=pending, max_idle_scrolls=1).run()

            self.assertEqual(processed, 1)
            self.assertEqual(browser.waited_label, "2 Aug")
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

    def test_pending_day_absent_after_single_click_is_completed_without_retry(self):
        class PendingThenAbsentBrowser(FakeBrowser):
            def delete_selected_day(self):
                self.trashed.append(["day"])
                return False

        browser = PendingThenAbsentBrowser([("2 Aug", 1)])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            processed = Cleaner(
                browser, day_mode=True, pending=pending, max_idle_scrolls=1
            ).run()

            self.assertEqual(processed, 1)
            self.assertEqual(browser.trashed, [["day"]])
            self.assertIsNone(pending.load())

    def test_reconciles_pending_target_absent_without_second_delete(self):
        browser = FakeBrowser([])
        with tempfile.TemporaryDirectory() as tmp:
            pending = PendingActionStore(Path(tmp) / "pending-action.json")
            pending.save(label="Foto - 2 ago", kind="media", scroll_top=200)
            processed = Cleaner(browser, day_mode=True, pending=pending, max_idle_scrolls=1).run()

            self.assertEqual(processed, 0)
            self.assertIsNone(pending.load())
            self.assertEqual(browser.trashed, [])

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
