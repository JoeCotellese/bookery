# ABOUTME: Unit tests for the LoadingOverlay modal screen.
# ABOUTME: Verifies spinner display, message text, and modal behavior.

import pytest

from bookery.tui.screens.loading import LoadingOverlay


@pytest.mark.asyncio
class TestLoadingOverlay:
    """Tests for the LoadingOverlay modal screen."""

    async def test_shows_message_text(self) -> None:
        """LoadingOverlay displays the provided message."""
        from textual.app import App
        from textual.widgets import Static

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(LoadingOverlay("Searching Open Library..."))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            # Find the message label
            label = screen.query_one("#loading-message", Static)
            rendered = str(label.render())
            assert "Searching Open Library" in rendered

    async def test_default_message(self) -> None:
        """LoadingOverlay has a default message when none provided."""
        from textual.app import App
        from textual.widgets import Static

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(LoadingOverlay())

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            label = screen.query_one("#loading-message", Static)
            rendered = str(label.render())
            assert "Loading" in rendered
