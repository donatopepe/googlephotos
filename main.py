"""CLI entry point for Google Photos browser cleaner."""

from __future__ import annotations

import logging
import sys

from googlephotos_cleaner.automation import Cleaner, CleanerError
from googlephotos_cleaner.browser import PlaywrightBrowser
from googlephotos_cleaner.cli import parse_args
from googlephotos_cleaner.diagnostics import CheckpointStore, DiagnosticLog, PendingActionStore


def configure_logging(log_file):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file)],
    )


def run(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_file)
    logger = logging.getLogger("googlephotos")
    diagnostic = DiagnosticLog(args.log_file.with_name("run.jsonl"))
    checkpoint = CheckpointStore(args.checkpoint_file)
    pending = PendingActionStore(args.checkpoint_file.with_name("pending-action.json"))
    browser = None
    keep_browser_open = False
    try:
        browser = PlaywrightBrowser(args.profile_dir, headless=False)
        diagnostic.event("browser_started", url=browser.page.url)
        cleaner = Cleaner(
            browser,
            batch_size=args.selection_size if args.selection_size > 1 else args.batch_size,
            max_batches=args.max_batches,
            max_retries=args.max_retries,
            dry_run=args.dry_run,
            logger=logger,
            diagnostic=diagnostic,
            checkpoint=checkpoint,
            # Day-first is default. Selection size controls batch capacity only;
            # --media-first explicitly opts into individual media batches.
            day_mode=not args.media_first,
            max_idle_scrolls=args.max_idle_scrolls,
            max_day_scan_failures=args.max_day_scan_failures,
            pending=pending,
            # User authorized discarding ambiguous media batch journals instead
            # of retrying their Trash action after a restart.
            discard_ambiguous_media_batches=True,
        )
        # Cleaner can stop a pass for idle DOM or a journaled pending action.
        # Keep same visible browser/context and start a fresh reconciliation pass;
        # never reopen Chrome or move the timeline.
        while True:
            cleaner.run()
            if cleaner.stop_requested:
                logger.warning("Cleaner requested safe stop")
                diagnostic.event("cleaner_stopped", "WARNING")
                return 0
            # Keep one browser/context alive; recoverable scan stalls are handled
            # inside Cleaner and must not turn into a five-minute inspection sleep.
            try:
                browser.page.wait_for_timeout(1000)
            except RuntimeError as exc:
                logger.error("Browser page closed: %s", exc)
                diagnostic.event("browser_page_closed", "ERROR", error_type=type(exc).__name__)
                return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except (CleanerError, OSError, RuntimeError) as exc:
        logger.error("Stopped safely: %s", exc)
        diagnostic.event("run_failed", "ERROR", error_type=type(exc).__name__, message=str(exc))
        if browser is not None:
            try:
                artifact_dir = args.diagnostics_dir / diagnostic.run_id
                paths = browser.capture_diagnostics(artifact_dir, type(exc).__name__)
                diagnostic.event(
                    "diagnostics_captured",
                    "ERROR",
                    directory=str(artifact_dir),
                    artifacts={key: str(value) for key, value in paths.items()},
                )
            except Exception as diagnostic_error:
                logger.error("Could not capture diagnostics: %s", diagnostic_error)
                diagnostic.event(
                    "diagnostics_failed",
                    "ERROR",
                    error_type=type(diagnostic_error).__name__,
                )
        if browser is not None and not args.exit_on_error:
            keep_browser_open = True
            logger.error("Browser left open for inspection; stop with Ctrl+C")
            try:
                browser.page.wait_for_timeout(300000)
            except Exception:
                keep_browser_open = False
        return 1
    finally:
        if browser is not None and not keep_browser_open:
            browser.close()


if __name__ == "__main__":
    sys.exit(run())
