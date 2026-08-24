from pathlib import Path

import unittest

from googlephotos_cleaner.cli import build_parser, parse_args


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

    def test_parser_supports_idle_scroll_limit(self):
        args = parse_args(["--max-idle-scrolls", "7"])
        self.assertEqual(args.max_idle_scrolls, 7)

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
