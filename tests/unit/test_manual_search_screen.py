# ABOUTME: Unit tests for the ManualSearchModal.
# ABOUTME: Verifies input field, submit behavior, and escape cancel.

import pytest

from bookery.tui.screens.manual import ManualSearchModal


@pytest.mark.asyncio
class TestManualSearchModal:
    """Tests for the ManualSearchModal."""

    async def test_has_input_field(self) -> None:
        """Modal contains an Input widget."""
        from textual.app import App
        from textual.widgets import Input

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(ManualSearchModal())

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            inputs = screen.query(Input)
            assert len(inputs) == 1

    async def test_escape_cancels(self) -> None:
        """Pressing Escape dismisses with None."""
        from textual.app import App

        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ManualSearchModal(),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: str | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert result is None

    async def test_submit_dismisses_with_query(self) -> None:
        """Typing text and pressing Enter dismisses with the query string."""
        from textual.app import App
        from textual.widgets import Input

        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ManualSearchModal(),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: str | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            input_widget = screen.query_one(Input)
            input_widget.value = "Italo Calvino"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

        assert result == "Italo Calvino"
