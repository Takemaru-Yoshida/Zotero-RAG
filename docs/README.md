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
| 3 | Embed each paper's full text with `multilingual-e5-large` | [`embedder.py`](../src/embedder.py) |
| 4 | Store latent vectors in a FAISS index on disk | [`vector_store.py`](../src/vector_store.py) |
| 5 | Embed the query text with the **same** model | `Embedder.embed_query()` |
| 6 | Cosine similarity vs. all stored vectors | `VectorStore.search()` |
| 7 | Show the most similar papers (top-K + threshold) | [`gui.py`](../src/gui.py) |

**Incremental sync:** on every launch and on demand, the app compares each
Zotero item's `dateModified` against what it indexed last time. Only new or
changed papers are re-embedded; deleted papers are dropped. See
[`indexer.py`](../src/indexer.py).

---

## The embedding model

**`intfloat/multilingual-e5-large`** (downloaded from the Hugging Face Hub only).

- Free, ~1.1 GB, runs fully offline after the first download.
- Strong English **and** Japanese retrieval scores (MTEB / JMTEB).
- Apple-Silicon GPU (MPS) / CUDA / CPU auto-detected.
- E5 requires prefixes — the app adds `query:` and `passage:` automatically.

> To try another model (e.g. `BAAI/bge-m3`), edit `embedding_model` and
> `embedding_dim` in the config file (see below) and re-sync. Keep both the
> index build and the queries on the same model.

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
