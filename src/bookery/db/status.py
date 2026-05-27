# ABOUTME: Read-status constants and dataclasses shared across CLI, catalog, and web.
# ABOUTME: Integer mapping mirrors KoboContentRow.read_status so no remap happens between layers.

from dataclasses import dataclass

STATUS_UNREAD = 0
STATUS_READING = 1
STATUS_FINISHED = 2

_STATUS_NAMES = {
    STATUS_UNREAD: "Unread",
    STATUS_READING: "Reading",
    STATUS_FINISHED: "Finished",
}


def status_name(status: int) -> str:
    """Return the human-readable label for a status integer.

    Falls back to ``"Unknown"`` on values outside the canonical set so a
    future schema addition never crashes a render path. Callers that want
    strict checking should compare against the ``STATUS_*`` constants.
    """
    return _STATUS_NAMES.get(status, "Unknown")


@dataclass(frozen=True, slots=True)
class BookStatus:
    """A row from the ``book_status`` table — catalog-side read state.

    This is the truth that the user manipulates via ``bookery mark finished/reading/unread``
    and that the web detail page surfaces. The device-side mirror lives in
    ``DeviceReadState`` and is populated by the P1a pull.
    """

    book_id: int
    status: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class DeviceReadState:
    """A row from ``device_read_state`` joined with ``devices``.

    Carries the device label/kind so CLI and web can render
    "Kobo (Mr. C's Libra)" without a second lookup.
    """

    device_id: int
    device_kind: str
    device_label: str | None
    book_id: int
    read_status: int
    percent_read: float | None
    last_read_at: str | None
    status_updated_at: str


@dataclass(frozen=True, slots=True)
class PushCandidate:
    """A book that *might* need its status pushed to the device.

    Produced by ``LibraryCatalog.list_push_candidates`` — one row per
    (device, book) with both a catalog status and a known on-device file.
    The orchestrator compares ``catalog_updated_at`` against
    ``device_status_updated_at`` to decide whether this candidate actually
    becomes a push, a no-op, or a pull-direction merge.
    """

    book_id: int
    remote_path: str
    catalog_status: int
    catalog_updated_at: str
    device_status_updated_at: str | None
