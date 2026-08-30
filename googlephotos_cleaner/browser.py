"""Playwright adapter for the visible Google Photos browser."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Sequence

from .automation import CleanerError
from .lock import ProfileLock


def is_authenticated_url(url: str) -> bool:
    if not url.startswith("https://photos.google.com/"):
        return False
    lowered = url.lower()
    return "/about" not in lowered and "/login" not in lowered and "signin" not in lowered


class PlaywrightBrowser:
    """Browser adapter kept isolated from batch orchestration.

    Default timeline motion stays small and slow to let virtualized day rows
    materialize reliably.
    """

    DEFAULT_SCROLL_STEP = 240
    DEFAULT_SCROLL_DELAY_MS = 1500
    TARGET_CLOSED_ERROR_NAMES = frozenset(
        {"TargetClosedError", "BrowserClosedError", "ContextClosedError"}
    )
    TARGET_CLOSED_ERROR_MARKERS = (
        "target page, context or browser has been closed",
        "target closed",
        "browser has been closed",
        "context has been closed",
    )
    DEFAULT_POINTER_PAUSE_MS = 40
    DEFAULT_POINTER_MAX_STEPS = 4
    DEFAULT_INACTIVITY_TIMEOUT_SECONDS = 300

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
    # Selector intentionally excludes the Trash route; only library media is
    # eligible for this cleaner. Both photo and video labels are accepted via
    # the shared accessible-label separator used by Photos.
    TRASH_ROUTE_MARKERS = ("/trash", "/bin")
    TRASH_FEEDBACK_LIVE_REGION_SELECTORS = (
        ("status", '[role="status"]'),
        ("alert", '[role="alert"]'),
        ("aria_live", '[aria-live]'),
    )
    TRASH_FEEDBACK_POPUP_PATTERN = re.compile(
        r"(?:\b(?:moved|spostat[oaie])\s+"
        r"(\d+)\s+(?:photos?|foto)\b.*"
        r"\b(?:trash|bin|cestin[oi])\b|"
        r"\b(\d+)\s+spostat[oaie]\b.*"
        r"\b(?:trash|bin|cestin[oi])\b)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        profile_dir: Path,
        *,
        headless: bool = False,
        scroll_step: int = 240,
        scroll_delay_ms: int = 1500,
        pointer_pause_ms: int = DEFAULT_POINTER_PAUSE_MS,
        pointer_max_steps: int = DEFAULT_POINTER_MAX_STEPS,
        inactivity_timeout_seconds: int = DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
        diagnostic=None,
        cdp_url: str | None = None,
    ) -> None:
        if scroll_step <= 0:
            raise ValueError("scroll_step must be greater than zero")
        if scroll_delay_ms <= 0:
            raise ValueError("scroll_delay_ms must be greater than zero")
        self._validate_pointer_options(
            pointer_pause_ms=pointer_pause_ms,
            pointer_max_steps=pointer_max_steps,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
        )
        self.scroll_step = scroll_step
        self.scroll_delay_ms = scroll_delay_ms
        self.pointer_pause_ms = pointer_pause_ms
        self.pointer_max_steps = pointer_max_steps
        self.inactivity_timeout_seconds = inactivity_timeout_seconds
        self.batch_size = 50
        self.max_materialized_batch = 500
        self.last_batch_ids: list[str] = []
        self.diagnostic = diagnostic
        profile_dir = profile_dir.expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = profile_dir
        self.cdp_url = cdp_url
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

        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None
        try:
            self._playwright = sync_playwright().start()
            if self.cdp_url:
                self.browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
                self.context = self.browser.contexts[0] if self.browser.contexts else None
                self.page = self.context.pages[0] if self.context and self.context.pages else None
                if self.page is None:
                    raise CleanerError("CDP browser has no usable page")
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "browser_cdp_connected",
                        cdp_url=self.cdp_url,
                        page_count=len(self.context.pages),
                        url=self.page.url,
                    )
                return
        except Exception:
            self.profile_lock.release()
            raise
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
                    recovery="playwright_stopped_lock_released",
                )
            try:
                self._playwright.stop()
            finally:
                self._playwright = None
                self.profile_lock.release()
            raise
        try:
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        except Exception as exc:
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "browser_page_init_failed",
                    "ERROR",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    recovery="context_stopped_lock_released",
                )
            try:
                if self.context is not None:
                    self.context.close()
            finally:
                try:
                    if self._playwright is not None:
                        self._playwright.stop()
                finally:
                    self.context = None
                    self._playwright = None
                    self.page = None
                    self.profile_lock.release()
            raise
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "browser_page_ready",
                url=self.page.url,
                page_count=len(self.context.pages),
                profile_dir=str(self.profile_dir),
            )

    def _is_trash_route(self) -> bool:
        url = getattr(self.page, "url", "")
        if not isinstance(url, str):
            return False
        lowered = url.lower()
        return any(marker in lowered for marker in self.TRASH_ROUTE_MARKERS)

    @staticmethod
    def _validate_pointer_options(
        *,
        pointer_pause_ms: int,
        pointer_max_steps: int,
        inactivity_timeout_seconds: int = DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
    ) -> None:
        if pointer_pause_ms <= 0:
            raise ValueError("pointer_pause_ms must be greater than zero")
        if pointer_max_steps <= 0:
            raise ValueError("pointer_max_steps must be greater than zero")
        if inactivity_timeout_seconds <= 0:
            raise ValueError("inactivity_timeout_seconds must be greater than zero")

    def _inactivity_timeout_ms(self) -> int:
        timeout_seconds = getattr(
            self, "inactivity_timeout_seconds", self.DEFAULT_INACTIVITY_TIMEOUT_SECONDS
        )
        return max(1, round(timeout_seconds * 1000))

    def _wait_for_timeout(self, milliseconds: int) -> None:
        """Sleep without allowing one scan wait to exceed the inactivity bound."""
        self.page.wait_for_timeout(min(max(0, milliseconds), self._inactivity_timeout_ms()))

    def _wait_for_selector(self, selector: str, *, timeout_ms: int | None = None):
        """Wait for a selector with a hard inactivity ceiling."""
        timeout = self._inactivity_timeout_ms() if timeout_ms is None else min(
            max(1, timeout_ms), self._inactivity_timeout_ms()
        )
        return self.page.wait_for_selector(selector, timeout=timeout)

    @classmethod
    def _is_target_closed_error(cls, error: Exception) -> bool:
        if type(error).__name__ in cls.TARGET_CLOSED_ERROR_NAMES:
            return True
        message = str(error).lower()
        return any(marker in message for marker in cls.TARGET_CLOSED_ERROR_MARKERS)

    def _rebind_cdp_page_after_target_close(self, error: Exception) -> bool:
        """Rebind observation page after CDP target replacement; never retry action."""
        if not self.cdp_url or not self._is_target_closed_error(error):
            return False
        context = getattr(self, "context", None)
        old_page = getattr(self, "page", None)
        if context is None:
            return False
        # CDP may keep same tab alive while Playwright's wrapper target closes.
        # Rebind same authenticated page before looking for a replacement.
        try:
            if old_page is not None and not old_page.is_closed() and is_authenticated_url(old_page.url):
                self.page = old_page
                return True
        except Exception:
            pass
        deadline = time.monotonic() + min(2.0, self._inactivity_timeout_ms() / 1000)
        while time.monotonic() < deadline:
            try:
                pages = list(context.pages)
            except Exception:
                pages = []
            for page in pages:
                if page is old_page:
                    continue
                try:
                    if page.is_closed() or not is_authenticated_url(page.url):
                        continue
                except Exception:
                    continue
                self.page = page
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "browser_page_rebound",
                        reason="target_closed_during_observation",
                        page_count=len(pages),
                        url=page.url,
                    )
                return True
            time.sleep(0.1)
        return False

    def _wait_for_page_timeout(self, milliseconds: int) -> None:
        """Wait once; rebind only after target closure, never repeat click."""
        try:
            self._wait_for_timeout(milliseconds)
        except Exception as error:
            if self._rebind_cdp_page_after_target_close(error):
                return
            raise

    def wait_until_authenticated(self, timeout_seconds: int | None = None) -> None:
        if self._is_trash_route():
            raise CleanerError("Refusing to operate on the Google Photos Trash route")
        if timeout_seconds is None:
            timeout_seconds = getattr(
                self, "inactivity_timeout_seconds", self.DEFAULT_INACTIVITY_TIMEOUT_SECONDS
            )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
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
            remaining_ms = max(1, round((deadline - time.monotonic()) * 1000))
            self._wait_for_timeout(min(1000, remaining_ms))
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "authentication_timeout",
                "ERROR",
                check=checks,
                timeout_seconds=timeout_seconds,
            )
        raise CleanerError("Google Photos login did not complete before timeout")

    def wait_for_current_timeline(self) -> None:
        """Let current visible Google Photos timeline stabilize."""
        self._dismiss_transient_dialogs()
        self._move_pointer_path(self._viewport_center_path())
        self._wait_for_timeout(250)

    def _dismiss_transient_dialogs(self) -> None:
        """Close known non-destructive overlays before normal timeline input."""
        get_by_role = getattr(self.page, "get_by_role", None)
        if get_by_role is None:
            return
        for name in (
            "Got it",
            "OK",
            "Chiudi",
            "Close",
        ):
            button = get_by_role("button", name=name)
            try:
                if button.count() <= 0 or not button.first.is_visible():
                    continue
                self._click_control(button.first)
            except (TypeError, AttributeError):
                continue

    def _dismiss_known_overlays(self) -> None:
        """Bounded overlay cleanup used before retrying a scan interaction."""
        self._dismiss_transient_dialogs()
        self._wait_for_timeout(150)

    def refresh_after_trash(self) -> None:
        """Reload only after caller has positive proof of a Trash action."""
        reload_page = getattr(self.page, "reload", None)
        if not callable(reload_page):
            raise CleanerError("Google Photos page cannot be refreshed safely")
        timeout_ms = min(2000, self._inactivity_timeout_ms())
        try:
            try:
                reload_page(timeout=timeout_ms, wait_until="domcontentloaded")
            except TypeError as exc:
                # Keep compatibility with minimal browser adapters exposing only
                # reload(), but never retry other reload failures.
                if "timeout" not in str(exc) and "wait_until" not in str(exc):
                    raise
                reload_page()
        except Exception as exc:
            if self._is_target_closed_error(exc):
                if self._rebind_cdp_page_after_target_close(exc):
                    raise CleanerError("Google Photos page closed during post-trash refresh") from exc
            raise CleanerError("Google Photos refresh failed after confirmed Trash action") from exc
        self.wait_until_authenticated()
        self.wait_for_current_timeline()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "post_trash_refresh_completed",
                result="refreshed_and_stabilized",
                positive_feedback=True,
                feedback_source=getattr(self, "last_feedback_source", None),
            )

    def _viewport_center_path(self) -> tuple[tuple[float, float], ...]:
        try:
            viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
            width = viewport.get("width", 0)
            height = viewport.get("height", 0)
            if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                return ()
            if width <= 0 or height <= 0:
                return ()
        except (AttributeError, TypeError):
            return ()
        x = viewport["width"] / 2
        y = viewport["height"] / 2
        return ((x, y),)

    def _move_pointer_path(
        self, points: Sequence[tuple[float, float]], *, pause_ms: int | None = None
    ) -> None:
        """Move along a bounded, interpolated viewport trajectory using visible input."""
        max_steps = getattr(self, "pointer_max_steps", self.DEFAULT_POINTER_MAX_STEPS)
        configured_pause = getattr(self, "pointer_pause_ms", self.DEFAULT_POINTER_PAUSE_MS)
        # ``pause_ms`` remains accepted for old internal callers, but configured
        # pointer options cap every path so a fallback cannot retry unboundedly.
        pause = configured_pause if pause_ms is None else min(pause_ms, configured_pause)
        waypoints = tuple(points)
        mouse = getattr(self.page, "mouse", None)
        if mouse is None or not callable(getattr(mouse, "move", None)) or not waypoints:
            return
        if len(waypoints) == 1:
            trajectory = waypoints
        else:
            segment_count = len(waypoints) - 1
            trajectory = []
            for step in range(max_steps):
                position = step / max(1, max_steps - 1)
                segment = min(int(position * segment_count), segment_count - 1)
                local = position * segment_count - segment
                start_x, start_y = waypoints[segment]
                end_x, end_y = waypoints[segment + 1]
                trajectory.append(
                    (
                        float(start_x) + (float(end_x) - float(start_x)) * local,
                        float(start_y) + (float(end_y) - float(start_y)) * local,
                    )
                )
        for x, y in trajectory:
            mouse.move(x, y)
            if pause > 0:
                self._wait_for_timeout(pause)
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "pointer_motion",
                pointer_moves=len(trajectory),
                pointer_path_steps=len(trajectory),
                pause_ms=pause,
            )

    def advance_timeline(self) -> bool:
        """Move current visible timeline down once using real visible mouse input."""
        viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
        before = self._dom_counts() if getattr(self, "diagnostic", None) is not None else {}
        x = viewport["width"] / 2
        y = viewport["height"] / 2
        step = getattr(self, "scroll_step", self.DEFAULT_SCROLL_STEP)
        delay = getattr(self, "scroll_delay_ms", self.DEFAULT_SCROLL_DELAY_MS)
        self._move_pointer_path(((x * 0.72, y * 0.66), (x, y)))
        self.page.mouse.wheel(0, step)
        self._move_pointer_path(((x * 0.88, y * 0.58), (x, y)))
        self._wait_for_timeout(delay)
        after = self._dom_counts() if getattr(self, "diagnostic", None) is not None else {}
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "timeline_advanced",
                viewport=viewport,
                pointer_moves=4,
                pointer_path_steps=4,
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
        self._wait_for_timeout(delay)
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

    def _visible_control_target(self, control):
        """Return visible descendant used only as normal Playwright click target."""
        visibility_check = getattr(control, "is_visible", None)
        bounds_check = getattr(control, "bounding_box", None)
        if not callable(visibility_check) and not callable(bounds_check):
            return control
        try:
            if control.is_visible():
                return control
        except AttributeError:
            try:
                if callable(bounds_check) and bounds_check() is not None:
                    return control
            except Exception:
                pass
        except Exception:
            pass
        for selector in ("svg", "[role=img]", "[data-icon]", "path"):
            try:
                descendants = control.locator(selector)
                for index in range(descendants.count()):
                    target = descendants.nth(index)
                    if target.is_visible() and target.bounding_box() is not None:
                        return target
            except Exception:
                continue
        return None

    @staticmethod
    def _is_pointer_interception_error(error: Exception) -> bool:
        message = str(error).lower()
        return "intercepts pointer events" in message

    def _visible_target_point(self, target) -> tuple[float, float] | None:
        try:
            box = target.bounding_box()
        except Exception:
            return None
        if not isinstance(box, dict):
            return None
        try:
            box_width = float(box.get("width", 0))
            box_height = float(box.get("height", 0))
            box_x = float(box.get("x", 0))
            box_y = float(box.get("y", 0))
        except (TypeError, ValueError):
            return None
        if box_width <= 0 or box_height <= 0:
            return None
        viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
        x = box_x + box_width / 2
        y = box_y + box_height / 2
        if isinstance(viewport, dict):
            width = viewport.get("width", 0)
            height = viewport.get("height", 0)
            if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                return None
            if not (0 <= x < width and 0 <= y < height):
                return None
        return x, y

    def _reactivate_hover_for_control(self, control) -> None:
        """Re-enter a visible control's container before reading it for a click."""
        point = self._visible_target_point(control)
        if point is None:
            return
        hover_point = self._visible_ancestor_point(control) or point
        self._move_pointer_path(
            self._hover_approach_path(*point, hover_point=hover_point),
            pause_ms=min(120, getattr(self, "pointer_pause_ms", self.DEFAULT_POINTER_PAUSE_MS)),
        )
        self._wait_for_timeout(120)

    def _visible_ancestor_point(self, control) -> tuple[float, float] | None:
        """Return the center of the nearest visible ancestor already in viewport."""
        viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
        if not isinstance(viewport, dict):
            return None
        for depth in range(1, 7):
            try:
                ancestor = control.locator("xpath=" + "/.." * depth)
                box = ancestor.bounding_box()
            except Exception:
                continue
            if not isinstance(box, dict):
                continue
            try:
                x, y = float(box["x"]), float(box["y"])
                width, height = float(box["width"]), float(box["height"])
                viewport_width = float(viewport["width"])
                viewport_height = float(viewport["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if width <= 0 or height <= 0:
                continue
            if x < 0 or y < 0 or x >= viewport_width or y >= viewport_height:
                continue
            if x + width > viewport_width or y + height > viewport_height:
                continue
            return x + width / 2, y + height / 2
        return None

    def _fresh_hover_control(self, control):
        """Re-resolve control after hover because virtualized rows may rerender."""
        label = None
        try:
            label = control.get_attribute("aria-label")
        except Exception:
            pass
        if not isinstance(label, str) or not label:
            return control
        if getattr(control, "get_attribute", None) is not None:
            try:
                role = control.get_attribute("role")
            except Exception:
                role = None
            if role == "button":
                return control
        # Trash controls are often implicit buttons without a role attribute;
        # never reinterpret their accessible label as a media checkbox label.
        normalized_label = " ".join(label.split()).casefold()
        if normalized_label in {
            "move to trash",
            "sposta nel cestino",
            "move to bin",
        }:
            return control
        fresh = self._fresh_labeled_control(label)
        if fresh is not None and self._visible_target_point(fresh) is not None:
            return fresh
        return None

    def _hover_approach_path(
        self, x: float, y: float, *, hover_point: tuple[float, float] | None = None
    ) -> tuple[tuple[float, float], ...]:
        viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
        width = float(viewport.get("width", x)) if isinstance(viewport, dict) else x
        height = float(viewport.get("height", y)) if isinstance(viewport, dict) else y
        destination = hover_point or (x, y)
        start = (
            max(0.0, min(width - 1.0, destination[0] - 80.0)),
            max(0.0, min(height - 1.0, destination[1] - 50.0)),
        )
        return (start, destination, (x, y))

    def _click_control(self, control) -> None:
        target = self._visible_control_target(control)
        if target is None:
            raise CleanerError("Visible control target not found")
        # Playwright Locator objects resolve against the current DOM at action
        # time. Re-resolving by label here would add another race for virtualized
        # rows; visibility and bounding-box checks above are the fail-closed gate.
        # Re-resolve labeled controls after hover because virtualized rows may rerender.
        self._reactivate_hover_for_control(target)
        refreshed = self._fresh_hover_control(target)
        if refreshed is None:
            raise CleanerError("Visible control target was replaced after hover")
        target = refreshed
        click_timeout = min(2000, self._inactivity_timeout_ms())
        try:
            try:
                target.click(timeout=click_timeout)
            except TypeError as exc:
                if "timeout" not in str(exc):
                    raise
                target.click()
        except Exception as exc:
            if not self._is_pointer_interception_error(exc):
                raise
            # One bounded, normal-click retry only. Never force-click or retry a
            # second time after this attempt; caller must fail closed.
            point = self._visible_target_point(target)
            if point is None:
                raise CleanerError("Intercepted control is no longer visibly clickable") from exc
            self._move_pointer_path((point,))
            try:
                target.click(timeout=click_timeout)
            except TypeError as retry_error:
                if "timeout" not in str(retry_error):
                    raise
                target.click()

    def _first_viewport_control(self, selectors: Sequence[str]):
        """Return top-left control in viewport without programmatic scrolling.

        Google Photos gives its day/media checkbox a zero-size box until pointer
        enters its already-visible parent. Move mouse only to a parent's existing
        viewport coordinates; unlike Locator.hover(), this cannot scroll a target
        into view.
        """
        viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
        visible: list[tuple[float, float, str, object, object]] = []
        candidate_count = 0
        target_count = 0
        self.last_locator_selector = None
        self.last_control_target = None
        for selector in selectors:
            locator = self.page.locator(selector)
            selector_count = locator.count()
            candidate_count += selector_count
            for index in range(selector_count):
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
                parent_point = (
                    parent_box["x"] + parent_box["width"] / 2,
                    parent_box["y"] + parent_box["height"] / 2,
                )
                self._move_pointer_path(
                    (
                        (parent_point[0] - 18, parent_point[1] - 12),
                        parent_point,
                    )
                )
                try:
                    box = candidate.bounding_box()
                except Exception:
                    continue
                target = self._visible_control_target(candidate)
                if target is not None:
                    target_count += 1
                    try:
                        target_box = target.bounding_box()
                    except Exception:
                        target_box = None
                    if target_box is not None:
                        box = target_box
                # The day checkbox can remain zero-sized until its row hover
                # state settles; re-read it after the visible pointer move.
                if box is None or box["width"] <= 0 or box["height"] <= 0:
                    self._move_pointer_path((parent_point,), pause_ms=120)
                    self._wait_for_timeout(150)
                    try:
                        box = candidate.bounding_box()
                    except Exception:
                        continue
                if box is not None and box["width"] > 0 and box["height"] > 0:
                    visible.append((parent_box["y"], parent_box["x"], selector, candidate, target))
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "control_materialization",
                candidate_count=candidate_count,
                visible_count=len(visible),
                selector_count=len(selectors),
                viewport=viewport,
                pointer_moves=len(visible),
                target_count=target_count,
            )
        if not visible:
            return None
        selected = min(visible, key=lambda item: (item[0], item[1]))
        self.last_locator_selector = selected[2]
        self.last_control_target = selected[4]
        return selected[3]

    def _fresh_labeled_control(self, label: str):
        """Resolve the same visible, materialized checkbox immediately before click."""
        try:
            locator = self.page.get_by_role("checkbox", name=label, exact=True)
            viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
            count = locator.count()
            for index in range(count):
                candidate = locator.first if index == 0 else locator.nth(index)
                if not candidate.is_visible():
                    continue
                box = candidate.bounding_box()
                if not box or box["width"] <= 0 or box["height"] <= 0:
                    continue
                if isinstance(viewport, dict):
                    if not (0 <= box["x"] < viewport.get("width", 0) and 0 <= box["y"] < viewport.get("height", 0)):
                        continue
                return candidate
            return None
        except (AttributeError, TypeError, StopIteration):
            return None

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

    def select_current_day(
        self,
        *,
        batch_size: int | None = None,
        excluded_media_ids: Sequence[str] = (),
    ) -> str | None:
        if batch_size is not None and batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if self._is_trash_route():
            raise CleanerError("Refusing to select media from the Google Photos Trash route")
        self._wait_for_timeout(750)
        control = self._day_locator()
        if control is None:
            effective_batch_size = batch_size if batch_size is not None else self.max_materialized_batch
            if batch_size is None and not excluded_media_ids:
                media = self.select_visible_batch(effective_batch_size)
            else:
                media = self.select_visible_batch(
                    effective_batch_size,
                    excluded_media_ids=excluded_media_ids,
                )
            self.last_selection_kind = "media" if media else None
            return f"batch:{len(media)}" if media else None
        label = control.get_attribute("aria-label") or "unknown-day"
        before = control.get_attribute("aria-checked")
        # Re-resolve after pointer materialization. Virtualized rows can expose
        # a stale hidden node first; never click a locator that is not visible.
        materialized = self._day_locator()
        if materialized is not None and materialized is not control:
            control = materialized
            label = control.get_attribute("aria-label") or label
            before = control.get_attribute("aria-checked")
        fresh = self._fresh_labeled_control(label)
        if fresh is not None:
            control = fresh
            before = control.get_attribute("aria-checked")
        if before == "true":
            self.last_selection_kind = "day"
            self._log_selection(
                kind="day",
                selector=getattr(self, "last_locator_selector", "DAY_SELECTORS"),
                label=label,
                before=before,
                after=before,
                verified=True,
            )
            return label
        self._reactivate_hover_for_control(control)
        self._click_control(control)
        self._wait_for_timeout(150)
        # Read clicked locator first. Google Photos may reorder virtualized rows,
        # so the topmost fresh locator can represent a different day.
        try:
            after = control.get_attribute("aria-checked")
        except (StopIteration, IndexError):
            after = None
        # Re-resolve only for diagnostics/fallback when clicked node has no state.
        if after is None:
            try:
                current = self._day_locator()
            except (StopIteration, IndexError):
                current = None
            try:
                after = current.get_attribute("aria-checked") if current is not None else None
            except (StopIteration, IndexError):
                after = before
        if after is not None and not isinstance(after, str):
            after = "true" if before == "false" else None
        verified = after == "true"
        self._log_selection(
            kind="day",
            selector=getattr(self, "last_locator_selector", "DAY_SELECTORS"),
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
        self._reactivate_hover_for_control(item)
        self._click_control(item)
        after = item.get_attribute("aria-checked")
        selected = self.page.locator('[role="checkbox"][aria-checked="true"]')
        verified = False
        for _ in range(5):
            if selected.count() > 0:
                verified = True
                break
            self._wait_for_timeout(150)
        self._log_selection(
            kind="media",
            selector=getattr(self, "last_locator_selector", "SINGLE_MEDIA_SELECTORS"),
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

    def select_visible_batch(
        self,
        batch_size: int,
        *,
        excluded_media_ids: Sequence[str] = (),
    ) -> Sequence[str]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        excluded_ids = set(excluded_media_ids)
        if self._is_trash_route():
            raise CleanerError("Refusing to select media from the Google Photos Trash route")
        self.last_batch_ids = []
        self._wait_for_selector(self.MEDIA_SELECTORS[0])
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
            # A selection overlay can survive a post-Trash reload while its
            # virtualized nodes are being replaced. Re-read once after the
            # bounded settle delay and only preserve a stable selection.
            self._wait_for_timeout(750)
            settled_selected = self.page.locator(
                '[role="checkbox"][aria-checked="true"][aria-label*=" - "]'
            )
            settled_count = settled_selected.count()
            if settled_count != preselected_count:
                self.last_batch_ids = []
                self.last_selection_kind = None
                raise CleanerError("Existing selection changed; refusing trash action")
            self.last_batch_ids = [f"already-selected-{index + 1}" for index in range(settled_count)]
            # Preserve user/manual selection rather than attempting another tile
            # click over an open Google Photos selection overlay.
            return [f"already-selected-{index + 1}" for index in range(settled_count)]
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
                if candidate_id in seen_ids or candidate_id in excluded_ids:
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
            self._reactivate_hover_for_control(item)
            self._click_control(item)
            self._wait_for_timeout(150)
            selected_after = selected.count()
            aria_after = item.get_attribute("aria-checked")
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "media_selection_attempt",
                    kind="media",
                    selector="MEDIA_SELECTORS",
                    media_index=index,
                    has_media_id=bool(media_id),
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
        self._wait_for_timeout(750)
        if selected.count() != len(ids):
            raise CleanerError("Selection count is inconsistent; refusing trash action")
        self.last_batch_ids = ids
        return ids

    def target_exists(self, label: str) -> bool:
        """Check an exact accessible label without unsafe CSS interpolation."""
        return self.page.get_by_role("checkbox", name=label, exact=True).count() > 0

    @staticmethod
    def _normalize_feedback_role(value: str | None) -> str:
        if value is None:
            return "missing"
        normalized = value.strip().lower()
        if normalized in {"status", "alert", "log"}:
            return normalized
        if normalized in {"", "generic"}:
            return "generic" if normalized else "missing"
        return "other"

    @staticmethod
    def _normalize_feedback_aria_live(value: str | None) -> str:
        if value is None:
            return "missing"
        normalized = value.strip().lower()
        if normalized in {"off", "polite", "assertive"}:
            return normalized
        if not normalized:
            return "missing"
        return "other"

    @staticmethod
    def _moved_count_from_popup_match(match: re.Match[str]) -> int:
        for group in match.groups():
            if group is not None:
                return int(group)
        raise ValueError("Trash popup quantity capture missing")

    def _observe_trash_feedback_live_regions(self) -> bool:
        for selector_kind, selector in self.TRASH_FEEDBACK_LIVE_REGION_SELECTORS:
            matched_count = 0
            visible_count = 0
            role_counts: dict[str, int] = {}
            aria_live_counts: dict[str, int] = {}
            visible_candidates: list[tuple[str, str, int | None]] = []
            try:
                locator = self.page.locator(selector)
                matched_count = locator.count()
                if not isinstance(matched_count, int):
                    continue
                for index in range(matched_count):
                    candidate = locator.first if index == 0 else locator.nth(index)
                    role = self._normalize_feedback_role(candidate.get_attribute("role"))
                    aria_live = self._normalize_feedback_aria_live(candidate.get_attribute("aria-live"))
                    role_counts[role] = role_counts.get(role, 0) + 1
                    aria_live_counts[aria_live] = aria_live_counts.get(aria_live, 0) + 1
                    if not candidate.is_visible():
                        continue
                    visible_count += 1
                    rendered_text = candidate.inner_text()
                    moved_count = None
                    if isinstance(rendered_text, str):
                        match = self.TRASH_FEEDBACK_POPUP_PATTERN.search(rendered_text)
                        if match is not None:
                            moved_count = self._moved_count_from_popup_match(match)
                    visible_candidates.append((role, aria_live, moved_count))
            except Exception as exc:
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_feedback_dom_observation_failed",
                        "ERROR",
                        selector_group="live_region",
                        selector_kind=selector_kind,
                        error_type=type(exc).__name__,
                    )
                return False
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_feedback_dom_observation",
                    selector_group="live_region",
                    selector_kind=selector_kind,
                    matched_count=matched_count,
                    visible_count=visible_count,
                    candidate_role_counts=role_counts,
                    candidate_aria_live_counts=aria_live_counts,
                )
                for role, aria_live, moved_count in visible_candidates:
                    candidate_event = {
                        "candidate_kind": "live_region",
                        "popup_kind": "unknown",
                        "visible": True,
                        "role": role,
                        "aria_live": aria_live,
                        "has_quantity": moved_count is not None,
                        "quantity_parseable": moved_count is not None,
                    }
                    if moved_count is not None:
                        candidate_event["moved_count"] = moved_count
                    self.diagnostic.event("trash_feedback_candidate", **candidate_event)
            for _role, _aria_live, moved_count in visible_candidates:
                if moved_count is None:
                    continue
                self.last_feedback_source = "browser_positive_feedback"
                self.last_feedback_count = moved_count
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_feedback_popup",
                        popup_kind="bottom_left_toast",
                        popup_selector=selector_kind,
                        moved_count=moved_count,
                        positive_feedback=True,
                        feedback_source=self.last_feedback_source,
                    )
                return True
        return False

    def _trash_feedback_visible(self) -> bool:
        """Require visible Google Photos Trash feedback, parsing popup count."""
        self.last_feedback_source = None
        self.last_feedback_count = None
        if self._observe_trash_feedback_live_regions():
            return True
        legacy_feedback = (
            "Moved to trash",
            "Moved to Trash",
            "Spostato nel cestino",
            "Spostata nel cestino",
            "Spostati nel cestino",
            "Spostato nel Cestino",
            "Moved to bin",
        )
        # Keep legacy checks first for existing adapter compatibility. They are
        # visibility-gated and do not claim quantity-bearing popup proof.
        for text in legacy_feedback:
            count = 0
            visible_count = 0
            try:
                locator = self.page.get_by_text(text, exact=False)
                count = locator.count()
                if not isinstance(count, int):
                    continue
                visible_target = None
                for index in range(count):
                    candidate = locator.first if index == 0 else locator.nth(index)
                    if candidate.is_visible():
                        visible_count += 1
                        visible_target = candidate
            except Exception as exc:
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_feedback_check_failed",
                        "ERROR",
                        feedback_category=text,
                        matched_count=count,
                        visible_count=visible_count,
                        feedback_source=None,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        positive_feedback=False,
                    )
                return False
            source = "browser_positive_feedback" if visible_count else (
                "dom_candidate_not_visible" if count else None
            )
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_feedback_candidate",
                    feedback_category=text,
                    matched_count=count,
                    visible_count=visible_count,
                    feedback_source=source,
                )
            if visible_target is not None:
                self.last_feedback_source = "browser_positive_feedback"
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_feedback_candidate_visible",
                        feedback_category=text,
                        matched_count=count,
                        visible_count=visible_count,
                        feedback_source=self.last_feedback_source,
                    )
                return True

        popup_pattern = self.TRASH_FEEDBACK_POPUP_PATTERN
        try:
            popup_locator = self.page.get_by_text(popup_pattern, exact=False)
            popup_count = popup_locator.count()
            if isinstance(popup_count, int):
                for index in range(popup_count):
                    candidate = popup_locator.first if index == 0 else popup_locator.nth(index)
                    if not candidate.is_visible():
                        continue
                    rendered_text = candidate.inner_text()
                    if not isinstance(rendered_text, str):
                        continue
                    match = popup_pattern.search(rendered_text)
                    if match is None:
                        continue
                    moved_count = self._moved_count_from_popup_match(match)
                    self.last_feedback_source = "browser_positive_feedback"
                    self.last_feedback_count = moved_count
                    if getattr(self, "diagnostic", None) is not None:
                        self.diagnostic.event(
                            "trash_feedback_popup",
                            popup_kind="bottom_left_toast",
                            popup_selector="text_pattern",
                            moved_count=moved_count,
                            positive_feedback=True,
                            feedback_source=self.last_feedback_source,
                        )
                    return True
        except Exception as exc:
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_feedback_check_failed",
                    "ERROR",
                    popup_selector="text_pattern",
                    feedback_source=None,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    positive_feedback=False,
                )
            return False
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_feedback_popup_absent",
                positive_feedback=False,
                feedback_source=None,
            )
        return False

    def wait_for_target_absence(self, label: str, timeout_ms: int = 30000) -> bool:
        """Reconcile only with positive trash feedback; never clicks Trash again."""
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than zero")
        deadline = time.monotonic() + timeout_ms / 1000
        checks = 0
        try:
            while time.monotonic() < deadline:
                checks += 1
                feedback = self._trash_feedback_visible()
                positive_source = self.last_feedback_source if feedback else None
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_reconcile_check",
                        target=label,
                        timeout_ms=timeout_ms,
                        check=checks,
                        target_count=self._target_count(label),
                        final=bool(feedback),
                        positive_feedback=feedback,
                        feedback_source=positive_source,
                    )
                if feedback:
                    return True
                self._wait_for_timeout(500)
            feedback = self._trash_feedback_visible()
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_reconcile_check",
                    target=label,
                    timeout_ms=timeout_ms,
                    check=max(checks, 1),
                    target_count=self._target_count(label),
                    final=True,
                    positive_feedback=feedback,
                    feedback_source=self.last_feedback_source if feedback else None,
                )
        except Exception as exc:
            self.last_feedback_source = None
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_reconcile_check_failed",
                    "ERROR",
                    target=label,
                    timeout_ms=timeout_ms,
                    check=max(checks, 1),
                    final=True,
                    positive_feedback=False,
                    feedback_source=None,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            raise
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_reconcile_timeout",
                "WARNING",
                target=label,
                timeout_ms=timeout_ms,
                checks=max(checks, 1),
                check=max(checks, 1),
                target_count=self._target_count(label),
                final=True,
                positive_feedback=feedback,
                feedback_source=self.last_feedback_source if feedback else None,
            )
        return feedback

    def _target_count(self, label: str) -> int:
        return self.page.get_by_role("checkbox", name=label, exact=True).count()

    def retry_pending_action(self, label: str) -> bool:
        """User-authorized one-time retry of a journaled pending Trash action."""
        target = self.page.get_by_role("checkbox", name=label, exact=True)
        if target.count() == 0:
            return False
        visible_target = self._visible_first(target)
        if visible_target is None:
            return False
        self._click_control(visible_target)
        return self.delete_selected_day()

    def _visible_first(self, locator):
        """Return first visible locator without forcing or scrolling it."""
        count = locator.count()
        for index in range(count):
            candidate = locator.first if index == 0 else locator.nth(index)
            try:
                visible = candidate.is_visible()
            except (AttributeError, TypeError):
                box = candidate.bounding_box()
                visible = box is not None and box["width"] > 0 and box["height"] > 0
            if visible:
                return candidate
        return None

    def _wait_for_trash_feedback(self, timeout_ms: int = 5000) -> bool:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than zero")
        started = time.monotonic()
        started_perf = time.perf_counter()
        deadline = started + timeout_ms / 1000
        checks = 0
        try:
            while time.monotonic() < deadline:
                checks += 1
                feedback = self._trash_feedback_visible()
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_feedback_check",
                        timeout_ms=timeout_ms,
                        check=checks,
                        final=False,
                        positive_feedback=feedback,
                        feedback_source=self.last_feedback_source,
                    )
                if feedback:
                    if getattr(self, "diagnostic", None) is not None:
                        self.diagnostic.event(
                            "trash_feedback_check",
                            timeout_ms=timeout_ms,
                            check=checks,
                            final=True,
                            positive_feedback=True,
                            feedback_source=self.last_feedback_source,
                            feedback_category="Moved to trash",
                            elapsed_ms=round((time.perf_counter() - started_perf) * 1000),
                            remaining_ms=max(0, timeout_ms - round((time.perf_counter() - started_perf) * 1000)),
                        )
                    return True
                self._wait_for_timeout(250)
            feedback = self._trash_feedback_visible()
        except Exception as exc:
            self.last_feedback_source = None
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_feedback_check",
                    "ERROR",
                    timeout_ms=timeout_ms,
                    check=max(checks, 1),
                    final=True,
                    positive_feedback=False,
                    feedback_source=None,
                    elapsed_ms=round((time.perf_counter() - started_perf) * 1000),
                    remaining_ms=max(0, timeout_ms - round((time.perf_counter() - started_perf) * 1000)),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            raise
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_feedback_check",
                timeout_ms=timeout_ms,
                check=max(checks, 1),
                final=True,
                positive_feedback=feedback,
                feedback_source=self.last_feedback_source if feedback else None,
                feedback_category="Moved to trash" if feedback else None,
                elapsed_ms=round((time.perf_counter() - started_perf) * 1000),
                remaining_ms=max(0, timeout_ms - round((time.perf_counter() - started_perf) * 1000)),
            )
        return feedback

    def delete_selected_day(self) -> bool:
        trash_names = (
            "Move to trash",
            "Sposta nel cestino",
            "Move to bin",
            "Sposta nel Cestino",
        )
        trash = None
        button_counts = {}
        visible_button_counts = {}
        for name in trash_names:
            candidate = self.page.get_by_role("button", name=name, exact=True)
            button_counts[name] = candidate.count()
            visible_candidate = self._visible_first(candidate) if button_counts[name] else None
            visible_button_counts[name] = 1 if visible_candidate is not None else 0
            if visible_candidate is not None:
                trash = visible_candidate
                break
        selected = self.page.locator('[role="checkbox"][aria-checked="true"]')
        selected_before = selected.count()
        if selected_before <= 0:
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_action_unavailable",
                    "WARNING",
                    target_kind=getattr(self, "last_selection_kind", "unknown"),
                    selected_before=selected_before,
                    action_button_counts=button_counts,
                    visible_action_button_counts=visible_button_counts,
                    result="not_clicked",
                    reason="empty_selection",
                )
            raise CleanerError("Refusing Trash action with empty selection")
        if trash is None:
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_action_unavailable",
                    "WARNING",
                    target_kind=getattr(self, "last_selection_kind", "unknown"),
                    selected_before=selected_before,
                    action_button_counts=button_counts,
                    visible_action_button_counts=visible_button_counts,
                    result="not_clicked",
                )
            raise CleanerError("Delete action not found; refusing blind click")
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_click_started",
                target_kind=getattr(self, "last_selection_kind", "unknown"),
                selected_before=selected_before,
                action_button_counts=button_counts,
                visible_action_button_counts=visible_button_counts,
                confirmation_required=None,
                result="started",
            )
        self._click_control(trash)
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_click_completed",
                selected_before=selected_before,
                result="clicked",
            )
        # Google Photos may expose a confirmation dialog only after the first
        # click. Give the dialog a bounded settle window before interpreting the
        # still-selected virtualized tiles as an ambiguous result.
        dialog = self.page.get_by_role("dialog")
        dialog_count = 0
        for _ in range(8):
            dialog_count = dialog.count()
            if dialog_count > 0:
                break
            self._wait_for_timeout(250)
        if dialog_count > 0:
            confirmation = None
            for name in trash_names:
                candidate = dialog.get_by_role("button", name=name, exact=True)
                confirmation = self._visible_first(candidate) if candidate.count() else None
                if confirmation is not None:
                    break
            if confirmation is None:
                raise CleanerError("Delete confirmation button not found")
            self._click_control(confirmation)
            self._wait_for_timeout(1000)
            selected_after = selected.count()
            feedback = self._wait_for_trash_feedback()
            if getattr(self, "diagnostic", None) is not None:
                self.diagnostic.event(
                    "trash_confirmation_completed",
                    selected_after=selected_after,
                    positive_feedback=feedback,
                    feedback_source=self.last_feedback_source,
                    result="confirmed" if feedback else "ambiguous",
                )
            if selected_after > 0:
                return False
            if not feedback:
                return False
            feedback_count = getattr(self, "last_feedback_count", None)
            if feedback_count is not None and feedback_count != selected_before:
                raise CleanerError("Trash feedback quantity is inconsistent; result is ambiguous")
            self.refresh_after_trash()
            return True
        for _ in range(10):
            self._wait_for_timeout(250)
            if selected_before > 0 and selected.count() == 0:
                # Virtualized DOM can drop selected nodes during a refresh. Only
                # confirm success when Google Photos also exposes positive feedback.
                feedback = self._wait_for_trash_feedback()
                if getattr(self, "diagnostic", None) is not None:
                    self.diagnostic.event(
                        "trash_feedback_checked",
                        selected_after=selected.count(),
                        positive_feedback=feedback,
                        feedback_source=self.last_feedback_source,
                        result="confirmed" if feedback else "ambiguous",
                    )
                if feedback:
                    feedback_count = getattr(self, "last_feedback_count", None)
                    if feedback_count is not None and feedback_count != selected_before:
                        raise CleanerError("Trash feedback quantity is inconsistent; result is ambiguous")
                    self.refresh_after_trash()
                return feedback

        # No dialog appeared in the bounded window. The first click has already
        # happened, so return pending and let the caller reconcile; never click
        # the destructive control a second time based on stale virtualized DOM.
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_dialog_detected",
                dialog_count=dialog_count,
                selected_count=selected.count(),
                result="dialog" if dialog_count else "no_dialog",
            )
        if dialog_count == 0:
            return False
        confirmation = None
        for name in trash_names:
            candidate = dialog.get_by_role("button", name=name, exact=True)
            confirmation = self._visible_first(candidate) if candidate.count() else None
            if confirmation is not None:
                break
        if confirmation is None:
            raise CleanerError("Delete confirmation button not found")
        self._click_control(confirmation)
        self._wait_for_timeout(1000)
        selected_after = selected.count()
        feedback = self._wait_for_trash_feedback()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_confirmation_completed",
                selected_after=selected_after,
                positive_feedback=feedback,
                feedback_source=self.last_feedback_source,
                result="confirmed" if feedback else "ambiguous",
            )
        if selected_after > 0:
            return False
        if not feedback:
            return False
        feedback_count = getattr(self, "last_feedback_count", None)
        if feedback_count is not None and feedback_count != selected_before:
            raise CleanerError("Trash feedback quantity is inconsistent; result is ambiguous")
        self.refresh_after_trash()
        return True

    def move_selected_to_trash(self, media_ids: Sequence[str]) -> None:
        if self._is_trash_route():
            raise CleanerError("Refusing Trash action on the Google Photos Trash route")
        if not media_ids:
            raise CleanerError("Refusing to trash an empty selection")

        button_counts = {}
        visible_button_counts = {}
        trash = None
        visible_trash = None
        for name in ("Move to trash", "Sposta nel cestino", "Move to bin", "Sposta nel Cestino"):
            try:
                candidate = self.page.get_by_role("button", name=name, exact=True)
            except StopIteration:
                break
            button_counts[name] = candidate.count()
            visible_candidate = self._visible_first(candidate) if button_counts[name] else None
            visible_button_counts[name] = 1 if visible_candidate is not None else 0
            if visible_candidate is not None:
                trash = candidate
                visible_trash = visible_candidate
                break
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_batch_click_started",
                selected_count=len(media_ids),
                action_button_counts=button_counts,
                visible_action_button_counts=visible_button_counts,
                result="started",
            )
        if visible_trash is None:
            raise CleanerError("Trash action not found visibly; refusing blind click")
        self._click_control(visible_trash)
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event("trash_batch_click_completed", result="clicked")
        self._wait_for_timeout(500)
        confirmation = None
        for name in ("Move to trash", "Sposta nel cestino", "Move to bin", "Sposta nel Cestino"):
            try:
                candidate = self.page.get_by_role("button", name=name, exact=True)
            except StopIteration:
                break
            visible_candidate = self._visible_first(candidate) if candidate.count() else None
            if visible_candidate is not None:
                confirmation = visible_candidate
                break
        confirmation_count = 1 if confirmation is not None else 0
        visible_confirmation = confirmation
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_batch_dialog_detected",
                confirmation_count=confirmation_count,
                visible_confirmation_count=1 if visible_confirmation is not None else 0,
                result="confirmation_available" if visible_confirmation is not None else "missing",
            )
        if visible_confirmation is None:
            raise CleanerError("Visible Trash confirmation not found; result is ambiguous")
        self._click_control(visible_confirmation)
        self._wait_for_timeout(1000)
        feedback = self._wait_for_trash_feedback()
        if getattr(self, "diagnostic", None) is not None:
            self.diagnostic.event(
                "trash_batch_feedback_checked",
                positive_feedback=feedback,
                feedback_source=self.last_feedback_source,
                result="confirmed" if feedback else "ambiguous",
            )
        if not feedback:
            raise CleanerError("Trash completion feedback not found; result is ambiguous")
        feedback_count = getattr(self, "last_feedback_count", None)
        if feedback_count is not None and feedback_count != len(media_ids):
            raise CleanerError("Trash feedback quantity is inconsistent; result is ambiguous")
        self.refresh_after_trash()

    def recover(self) -> None:
        """Dismiss transient overlays without reloading or resetting timeline."""
        self._dismiss_known_overlays()
        self._wait_for_timeout(500)

    def capture_diagnostics(self, directory: Path, reason: str) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        safe_reason = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in reason
        )[:80] or "error"
        screenshot = directory / f"{safe_reason}.png"
        self.page.screenshot(path=str(screenshot), full_page=True)
        return {"screenshot": screenshot}

    def close(self) -> None:
        close_error = None
        try:
            if self.context is not None:
                self.context.close()
            if self._playwright is not None:
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
                error_message=str(close_error) if close_error else None,
                recovery="lock_released",
            )
        if close_error is not None:
            raise close_error
