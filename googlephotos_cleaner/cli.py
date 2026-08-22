"""Command-line interface for the Google Photos cleaner."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Google Photos browser cleaner: process visible photos and days."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and log batches without moving photos to Trash",
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
        "--max-retries",
        type=lambda value: _non_negative_int(value),
        default=2,
        help="maximum safe recovery attempts before stopping (default: 2)",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=Path("data/diagnostics"),
        help="directory for error screenshots and HTML snapshots",
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
