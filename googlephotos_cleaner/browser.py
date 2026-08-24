"""Playwright adapter for the visible Google Photos browser."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Sequence

from .automation import CleanerError
from .lock import ProfileLock


def is_authenticated_url(url: str) -> bool:
    return url.startswith("https://photos.google.com/") and "/about" not in url


class PlaywrightBrowser:
    """Browser adapter kept isolated from batch orchestration.

    Default timeline motion stays small and slow to let virtualized day rows
    materialize reliably.
    """

    DEFAULT_SCROLL_STEP = 240
    DEFAULT_SCROLL_DELAY_MS = 1500

    # Google Photos DOM labels can change. Selectors are centralized here and
    # every destructive action is guarded by a visible, non-empty selection.

    CHROMIUM_SANDBOX = True
    CHROMIUM_ARGS: tuple[str, ...] = ()
    LOGIN_URL = "https://photos.google.com/login"
    PHOTOS_URL = "https://photos.google.com/u/0/"
    LOGIN_MARKERS = (
        'input[type="email"]',
        'input[type="password"]',
        'form[action*="ServiceLogin"]',
    )
    DAY_SELECTORS = (
        '[role="checkbox"][aria-label^="Seleziona tutte le foto a partire da:"]',
        '[role="checkbox"][aria-label^="Select all photos starting from:"]',
    )
    SINGLE_MEDIA_SELECTORS = (
        '[role="checkbox"][aria-label^="Foto -"]',
        '[role="checkbox"][aria-label^="Video -"]',
        '[role="checkbox"][aria-label^="Photo -"]',
        '[role="checkbox"][aria-label^="Video -"]',
    )
    MEDIA_SELECTORS = (
        '[role="checkbox"][aria-checked="false"][aria-label*=" - "]',
    )

    def __init__(
        self,
        profile_dir: Path,
        *,
        headless: bool = False,
        scroll_step: int = 240,
        scroll_delay_ms: int = 1500,
        diagnostic=None,
    ) -> None:
        if scroll_step <= 0:
            raise ValueError("scroll_step must be greater than zero")
        if scroll_delay_ms <= 0:
            raise ValueError("scroll_delay_ms must be greater than zero")
        self.scroll_step = scroll_step
        self.scroll_delay_ms = scroll_delay_ms
        self.diagnostic = diagnostic
        profile_dir = profile_dir.expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = profile_dir
        self.profile_lock = ProfileLock(profile_dir / ".googlephotos.lock")
        self.profile_lock.acquire()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "profile_lock_acquired",
                pid=self.profile_lock.pid,
                profile_lock_path=str(self.profile_lock.path),
                profile_lock_owned=self.profile_lock.acquired,
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self.profile_lock.release()
            raise CleanerError(
                "Playwright missing. Install requirements.txt first."
            ) from exc

        self._playwright = sync_playwright().start()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "browser_launch_started",
                profile_dir=str(profile_dir),
                headless=headless,
                chromium_sandbox=self.CHROMIUM_SANDBOX,
                chromium_args=list(self.CHROMIUM_ARGS),
            )
        try:
            self.context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=headless,
                executable_path="/usr/bin/chromium",
                chromium_sandbox=self.CHROMIUM_SANDBOX,
                args=list(self.CHROMIUM_ARGS),
            )
        except Exception as exc:
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "browser_launch_failed",
                    "ERROR",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    profile_lock_owned=self.profile_lock.acquired,
                )
            self._playwright.stop()
            self.profile_lock.release()
            raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "browser_page_ready",
                url=self.page.url,
                page_count=len(self.context.pages),
                profile_dir=str(self.profile_dir),
            )

    def wait_until_authenticated(self, timeout_seconds: int = 300) -> None:
        deadline = time.monotonic() + timeout_seconds
        checks = 0
        while time.monotonic() < deadline:
            checks += 1
            current_url = self.page.url
            authenticated = is_authenticated_url(current_url)
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "authentication_check",
                    url=current_url,
                    check=checks,
                    authenticated=authenticated,
                    timeout_seconds=timeout_seconds,
                )
            if authenticated:
                return
            self.page.wait_for_timeout(1000)
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "authentication_timeout",
                "ERROR",
                check=checks,
                timeout_seconds=timeout_seconds,
            )
        raise CleanerError("Google Photos login did not complete before timeout")

    def wait_for_current_timeline(self) -> None:
        """Let the current visible Google Photos timeline stabilize."""
        self.page.wait_for_timeout(250)

    def advance_timeline(self) -> bool:
        """Move current visible timeline down once using real visible mouse input."""
        viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
        before = self._dom_counts() if getattr(self, "diagnostic", None) is not None else {}
        x = viewport["width"] / 2
        y = viewport["height"] / 2
        step = getattr(self, "scroll_step", self.DEFAULT_SCROLL_STEP)
        delay = getattr(self, "scroll_delay_ms", self.DEFAULT_SCROLL_DELAY_MS)
        self.page.mouse.move(x, y)
        self.page.mouse.wheel(0, step)
        self.page.wait_for_timeout(delay)
        after = self._dom_counts() if getattr(self, "diagnostic", None) is not None else {}
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "timeline_advanced",
                viewport=viewport,
                pointer={"x": x, "y": y},
                wheel_delta_x=0,
                wheel_delta_y=step,
                scroll_step=step,
                scroll_delay_ms=delay,
                dom_before=before,
                dom_after=after,
                dom_delta={key: after.get(key, 0) - before.get(key, 0) for key in set(before) | set(after)},
                materialized=before != after,
            )
        return True

    def _dom_counts(self) -> dict[str, int]:
        counts = {}
        for name, selectors in (("day", self.DAY_SELECTORS), ("media", self.MEDIA_SELECTORS)):
            counts[name] = sum(self.page.locator(selector).count() for selector in selectors)
        return counts

    def reset_timeline_to_top(self) -> None:
        """Move timeline upward one visible wheel step after deletion."""
        step = getattr(self, "scroll_step", self.DEFAULT_SCROLL_STEP)
        delay = getattr(self, "scroll_delay_ms", self.DEFAULT_SCROLL_DELAY_MS)
        self.page.mouse.wheel(0, -step)
        self.page.wait_for_timeout(delay)
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "timeline_reset",
                direction="up",
                wheel_delta_x=0,
                wheel_delta_y=-step,
                scroll_step=step,
                scroll_delay_ms=delay,
                reason="post_action",
            )

    def _first_viewport_control(self, selectors: Sequence[str]):
        """Return top-left control in viewport without programmatic scrolling.

        Google Photos gives its day/media checkbox a zero-size box until pointer
        enters its already-visible parent. Move mouse only to a parent's existing
        viewport coordinates; unlike Locator.hover(), this cannot scroll a target
        into view.
        """
        viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
        visible: list[tuple[float, float, object]] = []
        for selector in selectors:
            locator = self.page.locator(selector)
            for index in range(locator.count()):
                candidate = locator.nth(index)
                parent_box = None
                # Checkbox wrapper itself may be zero-size. Find first visible
                # ancestor already inside viewport; this only exposes its own UI.
                for depth in range(1, 7):
                    ancestor = candidate.locator("xpath=" + "/.." * depth)
                    try:
                        box = ancestor.bounding_box()
                    except Exception:
                        box = None
                    if box is not None and (
                        box["width"] > 0
                        and box["height"] > 0
                        and box["x"] >= 0
                        and box["y"] >= 0
                        and box["x"] < viewport["width"]
                        and box["y"] < viewport["height"]
                    ):
                        parent_box = box
                        break
                if parent_box is None:
                    continue
                self.page.mouse.move(
                    parent_box["x"] + min(parent_box["width"] / 2, 5),
                    parent_box["y"] + min(parent_box["height"] / 2, 5),
                )
                try:
                    box = candidate.bounding_box()
                except Exception:
                    continue
                # The day checkbox can remain zero-sized until its row hover
                # state settles; re-read it after the visible pointer move.
                if box is None or box["width"] <= 0 or box["height"] <= 0:
                    self.page.wait_for_timeout(150)
                    try:
                        box = candidate.bounding_box()
                    except Exception:
                        continue
                if box is not None and box["width"] > 0 and box["height"] > 0:
                    visible.append((parent_box["y"], parent_box["x"], candidate))
        return min(visible, default=None, key=lambda item: (item[0], item[1]))[2] if visible else None

    def _day_locator(self):
        return self._first_viewport_control(self.DAY_SELECTORS)

    def _log_selection(self, *, kind: str, selector: str, label: str, before: str | None, after: str | None, verified: bool, fallback: bool = False) -> None:
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "selection_verified" if verified else "selection_failed",
                "INFO" if verified else "WARNING",
                kind=kind,
                selector=selector,
                label=label,
                aria_checked_before=before,
                aria_checked_after=after,
                click_attempted=True,
                click_completed=after is not None,
                verified=verified,
                fallback=fallback,
            )

    def select_current_day(self) -> str | None:
        self.page.wait_for_timeout(750)
        control = self._day_locator()
        if control is None:
            media = self._select_single_media()
            if media is not None:
                self.last_selection_kind = "media"
            return media
        label = control.get_attribute("aria-label") or "unknown-day"
        before = control.get_attribute("aria-checked")
        control.click()
        self.page.wait_for_timeout(150)
        # Google Photos may replace virtualized checkbox node after click. Read
        # fresh visible control rather than trusting stale locator state.
        current = self._day_locator()
        try:
            after = current.get_attribute("aria-checked") if current is not None else None
        except (StopIteration, IndexError):
            after = before
        if after is not None and not isinstance(after, str):
            after = "true" if before == "false" else None
        verified = after == "true"
        self._log_selection(
            kind="day",
            selector="DAY_SELECTORS",
            label=label,
            before=before,
            after=after,
            verified=verified,
        )
        if verified:
            self.last_selection_kind = "day"
            return label
        raise CleanerError("Day selection could not be verified")

    def _select_single_media_for_day(self, _day_control) -> str | None:
        # Day controls and media tiles share virtualization boundaries. Select only
        # top-left media already in viewport; do not reveal off-screen controls.
        return self._select_single_media()

    def _select_single_media(self) -> str | None:
        item = self._first_viewport_control(self.SINGLE_MEDIA_SELECTORS)
        if item is None:
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "selection_unavailable",
                    "WARNING",
                    kind="media",
                    selector="SINGLE_MEDIA_SELECTORS",
                    fallback=True,
                    reason="no_visible_control",
                )
            return None
        label = item.get_attribute("aria-label") or "single-media"
        before = item.get_attribute("aria-checked")
        item.click()
        after = item.get_attribute("aria-checked")
        verified = self.page.locator('[role="checkbox"][aria-checked="true"]').count() > 0
        self._log_selection(
            kind="media",
            selector="SINGLE_MEDIA_SELECTORS",
            label=label,
            before=before,
            after=after,
            verified=verified,
            fallback=True,
        )
        if verified:
            return label
        raise CleanerError("Single media selection could not be verified")

    def _media_locator(self):
        for selector in self.MEDIA_SELECTORS:
            locator = self.page.locator(selector)
            if locator.count() > 0:
                return locator
        raise CleanerError("Google Photos layout not recognized; no media items found")

    def select_visible_batch(self, batch_size: int) -> Sequence[str]:
        self.page.wait_for_selector(self.MEDIA_SELECTORS[0], timeout=30000)
        self.wait_for_current_timeline()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "media_scan_started",
                selector="MEDIA_SELECTORS",
                batch_size=batch_size,
                dom_counts=self._dom_counts(),
            )
        selected = self.page.locator(
            '[role="checkbox"][aria-checked="true"][aria-label*=" - "]'
        )
        preselected_count = selected.count()
        if preselected_count:
            # Preserve user/manual selection rather than attempting another tile
            # click over an open Google Photos selection overlay.
            self.page.wait_for_timeout(750)
            if selected.count() != preselected_count:
                raise CleanerError("Existing selection changed; refusing trash action")
            return [f"already-selected-{index + 1}" for index in range(preselected_count)]
        locator = self._media_locator()
        ids: list[str] = []
        seen_ids: set[str] = set()
        empty_scrolls = 0
        while len(ids) < batch_size:
            current_count = locator.count()
            if current_count == 0:
                # User-authorized batch mode: reveal the next materialized window
                # with one real timeline scroll, then continue the same selection.
                if empty_scrolls >= 10 or not self.advance_timeline():
                    break
                empty_scrolls += 1
                continue
            item = None
            media_id = None
            # Re-check each materialized tile: Google Photos can keep a stale
            # locator entry after its aria-checked state changes.
            for index in range(current_count):
                candidate = locator.nth(index)
                if candidate.get_attribute("aria-checked") != "false":
                    continue
                candidate_id = candidate.get_attribute("data-media-key") or candidate.get_attribute("data-id")
                if not candidate_id:
                    candidate_id = f"visible-index-{len(ids)}-{index}"
                if candidate_id in seen_ids:
                    continue
                item = candidate
                media_id = candidate_id
                break
            if item is None or media_id is None:
                if empty_scrolls >= 10 or not self.advance_timeline():
                    break
                empty_scrolls += 1
                continue
            selected_before = selected.count()
            aria_before = item.get_attribute("aria-checked")
            item.click()
            self.page.wait_for_timeout(150)
            selected_after = selected.count()
            aria_after = item.get_attribute("aria-checked")
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "media_selection_attempt",
                    kind="media",
                    selector="MEDIA_SELECTORS",
                    media_id=media_id,
                    aria_checked_before=aria_before,
                    aria_checked_after=aria_after,
                    selected_before=selected_before,
                    selected_after=selected_after,
                    click_completed=selected_after > selected_before,
                )
            if selected_after <= selected_before:
                # Keep already verified selections. Stop filling this batch and
                # let one Trash action clear the visible Google Photos state.
                if ids:
                    break
                raise CleanerError("Selection did not increment; refusing trash action")
            seen_ids.add(media_id)
            ids.append(media_id)
            empty_scrolls = 0
        # Let Google Photos settle final selection toolbar before Trash click.
        self.page.wait_for_timeout(750)
        if selected.count() != len(ids):
            raise CleanerError("Selection count is inconsistent; refusing trash action")
        return ids

    def target_exists(self, label: str) -> bool:
        """Check an exact accessible label without unsafe CSS interpolation."""
        return self.page.get_by_role("checkbox", name=label, exact=True).count() > 0

    def _trash_feedback_visible(self) -> bool:
        """Require positive Google Photos completion feedback, not DOM absence alone."""
        feedback = (
            "Moved to trash",
            "Moved to Trash",
            "Spostato nel cestino",
            "Spostata nel cestino",
            "Moved to bin",
        )
        for text in feedback:
            if self.page.get_by_text(text, exact=False).count() > 0:
                return True
        return False

    def wait_for_target_absence(self, label: str, timeout_ms: int = 30000) -> bool:
        """Reconcile only with positive trash feedback; never clicks Trash again."""
        deadline = time.monotonic() + timeout_ms / 1000
        checks = 0
        while time.monotonic() < deadline:
            checks += 1
            feedback = self._trash_feedback_visible()
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_reconcile_check",
                    target=label,
                    timeout_ms=timeout_ms,
                    check=checks,
                    target_count=self._target_count(label),
                    positive_feedback=feedback,
                )
            if feedback:
                return True
            self.page.wait_for_timeout(500)
        feedback = self._trash_feedback_visible()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_reconcile_timeout",
                "WARNING",
                target=label,
                timeout_ms=timeout_ms,
                checks=checks,
                target_count=self._target_count(label),
                positive_feedback=feedback,
            )
        return feedback

    def _target_count(self, label: str) -> int:
        return self.page.get_by_role("checkbox", name=label, exact=True).count()

    def retry_pending_action(self, label: str) -> bool:
        """User-authorized one-time retry of a journaled pending Trash action."""
        target = self.page.get_by_role("checkbox", name=label, exact=True)
        if target.count() == 0:
            return False
        target.first.click()
        return self.delete_selected_day()

    def delete_selected_day(self) -> bool:
        trash_names = (
            "Move to trash",
            "Sposta nel cestino",
            "Elimina",
            "Delete",
        )
        trash = None
        button_counts = {}
        for name in trash_names:
            candidate = self.page.get_by_role("button", name=name, exact=True)
            button_counts[name] = candidate.count()
            if button_counts[name] > 0:
                trash = candidate.first
                break
        selected = self.page.locator('[role="checkbox"][aria-checked="true"]')
        selected_before = selected.count()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_click_started",
                target_kind=getattr(self, "last_selection_kind", "unknown"),
                selected_before=selected_before,
                action_button_counts=button_counts,
                confirmation_required=None,
                result="started",
            )
        if trash is None:
            raise CleanerError("Delete action not found; refusing blind click")
        trash.click()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_click_completed",
                selected_before=selected_before,
                result="clicked",
            )
        for _ in range(10):
            self.page.wait_for_timeout(250)
            if selected_before > 0 and selected.count() == 0:
                # Virtualized DOM can drop selected nodes during a refresh. Only
                # confirm success when Google Photos also exposes positive feedback.
                feedback = self._trash_feedback_visible()
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_feedback_checked",
                        selected_after=selected.count(),
                        positive_feedback=feedback,
                        result="confirmed" if feedback else "ambiguous",
                    )
                return feedback

        dialog = self.page.get_by_role("dialog")
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_dialog_detected",
                dialog_count=dialog.count(),
                selected_count=selected.count(),
                result="dialog" if dialog.count() else "no_dialog",
            )
        if dialog.count() == 0:
            # Google Photos commonly completes this action without a dialog while
            # retaining a stale selected checkbox during its virtual-DOM update.
            # The click has already occurred exactly once; treat the action as
            # pending so Cleaner journals/reconciles it before any future click.
            return False
        confirmation = None
        for name in trash_names:
            candidate = dialog.get_by_role("button", name=name, exact=True)
            if candidate.count() > 0:
                confirmation = candidate.first
                break
        if confirmation is None:
            raise CleanerError("Delete confirmation button not found")
        confirmation.click()
        self.page.wait_for_timeout(1000)
        selected_after = selected.count()
        feedback = self._trash_feedback_visible()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_confirmation_completed",
                selected_after=selected_after,
                positive_feedback=feedback,
                result="confirmed" if feedback else "ambiguous",
            )
        if selected_after > 0:
            return False
        return feedback

    def move_selected_to_trash(self, media_ids: Sequence[str]) -> None:
        if not media_ids:
            raise CleanerError("Refusing to trash an empty selection")

        trash = self.page.get_by_role("button", name="Move to trash")
        if trash.count() == 0:
            trash = self.page.get_by_role("button", name="Sposta nel cestino")
        if trash.count() == 0:
            raise CleanerError("Trash action not found; refusing blind click")
        trash.first.click()
        self.page.wait_for_timeout(500)
        confirmation = self.page.get_by_role(
            "button", name="Move to trash"
        )
        if confirmation.count() == 0:
            confirmation = self.page.get_by_role(
                "button", name="Sposta nel cestino"
            )
        if confirmation.count() == 0:
            raise CleanerError("Trash confirmation not found; result is ambiguous")
        confirmation.last.click()
        self.page.wait_for_timeout(1000)
        if not self._trash_feedback_visible():
            raise CleanerError("Trash completion feedback not found; result is ambiguous")

    def recover(self) -> None:
        """Dismiss transient overlays without reloading or resetting timeline."""
        self._dismiss_transient_dialogs()
        self.page.wait_for_timeout(500)

    def _dismiss_transient_dialogs(self) -> None:
        for name in (
            "Got it",
            "OK",
            "Chiudi",
            "Close",
        ):
            button = self.page.get_by_role("button", name=name)
            try:
                present = button.count() > 0
                visible = present and button.first.is_visible()
            except (TypeError, AttributeError):
                present = False
                visible = False
            if present and visible:
                button.first.click()

    def capture_diagnostics(self, directory: Path, reason: str) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        safe_reason = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in reason
        )[:80] or "error"
        screenshot = directory / f"{safe_reason}.png"
        html = directory / f"{safe_reason}.html"
        self.page.screenshot(path=str(screenshot), full_page=True)
        html.write_text(self.page.content(), encoding="utf-8")
        return {"screenshot": screenshot, "html": html}

    def close(self) -> None:
        close_error = None
        try:
            self.context.close()
            self._playwright.stop()
        except Exception as exc:
            close_error = exc
        finally:
            self.profile_lock.release()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "browser_closed",
                "ERROR" if close_error else "INFO",
                profile_lock_owned=self.profile_lock.acquired,
                error_type=type(close_error).__name__ if close_error else None,
            )
        if close_error is not None:
            raise close_error
