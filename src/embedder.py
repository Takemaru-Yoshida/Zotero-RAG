"""Embedding model wrapper.

Uses ``intfloat/multilingual-e5-large`` via sentence-transformers. This model
is free, ~1.1 GB, fully offline after the first download, and scores highly on
both English and Japanese retrieval (MTEB / JMTEB). It is downloaded from the
Hugging Face Hub only.

E5 models are trained with explicit prefixes that must be used:
  * ``query: <text>``   for search queries (step 5)
  * ``passage: <text>`` for documents being indexed (step 3)

Long documents are split into overlapping token windows; each window is
embedded separately so that a relevant passage anywhere in a long paper can be
matched. Embeddings are L2-normalised so that an inner-product index computes
cosine similarity directly.
"""
from __future__ import annotations

import logging
import threading
from typing import Sequence

import numpy as np

from .chunker import Chunk, chunk_text

logger = logging.getLogger(__name__)


def _resolve_device(pref: str) -> str:
    import torch
    if pref and pref != "auto":
        return pref
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Embedder:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.device = _resolve_device(config.device)
        # The GUI embeds from several worker threads (sync, search, markers,
        # fact-check); the model is used by one of them at a time.
        self._lock = threading.RLock()

    def load(self, progress=None) -> None:
        """Lazily load the model (downloads from HF Hub on first run)."""
        with self._lock:
            if self.model is not None:
                return
            if progress:
                progress(f"Loading embedding model "
                         f"'{self.config.embedding_model}' on {self.device} ...")
            from sentence_transformers import SentenceTransformer
            kwargs = dict(device=self.device,
                          cache_folder=str(self.config.model_cache_dir))
            try:
                # Use the cached copy without touching the network, so the app
                # starts offline and never hangs on a flaky connection.
                self.model = SentenceTransformer(
                    self.config.embedding_model, local_files_only=True, **kwargs)
            except (OSError, ValueError):
                logger.info("Embedding model not cached yet; downloading %s",
                            self.config.embedding_model)
                self.model = SentenceTransformer(
                    self.config.embedding_model, **kwargs)
            self.model.max_seq_length = self.config.max_seq_length

    # -- chunking ----------------------------------------------------------- #
    def _count_tokens(self, texts: Sequence[str]) -> list[int]:
        enc = self.model.tokenizer(list(texts), add_special_tokens=False,
                                   verbose=False)
        return [len(ids) for ids in enc["input_ids"]]

    def chunk_document(self, text: str) -> list[Chunk]:
        """Split text into sentence-aligned, page-tagged passages."""
        self.load()
        # Leave room for the "passage:" prefix and special tokens.
        max_len = min(self.config.chunk_tokens, self.config.max_seq_length - 8)
        with self._lock:
            return chunk_text(text, self._count_tokens, max_len)

    # -- public API --------------------------------------------------------- #
    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        """Return an (n, dim) array of L2-normalised passage vectors."""
        if not texts:
            return np.zeros((0, self.config.embedding_dim), dtype=np.float32)
        self.load()
        with self._lock:
            vecs = self.model.encode(
                [f"passage: {t}" for t in texts],
                batch_size=self.config.batch_size,
                normalize_embeddings=True, convert_to_numpy=True,
                show_progress_bar=False,
            )
        return vecs.astype(np.float32)

    def embed_document(self, text: str) -> np.ndarray:
        """Chunk ``text`` and return its (n_chunks, dim) passage vectors."""
        return self.embed_passages([c.text for c in self.chunk_document(text)])

    def embed_query(self, text: str) -> np.ndarray:
        """Return a single (dim,) L2-normalised query vector."""
        self.load()
        with self._lock:
            vec = self.model.encode(
                [f"query: {text}"], normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )
        return vec[0].astype(np.float32)
