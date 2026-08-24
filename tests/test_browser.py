import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from googlephotos_cleaner.browser import PlaywrightBrowser, is_authenticated_url
from googlephotos_cleaner.automation import CleanerError


class BrowserDiagnosticsTests(unittest.TestCase):
    def test_browser_uses_small_slow_scroll_defaults(self):
        self.assertEqual(PlaywrightBrowser.DEFAULT_SCROLL_STEP, 240)
        self.assertEqual(PlaywrightBrowser.DEFAULT_SCROLL_DELAY_MS, 1500)

    def test_google_photos_landing_page_is_not_authenticated(self):
        self.assertFalse(is_authenticated_url("https://www.google.com/photos/about/"))
        self.assertFalse(is_authenticated_url("https://accounts.google.com/signin"))
        self.assertTrue(is_authenticated_url("https://photos.google.com/"))
        self.assertTrue(is_authenticated_url("https://photos.google.com/u/0/"))

    def test_browser_uses_chromium_sandbox_without_automation_flag(self):
        self.assertTrue(PlaywrightBrowser.CHROMIUM_SANDBOX)
        self.assertEqual(PlaywrightBrowser.CHROMIUM_ARGS, ())

    def test_browser_profile_path_is_not_recreated(self):
        self.assertTrue(hasattr(PlaywrightBrowser, "LOGIN_URL"))
        self.assertTrue(hasattr(PlaywrightBrowser, "PHOTOS_URL"))

    def test_browser_targets_library_route(self):
        self.assertEqual(PlaywrightBrowser.LOGIN_URL, "https://photos.google.com/login")
        self.assertEqual(PlaywrightBrowser.PHOTOS_URL, "https://photos.google.com/u/0/")

    def test_authenticated_session_does_not_reload_the_timeline(self):
        page = Mock()
        page.url = "https://photos.google.com/u/0/"
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        browser.wait_until_authenticated(timeout_seconds=1)

        page.goto.assert_not_called()

    def test_day_selector_uses_semantic_controls_without_visible_pseudo_selector(self):
        self.assertNotIn(":visible", PlaywrightBrowser.DAY_SELECTORS[0])
        self.assertNotIn(":visible", PlaywrightBrowser.DAY_SELECTORS[1])

    def test_single_media_fallback_targets_photo_and_video_checkboxes(self):
        self.assertEqual(
            PlaywrightBrowser.SINGLE_MEDIA_SELECTORS,
            (
                '[role="checkbox"][aria-label^="Foto -"]',
                '[role="checkbox"][aria-label^="Video -"]',
                '[role="checkbox"][aria-label^="Photo -"]',
                '[role="checkbox"][aria-label^="Video -"]',
            ),
        )

    def test_first_viewport_control_reveals_only_visible_parent_and_uses_top_left_order(self):
        first, second, hidden = Mock(), Mock(), Mock()
        first_parent, second_parent, hidden_parent = Mock(), Mock(), Mock()
        first.locator.return_value = first_parent
        second.locator.return_value = second_parent
        hidden.locator.return_value = hidden_parent
        first_parent.bounding_box.return_value = {"x": 300, "y": 200, "width": 40, "height": 40}
        second_parent.bounding_box.return_value = {"x": 20, "y": 100, "width": 40, "height": 40}
        hidden_parent.bounding_box.return_value = {"x": 0, "y": 900, "width": 40, "height": 40}
        first.bounding_box.return_value = {"x": 300, "y": 200, "width": 20, "height": 20}
        second.bounding_box.return_value = {"x": 20, "y": 100, "width": 20, "height": 20}
        locator = Mock()
        locator.count.return_value = 3
        locator.nth.side_effect = [first, second, hidden]
        page = Mock()
        page.evaluate.return_value = {"width": 800, "height": 600}
        page.locator.return_value = locator
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertIs(browser._first_viewport_control(("[role=checkbox]",)), second)
        self.assertEqual(browser.last_locator_selector, "[role=checkbox]")
        self.assertEqual(page.mouse.move.call_count, 2)
        first.hover.assert_not_called()
        second.hover.assert_not_called()
        hidden.hover.assert_not_called()

    def test_first_viewport_control_keeps_selected_candidate_target_after_materialization(self):
        first = Mock()
        second = Mock()
        target = Mock()
        for control in (first, second):
            control.locator.return_value = target
            control.is_visible.return_value = False
            control.bounding_box.return_value = {"x": 272, "y": 672, "width": 0, "height": 24}
        target.count.return_value = 1
        target.nth.return_value = target
        target.is_visible.return_value = True
        target.bounding_box.return_value = {"x": 280, "y": 672, "width": 24, "height": 24}
        locator = Mock()
        locator.count.return_value = 2
        locator.nth.side_effect = [first, second]
        page = Mock()
        page.evaluate.return_value = {"width": 1000, "height": 720}
        page.locator.return_value = locator
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        result = browser._first_viewport_control(("[role=checkbox]",))

        self.assertIs(result, first)
        self.assertIs(browser.last_control_target, target)

    def test_day_selection_rechecks_materialized_control_before_click(self):
        first = Mock()
        second = Mock()
        first.get_attribute.side_effect = ["Seleziona tutte le foto a partire da: dom 2 ago", "false"]
        second.get_attribute.side_effect = lambda name: (
            "Seleziona tutte le foto a partire da: dom 2 ago"
            if name == "aria-label" else ("true" if second.click.call_count else "false")
        )
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None
        browser._day_locator = Mock(side_effect=[first, second, second])

        result = browser.select_current_day()

        self.assertEqual(result, "Seleziona tutte le foto a partire da: dom 2 ago")
        first.click.assert_not_called()
        second.click.assert_called_once_with()

    def test_day_selection_clicks_and_verifies_current_day_control(self):
        control = Mock()
        control.get_attribute.side_effect = ["Seleziona tutte le foto a partire da: dom 2 ago", "true"]
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None
        browser._day_locator = Mock(return_value=control)

        result = browser.select_current_day()

        self.assertEqual(result, "Seleziona tutte le foto a partire da: dom 2 ago")
        control.click.assert_called_once_with()

    def test_first_viewport_control_retries_after_pointer_materialization(self):
        control = Mock()
        parent = Mock()
        control.locator.return_value = parent
        parent.bounding_box.return_value = {"x": 10, "y": 100, "width": 960, "height": 48}
        control.bounding_box.side_effect = [None, {"x": 10, "y": 100, "width": 24, "height": 24}]
        locator = Mock()
        locator.count.return_value = 1
        locator.nth.return_value = control
        page = Mock()
        page.evaluate.return_value = {"width": 1000, "height": 600}
        page.locator.return_value = locator
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None

        result = browser._first_viewport_control(("[role=checkbox]",))

        self.assertIs(result, control)
        self.assertEqual(page.mouse.move.call_count, 1)
        self.assertEqual(control.bounding_box.call_count, 2)

    def test_first_viewport_control_finds_visible_svg_inside_hidden_checkbox(self):
        control = Mock()
        svg = Mock()
        control.locator.return_value = svg
        svg.count.return_value = 1
        svg.nth.return_value = svg
        control.bounding_box.return_value = {"x": 272, "y": 672, "width": 0, "height": 24}
        control.is_visible.return_value = False
        svg.bounding_box.return_value = {"x": 280, "y": 672, "width": 24, "height": 24}
        svg.is_visible.return_value = True
        locator = Mock()
        locator.count.return_value = 1
        locator.nth.return_value = control
        page = Mock()
        page.evaluate.return_value = {"width": 1000, "height": 720}
        page.locator.return_value = locator
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None

        result = browser._first_viewport_control(("[role=checkbox]",))

        self.assertIs(result, control)
        self.assertIs(browser.last_control_target, svg)

    def test_click_control_does_not_reuse_target_from_previous_control(self):
        previous = Mock()
        current = Mock()
        previous_target = Mock()
        current_target = Mock()
        previous.is_visible.return_value = False
        previous.locator.return_value = previous_target
        previous_target.count.return_value = 1
        previous_target.nth.return_value = previous_target
        previous_target.is_visible.return_value = True
        previous_target.bounding_box.return_value = {"x": 1, "y": 1, "width": 24, "height": 24}
        current.is_visible.return_value = False
        current.locator.return_value = current_target
        current_target.count.return_value = 1
        current_target.nth.return_value = current_target
        current_target.is_visible.return_value = True
        current_target.bounding_box.return_value = {"x": 2, "y": 2, "width": 24, "height": 24}
        browser = object.__new__(PlaywrightBrowser)
        browser.page = Mock()
        browser.last_control_target = previous_target

        browser._click_control(current)

        previous_target.click.assert_not_called()
        current_target.click.assert_called_once_with()

    def test_click_control_uses_normal_visible_locator_when_visibility_api_missing(self):
        control = Mock()
        control.is_visible.side_effect = AttributeError
        control.bounding_box.return_value = {"x": 10, "y": 10, "width": 24, "height": 24}
        browser = object.__new__(PlaywrightBrowser)
        browser.page = Mock()

        browser._click_control(control)

        control.click.assert_called_once_with()

    def test_hidden_checkbox_click_uses_visible_svg_without_force(self):
        control = Mock()
        svg = Mock()
        control.is_visible.return_value = False
        control.locator.return_value = svg
        svg.count.return_value = 1
        svg.nth.return_value = svg
        svg.is_visible.return_value = True
        svg.bounding_box.return_value = {"x": 280, "y": 672, "width": 24, "height": 24}
        browser = object.__new__(PlaywrightBrowser)
        browser.page = Mock()

        browser._click_control(control)

        control.click.assert_not_called()
        svg.click.assert_called_once_with()

    def test_first_viewport_control_logs_hidden_candidates(self):
        control = Mock()
        parent = Mock()
        control.locator.return_value = parent
        parent.bounding_box.return_value = {"x": 10, "y": 100, "width": 960, "height": 48}
        control.bounding_box.return_value = None
        locator = Mock()
        locator.count.return_value = 1
        locator.nth.return_value = control
        page = Mock()
        page.evaluate.return_value = {"width": 1000, "height": 600}
        page.locator.return_value = locator
        diagnostic = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = diagnostic

        self.assertIsNone(browser._first_viewport_control(("[role=checkbox]",)))

        event = diagnostic.event.call_args
        self.assertEqual(event.args[0], "control_materialization")
        self.assertEqual(event.kwargs["candidate_count"], 1)
        self.assertEqual(event.kwargs["visible_count"], 0)

    def test_day_locator_reveals_zero_width_checkbox_from_visible_day_row(self):
        control = Mock()
        row = Mock()
        control.locator.return_value = row
        control.bounding_box.side_effect = [
            None,
            {"x": 0, "y": 100, "width": 24, "height": 24},
            {"x": 0, "y": 100, "width": 24, "height": 24},
        ]
        row.bounding_box.return_value = {"x": 0, "y": 100, "width": 960, "height": 48}
        page = Mock()
        page.evaluate.return_value = {"width": 1000, "height": 600}
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.nth.return_value = control
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        result = browser._day_locator()

        self.assertIs(result, control)
        self.assertEqual(page.mouse.move.call_count, 2)

    def test_day_selection_verifies_clicked_day_not_topmost_day(self):
        initial = Mock()
        clicked = Mock()
        other = Mock()
        initial.get_attribute.side_effect = ["Seleziona tutte le foto a partire da: dom 2 ago", "false"]
        clicked.get_attribute.side_effect = lambda name: (
            "Seleziona tutte le foto a partire da: dom 2 ago"
            if name == "aria-label" else ("true" if clicked.click.call_count else "false")
        )
        other.get_attribute.side_effect = ["Seleziona tutte le foto a partire da: lun 1 ago", "false"]
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None
        browser._day_locator = Mock(side_effect=[initial, clicked, other])

        result = browser.select_current_day()

        self.assertEqual(result, "Seleziona tutte le foto a partire da: dom 2 ago")
        clicked.click.assert_called_once_with()

    def test_day_selection_rechecks_fresh_control_after_click(self):
        stale = Mock()
        fresh = Mock()
        stale.get_attribute.side_effect = ["Seleziona tutte le foto a partire da: dom 2 ago", "false"]
        fresh.get_attribute.side_effect = lambda name: (
            "Seleziona tutte le foto a partire da: dom 2 ago"
            if name == "aria-label"
            else "true"
        )
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None
        browser._day_locator = Mock(side_effect=[stale, fresh, fresh])

        result = browser.select_current_day()

        self.assertEqual(result, "Seleziona tutte le foto a partire da: dom 2 ago")
        stale.click.assert_not_called()
        fresh.click.assert_called_once_with()

    def test_day_selection_never_falls_back_to_single_media_after_day_control_found(self):
        control = Mock()
        control.get_attribute.side_effect = ["Seleziona tutte le foto a partire da: dom 2 ago", "false"]
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None
        browser._day_locator = Mock(return_value=control)
        browser._select_single_media_for_day = Mock(return_value="Foto - Verticale - 2 ago")

        with self.assertRaises(CleanerError):
            browser.select_current_day()

        browser._select_single_media_for_day.assert_not_called()

    def test_advance_timeline_logs_wheel_and_dom_materialization(self):
        page = Mock()
        page.evaluate.side_effect = [
            {"width": 1000, "height": 600},
            {"day": 0, "media": 4},
            {"day": 1, "media": 8},
        ]
        locator = Mock()
        locator.count.side_effect = [0, 0, 4, 1, 0, 8]
        page.locator.return_value = locator
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.scroll_step = 240
        browser.scroll_delay_ms = 1500
        browser.diagnostic = Mock()

        self.assertTrue(browser.advance_timeline())

        browser.diagnostic.event.assert_called_once()
        context = browser.diagnostic.event.call_args.kwargs
        self.assertEqual(context["wheel_delta_y"], 240)
        self.assertEqual(context["dom_before"]["day"], 0)
        self.assertEqual(context["dom_after"]["day"], 1)
        self.assertTrue(context["materialized"])

    def test_advance_timeline_uses_visible_mouse_wheel_and_configured_delay(self):
        page = Mock()
        page.evaluate.return_value = {"width": 1000, "height": 600}
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.scroll_step = 240
        browser.scroll_delay_ms = 1500

        self.assertTrue(browser.advance_timeline())

        page.mouse.move.assert_called_once_with(500, 300)
        page.mouse.wheel.assert_called_once_with(0, 240)
        page.wait_for_timeout.assert_called_once_with(1500)

    def test_reset_timeline_to_top_uses_negative_wheel(self):
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.scroll_step = 240
        browser.scroll_delay_ms = 1500

        browser.reset_timeline_to_top()

        page.mouse.wheel.assert_called_once_with(0, -240)
        page.wait_for_timeout.assert_called_once_with(1500)

    def test_missing_day_checkbox_falls_back_to_one_visible_media(self):
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None
        browser._day_locator = Mock(return_value=None)
        browser._select_single_media = Mock(return_value="Foto - fallback")

        self.assertEqual(browser.select_current_day(), "Foto - fallback")
        self.assertEqual(browser.last_selection_kind, "media")

        browser._select_single_media.assert_called_once_with()
        page.goto.assert_not_called()

    def test_missing_day_checkbox_falls_back_to_visible_video(self):
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None
        browser._day_locator = Mock(return_value=None)
        browser._select_single_media = Mock(return_value="Video - fallback")

        self.assertEqual(browser.select_current_day(), "Video - fallback")
        self.assertEqual(browser.last_selection_kind, "media")

        browser._select_single_media.assert_called_once_with()

    def test_viewport_control_records_selector_for_selected_control(self):
        first = Mock()
        first.locator.return_value = first
        first.bounding_box.side_effect = [
            {"x": 0, "y": 100, "width": 20, "height": 20},
        ] * 7
        second = Mock()
        second.locator.return_value = second
        second.bounding_box.side_effect = [
            {"x": 0, "y": 10, "width": 20, "height": 20},
        ] * 7
        first_locator = Mock(count=Mock(return_value=1), nth=Mock(return_value=first))
        second_locator = Mock(count=Mock(return_value=1), nth=Mock(return_value=second))
        page = Mock()
        page.evaluate.return_value = {"width": 800, "height": 600}
        page.locator.side_effect = [first_locator, second_locator]
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None

        selected = browser._first_viewport_control(("first-selector", "second-selector"))

        self.assertIs(selected, second)
        self.assertEqual(browser.last_locator_selector, "second-selector")

    def test_viewport_control_ignores_virtualized_timeout(self):
        page = Mock()
        page.evaluate.return_value = {"width": 800, "height": 600}
        locator = Mock()
        locator.count.return_value = 1
        candidate = Mock()
        candidate.locator.side_effect = lambda _selector: candidate
        candidate.bounding_box.side_effect = TimeoutError("virtualized node")
        locator.nth.return_value = candidate
        page.locator.return_value = locator
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser.diagnostic = None

        self.assertIsNone(browser._first_viewport_control(("[role=checkbox]",)))

    def test_day_selector_targets_current_day_control(self):
        self.assertEqual(
            PlaywrightBrowser.DAY_SELECTORS,
            (
                '[role="checkbox"][aria-label^="Seleziona tutte le foto a partire da:"]',
                '[role="checkbox"][aria-label^="Select all photos starting from:"]',
            ),
        )

    def test_authenticated_page_has_photo_checkbox_selector(self):
        self.assertEqual(
            PlaywrightBrowser.MEDIA_SELECTORS,
            ('[role="checkbox"][aria-checked="false"][aria-label*=" - "]',),
        )

    def test_media_selectors_target_photo_items_not_select_all(self):
        self.assertIn(
            '[role="checkbox"][aria-checked="false"][aria-label*=" - "]',
            PlaywrightBrowser.MEDIA_SELECTORS,
        )
        self.assertNotEqual(
            PlaywrightBrowser.MEDIA_SELECTORS,
            ('[role="checkbox"][aria-checked="false"]',),
        )

    def test_target_absence_requires_positive_trash_feedback(self):
        page = Mock()
        page.get_by_role.return_value.count.return_value = 0
        page.get_by_text.return_value.count.return_value = 0
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertFalse(browser.wait_for_target_absence("Foto - test", timeout_ms=0))

    def test_capture_diagnostics_writes_screenshot_and_html(self):
        page = Mock()
        page.url = "https://photos.google.com/?authuser=secret"
        page.content.return_value = "<html>diagnostic</html>"
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        with tempfile.TemporaryDirectory() as tmp:
            paths = browser.capture_diagnostics(Path(tmp), "layout-error")

            self.assertEqual(paths["html"].read_text(), "<html>diagnostic</html>")
            self.assertTrue(paths["screenshot"].name.endswith(".png"))
            page.screenshot.assert_called_once_with(path=str(paths["screenshot"]), full_page=True)

    def test_selection_uses_fixed_item_locator_and_verifies_selected_items(self):
        self.assertIn(
            '[role="checkbox"][aria-checked="false"][aria-label*=" - "]',
            PlaywrightBrowser.MEDIA_SELECTORS,
        )

    def test_selection_verification_uses_actual_selected_count(self):
        self.assertIn(
            'aria-checked="true"',
            "[role=checkbox][aria-checked=\"true\"]",
        )

    def test_visible_batch_scrolls_for_more_media_until_batch_limit(self):
        class Item:
            def __init__(self, name, owner):
                self.name = name
                self.owner = owner

            def get_attribute(self, name):
                if name in {"data-id", "data-media-key"}:
                    return self.name
                if name == "aria-checked":
                    return "false" if self.name not in self.owner.selected else "true"
                return None

            def click(self):
                self.owner.selected.append(self.name)

        class Page:
            def __init__(self):
                self.stages = [["photo-1"], ["photo-2"], ["photo-3"]]
                self.stage = 0
                self.selected = []
                self.waits = []
                self.mouse = Mock()
                self.mouse.wheel.side_effect = self.advance

            def advance(self, *_args):
                self.stage += 1

            def wait_for_selector(self, *_args, **_kwargs):
                pass

            def evaluate(self, *_args):
                return {"width": 800, "height": 600}

            def wait_for_timeout(self, milliseconds):
                self.waits.append(milliseconds)

            def locator(self, selector):
                if selector == PlaywrightBrowser.MEDIA_SELECTORS[0]:
                    page = self
                    class Media:
                        def count(inner_self):
                            return len(page.stages[page.stage]) if page.stage < len(page.stages) else 0

                        @property
                        def first(inner_self):
                            return Item(page.stages[page.stage][0], page)

                        def nth(inner_self, index):
                            return Item(page.stages[page.stage][index], page)
                    return Media()
                page = self
                class Selected:
                    def count(inner_self):
                        return len(page.selected)
                return Selected()

        browser = object.__new__(PlaywrightBrowser)
        browser.page = Page()

        self.assertEqual(browser.select_visible_batch(3), ["photo-1", "photo-2", "photo-3"])
        self.assertEqual(browser.page.mouse.wheel.call_count, 2)

    def test_visible_batch_uses_existing_manual_selection_before_new_clicks(self):
        page = Mock()
        selected = Mock()
        selected.count.return_value = 3
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertEqual(
            browser.select_visible_batch(100),
            ["already-selected-1", "already-selected-2", "already-selected-3"],
        )
        page.wait_for_selector.assert_called_once()

    def test_visible_batch_returns_verified_partial_selection_when_next_click_stalls(self):
        page = Mock()
        first, second = Mock(), Mock()
        first.get_attribute.side_effect = lambda name: "false" if name == "aria-checked" else "photo-1"
        second.get_attribute.side_effect = lambda name: "false" if name == "aria-checked" else "photo-2"
        media = Mock()
        media.count.side_effect = [2, 2, 2]
        media.nth.side_effect = [first, second]
        selected = Mock()
        selected.count.side_effect = [0, 0, 1, 1, 1, 1]
        page.locator.side_effect = lambda selector: selected if 'aria-checked="true"' in selector else media
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertEqual(browser.select_visible_batch(2), ["photo-1"])
        first.click.assert_called_once_with()
        second.click.assert_called_once_with()

    def test_visible_batch_requires_each_click_to_increment_selection_count(self):
        page = Mock()
        item = Mock()
        item.get_attribute.side_effect = lambda name: "false" if name == "aria-checked" else "photo-1"
        selected = Mock()
        selected.count.return_value = 0
        page.evaluate.return_value = {"width": 800, "height": 600}
        page.mouse = Mock()
        media = Mock()
        media.count.side_effect = [1, 1, 0]
        media.first = item
        media.nth.return_value = item
        def locate(selector):
            return selected if 'aria-checked="true"' in selector else media
        page.locator.side_effect = locate
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser._first_viewport_control = Mock(return_value=item)

        with self.assertRaisesRegex(Exception, "Selection did not increment"):
            browser.select_visible_batch(1)

        item.click.assert_called_once_with()

    def test_selection_handles_locator_that_shrinks_after_each_click(self):
        class Item:
            def __init__(self, name, owner):
                self.name = name
                self.owner = owner

            def get_attribute(self, name):
                if name in {"data-id", "data-media-key"}:
                    return self.name
                if name == "aria-checked":
                    return "false" if self.name not in self.owner.selected else "true"
                return None

            def click(self):
                self.owner.selected.append(self.name)

        class DynamicLocator:
            def __init__(self):
                self.items = ["photo-1", "photo-2", "photo-3"]
                self.selected = []

            def count(self):
                return len(self.items) - len(self.selected)

            @property
            def first(self):
                remaining = [item for item in self.items if item not in self.selected]
                return Item(remaining[0], self)

            def nth(self, index):
                remaining = [item for item in self.items if item not in self.selected]
                return Item(remaining[index], self)

        class Page:
            def __init__(self):
                self.media = DynamicLocator()
                self.waits = []

            def goto(self, *_args, **_kwargs):
                pass

            def wait_for_selector(self, *_args, **_kwargs):
                pass

            def evaluate(self, *_args):
                return {"width": 800, "height": 600}

            def wait_for_timeout(self, milliseconds):
                self.waits.append(milliseconds)

            def locator(self, selector):
                if selector != PlaywrightBrowser.MEDIA_SELECTORS[0]:
                    class Selected:
                        def count(inner_self):
                            return len(self.media.selected)
                    return Selected()
                return self.media

        browser = object.__new__(PlaywrightBrowser)
        browser.page = Page()

        selected = browser.select_visible_batch(3)

        self.assertEqual(selected, ["photo-1", "photo-2", "photo-3"])
        self.assertEqual(browser.page.waits, [250, 150, 150, 150, 750])

    def test_delete_selected_day_marks_missing_selection_without_feedback_as_pending(self):
        page = Mock()
        action = Mock()
        action.count.return_value = 1
        action.first = action
        page.get_by_role.return_value = action
        page.get_by_text.return_value.count.return_value = 0
        selected = Mock()
        selected.count.side_effect = [1, 1, 0]
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertFalse(browser.delete_selected_day())

        action.click.assert_called_once_with()

    def test_delete_selected_day_ignores_hidden_trash_button(self):
        page = Mock()
        hidden = Mock()
        visible = Mock()
        hidden.count.return_value = 1
        hidden.first = hidden
        hidden.first.is_visible.return_value = False
        visible.count.return_value = 1
        visible.first = visible
        visible.first.is_visible.return_value = True
        absent = Mock()
        absent.count.return_value = 0
        dialog = Mock()
        dialog.count.return_value = 0
        dialog.get_by_role.return_value.count.return_value = 0
        page.get_by_role.side_effect = [hidden, visible, absent, absent, dialog]
        selected = Mock()
        selected.count.return_value = 0
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertFalse(browser.delete_selected_day())
        hidden.click.assert_not_called()
        visible.click.assert_called_once_with()

    def test_delete_selected_day_requires_positive_feedback_after_dom_disappears(self):
        page = Mock()
        action = Mock()
        action.count.return_value = 1
        action.first = action
        page.get_by_role.return_value = action
        page.get_by_text.return_value.count.return_value = 0
        selected = Mock()
        selected.count.side_effect = [1] + [0] * 10
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertFalse(browser.delete_selected_day())

    def test_delete_selected_day_accepts_feedback_after_polling(self):
        page = Mock()
        action = Mock()
        action.count.return_value = 1
        action.first = action
        action.first.is_visible.return_value = True
        page.get_by_role.return_value = action
        page.get_by_text.return_value.count.side_effect = [0] * 20 + [1]
        selected = Mock()
        selected.count.side_effect = [1] + [0] * 10
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertTrue(browser.delete_selected_day())

    def test_delete_selected_day_accepts_positive_feedback(self):
        page = Mock()
        action = Mock()
        action.count.return_value = 1
        action.first = action
        page.get_by_role.return_value = action
        page.get_by_text.return_value.count.side_effect = [1]
        selected = Mock()
        selected.count.side_effect = [1, 0]
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertTrue(browser.delete_selected_day())

    def test_delete_selected_day_clicks_confirm_when_second_button_appears(self):
        page = Mock()
        action = Mock()
        confirmation = Mock()
        action.count.return_value = 1
        action.first = action
        dialog = Mock()
        dialog.count.return_value = 1
        dialog.get_by_role.return_value = confirmation
        confirmation.count.return_value = 1
        confirmation.first = confirmation
        page.get_by_role.side_effect = [action, dialog]
        page.get_by_text.return_value.count.return_value = 1
        selected = Mock()
        selected.count.side_effect = [1] + [1] * 10 + [0]
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        browser.delete_selected_day()

        action.click.assert_called_once_with()
        confirmation.click.assert_called_once_with()

    def test_move_to_trash_ignores_hidden_action_button(self):
        page = Mock()
        hidden = Mock()
        visible = Mock()
        hidden.count.return_value = 1
        hidden.first = hidden
        hidden.first.is_visible.return_value = False
        visible.count.return_value = 1
        visible.first = visible
        visible.first.is_visible.return_value = True
        confirmation = Mock()
        confirmation.count.return_value = 0
        feedback = Mock()
        feedback.count.return_value = 0
        page.get_by_role.side_effect = [hidden, visible, confirmation, confirmation]
        page.get_by_text.return_value = feedback
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        with self.assertRaises(CleanerError):
            browser.move_selected_to_trash(["photo-1"])

        hidden.click.assert_not_called()
        visible.click.assert_called_once_with()

    def test_move_to_trash_requires_and_clicks_confirmation(self):
        page = Mock()
        trash = Mock()
        confirmation = Mock()
        page.get_by_role.side_effect = [trash, confirmation]
        page.get_by_text.return_value.count.side_effect = [1]
        trash.count.return_value = 1
        trash.first = trash
        trash.is_visible.return_value = True
        confirmation.count.return_value = 1
        confirmation.last = confirmation
        confirmation.first = confirmation
        confirmation.is_visible.return_value = True
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        browser.move_selected_to_trash(["photo-1"])

        trash.click.assert_called_once_with()
        confirmation.click.assert_called_once_with()

    def test_move_to_trash_rejects_hidden_confirmation_button(self):
        page = Mock()
        trash = Mock()
        confirmation = Mock()
        trash.count.return_value = 1
        trash.first = trash
        trash.first.is_visible.return_value = True
        confirmation.count.return_value = 1
        confirmation.first = confirmation
        confirmation.last = confirmation
        confirmation.first.is_visible.return_value = False
        page.get_by_role.side_effect = [trash, confirmation, confirmation]
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        with self.assertRaises(CleanerError):
            browser.move_selected_to_trash(["photo-1"])

        confirmation.click.assert_not_called()

    def test_move_to_trash_rejects_missing_positive_feedback(self):
        page = Mock()
        trash = Mock()
        confirmation = Mock()
        page.get_by_role.side_effect = [trash, confirmation]
        page.get_by_text.return_value.count.return_value = 0
        trash.count.return_value = 1
        trash.first = trash
        confirmation.count.return_value = 1
        confirmation.last = confirmation
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        with self.assertRaises(CleanerError):
            browser.move_selected_to_trash(["photo-1"])

    def test_trash_feedback_ignores_hidden_text(self):
        page = Mock()
        hidden = Mock()
        hidden.count.return_value = 1
        hidden.first = hidden
        hidden.first.is_visible.return_value = False
        page.get_by_text.return_value = hidden
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertFalse(browser._trash_feedback_visible())

    def test_trash_feedback_accepts_visible_text(self):
        page = Mock()
        feedback = Mock()
        feedback.count.return_value = 1
        feedback.first = feedback
        feedback.first.is_visible.return_value = True
        page.get_by_text.return_value = feedback
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertTrue(browser._trash_feedback_visible())

    def test_wait_for_target_absence_polls_for_positive_feedback_without_clicking(self):
        page = Mock()
        # Five feedback strings are checked before each polling wait.
        page.get_by_text.return_value.count.side_effect = [0, 0, 0, 0, 0, 1]
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        self.assertTrue(browser.wait_for_target_absence("Foto - 2 ago", timeout_ms=1000))
        page.wait_for_timeout.assert_called_once_with(500)
        page.get_by_role.assert_not_called()

    def test_wait_for_current_timeline(self):
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        browser.wait_for_current_timeline()

        page.wait_for_timeout.assert_called_once_with(250)

    def test_recover_preserves_timeline_and_dismisses_known_dialogs(self):
        page = Mock()
        page.url = "https://photos.google.com/"
        page.locator.return_value.count.return_value = 0
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        browser.recover()

        page.reload.assert_not_called()
        page.wait_for_timeout.assert_called_once_with(500)


if __name__ == "__main__":
    unittest.main()
