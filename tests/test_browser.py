import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from googlephotos_cleaner.browser import PlaywrightBrowser, is_authenticated_url


class BrowserDiagnosticsTests(unittest.TestCase):
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
        self.assertEqual(page.mouse.move.call_count, 2)
        first.hover.assert_not_called()
        second.hover.assert_not_called()
        hidden.hover.assert_not_called()

    def test_day_selection_falls_back_to_single_media_when_day_control_stays_unselected(self):
        control = Mock()
        control.get_attribute.side_effect = ["Seleziona tutte le foto a partire da: dom 2 ago", "false"]
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser._day_locator = Mock(return_value=control)
        browser._select_single_media_for_day = Mock(return_value="Foto - Verticale - 2 ago")

        result = browser.select_current_day()

        self.assertEqual(result, "Foto - Verticale - 2 ago")
        browser._select_single_media_for_day.assert_called_once_with(control)

    def test_day_scan_does_not_navigate_to_library(self):
        page = Mock()
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page
        browser._day_locator = Mock(return_value=None)
        browser._select_single_media = Mock(return_value=None)

        self.assertIsNone(browser.select_current_day())

        page.goto.assert_not_called()

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
        selected = Mock()
        selected.count.side_effect = [1] + [1] * 10 + [0]
        page.locator.return_value = selected
        browser = object.__new__(PlaywrightBrowser)
        browser.page = page

        browser.delete_selected_day()

        action.click.assert_called_once_with()
        confirmation.click.assert_called_once_with()

    def test_move_to_trash_requires_and_clicks_confirmation(self):
        page = Mock()
        trash = Mock()
        confirmation = Mock()
        page.get_by_role.side_effect = [trash, confirmation]
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
