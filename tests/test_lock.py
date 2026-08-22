import json
import os
import tempfile
import unittest
from pathlib import Path

from googlephotos_cleaner.lock import ProfileLock, ProfileLockedError


class ProfileLockTests(unittest.TestCase):
    def test_lock_is_reused_only_after_stale_pid_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "profile.lock"
            lock = ProfileLock(lock_path, pid=999999999)
            lock.acquire()
            self.assertEqual(json.loads(lock_path.read_text())["pid"], 999999999)
            lock.release()
            self.assertFalse(lock_path.exists())

    def test_active_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "profile.lock"
            lock_path.write_text(json.dumps({"pid": os.getpid()}))

            with self.assertRaises(ProfileLockedError):
                ProfileLock(lock_path).acquire()


if __name__ == "__main__":
    unittest.main()
