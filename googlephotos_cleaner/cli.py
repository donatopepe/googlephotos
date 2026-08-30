"""Command-line interface for the Google Photos cleaner."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence


class _FailClosedArgumentParser(argparse.ArgumentParser):
    """Reject unsafe mode combinations before the runtime is constructed."""

    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if parsed.dry_run and (parsed.execute or parsed.confirm_all_media_to_trash):
            self.error("--dry-run cannot be combined with destructive authorization")
        if parsed.execute != parsed.confirm_all_media_to_trash:
            self.error(
                "--execute and --confirm-all-media-to-trash must be supplied together"
            )
        # No mode flag is safe by default: an omitted mode means dry-run,
        # never an implicit Trash execution.
        if not parsed.execute:
            parsed.dry_run = True
        return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = _FailClosedArgumentParser(
        description="Google Photos browser cleaner: process visible photos and days."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="scan and log batches without moving photos to Trash",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="enable moving selected photos and videos to the Google Photos Trash",
    )
    parser.add_argument(
        "--confirm-all-media-to-trash",
        action="store_true",
        help="explicitly confirm that all selected photos and videos may be moved to Trash",
    )
    parser.add_argument(
        "--reconcile-pending",
        action="store_true",
        help="inspect existing pending action for positive feedback without clicking Trash",
    )
    parser.add_argument(
        "--max-batches",
        type=_positive_int,
        default=None,
        help="stop after this many batches (default: no limit)",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path("data/browser-profile"),
        help="persistent browser profile directory",
    )
    parser.add_argument(
        "--cdp-url",
        default=None,
        help="connect to an already authenticated Chrome DevTools endpoint instead of launching a browser",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("data/run.log"),
        help="runtime log path",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=50,
        help="maximum visible photos handled per batch (default: 50)",
    )
    parser.add_argument(
        "--selection-size",
        type=_positive_int,
        default=1,
        help="maximum current-viewport media targets to select before one Trash action (default: 1)",
    )
    parser.add_argument(
        "--media-first",
        action="store_true",
        help="skip day-first selection and process visible media batches instead",
    )
    parser.add_argument(
        "--max-retries",
        type=lambda value: _non_negative_int(value),
        default=2,
        help="maximum safe recovery attempts before stopping (default: 2)",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=Path("data/diagnostics"),
        help="directory for error screenshots (no page-content artifacts)",
    )
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=Path("data/checkpoint.json"),
        help="atomic progress checkpoint path",
    )
    parser.add_argument(
        "--exit-on-error",
        action="store_true",
        help="close browser and exit immediately after a diagnosed error",
    )
    parser.add_argument(
        "--max-idle-scrolls",
        type=_positive_int,
        default=5,
        help="consecutive timeline scrolls without progress before ending (default: 5)",
    )
    parser.add_argument(
        "--max-day-scan-failures",
        type=_positive_int,
        default=3,
        help="failure cycles before one bounded timeline recovery round (default: 3)",
    )
    parser.add_argument(
        "--scroll-step",
        type=_positive_int,
        default=240,
        help="timeline wheel distance per scroll (default: 240)",
    )
    parser.add_argument(
        "--scroll-delay-ms",
        type=_positive_int,
        default=1500,
        help="wait after each timeline scroll in milliseconds (default: 1500)",
    )
    parser.add_argument(
        "--pointer-pause-ms",
        type=_positive_int,
        default=40,
        help="pause between bounded visible pointer moves in milliseconds (default: 40)",
    )
    parser.add_argument(
        "--pointer-max-steps",
        type=_positive_int,
        default=4,
        help="maximum points in each bounded pointer trajectory (default: 4)",
    )
    parser.add_argument(
        "--inactivity-timeout-seconds",
        type=_positive_int,
        default=300,
        help="stop a single authentication/scan wait after this inactivity bound (default: 300)",
    )
    parser.add_argument(
        "--pending-action",
        choices=("block", "inspect", "discard"),
        default="inspect",
        help="pending Trash policy: inspect discards only after timeout and continues (default: inspect)"
    )
    parser.add_argument(
        "--pending-timeout-ms",
        type=_positive_int,
        default=30000,
        help="bounded pending reconciliation timeout in milliseconds (default: 30000)",
    )
    return parser


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)
