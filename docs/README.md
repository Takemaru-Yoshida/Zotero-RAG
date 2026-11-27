# Zotero-RAG — Semantic Search for Your Zotero Library

意味（ベクトル類似度）で Zotero の論文を検索するデスクトップアプリです。英語・日本語の
両方に対応します。キーワード一致ではなく「内容の近さ」で、関連論文を見つけられます。

A desktop RAG application that finds papers in your Zotero library by **meaning**
rather than keywords, in both English and Japanese.

---

## How it works / 処理の流れ

The spec maps to the code as follows. Steps 1–4 run on first launch (and whenever
new papers appear); steps 5–7 run on every search.

| Step | What happens | Code |
|------|--------------|------|
| 1 | Connect to Zotero (local HTTP API, or read-only DB fallback) | [`zotero_client.py`](../src/zotero_client.py) |
| 2 | Extract papers (journal articles, preprints, …) | `ZoteroClient.fetch_papers()` |
| 3 | Embed each paper's full text with the embedding model (default `Qwen3-Embedding-4B`) | [`embedder.py`](../src/embedder.py) |
| 4 | Store latent vectors in a FAISS index on disk | [`vector_store.py`](../src/vector_store.py) |
| 5 | Embed the query text with the **same** model | `Embedder.embed_query()` |
| 6 | Cosine similarity vs. all stored vectors | `VectorStore.search()` |
| 7 | Show the most similar papers (top-K + threshold) | [`gui.py`](../src/gui.py) |

**Incremental sync:** on every launch, on demand, and every
`auto_sync_minutes` (default 5; 0 turns it off) while the app is open, the app
compares each Zotero item's `dateModified` against what it indexed last time.
Only new or changed papers are re-embedded; deleted papers are dropped. See
[`indexer.py`](../src/indexer.py).

**Folders:** every sync also mirrors the Zotero collections (nested,
read-only) into `library.db`; the library page shows them next to the user's
own folders, which exist only in the app. See
[`folders.py`](../src/folders.py) and [`library_db.py`](../src/library_db.py).

---

## The embedding model

Default: **`Qwen/Qwen3-Embedding-4B`** (downloaded from the Hugging Face Hub only).

- Free, runs fully offline after the first download (~8 GB).
- 2560-d vectors; loaded as float16 on the GPU (about 8 GB of memory, so a
  machine with 16 GB or more is recommended).
- Apple-Silicon GPU (MPS) / CUDA / CPU auto-detected.

The first time the app starts it asks which of the two Qwen3 models to use
(the one that suits the machine's memory is preselected: 4B from 16 GB, 0.6B
below; see [`ui/model_choice.py`](../src/ui/model_choice.py)). It can be changed
later in **Settings → Embedding モデル**:

| Model | Vector size | Download | Notes |
|-------|-------------|----------|-------|
| `Qwen/Qwen3-Embedding-4B` (default) | 2560 | ~8 GB | highest accuracy |
| `Qwen/Qwen3-Embedding-0.6B` | 1024 | ~1.2 GB | light and fast |
| `intfloat/multilingual-e5-large` | 1024 | ~2.1 GB | the previous default |

Input prefixes (the Qwen3 query instruction, E5's `query:` / `passage:`),
vector size and the default similarity threshold come from the model's profile
in [`embedding_models.py`](../src/embedding_models.py).

Changing the model takes effect after a restart. The index records which model
built it, so the next sync re-embeds every paper, and `similarity_threshold`
is reset to the new model's default (cosine scales differ between models).

> Any other sentence-transformers model can be used by setting
> `embedding_model` and `embedding_dim` in the config file (see below); it is
> run without prefixes.

---

## Efficient vector search

Vectors are L2-normalised and searched with a FAISS inner-product index
(cosine similarity). Small libraries use an exact flat index; once the index
exceeds ~4,000 chunks it is automatically rebuilt as an **IVF (inverted-file)
ANN index** for a large speed-up at negligible recall cost. Long papers are
split into overlapping token windows so a relevant passage anywhere in a paper
can match.

---

## Security notes

- **Read-only Zotero access.** The app never writes to your Zotero database; it
  copies `zotero.sqlite` to a temp file before reading, so it can't lock or
  corrupt the live DB.
- **Local only.** No data leaves your machine. The only outbound network call is
  the one-time model download from Hugging Face.
- **No credentials/secrets.** The Zotero local API needs none; nothing sensitive
  is stored.
- **Input is treated as data.** Queries are encoded as text, never executed.
  All SQL uses parameterised queries.
- **Model provenance restricted** to Hugging Face / PyTorch as required.

---

## Setup

### From a fresh clone / download

`venv/`, `Zotero-RAG.app`, the model, and the latent vectors are **not in Git**
(excluded by `.gitignore`), so recreate them once after cloning. Latent vectors
are per-user and are rebuilt locally on first launch.

Prerequisites: Python 3.10+ and Zotero (installed, with papers). The icon and
`.app` build steps are macOS-only.

```bash
git clone git@github.com:<user>/Zotero-RAG.git
cd Zotero-RAG

python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# macOS: build the icon + double-clickable bundle
venv/bin/python scripts/make_icon.py
bash scripts/build_app.sh

open Zotero-RAG.app          # GUI, or: venv/bin/python app.py
```

**Windows / Linux:** skip the `.app` build; after the `pip install` run
`venv/bin/python app.py` (Windows: `venv\Scripts\python app.py`).

First launch downloads the model (~1.1 GB) from Hugging Face and builds the
index; later launches only sync new papers.

## Usage

**GUI:** double-click `Zotero-RAG.app` (or `venv/bin/python app.py`).
On launch it loads the saved index and checks Zotero for new papers, then you can
search. Adjust **Results** (top-K) and **Min similarity** (threshold) live.

**Command line:**

```bash
venv/bin/python app.py --status            # backend + index status
venv/bin/python app.py --sync              # build/update the index
venv/bin/python app.py --search "視覚野の階層的表現"
```

### First run with Zotero closed

The app reads your Zotero database directly (read-only), so it works even when
Zotero isn't running. For the **live** local-API path, open Zotero and enable
*Settings → Advanced → Allow other applications on this computer to communicate
with Zotero*.

## Configuration

Settings live in
`~/Library/Application Support/Zotero-RAG/config.json` (created on first run).
Key fields: `embedding_model`, `top_k`, `similarity_threshold`,
`item_types`, `zotero_data_dir`, `device`.

The index and metadata are stored alongside it (`index.faiss`,
`metadata.json`); the model cache is under `models/`.
