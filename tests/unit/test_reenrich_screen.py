# ABOUTME: Unit tests for the ReEnrichConfirmModal.
# ABOUTME: Verifies confirmation and cancel behavior for already-enriched books.

import pytest

from bookery.tui.screens.reenrich import ReEnrichConfirmModal


@pytest.mark.asyncio
class TestReEnrichConfirmModal:
    """Tests for the ReEnrichConfirmModal."""

    async def test_confirm_dismisses_with_true(self) -> None:
        """Pressing 'y' dismisses with True (proceed)."""
        from textual.app import App

        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ReEnrichConfirmModal(),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: bool | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()

        assert result is True

    async def test_cancel_dismisses_with_false(self) -> None:
        """Pressing Escape dismisses with False (cancel)."""
        from textual.app import App

        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ReEnrichConfirmModal(),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: bool | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert result is False

    async def test_n_dismisses_with_false(self) -> None:
        """Pressing 'n' dismisses with False (cancel)."""
        from textual.app import App

        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ReEnrichConfirmModal(),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: bool | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

        assert result is False

    async def test_shows_warning_message(self) -> None:
        """Modal displays a message about existing enrichment."""
        from textual.app import App
        from textual.widgets import Static

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(ReEnrichConfirmModal())

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            label = screen.query_one("#reenrich-message", Static)
            rendered = str(label.render())
            assert "already" in rendered.lower() or "enriched" in rendered.lower()
