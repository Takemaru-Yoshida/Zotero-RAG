"""Question asked when the app starts for the first time: which embedding
model to use.

The two Qwen3-Embedding sizes trade search quality against download size,
memory and indexing time, and changing the model later means indexing the
whole library again, so the choice is made before the first index is built.
"""
from __future__ import annotations

import json
import logging
import os

from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QRadioButton, QVBoxLayout, QWidget,
)

from ..config import Config
from ..embedding_models import (DEFAULT_MODEL, FIRST_RUN_MODELS, LEGACY_MODEL,
                                LIGHT_MODEL, recommended_model)
from .theme import C
from .widgets import button, label

logger = logging.getLogger(__name__)

# name -> (title, what the user gets)
_CHOICES = {
    DEFAULT_MODEL: (
        "Qwen3-Embedding-4B（高精度）",
        "検索の精度を優先します。ダウンロード約 8 GB、メモリ 16 GB 以上を推奨。"
        "文献 100 件の初回インデックスに 1 時間ほどかかります。"),
    LIGHT_MODEL: (
        "Qwen3-Embedding-0.6B（軽量）",
        "速さと軽さを優先します。ダウンロード約 1.2 GB で、メモリが 16 GB に"
        "満たない Mac 向けです。文献 100 件の初回インデックスは 10 分ほどです。"),
}


def memory_gb() -> float:
    """Installed memory in GB; 0 when the system does not tell."""
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
    except (ValueError, OSError, AttributeError):
        return 0.0


def needs_model_choice(config: Config) -> bool:
    """Whether to ask: only before the first index exists.

    An install that already has an index (built from the command line, or
    by a version without this question) keeps its model without being asked.
    """
    if config.model_chosen:
        return False
    if not config.meta_path.exists():
        return True
    # Settings without an answer next to an index (lost or unreadable
    # config.json): go on with the model the index was built with.
    built_with = _index_model(config)
    if built_with and built_with != config.embedding_model:
        config.use_model(built_with)
    config.model_chosen = True
    _save(config)
    return False


def _index_model(config: Config) -> str:
    """Model the index on disk was built with; "" when it cannot be read."""
    try:
        data = json.loads(config.meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("embedding_model") or LEGACY_MODEL)


def choose_model(config: Config, parent: QWidget | None = None) -> bool:
    """Ask for the model and store the answer; ``False`` if the dialog was
    closed without one (nothing is changed then)."""
    dialog = ModelChoiceDialog(memory_gb(), parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    config.use_model(dialog.model())
    config.pending_embedding_model = ""
    config.model_chosen = True
    _save(config)
    return True


def _save(config: Config) -> None:
    try:
        config.save()
    except OSError as e:
        # The choice still holds for this session; it is asked again later.
        logger.warning("Could not save the settings: %s", e)


class ModelChoiceDialog(QDialog):
    def __init__(self, memory: float, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Zotero-RAG — Embedding モデルの選択")
        self.setStyleSheet(f"QDialog {{ background: {C.bg}; }}")
        self.setMinimumWidth(560)
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 22, 24, 18)
        box.setSpacing(10)
        box.addWidget(label("使用する Embedding モデルを選んでください", "h2"))
        box.addWidget(label(
            "意味検索に使うモデルです。どちらも無料で、この Mac の中だけで"
            "動作します。選んだモデルは最初の同期のときにダウンロードされます。",
            "muted"))

        suggested = recommended_model(memory) if memory else DEFAULT_MODEL
        self.group = QButtonGroup(self)
        self._names: list[str] = []
        for name in FIRST_RUN_MODELS:
            title, detail = _CHOICES[name]
            if memory and name == suggested:
                title += f"  — この Mac（メモリ {memory:.0f} GB）におすすめ"
            radio = QRadioButton(title)
            radio.setChecked(name == suggested)
            self.group.addButton(radio, len(self._names))
            self._names.append(name)
            box.addSpacing(6)
            box.addWidget(radio)
            note = label(detail, "muted")
            note.setContentsMargins(24, 0, 0, 0)
            box.addWidget(note)

        box.addSpacing(8)
        box.addWidget(label(
            "あとから「設定」で変更できます。変更すると全文献を再インデックス"
            "します。", "muted"))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("終了", "outline", self.reject))
        start = button("このモデルで始める", on_click=self.accept)
        start.setDefault(True)
        row.addWidget(start)
        box.addLayout(row)

    def model(self) -> str:
        return self._names[self.group.checkedId()]
