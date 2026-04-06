# ABOUTME: Unit tests for the ConfirmScreen.
# ABOUTME: Verifies full diff display, accept/back/cancel behavior, and data loss warnings.

import pytest

from bookery.metadata.types import BookMetadata
from bookery.tui.screens.confirm import ConfirmScreen
from bookery.tui.widgets.metadata_diff import MetadataDiff


@pytest.mark.asyncio
class TestConfirmScreen:
    """Tests for the ConfirmScreen."""

    async def test_shows_full_diff(self) -> None:
        """Screen contains a MetadataDiff widget in full mode."""
        from textual.app import App

        current = BookMetadata(title="Original", isbn="111")
        proposed = BookMetadata(title="Updated", isbn="222")

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(ConfirmScreen(current, proposed))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            diff = screen.query_one(MetadataDiff)
            assert diff is not None
            rendered = str(diff.render())
            # Full mode should show all fields including unchanged
            assert "Title" in rendered

    async def test_accept_dismisses_with_true(self) -> None:
        """Pressing 'y' dismisses the screen with True."""
        from textual.app import App

        current = BookMetadata(title="Original")
        proposed = BookMetadata(title="Updated")
        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ConfirmScreen(current, proposed),
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

    async def test_back_dismisses_with_false(self) -> None:
        """Pressing 'b' dismisses the screen with False (back to candidates)."""
        from textual.app import App

        current = BookMetadata(title="Original")
        proposed = BookMetadata(title="Updated")
        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ConfirmScreen(current, proposed),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: bool | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()

        assert result is False

    async def test_escape_dismisses_with_none(self) -> None:
        """Pressing Escape dismisses with None (cancel entirely)."""
        from textual.app import App

        current = BookMetadata(title="Original")
        proposed = BookMetadata(title="Updated")
        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    ConfirmScreen(current, proposed),
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

        assert result is None

    async def test_data_loss_warning_visible(self) -> None:
        """When proposed clears an existing field, warning marker is shown."""
        from textual.app import App

        current = BookMetadata(title="Test", publisher="Einaudi")
        proposed = BookMetadata(title="Test", publisher=None)

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(ConfirmScreen(current, proposed))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            diff = screen.query_one(MetadataDiff)
            rendered = str(diff.render())
            assert "[-]" in rendered
