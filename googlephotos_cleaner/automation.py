"""Batch orchestration with bounded, non-destructive recovery."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Protocol, Sequence

from .diagnostics import CheckpointStore, DiagnosticLog, PendingActionStore, process_context


class CleanerError(RuntimeError):
    """Raised when the browser cannot safely continue."""


class DestructiveActionAmbiguous(CleanerError):
    """Trash action may have happened; never retry it automatically."""

class PassOutcome(str, Enum):
    CONTINUE = "continue"
    PASS_DONE = "pass_done"
    STOP_SAFE = "stop_safe"
    PENDING_UNRESOLVED = "pending_unresolved"
    DESTRUCTIVE_AMBIGUOUS = "destructive_ambiguous"


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
        reset_timeline_after_action: bool = True,
        discard_ambiguous_media_batches: bool = False,
        pending_policy: str = "block",
        pending_timeout_ms: int = 30000,
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
        if pending_policy not in {"block", "inspect", "discard"}:
            raise ValueError("pending_policy must be block, inspect, or discard")
        if pending_timeout_ms <= 0:
            raise ValueError("pending_timeout_ms must be greater than zero")
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
        self.reset_timeline_after_action = reset_timeline_after_action
        self.pending_policy = pending_policy
        self.pending_timeout_ms = pending_timeout_ms
        self.last_outcome = PassOutcome.CONTINUE

    def _runtime_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {
            **process_context(),
            "mode": "dry-run" if self.dry_run else "delete",
            "pending_policy": self.pending_policy,
            "pending_timeout_ms": self.pending_timeout_ms,
            "max_batches": self.max_batches,
            "max_retries": self.max_retries,
            "max_idle_scrolls": self.max_idle_scrolls,
            "max_day_scan_failures": self.max_day_scan_failures,
            "scroll_step": getattr(self.browser, "scroll_step", None),
            "scroll_delay_ms": getattr(self.browser, "scroll_delay_ms", None),
        }
        profile_dir = getattr(self.browser, "profile_dir", None)
        if profile_dir is not None:
            context["profile_dir"] = str(profile_dir)
        if self.pending is not None:
            context["pending_path"] = str(self.pending.path)
        if self.checkpoint is not None:
            context["checkpoint_path"] = str(self.checkpoint.path)
        lock = getattr(self.browser, "profile_lock", None)
        if lock is not None:
            context["profile_lock_path"] = str(getattr(lock, "path", ""))
            context["profile_lock_owner_pid"] = getattr(lock, "pid", None)
            context["profile_lock_owned"] = getattr(lock, "acquired", None)
        return context

    def _event(self, phase: str, level: str = "INFO", **context: Any) -> None:
        if self.diagnostic is not None:
            self.diagnostic.event(phase, level, **context)
        if level in {"WARNING", "ERROR"} or phase in {
            "run_started",
            "authenticated",
            "day_scan",
            "day_selection",
            "day_trash_started",
            "day_trash_completed",
            "finished",
            "batch_limit",
            "cleaner_terminal_state",
        }:
            self.logger.log(
                logging.getLevelNamesMapping().get(level, logging.INFO),
                "phase=%s %s",
                phase,
                " ".join(f"{key}={value!r}" for key, value in context.items()),
            )

    def _recover(self, attempt: int, error: Exception) -> None:
        recover = getattr(self.browser, "recover", None)
        if recover is None:
            raise CleanerError(f"No safe recovery available: {error}") from error
        self._event(
            "retry",
            "WARNING",
            attempt=attempt,
            error_type=type(error).__name__,
            error_message=str(error),
        )
        try:
            recover()
        except Exception as recovery_error:
            self._event(
                "recovery_failed",
                "ERROR",
                attempt=attempt,
                error_type=type(recovery_error).__name__,
                error_message=str(recovery_error),
            )
            raise CleanerError("Safe recovery failed") from recovery_error

    def run(self) -> int:
        if self.last_outcome is not PassOutcome.CONTINUE:
            self.stop_requested = True
            self._event(
                "cleaner_terminal_state",
                "WARNING",
                outcome=self.last_outcome.value,
                stop_requested=True,
                already_terminal=True,
            )
            return 0
        self.stop_requested = False
        self._event("run_started", **self._runtime_context())
        self.browser.wait_until_authenticated()
        self._event("authenticated")
        if self.pending:
            previous = self.pending.load()
            self._event(
                "pending_loaded",
                pending_exists=previous is not None,
                pending_kind=previous.get("kind") if previous else None,
                pending_count=previous.get("count") if previous else None,
            )
            if previous and self.dry_run and self.pending_policy != "discard":
                self._event("pending_unresolved", "WARNING", target=previous.get("label"), policy=self.pending_policy)
                self.stop_requested = True
                self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                return 0
            if previous and self.pending_policy == "discard":
                self.pending.clear()
                self._event("pending_discarded_manual", "WARNING", target=previous.get("label"), policy=self.pending_policy)
                previous = None
            if previous and self.pending_policy in {"block", "inspect"}:
                self._event(
                    "pending_inspected" if self.pending_policy == "inspect" else "pending_unresolved",
                    "WARNING",
                    target=previous.get("label"),
                    policy=self.pending_policy,
                )
                self.stop_requested = True
                self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                return 0
            if previous and previous.get("kind") == "media_batch":
                if self.discard_ambiguous_media_batches or self.pending_policy == "discard":
                    self.pending.clear()
                    self._event(
                        "pending_batch_discarded",
                        "WARNING",
                        target=previous["label"],
                        count=previous.get("count"),
                        policy=self.pending_policy,
                    )
                    previous = None
                else:
                    self._event(
                        "pending_batch_unresolved",
                        "WARNING",
                        target=previous["label"],
                        count=previous.get("count"),
                    )
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                    self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                    return 0
            if previous:
                target_exists = getattr(self.browser, "target_exists", None)
                retry_pending = getattr(self.browser, "retry_pending_action", None)
                if target_exists is None:
                    raise CleanerError("Pending action cannot be reconciled")
                if not target_exists(previous["label"]):
                    wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                    target_absent = (
                        wait_for_absence(previous["label"], timeout_ms=self.pending_timeout_ms)
                        if wait_for_absence is not None
                        else False
                    )
                    if target_absent:
                        self.pending.clear()
                        self._event("pending_reconciled", target=previous["label"], result="absent")
                    else:
                        self._event(
                            "pending_unresolved",
                            "WARNING",
                            target=previous["label"],
                            result="absent_without_feedback",
                        )
                        self.stop_requested = True
                        self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                        self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                        return 0
                elif retry_pending is not None:
                    # A prior destructive result is ambiguous. Do not click Trash
                    # again; wait only for positive feedback from the original action.
                    wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                    target_absent = (
                        wait_for_absence(previous["label"], timeout_ms=self.pending_timeout_ms)
                        if wait_for_absence is not None
                        else False
                    )
                    if target_absent:
                        self.pending.clear()
                        self._event(
                            "pending_reconciled",
                            target=previous["label"],
                            result="present_after_wait",
                        )
                    else:
                        self._event(
                            "pending_unresolved",
                            "WARNING",
                            target=previous["label"],
                            result="present_without_feedback",
                        )
                        self.stop_requested = True
                        self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                        self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                        return 0
                else:
                    wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                    target_absent = (
                        wait_for_absence(previous["label"], timeout_ms=self.pending_timeout_ms)
                        if wait_for_absence is not None
                        else False
                    )
                    if target_absent:
                        self.pending.clear()
                        self._event(
                            "pending_reconciled", target=previous["label"], result="absent_after_wait"
                        )
                    else:
                        self._event("pending_reconciled", "WARNING", target=previous["label"], result="present_without_feedback")
                        self.stop_requested = True
                        self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                        self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
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
                        self._event(
                            "scan_failed",
                            "ERROR",
                            attempts=attempt + 1,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                        raise CleanerError("Scan failed after bounded retries") from exc
                    self._recover(attempt + 1, exc)

            if media_ids is None:
                raise CleanerError("Scan returned no result")
            if not media_ids:
                self.last_outcome = PassOutcome.PASS_DONE
                self.stop_requested = True
                self._event("finished", photos=total_photos, batches=processed, outcome=self.last_outcome.value)
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
                        error_message=str(exc),
                    )
                    if self.checkpoint:
                        self.checkpoint.save(
                            batch=processed, photos=total_photos, state="ambiguous"
                        )
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
                    raise DestructiveActionAmbiguous(
                        "Trash result is ambiguous; refusing destructive retry"
                    ) from exc
                if self.pending:
                    self.pending.clear()
                self._event(
                    "trash_completed",
                    count=len(media_ids),
                    positive_feedback=True,
                    result="confirmed",
                    feedback_source="browser_positive_feedback",
                )
                self.logger.info("Moved %d photos to Trash", len(media_ids))

            processed += 1
            total_photos += len(media_ids)
            if self.checkpoint:
                self.checkpoint.save(
                    batch=processed, photos=total_photos, state="running"
                )
            self._event("checkpoint_saved", batch=processed, photos=total_photos)
            if self.max_batches is not None and processed >= self.max_batches:
                self.stop_requested = True
                self.last_outcome = PassOutcome.PASS_DONE
                self._event("batch_limit", batches=processed, photos=total_photos)
                return processed

        self.last_outcome = PassOutcome.PASS_DONE
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
                    self._event(
                        "day_scan",
                        day=day,
                        attempt=attempt,
                        max_attempts=self.max_retries + 1,
                        selection_kind=getattr(self.browser, "last_selection_kind", None),
                    )
                    break
                except Exception as exc:
                    scan_failed = True
                    self._event(
                        "day_scan_failed",
                        "WARNING",
                        attempt=attempt + 1,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                    if attempt >= self.max_retries:
                        self._event(
                            "day_scan_skipped",
                            "WARNING",
                            attempts=attempt + 1,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                        break
                    self._recover(attempt + 1, exc)
            if not day:
                if scan_failed:
                    scan_failures += 1
                if scan_failed and scan_failures >= self.max_day_scan_failures:
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.STOP_SAFE
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
                advance_timeline = getattr(self.browser, "advance_timeline", None)
                should_advance = (
                    scan_failed
                    or (processed == 0 and idle_scrolls == 1)
                    or idle_scrolls >= self.max_idle_scrolls
                )
                if should_advance and advance_timeline is not None and advance_timeline():
                    self._event("timeline_advanced", idle_scrolls=idle_scrolls)
                    idle_scrolls = 0
                    continue
                if idle_scrolls < self.max_idle_scrolls:
                    continue
                self._event("timeline_paused", "WARNING", idle_scrolls=idle_scrolls)
                self.last_outcome = PassOutcome.STOP_SAFE
                if self.checkpoint:
                    self.checkpoint.save(batch=processed, photos=total_photos, state="idle")
                return processed
            idle_scrolls = 0
            scan_failures = 0
            if self.dry_run:
                self._event(
                    "day_selection",
                    day=day,
                    dry_run=True,
                    selection_kind=getattr(self.browser, "last_selection_kind", None),
                    fallback=getattr(self.browser, "last_selection_kind", None) == "media",
                )
                self.logger.info("Dry-run: found current day %s", day)
            else:
                self._event("day_trash_started", day=day)
                try:
                    if self.pending:
                        target_kind = "media" if getattr(self.browser, "last_selection_kind", "day") == "media" else "day"
                        self.pending.save(label=day, kind=target_kind, scroll_top=0)
                    completed = self.browser.delete_selected_day()
                    if completed is False:
                        self._event("day_trash_pending", "WARNING", day=day)
                        # The action was clicked once and journaled. Reconcile it
                        # before any further selection or destructive action.
                        wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                        if wait_for_absence is not None:
                            target_absent = wait_for_absence(day, timeout_ms=self.pending_timeout_ms)
                        else:
                            wait_for_timeline = getattr(self.browser, "wait_for_current_timeline", None)
                            if wait_for_timeline is not None:
                                wait_for_timeline()
                            target_absent = not self.browser.target_exists(day)
                        if self.pending and target_absent:
                            self.pending.clear()
                            self._event(
                                "day_trash_completed",
                                day=day,
                                reconciled=True,
                                positive_feedback=True,
                                result="confirmed",
                                reconciliation="feedback_confirmed",
                            )
                            self.logger.info("Moved day %s to Trash", day)
                            reset_top = getattr(self.browser, "reset_timeline_to_top", None)
                            if reset_top is not None and self.reset_timeline_after_action:
                                reset_top()
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
                            self.stop_requested = True
                            self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                            self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
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
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
                    self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                    return processed
                self._event(
                    "day_trash_completed",
                    day=day,
                    positive_feedback=True,
                    result="confirmed",
                    feedback_source=getattr(self.browser, "last_feedback_source", None),
                )
                self.logger.info("Moved day %s to Trash", day)
                reset_top = getattr(self.browser, "reset_timeline_to_top", None)
                if reset_top is not None and self.reset_timeline_after_action:
                    reset_top()
            processed += 1
            total_photos += 1
            if self.checkpoint:
                self.checkpoint.save(batch=processed, photos=total_photos, state="running")
            self._event("day_checkpoint_saved", day=day, days=processed)
            if self.max_batches is not None and processed >= self.max_batches:
                self.stop_requested = True
                self.last_outcome = PassOutcome.PASS_DONE
                self._event("batch_limit", batches=processed, photos=total_photos)
                return processed
        self.last_outcome = PassOutcome.PASS_DONE
        return processed
