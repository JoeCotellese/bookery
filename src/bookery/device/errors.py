# ABOUTME: Typed exceptions for the device sync subsystem (Kobo first).
# ABOUTME: Each carries an exit_code class attribute the CLI maps to process exit status.


class DeviceError(Exception):
    """Base class for device sync errors."""

    exit_code: int = 1


class KepubifyMissing(DeviceError):
    exit_code = 3

    def __init__(self) -> None:
        super().__init__(
            "kepubify is not on PATH. Install it (e.g. `brew install kepubify`) "
            "and re-run."
        )


class KepubifyFailed(DeviceError):
    exit_code = 1

    def __init__(self, stderr: str) -> None:
        super().__init__(f"kepubify failed: {stderr}".rstrip())
        self.stderr = stderr


class KoboNotMounted(DeviceError):
    exit_code = 1

    def __init__(self) -> None:
        super().__init__(
            "No mounted Kobo detected. Pass --target /path/to/mount to override."
        )
