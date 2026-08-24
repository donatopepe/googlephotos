"""Batch orchestration with bounded, non-destructive recovery."""

from __future__ import annotations

import logging
from typing import Any, Protocol, Sequence

from .diagnostics import CheckpointStore, DiagnosticLog, PendingActionStore


class CleanerError(RuntimeError):
    """Raised when the browser cannot safely continue."""


class DestructiveActionAmbiguous(CleanerError):
    """Trash action may have happened; never retry it automatically."""


class BrowserAdapter(Protocol):
    def wait_until_authenticated(self) -> None: ...

    def select_visible_batch(self, batch_size: int) -> Sequence[str]: ...

    def move_selected_to_trash(self, media_ids: Sequence[str]) -> None: ...


class Cleaner:
    def __init__(
        self,
        browser: BrowserAdapter,
        *,
        batch_size: int = 50,
        max_batches: int | None = None,
        max_retries: int = 2,
        dry_run: bool = False,
        logger: logging.Logger | None = None,
        diagnostic: DiagnosticLog | None = None,
        checkpoint: CheckpointStore | None = None,
        day_mode: bool = True,
        max_idle_scrolls: int = 5,
        max_day_scan_failures: int = 3,
        pending: PendingActionStore | None = None,
        discard_ambiguous_media_batches: bool = False,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if max_batches is not None and max_batches <= 0:
            raise ValueError("max_batches must be greater than zero")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if max_idle_scrolls <= 0:
            raise ValueError("max_idle_scrolls must be greater than zero")
        if max_day_scan_failures <= 0:
            raise ValueError("max_day_scan_failures must be greater than zero")
        self.browser = browser
        self.batch_size = batch_size
        self.max_batches = max_batches
        self.max_retries = max_retries
        self.dry_run = dry_run
        self.logger = logger or logging.getLogger(__name__)
        self.diagnostic = diagnostic
        self.checkpoint = checkpoint
        self.day_mode = day_mode
        self.max_idle_scrolls = max_idle_scrolls
        self.max_day_scan_failures = max_day_scan_failures
        self.pending = pending
        self.discard_ambiguous_media_batches = discard_ambiguous_media_batches
        self.stop_requested = False

    def _event(self, phase: str, level: str = "INFO", **context: Any) -> None:
        if self.diagnostic is not None:
            self.diagnostic.event(phase, level, **context)

    def _recover(self, attempt: int, error: Exception) -> None:
        recover = getattr(self.browser, "recover", None)
        if recover is None:
            raise CleanerError(f"No safe recovery available: {error}") from error
        self._event("retry", "WARNING", attempt=attempt, error_type=type(error).__name__)
        try:
            recover()
        except Exception as recovery_error:
            self._event(
                "recovery_failed",
                "ERROR",
                attempt=attempt,
                error_type=type(recovery_error).__name__,
            )
            raise CleanerError("Safe recovery failed") from recovery_error

    def run(self) -> int:
        self._event("run_started", mode="dry-run" if self.dry_run else "delete")
        self.browser.wait_until_authenticated()
        self._event("authenticated")
        if self.pending:
            previous = self.pending.load()
            if previous:
                # A media batch has no stable single checkbox label to reconcile.
                # Preserve its journal and block all later destructive work rather
                # than mistaking a virtualized DOM disappearance for completion.
                if previous.get("kind") == "media_batch":
                    if self.discard_ambiguous_media_batches:
                        self.pending.clear()
                        self._event(
                            "pending_batch_discarded",
                            "WARNING",
                            target=previous["label"],
                            count=previous.get("count"),
                        )
                    else:
                        self._event(
                            "pending_batch_unresolved",
                            "WARNING",
                            target=previous["label"],
                            count=previous.get("count"),
                        )
                        return 0
                target_exists = getattr(self.browser, "target_exists", None)
                retry_pending = getattr(self.browser, "retry_pending_action", None)
                if target_exists is None:
                    raise CleanerError("Pending action cannot be reconciled")
                if not target_exists(previous["label"]):
                    self.pending.clear()
                    self._event("pending_reconciled", target=previous["label"], result="absent")
                elif retry_pending is not None:
                    # User-authorized after restart: click this exact pending target
                    # once more, then require positive completion feedback.
                    self._event("pending_retry_started", target=previous["label"])
                    if retry_pending(previous["label"]):
                        self.pending.clear()
                        self._event("pending_retry_completed", target=previous["label"])
                    else:
                        self._event("pending_retry_unresolved", "WARNING", target=previous["label"])
                        return 0
                else:
                    wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                    target_absent = (
                        wait_for_absence(previous["label"])
                        if wait_for_absence is not None
                        else not target_exists(previous["label"])
                    )
                    if target_absent:
                        self.pending.clear()
                        self._event(
                            "pending_reconciled", target=previous["label"], result="absent_after_wait"
                        )
                    else:
                        self._event("pending_reconciled", target=previous["label"], result="present")
                        return 0
        processed = 0
        total_photos = 0

        while self.max_batches is None or processed < self.max_batches:
            if self.day_mode:
                return self._run_days(processed, total_photos)

            media_ids: list[str] | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    media_ids = list(self.browser.select_visible_batch(self.batch_size))
                    self._event("scan", attempt=attempt, found=len(media_ids))
                    break
                except Exception as exc:
                    self.logger.warning("Recoverable scan failure (attempt %d): %s", attempt + 1, exc)
                    if attempt >= self.max_retries:
                        self._event("scan_failed", "ERROR", attempts=attempt + 1, error_type=type(exc).__name__)
                        raise CleanerError("Scan failed after bounded retries") from exc
                    self._recover(attempt + 1, exc)

            if media_ids is None:
                raise CleanerError("Scan returned no result")
            if not media_ids:
                self._event("finished", photos=total_photos, batches=processed)
                if self.checkpoint:
                    self.checkpoint.save(batch=processed, photos=total_photos, state="completed")
                self.logger.info("No photos found; finished")
                return processed

            if self.dry_run:
                self._event("selection", count=len(media_ids), dry_run=True)
                self.logger.info("Dry-run: found %d visible photos", len(media_ids))
            else:
                self._event("trash_started", count=len(media_ids))
                if self.pending:
                    self.pending.save(
                        label=f"batch:{processed + 1}",
                        kind="media_batch",
                        scroll_top=0,
                        count=len(media_ids),
                        media_ids=list(media_ids),
                    )
                try:
                    self.browser.move_selected_to_trash(media_ids)
                except Exception as exc:
                    self._event(
                        "destructive_action_ambiguous",
                        "ERROR",
                        error_type=type(exc).__name__,
                        count=len(media_ids),
                    )
                    if self.checkpoint:
                        self.checkpoint.save(
                            batch=processed, photos=total_photos, state="ambiguous"
                        )
                    raise DestructiveActionAmbiguous(
                        "Trash result is ambiguous; refusing destructive retry"
                    ) from exc
                if self.pending:
                    self.pending.clear()
                self._event("trash_completed", count=len(media_ids))
                self.logger.info("Moved %d photos to Trash", len(media_ids))

            processed += 1
            total_photos += len(media_ids)
            if self.checkpoint:
                self.checkpoint.save(
                    batch=processed, photos=total_photos, state="running"
                )
            self._event("checkpoint_saved", batch=processed, photos=total_photos)

        self._event("batch_limit", batches=processed, photos=total_photos)
        self.logger.info("Reached batch limit: %d", processed)
        return processed

    def _run_days(self, processed: int, total_photos: int) -> int:
        idle_scrolls = 0
        scan_failures = 0
        while self.max_batches is None or processed < self.max_batches:
            day = None
            scan_failed = False
            for attempt in range(self.max_retries + 1):
                try:
                    day = self.browser.select_current_day()
                    self._event("day_scan", day=day, attempt=attempt)
                    break
                except Exception as exc:
                    scan_failed = True
                    self._event(
                        "day_scan_failed",
                        "WARNING",
                        attempt=attempt + 1,
                        error_type=type(exc).__name__,
                    )
                    if attempt >= self.max_retries:
                        self._event(
                            "day_scan_skipped",
                            "WARNING",
                            attempts=attempt + 1,
                            error_type=type(exc).__name__,
                        )
                        break
                    self._recover(attempt + 1, exc)
            if not day:
                if scan_failed:
                    scan_failures += 1
                if scan_failed and scan_failures >= self.max_day_scan_failures:
                    self.stop_requested = True
                    self._event(
                        "day_scan_stopped",
                        "ERROR",
                        failures=scan_failures,
                    )
                    if self.checkpoint:
                        self.checkpoint.save(batch=processed, photos=total_photos, state="scan_failed")
                    return processed
                idle_scrolls += 1
                self._event("timeline_idle", idle_scrolls=idle_scrolls)
                wait_for_timeline = getattr(self.browser, "wait_for_current_timeline", None)
                if wait_for_timeline is not None:
                    wait_for_timeline()
                if idle_scrolls < self.max_idle_scrolls:
                    continue
                advance_timeline = getattr(self.browser, "advance_timeline", None)
                if advance_timeline is not None and advance_timeline():
                    self._event("timeline_advanced", idle_scrolls=idle_scrolls)
                    idle_scrolls = 0
                    continue
                self._event("timeline_paused", "WARNING", idle_scrolls=idle_scrolls)
                if self.checkpoint:
                    self.checkpoint.save(batch=processed, photos=total_photos, state="idle")
                return processed
            idle_scrolls = 0
            scan_failures = 0
            if self.dry_run:
                self._event("day_selection", day=day, dry_run=True)
                self.logger.info("Dry-run: found current day %s", day)
            else:
                self._event("day_trash_started", day=day)
                try:
                    if self.pending:
                        self.pending.save(label=day, kind="day", scroll_top=0)
                    completed = self.browser.delete_selected_day()
                    if completed is False:
                        self._event("day_trash_pending", "WARNING", day=day)
                        # The action was clicked once and journaled. Reconcile it
                        # before any further selection or destructive action.
                        wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                        if wait_for_absence is not None:
                            target_absent = wait_for_absence(day)
                        else:
                            wait_for_timeline = getattr(self.browser, "wait_for_current_timeline", None)
                            if wait_for_timeline is not None:
                                wait_for_timeline()
                            target_absent = not self.browser.target_exists(day)
                        if self.pending and target_absent:
                            self.pending.clear()
                            self._event("day_trash_completed", day=day, reconciled=True)
                            self.logger.info("Moved day %s to Trash", day)
                            processed += 1
                            total_photos += 1
                            if self.checkpoint:
                                self.checkpoint.save(
                                    batch=processed, photos=total_photos, state="running"
                                )
                            self._event("day_checkpoint_saved", day=day, days=processed)
                        else:
                            if self.checkpoint:
                                self.checkpoint.save(
                                    batch=processed, photos=total_photos, state="pending"
                                )
                            self._event("day_trash_unresolved", "WARNING", day=day)
                            return processed
                        continue
                    if self.pending:
                        self.pending.clear()
                except Exception as exc:
                    # A click may already have reached Google Photos. Keep its
                    # journal entry and stop this run without a second click.
                    self._event(
                        "destructive_action_pending",
                        "WARNING",
                        day=day,
                        error_type=type(exc).__name__,
                    )
                    if self.checkpoint:
                        self.checkpoint.save(batch=processed, photos=total_photos, state="pending")
                    self.logger.warning(
                        "Trash result pending for %s; will reconcile before another click", day
                    )
                    return processed
                self._event("day_trash_completed", day=day)
                self.logger.info("Moved day %s to Trash", day)
            processed += 1
            total_photos += 1
            if self.checkpoint:
                self.checkpoint.save(batch=processed, photos=total_photos, state="running")
            self._event("day_checkpoint_saved", day=day, days=processed)
        return processed
