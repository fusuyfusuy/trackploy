"""Notification adapters: Rich terminal feed, OSC terminal desktop notifications, and desktop popups."""

from trackploy.notifiers.console import ConsoleNotifier
from trackploy.notifiers.desktop import DesktopNotifier
from trackploy.notifiers.osc import OscNotifier

__all__ = ["ConsoleNotifier", "DesktopNotifier", "OscNotifier"]
