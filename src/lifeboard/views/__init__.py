"""Top-level pages shown in the main window's QStackedWidget."""

from __future__ import annotations

from .dashboard import DashboardView
from .library import LibraryView
from .settings import SettingsView
from .workout import WorkoutView

__all__ = ["DashboardView", "WorkoutView", "LibraryView", "SettingsView"]
