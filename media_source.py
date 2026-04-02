"""MediaSource for browsing PNZEO camera SD card recordings."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import PNZEOCoordinator

_LOGGER = logging.getLogger(__name__)

# Pagination limit for file list queries
FILE_LIST_PAGE_SIZE = 20


async def async_get_media_source(hass: HomeAssistant) -> PNZEOMediaSource:
    """Set up PNZEO media source."""
    return PNZEOMediaSource(hass)


class PNZEOMediaSource(MediaSource):
    """Provide PNZEO camera SD recordings as media source."""

    name = "PNZEO Camera Recordings"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize PNZEO media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    def _get_coordinator(self) -> PNZEOCoordinator | None:
        """Get the first available coordinator."""
        for entry_data in self.hass.data.get(DOMAIN, {}).values():
            if isinstance(entry_data, PNZEOCoordinator):
                return entry_data
        return None

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable/downloadable URL.

        Item identifier format: "file|{filename}"
        The camera serves files via CGI, but since we're over PPPP (UDP),
        we cannot provide a direct HTTP URL. Instead, we use the PPPP client
        to fetch the file data and serve it through HA's built-in media proxy.

        For now, raise Unresolvable since PPPP file download requires
        a streaming DRW protocol implementation. Users can note the filename
        for manual retrieval. Future: implement DRW file streaming.
        """
        coordinator = self._get_coordinator()
        if coordinator is None:
            raise Unresolvable("No PNZEO camera configured")

        identifier = item.identifier
        if not identifier or not identifier.startswith("file|"):
            raise Unresolvable(f"Invalid media identifier: {identifier}")

        filename = identifier.split("|", 1)[1]

        # PPPP cameras don't have HTTP servers -- files are accessed via
        # DRW protocol over UDP. For now, we provide browse-only functionality.
        # The file list shows what's recorded; actual download requires
        # DRW file streaming which is complex and deferred.
        raise Unresolvable(
            f"Direct file download not yet supported for PPPP cameras. "
            f"Recording: {filename}"
        )

    async def async_browse_media(
        self, item: MediaSourceItem
    ) -> BrowseMediaSource:
        """Browse SD card recordings.

        Navigation tree:
          Root -> Months (from calendar) -> Days -> Files

        Identifier format:
          "" or None -> root (show available months)
          "month|YYYY-MM" -> show days with recordings in that month
          "day|YYYY-MM-DD" -> show recording files for that day
        """
        coordinator = self._get_coordinator()
        if coordinator is None:
            return self._build_empty_root("No camera connected")

        identifier = item.identifier if item.identifier else ""

        if not identifier:
            return await self._browse_root(coordinator)

        parts = identifier.split("|", 1)
        browse_type = parts[0]
        browse_value = parts[1] if len(parts) > 1 else ""

        if browse_type == "month":
            return await self._browse_month(coordinator, browse_value)
        elif browse_type == "day":
            return await self._browse_day(coordinator, browse_value)

        return self._build_empty_root("Unknown browse path")

    async def _browse_root(
        self, coordinator: PNZEOCoordinator
    ) -> BrowseMediaSource:
        """Show available months (current month and 2 previous)."""
        children = []
        now = datetime.now()

        for i in range(3):  # Current month + 2 previous
            dt = now - timedelta(days=i * 30)
            month_str = dt.strftime("%Y-%m")
            month_label = dt.strftime("%B %Y")

            # Query calendar to see if month has recordings
            resp = await coordinator.device.client.get_record_calendar(month_str)
            has_recordings = False
            if resp and resp.get("success"):
                # Calendar response contains a bitmask or day count
                calendar_data = resp.get("json", {})
                if calendar_data:
                    has_recordings = True

            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"month|{month_str}",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.VIDEO,
                    title=month_label,
                    can_play=False,
                    can_expand=True,
                    thumbnail=None,
                )
            )

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier="",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.VIDEO,
            title="SD Card Recordings",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _browse_month(
        self, coordinator: PNZEOCoordinator, month: str
    ) -> BrowseMediaSource:
        """Show days with recordings in a given month.

        Uses get_record_calendar to get bitmask of days with recordings.
        """
        children = []
        resp = await coordinator.device.client.get_record_calendar(month)

        if resp and resp.get("success"):
            # Parse calendar bitmask -- bit N set means day N has recordings
            # Camera returns calendar as integer bitmask or day-indexed fields
            raw_calendar = resp.get("json", resp)

            # Try bitmask format: "calendar" key with integer value
            bitmask = 0
            if isinstance(raw_calendar, dict):
                bitmask = int(raw_calendar.get(
                    "calendar", raw_calendar.get("result", 0)
                ))
            elif isinstance(raw_calendar, int):
                bitmask = raw_calendar

            if bitmask > 0:
                for day in range(1, 32):
                    if bitmask & (1 << day):
                        day_str = f"{month}-{day:02d}"
                        children.append(
                            BrowseMediaSource(
                                domain=DOMAIN,
                                identifier=f"day|{day_str}",
                                media_class=MediaClass.DIRECTORY,
                                media_content_type=MediaType.VIDEO,
                                title=f"Day {day}",
                                can_play=False,
                                can_expand=True,
                            )
                        )
            else:
                # Fallback: if no bitmask, show all days of the month
                # and let file list queries determine if recordings exist
                try:
                    year, mon = month.split("-")
                    now = datetime.now()
                    max_day = min(
                        int(now.day) if month == now.strftime("%Y-%m") else 28,
                        28,
                    )
                    for d in range(max_day, 0, -1):
                        day_str = f"{month}-{d:02d}"
                        children.append(
                            BrowseMediaSource(
                                domain=DOMAIN,
                                identifier=f"day|{day_str}",
                                media_class=MediaClass.DIRECTORY,
                                media_content_type=MediaType.VIDEO,
                                title=f"Day {d}",
                                can_play=False,
                                can_expand=True,
                            )
                        )
                except (ValueError, IndexError):
                    pass

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"month|{month}",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.VIDEO,
            title=f"Recordings - {month}",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _browse_day(
        self, coordinator: PNZEOCoordinator, day: str
    ) -> BrowseMediaSource:
        """Show recording files for a specific day.

        Uses get_record_file_list with pagination.
        """
        children = []

        # Query file list for the day
        resp = await coordinator.device.client.get_record_file_list(
            start_date=day,
            end_date=day,
            rec_type=0,
            start_idx=0,
            count=FILE_LIST_PAGE_SIZE,
        )

        if resp and resp.get("success"):
            file_data = resp.get("json", resp)

            # Parse file entries from response
            # Expected format varies by camera firmware:
            # Option A: json with "files" array
            # Option B: key-value with file[0], file[1] etc
            files: list[dict[str, Any]] = []

            if isinstance(file_data, dict):
                # Try JSON array format
                if "files" in file_data:
                    files = file_data["files"]
                elif "filelist" in file_data:
                    files = file_data["filelist"]
                else:
                    # Try indexed key format: file_name[0], file_size[0], etc
                    idx = 0
                    while True:
                        name_key = f"file_name[{idx}]"
                        alt_name = f"fileName[{idx}]"
                        fname = (
                            file_data.get(name_key)
                            or file_data.get(alt_name)
                            or resp.get(name_key)
                            or resp.get(alt_name)
                        )
                        if not fname:
                            break
                        size_key = f"file_size[{idx}]"
                        alt_size = f"fileSize[{idx}]"
                        fsize = (
                            file_data.get(size_key)
                            or file_data.get(alt_size)
                            or resp.get(size_key)
                            or resp.get(alt_size)
                            or "0"
                        )
                        files.append({"name": fname, "size": fsize})
                        idx += 1

            for f in files:
                if isinstance(f, dict):
                    fname = f.get("name", f.get("fileName", "unknown"))
                    fsize = f.get("size", f.get("fileSize", 0))
                elif isinstance(f, str):
                    fname = f
                    fsize = 0
                else:
                    continue

                # Format size for display
                try:
                    size_mb = int(fsize) / (1024 * 1024)
                    size_str = f" ({size_mb:.1f} MB)" if size_mb > 0 else ""
                except (ValueError, TypeError):
                    size_str = ""

                children.append(
                    BrowseMediaSource(
                        domain=DOMAIN,
                        identifier=f"file|{fname}",
                        media_class=MediaClass.VIDEO,
                        media_content_type=MediaType.VIDEO,
                        title=f"{fname}{size_str}",
                        can_play=False,  # Cannot play via PPPP directly
                        can_expand=False,
                    )
                )

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"day|{day}",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.VIDEO,
            title=f"Recordings - {day}",
            can_play=False,
            can_expand=True,
            children=children,
        )

    def _build_empty_root(self, message: str) -> BrowseMediaSource:
        """Build empty root with message."""
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier="",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.VIDEO,
            title=message,
            can_play=False,
            can_expand=False,
            children=[],
        )
