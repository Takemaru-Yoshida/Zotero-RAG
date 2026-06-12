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

import numpy as np


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

    def load(self, progress=None) -> None:
        """Lazily load the model (downloads from HF Hub on first run)."""
        if self.model is not None:
            return
        if progress:
            progress(f"Loading embedding model '{self.config.embedding_model}' "
                     f"on {self.device} ...")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(
            self.config.embedding_model,
            device=self.device,
            cache_folder=str(self.config.model_cache_dir),
        )
        self.model.max_seq_length = self.config.max_seq_length

    # -- chunking ----------------------------------------------------------- #
    def _chunk(self, text: str) -> list[str]:
        """Split text into overlapping windows by tokenizer word pieces."""
        tok = self.model.tokenizer
        max_len = self.config.max_seq_length - 8  # room for the "passage:" prefix
        overlap = min(self.config.chunk_overlap_tokens, max_len // 2)
        ids = tok.encode(text, add_special_tokens=False)
        if not ids:
            return []
        if len(ids) <= max_len:
            return [text]
        chunks, start = [], 0
        step = max_len - overlap
        while start < len(ids):
            window = ids[start:start + max_len]
            chunks.append(tok.decode(window, skip_special_tokens=True))
            start += step
        return chunks

    # -- public API --------------------------------------------------------- #
    def embed_document(self, text: str) -> np.ndarray:
        """Return an (n_chunks, dim) array of L2-normalised passage vectors."""
        self.load()
        chunks = self._chunk(text)
        if not chunks:
            return np.zeros((0, self.config.embedding_dim), dtype=np.float32)
        inputs = [f"passage: {c}" for c in chunks]
        vecs = self.model.encode(
            inputs, batch_size=self.config.batch_size,
            normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vecs.astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """Return a single (dim,) L2-normalised query vector."""
        self.load()
        vec = self.model.encode(
            [f"query: {text}"], normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )
        return vec[0].astype(np.float32)
