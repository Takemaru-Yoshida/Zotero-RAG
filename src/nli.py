"""Local natural-language-inference model for the citation fact-check.

Given a premise (a passage of the cited paper) and a hypothesis (the claim in
the manuscript) the model returns the probabilities of *entailment*,
*neutral* and *contradiction*. The default model is a multilingual mDeBERTa-v3
fine-tuned on XNLI + multilingual NLI data: free, offline after the first
download from the Hugging Face Hub, and usable for English and Japanese text.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NliScores:
    entailment: float
    neutral: float
    contradiction: float


class NliModel:
    def __init__(self, config):
        self.config = config
        self.tokenizer = None
        self.model = None
        self._label_index: dict[str, int] = {}
        self._lock = threading.RLock()

    def load(self) -> None:
        """Lazily load the model (downloads from HF Hub on first run)."""
        with self._lock:
            if self.model is not None:
                return
            from transformers import (AutoModelForSequenceClassification,
                                      AutoTokenizer)
            name = self.config.nli_model
            cache = str(self.config.model_cache_dir)
            logger.info("Loading NLI model %s on %s", name, self.config.nli_device)
            try:
                # Cached copy first: no network access once downloaded.
                self.tokenizer = AutoTokenizer.from_pretrained(
                    name, cache_dir=cache, local_files_only=True)
                model = AutoModelForSequenceClassification.from_pretrained(
                    name, cache_dir=cache, local_files_only=True)
            except (OSError, ValueError):
                logger.info("NLI model not cached yet; downloading %s", name)
                self.tokenizer = AutoTokenizer.from_pretrained(
                    name, cache_dir=cache)
                model = AutoModelForSequenceClassification.from_pretrained(
                    name, cache_dir=cache)
            model.to(self.config.nli_device).eval()
            # Label order differs between NLI checkpoints; read it from config.
            for i, label in model.config.id2label.items():
                self._label_index[str(label).lower()[:6]] = int(i)
            missing = {"entail", "neutra", "contra"} - set(self._label_index)
            if missing:
                raise ValueError(
                    f"{name} is not a 3-way NLI model "
                    f"(labels: {model.config.id2label})")
            self.model = model

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[NliScores]:
        """Score ``(premise, hypothesis)`` pairs."""
        if not pairs:
            return []
        import torch
        with self._lock:
            # On macOS the faiss and torch wheels each ship their own OpenMP
            # runtime; multi-threaded CPU inference in a process that has also
            # used FAISS segfaults. One thread is plenty for a few sentence
            # pairs, so pin it while this model loads and runs.
            on_cpu = self.config.nli_device == "cpu"
            threads = torch.get_num_threads()
            if on_cpu:
                torch.set_num_threads(1)
            try:
                self.load()
                enc = self.tokenizer(
                    [p for p, _ in pairs], [h for _, h in pairs],
                    truncation="only_first", max_length=512, padding=True,
                    return_tensors="pt").to(self.config.nli_device)
                with torch.no_grad():
                    probs = torch.softmax(self.model(**enc).logits, dim=-1).cpu()
            finally:
                if on_cpu:
                    torch.set_num_threads(threads)
        idx = self._label_index
        return [NliScores(float(p[idx["entail"]]), float(p[idx["neutra"]]),
                          float(p[idx["contra"]])) for p in probs]
