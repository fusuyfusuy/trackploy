"""Desktop notifications via notify-send CLI."""

import asyncio
import shutil
from trackploy.models import TrackployEvent


class DesktopNotifier:
    """Invokes system notify-send if available."""

    def __init__(self, enable_desktop: bool = True):
        self.enable_desktop = enable_desktop
        self._notify_send = shutil.which("notify-send")

    async def notify(self, event: TrackployEvent) -> None:
        """Trigger desktop notification asynchronously."""
        if not self.enable_desktop or not self._notify_send:
            return

        urgency = "critical" if event.is_critical else "normal"
        icon = "dialog-error" if event.is_critical else "dialog-information"

        try:
            proc = await asyncio.create_subprocess_exec(
                self._notify_send,
                "-u", urgency,
                "-i", icon,
                "-a", "Trackploy",
                event.title,
                event.summary,
            )
            await asyncio.wait_for(proc.communicate(), timeout=3.0)
        except Exception:
            pass
