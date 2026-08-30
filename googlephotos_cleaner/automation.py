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
    BOUNDED_STOP = "bounded_stop"
    STOP_SAFE = "stop_safe"
    PENDING_UNRESOLVED = "pending_unresolved"
    DESTRUCTIVE_AMBIGUOUS = "destructive_ambiguous"


class BrowserAdapter(Protocol):
    def wait_until_authenticated(self) -> None: ...

    def select_current_day(
        self,
        *,
        batch_size: int | None = None,
        excluded_media_ids: Sequence[str] = (),
    ) -> str | None: ...

    def select_visible_batch(
        self,
        batch_size: int,
        *,
        excluded_media_ids: Sequence[str] = (),
    ) -> Sequence[str]: ...

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
        execute: bool = False,
        confirm_all_media_to_trash: bool = False,
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
        if not isinstance(execute, bool) or not isinstance(confirm_all_media_to_trash, bool):
            raise ValueError("execute and confirm_all_media_to_trash must be booleans")
        if execute != confirm_all_media_to_trash:
            raise CleanerError(
                "destructive actions require both execute and confirm_all_media_to_trash"
            )
        if dry_run and (execute or confirm_all_media_to_trash):
            raise CleanerError("dry_run cannot be combined with destructive authorization")
        if execute and pending is None:
            raise CleanerError(
                "destructive actions require a durable pending store"
            )
        self.browser = browser
        self.batch_size = batch_size
        self.max_batches = max_batches
        self.max_retries = max_retries
        self.dry_run = dry_run
        self.execute = execute
        self.confirm_all_media_to_trash = confirm_all_media_to_trash
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
        self.reconcile_pending_only = False
        self.last_outcome = PassOutcome.CONTINUE
        self._day_scan_recovery_rounds = 0
        self._skipped_ambiguous_targets: set[str] = set()
        self._skipped_ambiguous_media_ids: set[str] = set()

    def _browser_batch_ids(self, media_ids: Sequence[str]) -> list[str]:
        """Return stable IDs for a selected batch when the adapter exposes them."""
        exposed = getattr(self.browser, "last_batch_ids", None)
        if exposed is None:
            return list(media_ids)
        return list(exposed)

    def _batch_is_skipped(self, media_ids: Sequence[str]) -> bool:
        stable_ids = set(self._browser_batch_ids(media_ids))
        return bool(stable_ids) and bool(stable_ids & self._skipped_ambiguous_media_ids)

    def _select_media_batch(self) -> list[str]:
        """Select one bounded batch while excluding previously ambiguous media."""
        excluded = self._skipped_ambiguous_media_ids
        try:
            return list(
                self.browser.select_visible_batch(
                    self.batch_size,
                    excluded_media_ids=excluded,
                )
            )
        except TypeError as exc:
            if "excluded_media_ids" not in str(exc):
                raise
            return list(self.browser.select_visible_batch(self.batch_size))

    def _checkpoint(self, *, batch: int, photos: int, state: str, reason: str) -> None:
        if self.checkpoint is None:
            return
        self.checkpoint.save(
            batch=batch,
            photos=photos,
            state=state,
            reason=reason,
            run_id=getattr(self.diagnostic, "run_id", None),
            **process_context(),
        )

    def _runtime_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {
            **process_context(),
            "mode": "delete" if self.execute else "dry-run",
            "execute": self.execute,
            "confirm_all_media_to_trash": self.confirm_all_media_to_trash,
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
        if phase == "cleaner_terminal_state":
            context.setdefault("result", "terminal_state")
            context.setdefault("positive_feedback", False)
            context.setdefault("feedback_source", None)
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
                result="already_terminal",
                positive_feedback=False,
                feedback_source=None,
            )
            return 0
        self.stop_requested = False
        if self.checkpoint is not None:
            checkpoint = self.checkpoint.load(
                current_run_id=getattr(self.diagnostic, "run_id", None),
            )
            if checkpoint and checkpoint.get("state") in {"pending", "ambiguous"}:
                checkpoint_is_pending = checkpoint.get("state") == "pending"
                if self.pending_policy == "discard":
                    self.checkpoint.path.unlink(missing_ok=True)
                    self._event(
                        "checkpoint_discarded_manual",
                        "WARNING",
                        state=checkpoint.get("state"),
                        reason=checkpoint.get("reason"),
                        policy=self.pending_policy,
                        result="discarded_without_reconciliation",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                elif checkpoint_is_pending and self.pending_policy == "inspect":
                    self._event(
                        "checkpoint_pending_discarded_after_timeout",
                        "WARNING",
                        state=checkpoint.get("state"),
                        reason=checkpoint.get("reason"),
                        policy=self.pending_policy,
                        result="discarded_without_reconciliation",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    self.checkpoint.path.unlink(missing_ok=True)
                else:
                    self.stop_requested = True
                    self.last_outcome = (
                        PassOutcome.DESTRUCTIVE_AMBIGUOUS
                        if checkpoint.get("state") == "ambiguous"
                        else PassOutcome.PENDING_UNRESOLVED
                    )
                    self._event(
                        "checkpoint_unresolved",
                        "WARNING",
                        state=checkpoint.get("state"),
                        reason=checkpoint.get("reason"),
                        resumable=False,
                    )
                    self._event(
                        "cleaner_terminal_state",
                        "WARNING",
                        outcome=self.last_outcome.value,
                        stop_requested=True,
                        checkpoint_state=checkpoint.get("state"),
                        result="unresolved_checkpoint",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    return 0
            if checkpoint and checkpoint.get("state") == "stale":
                # A running checkpoint from a dead process has no pending Trash
                # action: its last durable reason is safe to discard manually.
                # Never resume its cursor, since it may point at stale DOM.
                if self.pending_policy == "discard":
                    self.checkpoint.path.unlink(missing_ok=True)
                    self._event(
                        "checkpoint_discarded_manual",
                        "WARNING",
                        state=checkpoint.get("state"),
                        reason=checkpoint.get("reason"),
                        policy=self.pending_policy,
                        result="discarded_without_reconciliation",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    # An explicitly discarded stale checkpoint is not a
                    # resumable cursor. Continue with a fresh bounded scan.
                    checkpoint = None
                else:
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.STOP_SAFE
                    self._event(
                        "checkpoint_stale",
                        "WARNING",
                        state=checkpoint.get("state"),
                        reason=checkpoint.get("reason"),
                        resumable=False,
                    )
                    self._event(
                        "cleaner_terminal_state",
                        "WARNING",
                        outcome=self.last_outcome.value,
                        stop_requested=True,
                        checkpoint_state="stale",
                        result="stale_checkpoint",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    return 0
        self._event("run_started", **self._runtime_context())
        self.browser.wait_until_authenticated()
        self._event("authenticated")
        if self.pending:
            pending_file_exists = self.pending.path.exists()
            previous = self.pending.load()
            self._event(
                "pending_loaded",
                pending_exists=previous is not None,
                pending_file_exists=pending_file_exists,
                pending_kind=previous.get("kind") if previous else None,
                pending_count=previous.get("count") if previous else None,
                result="observed",
                positive_feedback=False,
                feedback_source=None,
            )
            if pending_file_exists and previous is None:
                self._event(
                    "pending_unresolved",
                    "WARNING",
                    policy=self.pending_policy,
                    result="invalid_pending_store",
                    positive_feedback=False,
                    feedback_source=None,
                )
                self.stop_requested = True
                self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                self._event(
                    "cleaner_terminal_state",
                    "WARNING",
                    outcome=self.last_outcome.value,
                    stop_requested=True,
                    pending_exists=True,
                    result="invalid_pending_store",
                    positive_feedback=False,
                    feedback_source=None,
                )
                return 0
            if previous and self.dry_run and self.pending_policy != "discard":
                self._event(
                    "pending_unresolved",
                    "WARNING",
                    target=previous.get("label"),
                    policy=self.pending_policy,
                    result="policy_blocked_dry_run",
                    positive_feedback=False,
                    feedback_source=None,
                )
                self.stop_requested = True
                self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                self._event(
                    "cleaner_terminal_state",
                    "WARNING",
                    outcome=self.last_outcome.value,
                    stop_requested=True,
                    pending_exists=True,
                    positive_feedback=False,
                    feedback_source=None,
                )
                return 0
            if self.reconcile_pending_only and not previous:
                self.last_outcome = PassOutcome.PASS_DONE
                self.stop_requested = True
                self._event(
                    "pending_reconciliation_skipped",
                    "INFO",
                    reason="no_pending_action",
                    result="nothing_to_reconcile",
                    positive_feedback=False,
                    feedback_source=None,
                )
                self._event(
                    "cleaner_terminal_state",
                    "INFO",
                    outcome=self.last_outcome.value,
                    stop_requested=True,
                    pending_exists=False,
                    positive_feedback=False,
                    feedback_source=None,
                )
                return 0
            if previous and self.reconcile_pending_only and self.pending_policy == "discard":
                self.pending.clear()
                self.last_outcome = PassOutcome.PASS_DONE
                self.stop_requested = True
                self._event(
                    "pending_discarded_manual",
                    "WARNING",
                    target=previous.get("label"),
                    policy=self.pending_policy,
                    positive_feedback=False,
                    feedback_source=None,
                    result="discarded_without_reconciliation",
                )
                self._event(
                    "cleaner_terminal_state",
                    "WARNING",
                    outcome=self.last_outcome.value,
                    stop_requested=True,
                    pending_exists=False,
                    positive_feedback=False,
                    feedback_source=None,
                )
                return 0
            if previous and self.reconcile_pending_only:
                wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                feedback_source = None
                reconciled = False
                if wait_for_absence is not None:
                    reconciled = wait_for_absence(previous["label"], timeout_ms=self.pending_timeout_ms)
                    feedback_source = getattr(self.browser, "last_feedback_source", None)
                if reconciled and feedback_source == "browser_positive_feedback":
                    self.pending.clear()
                    self.last_outcome = PassOutcome.PASS_DONE
                    self.stop_requested = True
                    self._event(
                        "pending_reconciled",
                        target=previous["label"],
                        result="reconciled",
                        positive_feedback=True,
                        feedback_source=feedback_source,
                    )
                else:
                    self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                    self.stop_requested = True
                    self._event(
                        "pending_unresolved",
                        "WARNING",
                        target=previous["label"],
                        result="reconcile_only_unresolved",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                self._event(
                    "cleaner_terminal_state",
                    "WARNING" if self.last_outcome is not PassOutcome.PASS_DONE else "INFO",
                    outcome=self.last_outcome.value,
                    stop_requested=True,
                    pending_exists=self.pending.load() is not None,
                    positive_feedback=self.last_outcome is PassOutcome.PASS_DONE,
                    feedback_source=feedback_source if self.last_outcome is PassOutcome.PASS_DONE else None,
                )
                return 0
            if previous and self.pending_policy == "discard":
                self.pending.clear()
                self._event(
                    "pending_discarded_manual",
                    "WARNING",
                    target=previous.get("label"),
                    policy=self.pending_policy,
                    positive_feedback=False,
                    feedback_source=None,
                    result="discarded_without_reconciliation",
                )
                previous = None
            if previous and self.pending_policy == "block":
                self._event(
                    "pending_reconciliation_skipped",
                    "WARNING",
                    target=previous.get("label"),
                    reason="policy_blocks_automatic_reconciliation",
                    result="not_attempted",
                    positive_feedback=False,
                    feedback_source=None,
                )
                self._event(
                    "pending_unresolved",
                    "WARNING",
                    target=previous.get("label"),
                    policy=self.pending_policy,
                    result="policy_blocked",
                    positive_feedback=False,
                    feedback_source=None,
                )
                self.stop_requested = True
                self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                self._event(
                    "cleaner_terminal_state",
                    "WARNING",
                    outcome=self.last_outcome.value,
                    stop_requested=True,
                    pending_exists=True,
                    positive_feedback=False,
                    feedback_source=None,
                )
                return 0
            if previous and self.pending_policy == "inspect":
                self._event(
                    "pending_inspected",
                    "WARNING",
                    target=previous.get("label"),
                    policy=self.pending_policy,
                    result="reconciliation_attempted",
                    positive_feedback=False,
                    feedback_source=None,
                )
                wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                target_label = previous["label"]
                reconciled = (
                    wait_for_absence(target_label, timeout_ms=self.pending_timeout_ms)
                    if wait_for_absence is not None
                    else False
                )
                feedback_source = getattr(self.browser, "last_feedback_source", None)
                if reconciled and feedback_source == "browser_positive_feedback":
                    self.pending.clear()
                    previous = None
                    self._event(
                        "pending_reconciled",
                        target=target_label,
                        result="reconciled",
                        positive_feedback=True,
                        feedback_source=feedback_source,
                    )
                else:
                    # ``inspect`` is an explicit recovery policy: after the
                    # bounded reconciliation timeout, discard only the local
                    # journal and continue scanning. This never retries the
                    # original Trash click; the uncertain browser action stays
                    # represented by the diagnostic event. Keep a local
                    # tombstone so the same target cannot become eligible for
                    # another destructive click during this run.
                    self.pending.clear()
                    self._skipped_ambiguous_targets.add(target_label)
                    self._event(
                        "pending_discarded_after_timeout",
                        "WARNING",
                        target=target_label,
                        policy=self.pending_policy,
                        result="discarded_without_reconciliation",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    previous = None
            if previous and previous.get("kind") == "media_batch":
                if self.discard_ambiguous_media_batches or self.pending_policy == "discard":
                    self.pending.clear()
                    self._event(
                        "pending_batch_discarded",
                        "WARNING",
                        target=previous["label"],
                        count=previous.get("count"),
                        policy=self.pending_policy,
                        positive_feedback=False,
                        feedback_source=None,
                        result="discarded_without_reconciliation",
                    )
                    previous = None
                else:
                    self._event(
                        "pending_batch_unresolved",
                        "WARNING",
                        target=previous["label"],
                        count=previous.get("count"),
                        result="policy_blocked",
                        positive_feedback=False,
                        feedback_source=None,
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
                    feedback_source = getattr(self.browser, "last_feedback_source", None)
                    if target_absent and feedback_source == "browser_positive_feedback":
                        self.pending.clear()
                        self._event(
                            "pending_reconciled",
                            target=previous["label"],
                            result="reconciled",
                            positive_feedback=True,
                            feedback_source=feedback_source,
                        )
                    else:
                        self._event(
                            "pending_unresolved",
                            "WARNING",
                            target=previous["label"],
                            result="absent_without_feedback",
                            positive_feedback=False,
                            feedback_source=None,
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
                    feedback_source = getattr(self.browser, "last_feedback_source", None)
                    if target_absent and feedback_source == "browser_positive_feedback":
                        self.pending.clear()
                        self._event(
                            "pending_reconciled",
                            target=previous["label"],
                            result="reconciled",
                            positive_feedback=True,
                            feedback_source=feedback_source,
                        )
                    else:
                        self._event(
                            "pending_unresolved",
                            "WARNING",
                            target=previous["label"],
                            result="present_without_feedback",
                            positive_feedback=False,
                            feedback_source=None,
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
                    feedback_source = getattr(self.browser, "last_feedback_source", None)
                    if target_absent and feedback_source == "browser_positive_feedback":
                        self.pending.clear()
                        self._event(
                            "pending_reconciled",
                            target=previous["label"],
                            result="reconciled",
                            positive_feedback=True,
                            feedback_source=feedback_source,
                        )
                    else:
                        self._event(
                            "pending_unresolved",
                            "WARNING",
                            target=previous["label"],
                            result="present_without_feedback",
                            positive_feedback=False,
                            feedback_source=None,
                        )
                        if self.pending_policy == "inspect":
                            self.pending.clear()
                            self._skipped_ambiguous_targets.add(previous["label"])
                            self._event(
                                "pending_discarded_after_timeout",
                                "WARNING",
                                target=previous["label"],
                                policy=self.pending_policy,
                                result="discarded_without_reconciliation",
                                positive_feedback=False,
                                feedback_source=None,
                            )
                        else:
                            self.stop_requested = True
                            self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                            self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                            return 0
        processed = 0
        total_photos = 0

        while self.max_batches is None or processed < self.max_batches:
            if self.day_mode:
                processed = self._run_days(processed, total_photos)
                if self.stop_requested or self.last_outcome is not PassOutcome.CONTINUE:
                    return processed
                continue

            media_ids: list[str] | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    media_ids = self._select_media_batch()
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
                            result="scan_failed",
                            positive_feedback=False,
                            feedback_source=None,
                        )
                        self._checkpoint(batch=processed, photos=total_photos, state="scan_failed", reason="max_retries")
                        raise CleanerError("Scan failed after bounded retries") from exc
                    self._recover(attempt + 1, exc)

            if media_ids is None:
                raise CleanerError("Scan returned no result")
            if not media_ids:
                self.last_outcome = PassOutcome.PASS_DONE
                self.stop_requested = True
                self._event("finished", photos=total_photos, batches=processed, outcome=self.last_outcome.value)
                self._checkpoint(batch=processed, photos=total_photos, state="completed", reason="no_photos")
                self.logger.info("No photos found; finished")
                return processed

            if self.dry_run or not self.execute:
                self._event("selection", count=len(media_ids), dry_run=True)
                self.logger.info("Dry-run: found %d visible photos", len(media_ids))
            else:
                self._event("trash_started", count=len(media_ids))
                stable_batch_ids = self._browser_batch_ids(media_ids)
                if self._batch_is_skipped(media_ids):
                    self._event(
                        "ambiguous_target_skipped",
                        "WARNING",
                        target=f"batch:{processed + 1}",
                        target_kind="media_batch",
                        media_ids=stable_batch_ids,
                        result="not_selected_again",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    continue
                if self.pending:
                    self.pending.save(
                        label=f"batch:{processed + 1}",
                        kind="media_batch",
                        scroll_top=0,
                        count=len(media_ids),
                        media_ids=stable_batch_ids,
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
                        result="ambiguous",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    self._checkpoint(
                        batch=processed,
                        photos=total_photos,
                        state="pending" if self.pending_policy == "inspect" else "ambiguous",
                        reason="trash_result_unknown",
                    )
                    if self.pending_policy == "inspect" and self.pending is not None:
                        self._skipped_ambiguous_targets.add(f"batch:{processed + 1}")
                        self._skipped_ambiguous_media_ids.update(stable_batch_ids)
                        wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                        reconciled = (
                            wait_for_absence(f"batch:{processed + 1}", timeout_ms=self.pending_timeout_ms)
                            if wait_for_absence is not None
                            else False
                        )
                        feedback_source = getattr(self.browser, "last_feedback_source", None)
                        if reconciled and feedback_source == "browser_positive_feedback":
                            self.pending.clear()
                            self._event(
                                "pending_reconciled",
                                target=f"batch:{processed + 1}",
                                result="reconciled",
                                positive_feedback=True,
                                feedback_source=feedback_source,
                            )
                        else:
                            self.pending.clear()
                            self._skipped_ambiguous_targets.add(f"batch:{processed + 1}")
                            self._event(
                                "pending_discarded_after_timeout",
                                "WARNING",
                                target=f"batch:{processed + 1}",
                                policy=self.pending_policy,
                                result="discarded_without_reconciliation",
                                positive_feedback=False,
                                feedback_source=None,
                            )
                            continue
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
                    raise DestructiveActionAmbiguous(
                        "Trash result is ambiguous; refusing destructive retry"
                    ) from exc
                feedback_source = getattr(self.browser, "last_feedback_source", None)
                if feedback_source != "browser_positive_feedback":
                    error = DestructiveActionAmbiguous(
                        "Trash completion has no positive feedback source; refusing completion claim"
                    )
                    self._event(
                        "destructive_action_ambiguous",
                        "ERROR",
                        error_type=type(error).__name__,
                        count=len(media_ids),
                        error_message=str(error),
                        result="ambiguous",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    self._checkpoint(
                        batch=processed,
                        photos=total_photos,
                        state="pending" if self.pending_policy == "inspect" else "ambiguous",
                        reason="missing_positive_feedback",
                    )
                    if self.pending_policy == "inspect" and self.pending is not None:
                        self._skipped_ambiguous_targets.add(f"batch:{processed + 1}")
                        self._skipped_ambiguous_media_ids.update(stable_batch_ids)
                        wait_for_absence = getattr(self.browser, "wait_for_target_absence", None)
                        reconciled = (
                            wait_for_absence(f"batch:{processed + 1}", timeout_ms=self.pending_timeout_ms)
                            if wait_for_absence is not None
                            else False
                        )
                        feedback_source = getattr(self.browser, "last_feedback_source", None)
                        self.pending.clear()
                        if not (reconciled and feedback_source == "browser_positive_feedback"):
                            self._skipped_ambiguous_targets.add(f"batch:{processed + 1}")
                        if reconciled and feedback_source == "browser_positive_feedback":
                            self._event(
                                "pending_reconciled",
                                target=f"batch:{processed + 1}",
                                result="reconciled",
                                positive_feedback=True,
                                feedback_source=feedback_source,
                            )
                        else:
                            self._event(
                                "pending_discarded_after_timeout",
                                "WARNING",
                                target=f"batch:{processed + 1}",
                                policy=self.pending_policy,
                                result="discarded_without_reconciliation",
                                positive_feedback=False,
                                feedback_source=None,
                            )
                        continue
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
                    self._event(
                        "cleaner_terminal_state",
                        "WARNING",
                        outcome=self.last_outcome.value,
                        stop_requested=True,
                        pending_exists=self.pending is not None and self.pending.load() is not None,
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    raise error
                if self.pending:
                    self.pending.clear()
                self._event(
                    "trash_completed",
                    count=len(media_ids),
                    positive_feedback=True,
                    result="confirmed",
                    feedback_source=feedback_source,
                )
                self.logger.info("Moved %d photos to Trash", len(media_ids))

            processed += 1
            total_photos += len(media_ids)
            self._checkpoint(batch=processed, photos=total_photos, state="running", reason="batch_processed")
            self._event("checkpoint_saved", batch=processed, photos=total_photos)
            if self.max_batches is not None and processed >= self.max_batches:
                self.stop_requested = True
                self.last_outcome = PassOutcome.BOUNDED_STOP
                self._checkpoint(batch=processed, photos=total_photos, state="bounded_stop", reason="max_batches")
                self._event("batch_limit", batches=processed, photos=total_photos)
                return processed

        self.last_outcome = PassOutcome.BOUNDED_STOP
        self._checkpoint(batch=processed, photos=total_photos, state="bounded_stop", reason="max_batches")
        self._event("batch_limit", batches=processed, photos=total_photos)
        self.logger.info("Reached batch limit: %d", processed)
        return processed

    def _run_days(self, processed: int, total_photos: int) -> int:
        idle_scrolls = 0
        scan_failures = 0
        batch_size = max(1, self.batch_size)
        while self.max_batches is None or processed < self.max_batches:
            day = None
            scan_failed = False
            for attempt in range(self.max_retries + 1):
                try:
                    try:
                        day = self.browser.select_current_day(
                            batch_size=batch_size,
                            excluded_media_ids=self._skipped_ambiguous_media_ids,
                        )
                    except TypeError as exc:
                        if "batch_size" not in str(exc) and "excluded_media_ids" not in str(exc):
                            raise
                        try:
                            day = self.browser.select_current_day(
                                excluded_media_ids=self._skipped_ambiguous_media_ids,
                            )
                        except TypeError as legacy_exc:
                            if "excluded_media_ids" not in str(legacy_exc):
                                raise
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
                if self._skipped_ambiguous_targets and not scan_failed:
                    self._event(
                        "ambiguous_target_advance_requested",
                        "WARNING",
                        target_kind="day",
                        result="advance_timeline",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    advance_timeline = getattr(self.browser, "advance_timeline", None)
                    if advance_timeline is not None and advance_timeline():
                        idle_scrolls = 0
                        continue
                if scan_failed:
                    scan_failures += 1
                if scan_failed and scan_failures >= self.max_day_scan_failures:
                    self._day_scan_recovery_rounds += 1
                    if self._day_scan_recovery_rounds <= self.max_retries:
                        self._event(
                            "day_scan_recovery_round",
                            "WARNING",
                            round=self._day_scan_recovery_rounds,
                            max_rounds=self.max_retries,
                            failures=scan_failures,
                            result="timeline_reset_and_retry",
                        )
                        reset_top = getattr(self.browser, "reset_timeline_to_top", None)
                        if reset_top is not None:
                            reset_top()
                        recover = getattr(self.browser, "recover", None)
                        if recover is not None:
                            recover()
                        scan_failures = 0
                        idle_scrolls = 0
                        continue
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.STOP_SAFE
                    self._event(
                        "day_scan_stopped",
                        "ERROR",
                        failures=scan_failures,
                        recovery_rounds=self._day_scan_recovery_rounds,
                    )
                    self._checkpoint(batch=processed, photos=total_photos, state="scan_failed", reason="max_day_scan_failures")
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
                self._checkpoint(batch=processed, photos=total_photos, state="idle", reason="timeline_idle")
                return processed
            idle_scrolls = 0
            scan_failures = 0
            selection_kind = getattr(self.browser, "last_selection_kind", "day")
            target_kind = "day" if selection_kind == "day" else "media_batch"
            stable_batch_ids = self._browser_batch_ids(()) if selection_kind == "media" else []
            if selection_kind == "media" and set(stable_batch_ids) & self._skipped_ambiguous_media_ids:
                self._event(
                    "ambiguous_target_skipped",
                    "WARNING",
                    target=day,
                    target_kind=target_kind,
                    media_ids=stable_batch_ids,
                    result="not_selected_again",
                    positive_feedback=False,
                    feedback_source=None,
                )
                continue
            if day in self._skipped_ambiguous_targets:
                # A pending journal was discarded for this exact accessible
                # target; never select or click its Trash control again. Move
                # the timeline first so a stale virtualized node cannot cause
                # a tight replay loop.
                self._event(
                    "ambiguous_target_skipped",
                    "WARNING",
                    target=day,
                    target_kind=target_kind,
                    result="not_selected_again",
                    positive_feedback=False,
                    feedback_source=None,
                )
                advance_timeline = getattr(self.browser, "advance_timeline", None)
                if advance_timeline is not None and advance_timeline():
                    idle_scrolls = 0
                    continue
                idle_scrolls += 1
                if idle_scrolls < self.max_idle_scrolls:
                    continue
                self.last_outcome = PassOutcome.STOP_SAFE
                self.stop_requested = True
                self._checkpoint(batch=processed, photos=total_photos, state="idle", reason="ambiguous_target_stalled")
                return processed
            if self.dry_run or not self.execute:
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
                        if target_kind == "media_batch":
                            self.pending.save(
                                label=day,
                                kind="media_batch",
                                scroll_top=0,
                                count=len(stable_batch_ids),
                                media_ids=list(stable_batch_ids),
                            )
                        else:
                            self.pending.save(label=day, kind=target_kind, scroll_top=0)
                    completed = self.browser.delete_selected_day()
                    if completed is False:
                        self._event(
                            "day_trash_pending",
                            "WARNING",
                            day=day,
                            result="pending_reconciliation",
                            positive_feedback=False,
                            feedback_source=None,
                        )
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
                            feedback_source = getattr(self.browser, "last_feedback_source", None)
                            if feedback_source != "browser_positive_feedback":
                                error = DestructiveActionAmbiguous(
                                    "Trash reconciliation has no positive feedback source; refusing completion claim"
                                )
                                self._event(
                                    "destructive_action_ambiguous",
                                    "ERROR",
                                    day=day,
                                    error_type=type(error).__name__,
                                    error_message=str(error),
                                    result="ambiguous",
                                    positive_feedback=False,
                                    feedback_source=None,
                                )
                                self._checkpoint(batch=processed, photos=total_photos, state="ambiguous", reason="missing_reconciliation_feedback")
                                self.stop_requested = True
                                self.last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
                                raise error
                            self.pending.clear()
                            self._event(
                                "day_trash_completed",
                                day=day,
                                reconciled=True,
                                positive_feedback=True,
                                result="confirmed",
                                feedback_source=feedback_source,
                                reconciliation="feedback_confirmed",
                            )
                            self.logger.info("Moved day %s to Trash", day)
                            reset_top = getattr(self.browser, "reset_timeline_to_top", None)
                            if reset_top is not None and self.reset_timeline_after_action:
                                reset_top()
                            processed += 1
                            total_photos += len(stable_batch_ids) if target_kind == "media_batch" else 1
                            self._checkpoint(batch=processed, photos=total_photos, state="running", reason="day_processed")
                            self._event("day_checkpoint_saved", day=day, days=processed)
                            if self.max_batches is not None and processed >= self.max_batches:
                                self.stop_requested = True
                                self.last_outcome = PassOutcome.BOUNDED_STOP
                                self._checkpoint(batch=processed, photos=total_photos, state="bounded_stop", reason="max_batches")
                                self._event("batch_limit", batches=processed, photos=total_photos)
                                return processed
                        else:
                            if self.pending_policy != "inspect":
                                self._checkpoint(batch=processed, photos=total_photos, state="pending", reason="reconciliation_unresolved")
                            self._event(
                                "day_trash_unresolved",
                                "WARNING",
                                day=day,
                                result="pending_unresolved",
                                positive_feedback=False,
                                feedback_source=None,
                            )
                            # Pending timeout policy applies after the bounded
                            # reconciliation wait. Discard only local journal;
                            # never repeat original Trash click.
                            if self.pending_policy == "inspect" and self.pending is not None:
                                self.pending.clear()
                                self._skipped_ambiguous_targets.add(day)
                                self._event(
                                    "pending_discarded_after_timeout",
                                    "WARNING",
                                    target=day,
                                    policy=self.pending_policy,
                                    result="discarded_without_reconciliation",
                                    positive_feedback=False,
                                    feedback_source=None,
                                )
                                continue
                            self.stop_requested = True
                            self.last_outcome = PassOutcome.PENDING_UNRESOLVED
                            self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                            return processed
                        continue
                    if self.pending:
                        self.pending.clear()
                except DestructiveActionAmbiguous:
                    raise
                except Exception as exc:
                    # A click may already have reached Google Photos. Keep its
                    # journal entry and stop this run without a second click.
                    self._event(
                        "destructive_action_pending",
                        "WARNING",
                        day=day,
                        error_type=type(exc).__name__,
                        result="pending_reconciliation",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    self._checkpoint(batch=processed, photos=total_photos, state="pending", reason="trash_result_pending")
                    self.logger.warning(
                        "Trash result pending for %s; will reconcile before another click", day
                    )
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
                    self._event("cleaner_terminal_state", "WARNING", outcome=self.last_outcome.value, stop_requested=True, pending_exists=True)
                    return processed
                feedback_source = getattr(self.browser, "last_feedback_source", None)
                if feedback_source != "browser_positive_feedback":
                    error = DestructiveActionAmbiguous(
                        "Trash completion has no positive feedback source; refusing completion claim"
                    )
                    self._event(
                        "destructive_action_ambiguous",
                        "ERROR",
                        day=day,
                        error_type=type(error).__name__,
                        error_message=str(error),
                        result="ambiguous",
                        positive_feedback=False,
                        feedback_source=None,
                    )
                    self._checkpoint(batch=processed, photos=total_photos, state="ambiguous", reason="missing_positive_feedback")
                    if self.pending is not None and self.pending.load() is None:
                        if target_kind == "media_batch":
                            self.pending.save(
                                label=day,
                                kind="media_batch",
                                scroll_top=0,
                                count=len(stable_batch_ids),
                                media_ids=list(stable_batch_ids),
                            )
                        else:
                            self.pending.save(label=day, kind=target_kind, scroll_top=0)
                    self.stop_requested = True
                    self.last_outcome = PassOutcome.DESTRUCTIVE_AMBIGUOUS
                    raise error
                self._event(
                    "day_trash_completed",
                    day=day,
                    positive_feedback=True,
                    result="confirmed",
                    feedback_source=feedback_source,
                )
                self.logger.info("Moved day %s to Trash", day)
                reset_top = getattr(self.browser, "reset_timeline_to_top", None)
                if reset_top is not None and self.reset_timeline_after_action:
                    reset_top()
            processed += 1
            total_photos += len(stable_batch_ids) if target_kind == "media_batch" else 1
            self._checkpoint(batch=processed, photos=total_photos, state="running", reason="day_processed")
            self._event("day_checkpoint_saved", day=day, days=processed)
            if self.max_batches is not None and processed >= self.max_batches:
                self.stop_requested = True
                self.last_outcome = PassOutcome.BOUNDED_STOP
                self._checkpoint(batch=processed, photos=total_photos, state="bounded_stop", reason="max_batches")
                self._event("batch_limit", batches=processed, photos=total_photos)
                return processed
        self.last_outcome = PassOutcome.PASS_DONE
        self._checkpoint(batch=processed, photos=total_photos, state="completed", reason="no_more_days")
        return processed
