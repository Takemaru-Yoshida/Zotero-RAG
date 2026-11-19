# Task Plan: DocMeg (仮/) の機能を Zotero-RAG デスクトップアプリへ移植

## Goal
`仮/` の Web UI（モック動作）が持つ機能を、PyQt6 デスクトップアプリ上で実データ
（Zotero ライブラリ + 追加 PDF）に対して動作させる。`.app` ランチャーは変更しない。

## Decisions Made (ユーザー確認済み 2026-11-13)
- UI: PyQt6 で再実装（WebView は使わない）
- ファクトチェック判定: ローカル NLI モデル（多言語 mDeBERTa-xnli、CPU 実行）
- 文献ソース: Zotero 同期 + アプリへの PDF 直接追加
- 移植しない: ランディング / ログイン / サインアップ / プロフィール（ローカルアプリのため不要）

## Design
- チャンクを「文単位で詰めた一節」(既定 256 tokens, 重複なし) に変更し、本文とページ番号を
  SQLite (`library.db`) に保存 → 一節単位の検索・ビューア・マーカーが可能になる。
  既存インデックスは schema 版数の不一致で自動的に再構築される。
- AI 重要文マーカー: LLM なしの抽出型（文献ベクトル重心 + 要旨との類似度）。初回表示時に計算しキャッシュ。
- 引用関係: 本文（参考文献リスト）に他文献のタイトルが現れるかで検出。類似: 文献ベクトルの相互 kNN。
- 参考文献リスト・PDF 抽出ノイズの一節は検索/マーカー/根拠から除外（`row_meta[].ref`、判定規則は
  `REF_RULE` で版管理し、保存済み本文から再判定）。
- モデルはキャッシュがあればオフラインで読み込む（Hub へ通信しない）。

## Phases
- [x] P0-1 調査（仮/ と既存 src/ の把握、Zotero DB スキーマ確認）
- [x] P0-2 バックエンド: chunker / library_db / zotero_client 拡張 / vector_store / indexer / local_library
- [x] P0-3 バックエンド: search(一節) / highlights / nli / factcheck / graph / services
- [x] P0-4 UI: theme / widgets / main_window / 7 画面
- [x] P0-5 CLI 拡張（--factcheck）と単体テスト（32 件 pass）
- [x] P1-1 実データで再インデックス（101 文献 / 9,233 一節）→ 検索・マーカー・グラフ・GUI 全ページを検証
- [ ] P1-1b 実 NLI モデルでのファクトチェック検証（重み 558MB のダウンロード待ち。スタブ判定器では検証済み）
- [x] P1-2 README 更新、コードレビュー

## Errors Encountered
- 検索上位に参考文献リストの一節が並ぶ → 参考文献/ノイズ判定を追加し検索対象から除外。
- モデル読み込みのたびに HF Hub へ通信し、不安定な回線で数分ハング → `local_files_only=True` を優先。
- `huggingface_hub`（xet）で NLI 重みのダウンロードが 0 バイトのまま停止 → curl のレジュームで取得中。
- `QFrame#card QWidget { background: transparent }` でカード内の主ボタンが透明に → 背景はパレットで指定。
- `clear_layout` で `setParent(None)` 後に参照が解放され例外 → 変数に保持してから削除。

## Status
**P1-1b のみ残り** — NLI 重みのダウンロード完了後に
`venv/bin/python app.py --factcheck <原稿.txt>` で実モデルの判定を確認する。
