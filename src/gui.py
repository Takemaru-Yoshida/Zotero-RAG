"""GUI entry point.

The interface now lives in the ``src.ui`` package (dashboard, library,
document viewer, semantic search, citation fact-check, relation graph and
settings). This module is kept so that ``app.py`` and the ``.app`` launcher
keep working unchanged.
"""
from __future__ import annotations

from .ui.main_window import MainWindow, run

__all__ = ["MainWindow", "run"]
