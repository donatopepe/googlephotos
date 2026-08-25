import json
import tempfile
import unittest
from pathlib import Path

from googlephotos_cleaner.diagnostics import DiagnosticLog, CheckpointStore, PendingActionStore, redact_url


class DiagnosticsTests(unittest.TestCase):
    def test_redact_url_removes_query_and_fragment(self):
        self.assertEqual(
            redact_url("https://photos.google.com/u/0/?authuser=secret#photo"),
            "https://photos.google.com/u/0/",
        )

    def test_log_writes_jsonl_with_run_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            log = DiagnosticLog(path, run_id="test-run")
            log.event("scan", "INFO", attempt=2, found=4, url="https://photos.google.com/?x=y")

            event = json.loads(path.read_text().strip())

            self.assertEqual(event["run_id"], "test-run")
            self.assertEqual(event["phase"], "scan")
            self.assertEqual(event["attempt"], 2)
            self.assertEqual(event["url"], "https://photos.google.com/")
            self.assertEqual(event["found"], 4)
            self.assertTrue(event["timestamp"])

    def test_log_supports_verbose_runtime_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            log = DiagnosticLog(path, run_id="verbose")
            log.event(
                "scroll",
                "INFO",
                pid=123,
                profile_lock_owner_pid=123,
                wheel_delta_y=240,
                viewport={"width": 1000, "height": 600},
                dom_before={"day": 0, "media": 4},
                dom_after={"day": 1, "media": 8},
                materialized=True,
                result="advanced",
            )

            event = json.loads(path.read_text().strip())

            self.assertEqual(event["pid"], 123)
            self.assertEqual(event["wheel_delta_y"], 240)
            self.assertEqual(event["dom_before"]["media"], 4)
            self.assertEqual(event["dom_after"]["day"], 1)
            self.assertTrue(event["materialized"])
            self.assertEqual(event["result"], "advanced")

    def test_log_redacts_nested_sensitive_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            log = DiagnosticLog(path, run_id="safe")
            log.event(
                "error",
                details={"password": "secret", "url": "https://photos.google.com/?token=x"},
            )

            event = json.loads(path.read_text().strip())

            self.assertNotIn("password", event["details"])
            self.assertEqual(event["details"]["url"], "https://photos.google.com/")

    def test_log_redacts_page_content_and_credentials_from_verbose_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            log = DiagnosticLog(path, run_id="verbose-safe")
            log.event(
                "browser_state",
                html="<input password='secret'>cookie=secret",
                cookie="secret",
                authorization="secret",
                details={"token": "secret", "message": "password=secret"},
            )

            text = path.read_text()

            self.assertNotIn("secret", text)
            self.assertNotIn("<input", text)

    def test_log_redacts_sensitive_values_inside_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            log = DiagnosticLog(path, run_id="message-safe")
            log.event(
                "error",
                message="https://photos.google.com/?token=secret token=secret password=hunter2",
            )

            event = json.loads(path.read_text().strip())

            self.assertNotIn("hunter2", event["message"])
            self.assertNotIn("token=secret", event["message"])
            self.assertEqual(event["message"].split()[0], "https://photos.google.com/")

    def test_pending_action_round_trip_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PendingActionStore(Path(tmp) / "pending-action.json")
            store.save(label="Foto - 2 ago", kind="media", scroll_top=500, cookie="no")

            pending = store.load()

            self.assertEqual(pending["label"], "Foto - 2 ago")
            self.assertEqual(pending["kind"], "media")
            self.assertEqual(pending["scroll_top"], 500)
            self.assertNotIn("cookie", pending)
            store.clear()
            self.assertIsNone(store.load())

    def test_checkpoint_load_marks_legacy_running_state_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps({"batch": 1, "photos": 1, "state": "running"}))
            checkpoint = CheckpointStore(path)
            loaded = checkpoint.load()
            self.assertEqual(loaded["state"], "stale")
            self.assertEqual(loaded["reason"], "legacy_running_without_run_identity")
            self.assertFalse(loaded["resumable"])

    def test_checkpoint_load_marks_foreign_running_state_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            path.write_text(json.dumps({"batch": 1, "photos": 1, "state": "running", "run_id": "other-run"}))
            checkpoint = CheckpointStore(path)
            loaded = checkpoint.load(current_run_id="current-run")
            self.assertEqual(loaded["state"], "stale")
            self.assertEqual(loaded["reason"], "run_identity_mismatch")
            self.assertFalse(loaded["resumable"])

    def test_checkpoint_is_written_atomically_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            store = CheckpointStore(path)
            store.save(
                batch=3,
                photos=120,
                state="completed",
                reason="bounded pass complete",
                run_id="run-123",
                pid=4321,
                password="never-save",
            )

            saved = json.loads(path.read_text())

            self.assertEqual(saved["batch"], 3)
            self.assertEqual(saved["photos"], 120)
            self.assertEqual(saved["state"], "completed")
            self.assertEqual(saved["reason"], "bounded pass complete")
            self.assertEqual(saved["run_id"], "run-123")
            self.assertEqual(saved["pid"], 4321)
            self.assertNotIn("password", saved)
            self.assertFalse(path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
