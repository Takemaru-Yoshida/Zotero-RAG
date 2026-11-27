# Zotero-RAG — documentation

A desktop app (PyQt6) that manages a Zotero library by **meaning** rather than
keywords, in English and Japanese: semantic search, AI markers on the paper,
a relation graph and a citation fact-check. Everything runs on the local
machine and Zotero is only ever read.

日本語の詳しい説明は [設計書.md](設計書.md) にあります。

---

## Features

| Page | What it does |
|------|--------------|
| Dashboard | Counts of papers, checked citations and citations that need review; recent papers and fact-check runs |
| Library | Zotero items plus PDFs added to the app; filter by folder, text, tag and star |
| Document viewer | Extracted text or the original PDF, with AI key-sentence markers (green) and "find in paper" markers (yellow); related papers |
| Semantic search | Passages of the whole library ranked by meaning, across languages |
| Citation fact-check | Checks each `(Author, 2020)` / `Author (2020)` citation of a manuscript against the cited paper: supported / partial / refuted / not found, with the evidence sentence |
| Relation graph | Citation links and content similarity between papers |
| Settings | Zotero folder, search defaults, embedding model, AI features |

---

## How the index is built

| Step | What happens | Code |
|------|--------------|------|
| 1 | Connect to Zotero (local HTTP API, or a read-only copy of the DB) | [`zotero_client.py`](../src/zotero_client.py) |
| 2 | Fetch the papers; PDFs added to the app join them | `ZoteroClient.fetch_papers()`, [`local_library.py`](../src/local_library.py) |
| 3 | Split the full text into passages | [`chunker.py`](../src/chunker.py) |
| 4 | Embed every passage | [`embedder.py`](../src/embedder.py) |
| 5 | Store passage text in SQLite and vectors in FAISS | [`library_db.py`](../src/library_db.py), [`vector_store.py`](../src/vector_store.py) |

**Passages.** Sentences (English and Japanese punctuation) are packed into
passages of at most 256 tokens (`chunk_tokens`) that do not overlap. Each
passage remembers the PDF page it starts on. Passages that look like a
reference list are flagged and left out of semantic search.

**Incremental sync.** At launch, on demand, and every `auto_sync_minutes`
(default 5; 0 turns it off) while the app is open, each Zotero item's
`dateModified` is compared with what was indexed. Only new or changed papers
are embedded again; deleted papers are dropped. The index is saved every 25
papers and at the end. If more than half of the indexed Zotero papers are
missing, the sync stops instead of emptying the index. See
[`indexer.py`](../src/indexer.py).

**Folders.** Every sync mirrors the Zotero collections (nested, read-only)
into `library.db`; the library page shows them next to the user's own folders,
which exist only in the app. See [`folders.py`](../src/folders.py).

---

## The embedding model

| Model | Vector size | Download | Default threshold | Notes |
|-------|-------------|----------|-------------------|-------|
| `Qwen/Qwen3-Embedding-4B` (default) | 2560 | ~8 GB | 0.45 | highest accuracy; 16 GB of memory or more recommended |
| `Qwen/Qwen3-Embedding-0.6B` | 1024 | ~1.2 GB | 0.45 | light and fast |
| `intfloat/multilingual-e5-large` | 1024 | ~2.1 GB | 0.78 | the previous default |

All are free, downloaded from the Hugging Face Hub only, and run offline after
the first download. Apple-Silicon GPU (MPS) / CUDA / CPU is auto-detected; the
Qwen3 models are loaded as float16 on the GPU.

**First start.** The first time the GUI starts it asks which of the two Qwen3
models to use, before the main window opens (see
[`ui/model_choice.py`](../src/ui/model_choice.py)). The one that suits the
machine's memory is preselected: 4B from 16 GB, 0.6B below. Closing the dialog
downloads nothing and the question comes back at the next start. An install
that already has an index is not asked. An install that only ever used the
command line gets 4B.

**Changing the model** in Settings takes effect after a restart. The index
records which model built it, so the next sync embeds every paper again, and
`similarity_threshold` is reset to the new model's default (cosine scales
differ between models).

Measured on 101 papers (8,818 passages, Apple Silicon, 24 GB): a full index
takes about 1 hour with 4B and about 12 minutes with 0.6B (download included).

Input prefixes (the Qwen3 query instruction, E5's `query:` / `passage:`),
vector size and the default threshold come from the model's profile in
[`embedding_models.py`](../src/embedding_models.py). Any other
sentence-transformers model can be used by setting `embedding_model` and
`embedding_dim` in the config file; it is run without prefixes.

---

## Vector search

Vectors are L2-normalised and searched with a FAISS inner-product index
(cosine similarity). Below 50,000 vectors the index is exact (`IndexFlatIP`);
from 50,000 it is rebuilt automatically as an IVF index
(`nlist = max(16, √N)`, `nprobe = min(nlist, 16)`).

---

## Document viewer and markers

- **AI key sentences** (green): the passages closest to the paper's centroid
  vector (blended with title and abstract), and in each the closest sentence.
  Extractive, local, cached in `library.db`. See
  [`highlights.py`](../src/highlights.py).
- **Find in paper** (yellow): the passages of the paper closest to a typed
  sentence.
- **Text / PDF switch.** The same markers are shown on the extracted text or
  drawn on the pages of the original PDF (QtPdf, bundled with PyQt6; see
  [`ui/pdf_view.py`](../src/ui/pdf_view.py)). A marker's place on the page is
  found in the PDF's text layer after reducing both sides to their letters
  ([`pdf_locate.py`](../src/pdf_locate.py)); 780 of 782 sampled sentences from
  100 papers were located. A scanned PDF without a text layer is shown
  without markers.

---

## Citation fact-check

For every cited claim the pipeline finds the cited paper by author surname and
year, takes the passages closest in meaning to the claim (4 by default), and
asks a local NLI model
(`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`, ~560 MB,
downloaded at the first check) whether they entail or contradict it.

| Verdict | Rule |
|---------|------|
| supported | some passage entails the claim and the candidates do not contradict it as a group |
| refuted | the median contradiction over the candidates reaches the threshold and nothing entails |
| partial | anything else, including conflicting signals |
| not found | no paper in the library matches author and year |

See [`factcheck.py`](../src/factcheck.py) and [`nli.py`](../src/nli.py). The
verdict is a guide; confirm with the evidence sentence and the paper.

---

## Relation graph

- **cites**: the title of paper B (25 characters or more) appears in the full
  text of paper A. Zotero stores no citation links, so they are detected from
  the text.
- **similar**: the two papers are mutual nearest neighbours (k = 3) by the
  cosine of their mean passage vectors.

See [`graph.py`](../src/graph.py).

---

## Security notes

- **Read-only Zotero access.** The app never writes to the Zotero database; it
  copies `zotero.sqlite` to a temp file before reading.
- **Local only.** Papers and manuscripts never leave the machine. The only
  outbound network calls are the one-time model downloads from Hugging Face.
- **No credentials.** The Zotero local API needs none; nothing sensitive is
  stored.
- **Input is treated as data.** Queries and manuscripts are encoded, never
  executed. All SQL uses parameterised queries.

---

## Setup

`venv/`, `Zotero-RAG.app`, the models and the vectors are **not in Git**, so
recreate them once after cloning.

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

The first launch asks for the embedding model, downloads it and indexes the
whole library; later launches only sync new papers.

## Usage

**GUI:** double-click `Zotero-RAG.app` (or `venv/bin/python app.py`).

**Command line:**

```bash
venv/bin/python app.py --status            # backend + index status
venv/bin/python app.py --sync              # build/update the index
venv/bin/python app.py --search "視覚野の階層的表現"
venv/bin/python app.py --factcheck draft.txt
```

**Tests:** `venv/bin/python -m pytest tests -q`

### Zotero closed or open

The app reads the Zotero database directly (read-only), so it works when
Zotero is not running. For the local-API path, open Zotero and enable
*Settings → Advanced → Allow other applications on this computer to communicate
with Zotero*.

## Configuration and data

Everything lives in `~/Library/Application Support/Zotero-RAG/` (override with
`ZOTERO_RAG_HOME`):

| File | Content |
|------|---------|
| `config.json` | settings: `embedding_model`, `top_k`, `similarity_threshold`, `auto_sync_minutes`, `document_view`, `item_types`, `zotero_data_dir`, `device`, … |
| `index.faiss`, `metadata.json` | the vectors, and which paper and model each row belongs to |
| `library.db` | passage text, cached markers, stars, folders, fact-check history, imported PDFs |
| `library/` | copies of PDFs added to the app |
| `models/` | model cache |
