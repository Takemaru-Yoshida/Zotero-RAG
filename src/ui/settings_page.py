"""Settings: Zotero location, search defaults, AI features, system info."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from ..embedding_models import MODEL_PROFILES
from ..zotero_client import ZoteroClient
from .widgets import Card, PageHeader, button, label, scrollable


class SettingsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        config = app.services.config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(PageHeader("設定"))
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(0, 0, 8, 0)
        box.setSpacing(14)
        body.setMaximumWidth(760)
        outer.addWidget(scrollable(body), 1)

        # -- Zotero ----------------------------------------------------------- #
        zotero = Card()
        zotero.box.addWidget(label("Zotero", "h2"))
        zotero.box.addWidget(label(
            "ライブラリは読み取り専用で同期します。Zotero のデータベースには"
            "一切書き込みません。", "muted"))
        row = QHBoxLayout()
        self.data_dir = QLineEdit(config.zotero_data_dir)
        row.addWidget(self.data_dir, 1)
        row.addWidget(button("参照…", "outline", self._browse))
        zotero.box.addLayout(row)
        box.addWidget(zotero)

        # -- search ----------------------------------------------------------- #
        search = Card()
        search.box.addWidget(label("検索", "h2"))
        form = QFormLayout()
        self.top_k = QSpinBox()
        self.top_k.setRange(1, 50)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 1.0)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(2)
        self.neighbours = QSpinBox()
        self.neighbours.setRange(1, 10)
        form.addRow("意味検索の表示件数", self.top_k)
        form.addRow("意味検索の最小類似度", self.threshold)
        form.addRow("関連グラフの近傍数（内容の類似）", self.neighbours)
        search.box.addLayout(form)
        box.addWidget(search)

        # -- embedding model -------------------------------------------------- #
        model = Card()
        model.box.addWidget(label("Embedding モデル", "h2"))
        model.box.addWidget(label(
            "すべて無料で、この Mac の中だけで動作します。変更すると初回に"
            "モデルをダウンロードし、アプリの再起動後に全文献を再インデックス"
            "します（最小類似度もモデルの既定値に戻ります）。", "muted"))
        self.model = QComboBox()
        for profile in MODEL_PROFILES.values():
            self.model.addItem(profile.label, profile.name)
        if config.embedding_model not in MODEL_PROFILES:
            self.model.addItem(config.embedding_model, config.embedding_model)
        model.box.addWidget(self.model)
        box.addWidget(model)

        # -- AI features ------------------------------------------------------ #
        ai = Card()
        ai.box.addWidget(label("AI 機能", "h2"))
        ai.box.addWidget(label("マーカー・ファクトチェックの動作", "muted"))
        self.auto_mark = QCheckBox("文献を開いたとき、重要文に自動でマーカーを付ける")
        self.strict = QCheckBox("ファクトチェックで「一部支持」も要確認として扱う")
        ai.box.addWidget(self.auto_mark)
        ai.box.addWidget(self.strict)
        box.addWidget(ai)

        actions = QHBoxLayout()
        actions.addWidget(button("保存", on_click=self._save))
        self.saved = label("", "muted")
        actions.addWidget(self.saved, 1)
        box.addLayout(actions)

        # -- system info ------------------------------------------------------ #
        system = Card()
        system.box.addWidget(label("システム情報", "h2"))
        self.info = QFormLayout()
        self.info_values: dict[str, object] = {}
        for name in ("Embedding モデル", "判定モデル（NLI）", "Zotero 接続",
                     "登録文献", "一節（ベクトル）", "インデックス", "データ保存先"):
            value = label("", selectable=True)
            self.info_values[name] = value
            self.info.addRow(label(name, "muted", wrap=False), value)
        system.box.addLayout(self.info)
        box.addWidget(system)
        box.addStretch(1)

    def refresh(self) -> None:
        s = self.app.services
        config = s.config
        self.data_dir.setText(config.zotero_data_dir)
        self.top_k.setValue(config.top_k)
        self.threshold.setValue(config.similarity_threshold)
        self.neighbours.setValue(config.graph_neighbors)
        self.model.setCurrentIndex(max(0, self.model.findData(
            config.pending_embedding_model or config.embedding_model)))
        self.auto_mark.setChecked(config.auto_mark)
        self.strict.setChecked(config.strict_partial)
        self.saved.setText("")
        values = {
            "Embedding モデル": f"{config.embedding_model}（{config.embedding_dim} 次元）",
            "判定モデル（NLI）": config.nli_model,
            "Zotero 接続": s.indexer.client.backend_name(),
            "登録文献": f"{s.store.n_papers} 件",
            "一節（ベクトル）": f"{s.store.n_vectors} 件",
            "インデックス": s.store.index_kind(),
            "データ保存先": str(config.db_path.parent),
        }
        for name, text in values.items():
            self.info_values[name].setText(text)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Zotero データフォルダ", self.data_dir.text())
        if path:
            self.data_dir.setText(path)

    def _save(self) -> None:
        s = self.app.services
        config = s.config
        dir_changed = self.data_dir.text().strip() != config.zotero_data_dir
        config.zotero_data_dir = self.data_dir.text().strip()
        config.top_k = self.top_k.value()
        config.similarity_threshold = self.threshold.value()
        config.graph_neighbors = self.neighbours.value()
        config.auto_mark = self.auto_mark.isChecked()
        config.strict_partial = self.strict.isChecked()
        # Applied at the next start (see ``Config.load``); empty = no change.
        picked = self.model.currentData()
        config.pending_embedding_model = (
            "" if picked == config.embedding_model else picked)
        model_changed = bool(config.pending_embedding_model)
        config.save()
        if dir_changed:
            s.indexer.client = ZoteroClient(config)
        s.invalidate_graph()
        self.refresh()
        note = ""
        if model_changed:
            # This session keeps the model its index was built with.
            note = "アプリを再起動すると、新しいモデルで再インデックスします。"
        elif dir_changed:
            note = "「新着を確認」で新しいフォルダを同期してください。"
        self.saved.setText("保存しました。" + note)
