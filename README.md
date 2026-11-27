# Zotero-RAG

Zotero ライブラリの文献管理・意味検索（RAG）・AI マーカー・関連グラフ・
**引用ファクトチェック**をひとつにしたデスクトップアプリ（PyQt6）— English & 日本語.
すべてローカルで動作し、Zotero のデータベースは読み取り専用で扱います。

## 機能 (Features)

| 画面 | 内容 |
|---|---|
| ダッシュボード | 登録文献数・チェック済み引用数・要確認の引用数、最近の文献とファクトチェック履歴 |
| ライブラリ | Zotero の文献 + アプリに直接追加した PDF。フォルダ（Zotero コレクション + アプリ内のマイフォルダ）・タイトル/著者/掲載誌・タグ・お気に入りで絞り込み |
| 文献ビューア | 「テキスト / PDF」ボタンで、抽出した本文（一節ごと）と元の PDF を切り替え。どちらにも AI 重要文マーカー（緑）と「探したい文」の意味検索マーカー（黄）を表示。関連文献 |
| 意味検索 | ライブラリ全体から、質問と意味の近い**一節**を類似度順に表示（日英横断）。クリックで該当箇所へ |
| 引用ファクトチェック | 原稿中の `(著者, 年)` / `著者 (年)` 引用を原文と照合し、支持 / 一部支持 / 矛盾 / 文献なし を根拠の一文つきで判定 |
| 関連グラフ | 引用関係（本文中の参考文献から検出）と内容の類似（文献ベクトルの相互近傍）を可視化 |
| 設定 | Zotero データフォルダ、検索の件数・しきい値、AI 機能の切り替え、システム情報 |

- PDF の追加: 「＋ 文献を追加」またはウィンドウへのドラッグ&ドロップ。追加した PDF は
  文献ビューアの「情報を編集」で著者・出版年などを入力できます（ファクトチェックの照合に使用）。
- 使用モデル（いずれも無料・ローカル実行、初回のみ Hugging Face から自動ダウンロード）:
  - 埋め込み: 初回起動時に `Qwen/Qwen3-Embedding-4B`（高精度・約 8 GB、メモリ 16 GB 以上を
    推奨）か `Qwen/Qwen3-Embedding-0.6B`（軽量・約 1.2 GB）を選びます。メモリ量に応じた
    おすすめが選択済みで表示されます。あとから設定画面で変更でき（従来の
    `multilingual-e5-large` 約 2.1 GB も選択可）、変更するとアプリ再起動後に全文献を
    再インデックスします。`--sync` などコマンドラインだけで使い始めた場合は 4B になります。
  - 引用ファクトチェックの含意判定: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
    （約 560 MB。「チェックする」を初めて押したときにダウンロード）
- ダウンロード後はネットワークなしで起動・検索できます。
- 旧バージョン（v1）のインデックスは、初回起動時に自動で新形式（文単位の一節 + 本文保存）へ
  再構築されます（101 文献で数分〜十数分）。

ドキュメント / Documentation:
- **[docs/設計書.md](docs/設計書.md)** — 日本語の設計説明書（アプリの仕組み・操作方法）
- **[docs/README.md](docs/README.md)** — English documentation
- **[docs/pptx/Zotero-RAG.pptx](docs/pptx/Zotero-RAG.pptx)** — illustrated walkthrough

## クローン／ダウンロード後の立ち上げ方 (Setup after clone)

`venv/`・`Zotero-RAG.app`・モデル・潜在ベクトルは **Git に含まれていません**
（`.gitignore` で除外）。クローン後は以下を一度だけ実行して再生成します。

**前提:** Python 3.10+ と Zotero（インストール済み・論文が登録済み）。
アイコン再生成と `.app` ビルドは macOS 用です。

```bash
# 1. リポジトリを取得
git clone git@github.com:<ユーザー名>/Zotero-RAG.git
cd Zotero-RAG

# 2. 仮想環境を作成して依存をインストール
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# 3. （macOS）アイコンを生成し、ダブルクリック起動できる .app をビルド
venv/bin/python scripts/make_icon.py
bash scripts/build_app.sh

# 4. 起動（初回は Embedding モデルを選択 → HuggingFace から自動DL＋索引構築）
open Zotero-RAG.app          # GUI。または: venv/bin/python app.py
```

> **macOS 以外（Windows / Linux）**: 手順 3 の `.app` ビルドは不要です。
> 手順 2 のあと `venv/bin/python app.py`（Windows は `venv\Scripts\python app.py`）
> で GUI を起動できます。
>
> 初回起動時に Embedding モデル（4B / 0.6B）を選ぶと、ダウンロードとインデックス構築が走ります。2回目以降は
> 新着論文だけを同期するため高速です。潜在ベクトルは各自の環境の
> `~/Library/Application Support/Zotero-RAG/` に保存され、共有されません。

### Zotero との同期とフォルダ

- **同期のタイミング**: 起動時、サイドバーの「新着を確認」、および起動中は
  5 分ごと（`config.json` の `auto_sync_minutes`。0 で自動同期を止める）。
  Zotero で追加・変更・削除した文献はこのタイミングで反映されます。
- **Zotero コレクション**: 入れ子も含めてライブラリ画面の左側に表示されます
  （読み取り専用。編集は Zotero 側で行い、同期のたびに反映）。親コレクションを
  選ぶと、サブコレクションの文献も表示します。
- **マイフォルダ**: 「＋ 新しいフォルダ」で作成し、文献カードの右クリック、
  または文献ページの「フォルダ」ボタンで出し入れします。1 つの文献を複数の
  フォルダに入れられます。フォルダ名の右クリックで名前変更・削除。
  Zotero 側には書き込みません。

## Quick start（セットアップ済みの場合）

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python scripts/make_icon.py     # build the app icon
bash scripts/build_app.sh                # build Zotero-RAG.app
open Zotero-RAG.app                       # launch the GUI
```

Command-line:

```bash
venv/bin/python app.py --status
venv/bin/python app.py --sync
venv/bin/python app.py --search "contrastive self-supervised learning"
venv/bin/python app.py --factcheck draft.txt   # 原稿ファイルの引用を照合
```

Tests:

```bash
venv/bin/pip install pytest
venv/bin/python -m pytest tests -q
```

## Project layout

```
app.py                 entry point (GUI / --sync / --search / --factcheck / --status)
requirements.txt       pinned dependencies
src/
  config.py            settings + paths
  zotero_client.py     Zotero local API + read-only SQLite fallback
  local_library.py     PDFs imported directly into the app
  chunker.py           sentence-aligned passages, page tracking, bibliography filter
  embedding_models.py  supported embedding models (prefixes, vector size, threshold)
  embedder.py          runs the configured embedding model
  vector_store.py      FAISS index, per-passage search, persistence
  library_db.py        SQLite: passage text, highlights, stars, folders, fact-check history
  folders.py           folder tree (Zotero collections + own folders)
  indexer.py           incremental sync (Zotero + imported PDFs)
  search.py            paper-level and passage-level semantic search
  highlights.py        AI key sentences + "find in paper" markers
  pdf_locate.py        finds a marked sentence in a PDF page's text layer
  nli.py               local NLI model (entailment / contradiction)
  factcheck.py         citation parsing, paper matching, verdicts
  graph.py             citation / similarity edges, force layout
  services.py          facade used by the GUI and the CLI
  gui.py               GUI entry point (→ src/ui)
  ui/                  PyQt6 pages: dashboard, library, document, search,
                       fact-check, graph, settings
tests/                 unit tests (pytest)
scripts/
  make_icon.py         SVG → .icns
  build_app.sh         build the double-clickable .app
assets/                icon.svg / icon.png / icon.icns
docs/                  README + PptxGenJS presentation
```
