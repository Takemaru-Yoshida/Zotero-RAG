# Zotero-RAG

Semantic (vector) search over your Zotero library — English & 日本語.

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

# 4. 起動（初回はモデル約1.1GBをHuggingFaceから自動DL＋索引構築）
open Zotero-RAG.app          # GUI。または: venv/bin/python app.py
```

> **macOS 以外（Windows / Linux）**: 手順 3 の `.app` ビルドは不要です。
> 手順 2 のあと `venv/bin/python app.py`（Windows は `venv\Scripts\python app.py`）
> で GUI を起動できます。
>
> 初回起動時にモデルのダウンロードとインデックス構築が走ります。2回目以降は
> 新着論文だけを同期するため高速です。潜在ベクトルは各自の環境の
> `~/Library/Application Support/Zotero-RAG/` に保存され、共有されません。

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
```

## Project layout

```
app.py                 entry point (GUI / --sync / --search / --status)
requirements.txt       pinned dependencies
src/
  config.py            settings + paths
  zotero_client.py     Zotero local API + read-only SQLite fallback
  embedder.py          multilingual-e5-large, chunking, E5 prefixes
  vector_store.py      FAISS index (flat → IVF), persistence
  indexer.py           steps 2-4 + incremental sync
  search.py            steps 5-7
  gui.py               PyQt6 desktop UI
scripts/
  make_icon.py         SVG → .icns
  build_app.sh         build the double-clickable .app
assets/                icon.svg / icon.png / icon.icns
docs/                  README + PptxGenJS presentation
```
