"""OSC 9 / OSC 777 and Terminal Bell notification adapter."""

import sys
from trackploy.models import TrackployEvent


class OscNotifier:
    """Emits ANSI OSC escape codes to trigger native terminal desktop notifications."""

    def __init__(self, enable_bell: bool = True, enable_osc: bool = True):
        self.enable_bell = enable_bell
        self.enable_osc = enable_osc

    def notify(self, event: TrackployEvent) -> None:
        """Send OSC escape sequences and optional bell chime."""
        if not sys.stdout.isatty():
            return

        title = event.title.replace(";", " ")
        summary = event.summary.replace(";", " ")

        if self.enable_osc:
            # OSC 9: \033]9;<message>\007 (iTerm2, WezTerm, Ghostty)
            msg_osc9 = f"\033]9;[{event.target}] {title} - {summary}\007"
            # OSC 777: \033]777;notify;<title>;<message>\007 (Ghostty, rxvt, Kitty)
            msg_osc777 = f"\033]777;notify;{title};{summary}\007"

            sys.stdout.write(msg_osc9 + msg_osc777)
            sys.stdout.flush()

        if self.enable_bell and (event.is_critical or event.is_success):
            sys.stdout.write("\a")
            sys.stdout.flush()
