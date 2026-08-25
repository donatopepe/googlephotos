"""CLI entry point for Google Photos browser cleaner."""

from __future__ import annotations

import logging
import sys

from googlephotos_cleaner.automation import Cleaner, CleanerError
from googlephotos_cleaner.browser import PlaywrightBrowser
from googlephotos_cleaner.cli import parse_args
from googlephotos_cleaner.diagnostics import CheckpointStore, DiagnosticLog, PendingActionStore, process_context


def configure_logging(log_file):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("googlephotos")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(logging.StreamHandler())
    logger.addHandler(logging.FileHandler(log_file))
    return logger


def emit_terminal_summary(
    diagnostic,
    *,
    outcome,
    stop_requested,
    processed,
    pending,
    checkpoint,
    browser=None,
    browser_cleanup="not_started",
    checkpoint_state=None,
    checkpoint_reason=None,
):
    diagnostic.event(
        "cleaner_stopped",
        "WARNING" if stop_requested or outcome in {"failed", "interrupted", "failed_close"} else "INFO",
        outcome=outcome,
        stop_requested=stop_requested,
        processed=processed,
        pending_path=str(pending.path),
        pending_exists=pending.path.exists(),
        checkpoint_path=str(checkpoint.path),
        checkpoint_exists=checkpoint.path.exists(),
        profile_dir=str(getattr(browser, "profile_dir", "")) if browser is not None else None,
        profile_lock_path=str(getattr(getattr(browser, "profile_lock", None), "path", "")) if browser is not None else None,
        profile_lock_owner_pid=getattr(getattr(browser, "profile_lock", None), "pid", None) if browser is not None else None,
        profile_lock_owned=getattr(getattr(browser, "profile_lock", None), "acquired", None) if browser is not None else None,
        browser_cleanup=browser_cleanup,
        checkpoint_state=checkpoint_state,
        checkpoint_reason=checkpoint_reason,
        result="terminal_summary",
        positive_feedback=False,
        feedback_source=None,
        **process_context(),
    )


def run(argv=None) -> int:
    args = parse_args(argv)
    logger = configure_logging(args.log_file)
    diagnostic = DiagnosticLog(args.log_file.with_name("run.jsonl"))
    checkpoint = CheckpointStore(args.checkpoint_file)
    pending = PendingActionStore(args.checkpoint_file.with_name("pending-action.json"))
    browser = None
    keep_browser_open = False
    processed = None
    run_outcome = None
    browser_cleanup = "not_started"
    cleaner_stop_requested = False
    processed_total = 0
    exit_code = 0
    checkpoint_state = None
    checkpoint_reason = None
    try:
        browser = PlaywrightBrowser(
            args.profile_dir,
            headless=False,
            scroll_step=args.scroll_step,
            scroll_delay_ms=args.scroll_delay_ms,
            diagnostic=diagnostic,
        )
        diagnostic.event(
            "browser_started",
            **process_context(),
            profile_dir=str(browser.profile_dir),
            profile_lock_path=str(browser.profile_lock.path),
            profile_lock_owner_pid=getattr(browser.profile_lock, "pid", None),
            profile_lock_owned=getattr(browser.profile_lock, "acquired", None),
            pending_path=str(pending.path),
            checkpoint_path=str(checkpoint.path),
            url=browser.page.url,
            page_count=len(browser.context.pages),
            scroll_step=args.scroll_step,
            scroll_delay_ms=args.scroll_delay_ms,
            max_idle_scrolls=args.max_idle_scrolls,
            max_day_scan_failures=args.max_day_scan_failures,
            pending_policy=args.pending_action,
            pending_timeout_ms=args.pending_timeout_ms,
        )
        diagnostic.event(
            "run_configured",
            **process_context(),
            mode="dry-run" if args.dry_run else "delete",
            pending_policy=args.pending_action,
            pending_timeout_ms=args.pending_timeout_ms,
        )
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
            reset_timeline_after_action=True,
            # User authorized discarding ambiguous media batch journals instead
            # of retrying their Trash action after a restart.
            discard_ambiguous_media_batches=args.pending_action == "discard",
            pending_policy=args.pending_action,
            pending_timeout_ms=args.pending_timeout_ms,
        )
        # One invocation owns one bounded pass. Cleaner handles bounded
        # recovery and terminal stop; never re-enter pass loop.
        processed = cleaner.run()
        processed_total = processed or 0
        run_outcome = cleaner.last_outcome.value
        cleaner_stop_requested = bool(getattr(cleaner, "stop_requested", False))
    except KeyboardInterrupt:
        run_outcome = "interrupted"
        logger.warning("Interrupted by user")
        checkpoint_state = "interrupted"
        checkpoint_reason = "keyboard_interrupt"
        checkpoint.save(
            batch=processed_total,
            photos=processed_total,
            state=checkpoint_state,
            reason=checkpoint_reason,
            run_id=diagnostic.run_id,
            **process_context(),
        )
        exit_code = 130
    except (CleanerError, OSError, RuntimeError) as exc:
        cleaner_outcome = getattr(locals().get("cleaner"), "last_outcome", None)
        run_outcome = (
            cleaner_outcome.value
            if cleaner_outcome is not None and cleaner_outcome.value != "continue"
            else "failed"
        )
        logger.error("Stopped safely: %s", exc)
        checkpoint_state = "ambiguous" if run_outcome == "destructive_ambiguous" else "scan_failed"
        checkpoint_reason = type(exc).__name__
        checkpoint.save(
            batch=processed_total,
            photos=processed_total,
            state=checkpoint_state,
            reason=checkpoint_reason,
            run_id=diagnostic.run_id,
            **process_context(),
        )
        exit_code = 1
        diagnostic.event(
            "run_failed",
            "ERROR",
            error_type=type(exc).__name__,
            error_message=str(exc),
            recovery="diagnostics_capture_attempted",
            result="failed",
            positive_feedback=False,
            feedback_source=None,
        )
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
                diagnostic.event(
                    "diagnostics_failed",
                    "ERROR",
                    error_type=type(diagnostic_error).__name__,
                    error_message=str(diagnostic_error),
                    console_reported=False,
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
            try:
                browser.close()
                browser_cleanup = "closed"
            except Exception as close_error:
                browser_cleanup = "failed"
                run_outcome = "failed_close"
                checkpoint_state = "close_failed"
                checkpoint_reason = "browser_close_failed"
                checkpoint.save(
                    batch=processed_total,
                    photos=processed_total,
                    state=checkpoint_state,
                    reason=checkpoint_reason,
                    run_id=diagnostic.run_id,
                    **process_context(),
                )
                exit_code = 1
                diagnostic.event(
                    "browser_close_failed",
                    "ERROR",
                    error_type=type(close_error).__name__,
                    error_message=str(close_error),
                    result="close_failed",
                    positive_feedback=False,
                    feedback_source=None,
                )
        if run_outcome is None:
            run_outcome = "finished"
        checkpoint_snapshot = checkpoint.load()
        if checkpoint_snapshot is not None:
            checkpoint_state = checkpoint_snapshot.get("state")
            checkpoint_reason = checkpoint_snapshot.get("reason")
        emit_terminal_summary(
            diagnostic,
            outcome=run_outcome,
            stop_requested=cleaner_stop_requested or run_outcome in {"failed", "interrupted", "failed_close"},
            processed=processed,
            pending=pending,
            checkpoint=checkpoint,
            browser=browser,
            browser_cleanup=browser_cleanup,
            checkpoint_state=checkpoint_state,
            checkpoint_reason=checkpoint_reason,
        )
        diagnostic.event(
            "run_finished",
            **process_context(),
            outcome=run_outcome,
            stop_requested=cleaner_stop_requested or run_outcome in {"failed", "interrupted", "failed_close"},
            processed=processed,
            browser_open=browser is not None and keep_browser_open,
            pending_path=str(pending.path),
            pending_exists=pending.path.exists(),
            checkpoint_path=str(checkpoint.path),
            checkpoint_exists=checkpoint.path.exists(),
            profile_dir=str(getattr(browser, "profile_dir", "")) if browser is not None else None,
            profile_lock_path=str(getattr(getattr(browser, "profile_lock", None), "path", "")) if browser is not None else None,
            profile_lock_owner_pid=getattr(getattr(browser, "profile_lock", None), "pid", None) if browser is not None else None,
            profile_lock_owned=getattr(getattr(browser, "profile_lock", None), "acquired", None) if browser is not None else None,
            browser_cleanup=browser_cleanup,
            checkpoint_state=checkpoint_state,
            checkpoint_reason=checkpoint_reason,
            result="run_finished",
            positive_feedback=False,
            feedback_source=None,
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
