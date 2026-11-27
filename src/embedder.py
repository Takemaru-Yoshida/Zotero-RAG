"""Embedding model wrapper.

Runs the model named in the config (default ``Qwen/Qwen3-Embedding-4B``) via
sentence-transformers. The models are free, downloaded from the Hugging Face
Hub only, and fully offline after the first download.

Each model family expects its own input format; the prefixes come from the
model's profile in ``embedding_models``:
  * Qwen3-Embedding: an instruction before search queries, plain passages
  * E5: ``query: <text>`` for queries, ``passage: <text>`` for passages

Long documents are split into sentence-aligned passages (see ``chunker``);
each passage is embedded separately so that a relevant passage anywhere in a
long paper can be matched. Embeddings are L2-normalised so that an inner-product index computes
cosine similarity directly.
"""
from __future__ import annotations

import logging
import threading
from typing import Sequence

import numpy as np

from .chunker import Chunk, chunk_text
from .embedding_models import profile_for

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
        # Fixed at start-up: a model picked in Settings applies after restart.
        self.model_name = config.embedding_model
        self.dim = config.embedding_dim
        self.profile = profile_for(self.model_name, self.dim)
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
                         f"'{self.model_name}' on {self.device} ...")
            from sentence_transformers import SentenceTransformer
            kwargs = dict(device=self.device,
                          cache_folder=str(self.config.model_cache_dir))
            import torch
            if self.profile.half_precision and self.device != "cpu":
                kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
            # On macOS the faiss and torch wheels each ship their own OpenMP
            # runtime; converting the weights on several CPU threads in a
            # process that has also used FAISS segfaults (see ``nli.py``).
            threads = torch.get_num_threads()
            torch.set_num_threads(1)
            try:
                # Use the cached copy without touching the network, so the app
                # starts offline and never hangs on a flaky connection.
                model = SentenceTransformer(
                    self.model_name, local_files_only=True, **kwargs)
            except (OSError, ValueError):
                logger.info("Embedding model not cached yet; downloading %s",
                            self.model_name)
                model = SentenceTransformer(self.model_name, **kwargs)
            finally:
                torch.set_num_threads(threads)
            model.max_seq_length = self.config.max_seq_length
            if self.profile.left_padding:
                model.tokenizer.padding_side = "left"
            # Renamed in sentence-transformers 5.
            get_dim = getattr(model, "get_embedding_dimension", None) \
                or model.get_sentence_embedding_dimension
            dim = get_dim()
            if dim != self.dim:
                raise ValueError(
                    f"{self.model_name} produces {dim}-d vectors "
                    f"but embedding_dim is {self.dim}; "
                    "correct embedding_dim in the config file.")
            self.model = model

    # -- chunking ----------------------------------------------------------- #
    def _count_tokens(self, texts: Sequence[str]) -> list[int]:
        enc = self.model.tokenizer(list(texts), add_special_tokens=False,
                                   verbose=False)
        return [len(ids) for ids in enc["input_ids"]]

    def chunk_document(self, text: str) -> list[Chunk]:
        """Split text into sentence-aligned, page-tagged passages."""
        self.load()
        # Leave room for the passage prefix and special tokens.
        max_len = min(self.config.chunk_tokens, self.config.max_seq_length - 8)
        with self._lock:
            return chunk_text(text, self._count_tokens, max_len)

    # -- public API --------------------------------------------------------- #
    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        """Return an (n, dim) array of L2-normalised passage vectors."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        self.load()
        with self._lock:
            vecs = self.model.encode(
                [self.profile.passage_prefix + t for t in texts],
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
                [self.profile.query_prefix + text], normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )
        return vec[0].astype(np.float32)
