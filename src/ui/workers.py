"""Background execution so the window never freezes.

``run_task`` runs any callable on a ``QThread`` and delivers its result (or
error message) back on the GUI thread through signals.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)


class Task(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str, float)

    def __init__(self, fn: Callable[..., Any], with_progress: bool,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._fn = fn
        self._with_progress = with_progress

    def run(self) -> None:
        try:
            if self._with_progress:
                result = self._fn(lambda msg, frac: self.progress.emit(msg, frac))
            else:
                result = self._fn()
        except Exception as e:  # noqa: BLE001 - every failure goes to the UI
            logger.exception("Background task failed")
            self.failed.emit(str(e) or type(e).__name__)
            return
        self.done.emit(result)


def run_task(owner: QObject, fn: Callable[..., Any],
             on_done: Callable[[Any], None],
             on_error: Optional[Callable[[str], None]] = None,
             on_progress: Optional[Callable[[str, float], None]] = None) -> Task:
    """Run ``fn`` in the background and call ``on_done(result)`` when finished.

    When ``on_progress`` is given, ``fn`` receives a ``progress(msg, fraction)``
    callback as its only argument.
    """
    task = Task(fn, with_progress=on_progress is not None, parent=owner)
    tasks: list[Task] = owner.__dict__.setdefault("_tasks", [])
    tasks.append(task)   # keep a reference until the thread has finished
    task.done.connect(on_done)
    if on_error:
        task.failed.connect(on_error)
    if on_progress:
        task.progress.connect(on_progress)
    task.finished.connect(lambda: task in tasks and tasks.remove(task))
    task.start()
    return task
