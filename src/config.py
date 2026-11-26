"""Application configuration.

Loads settings from a JSON file in the per-user application-data directory and
provides typed accessors with safe defaults. No secrets are stored here; the
Zotero local API needs no credentials and all data stays on the local machine.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .embedding_models import DEFAULT_MODEL, LEGACY_MODEL, profile_for

# Bumped when saved settings must be migrated (see ``Config._migrate``).
#   2: default embedding model became Qwen3-Embedding-4B
CONFIG_VERSION = 2


def _default_zotero_data_dir() -> Path:
    """Locate the Zotero data directory in a platform-aware way."""
    env = os.environ.get("ZOTERO_DATA_DIR")
    if env:
        return Path(env).expanduser()
    home = Path.home()
    candidates = [
        home / "Zotero",                       # macOS / Linux default
        home / "Library" / "Application Support" / "Zotero",
    ]
    for c in candidates:
        if (c / "zotero.sqlite").exists():
            return c
    return home / "Zotero"


def app_data_dir() -> Path:
    """Directory where the app stores its index, config and model cache."""
    base = Path(
        os.environ.get("ZOTERO_RAG_HOME")
        or (Path.home() / "Library" / "Application Support" / "Zotero-RAG"
            if os.uname().sysname == "Darwin"
            else Path.home() / ".local" / "share" / "Zotero-RAG")
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def _version(data: dict) -> int:
    """Version of a saved config; files from before versioning count as 1."""
    try:
        return int(data.get("config_version", 1))
    except (TypeError, ValueError):
        return 1


@dataclass
class Config:
    # --- Zotero integration ---
    zotero_data_dir: str = field(default_factory=lambda: str(_default_zotero_data_dir()))
    # Local Zotero HTTP API. Enabled by default in Zotero 7
    # (Settings > Advanced > "Allow other applications on this computer to
    # communicate with Zotero"). Used when reachable; otherwise the app falls
    # back to a read-only copy of zotero.sqlite + the .zotero-ft-cache files.
    zotero_api_base: str = "http://127.0.0.1:23119"
    zotero_library_type: str = "user"   # "user" or "group"
    zotero_library_id: int = 0          # 0 = local "My Library"

    config_version: int = CONFIG_VERSION

    # --- Embedding model (free, local, multilingual EN+JA) ---
    # Any model in ``embedding_models.MODEL_PROFILES``; prefixes, vector size
    # and float16 loading follow from the profile. Changing the model makes
    # the next sync rebuild the whole index.
    embedding_model: str = DEFAULT_MODEL
    # Taken from the profile for known models (see ``__post_init__``).
    embedding_dim: int = 0
    # Model picked in Settings; applied by ``load`` at the next start, so the
    # running session keeps its model, index and threshold scale.
    pending_embedding_model: str = ""
    max_seq_length: int = 512           # encoder input limit (tokens)
    chunk_overlap_tokens: int = 64      # legacy (v1 index); unused since v2
    # Passages are packed from whole sentences up to this many tokens. Smaller
    # passages give sharper search hits, markers and fact-check evidence.
    chunk_tokens: int = 256
    device: str = "auto"                # auto | cpu | cuda | mps

    # --- Retrieval ---
    top_k: int = 10                     # max results shown
    # Cosine; results below are hidden. The scale depends on the model, so
    # this is reset to the profile's default whenever the model changes.
    similarity_threshold: float = profile_for(DEFAULT_MODEL).default_threshold
    # Aggregate per-document score from its chunk scores: "max" or "mean".
    score_aggregation: str = "max"

    # --- Indexing ---
    item_types: tuple = ("journalArticle", "preprint", "conferencePaper",
                         "book", "bookSection", "report", "thesis")
    batch_size: int = 16
    # While the app is open, check Zotero for new or changed papers this
    # often (minutes; 0 = only at start-up and with the sync button).
    auto_sync_minutes: float = 5

    # --- AI markers (document viewer) ---
    auto_mark: bool = True              # show AI key-sentence markers by default
    # How a paper is shown: "text" (extracted text) or "pdf" (the original
    # PDF with the markers drawn on it). Remembers the viewer's last choice.
    document_view: str = "text"
    key_sentences: int = 5              # key sentences extracted per paper

    # --- Citation fact-check (local NLI model; free, multilingual, offline) ---
    nli_model: str = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
    nli_device: str = "cpu"             # a few sentence pairs; CPU is enough
    factcheck_candidates: int = 4       # passages of the cited paper to test
    entail_threshold: float = 0.5       # P(entailment) needed for "supported"
    contradict_threshold: float = 0.5   # P(contradiction) needed for "refuted"
    strict_partial: bool = False        # count "partial" as needing review

    # --- Relation graph ---
    graph_neighbors: int = 3            # mutual k-NN for "similar" edges

    def __post_init__(self) -> None:
        profile = profile_for(self.embedding_model, self.embedding_dim)
        if profile.dim:
            self.embedding_dim = profile.dim

    def use_model(self, name: str) -> None:
        """Switch the embedding model, with its vector size and threshold."""
        profile = profile_for(name, self.embedding_dim)
        self.embedding_model = name
        self.embedding_dim = profile.dim
        self.similarity_threshold = profile.default_threshold

    @classmethod
    def _migrate(cls, data: dict) -> dict:
        """Bring settings saved by an older version of the app up to date."""
        if _version(data) < 2:
            # The old default was written into every saved config; move those
            # installs to the new default (a hand-picked model is kept).
            if data.get("embedding_model", LEGACY_MODEL) == LEGACY_MODEL:
                data["embedding_model"] = DEFAULT_MODEL
                data.pop("embedding_dim", None)
                data.pop("similarity_threshold", None)
        data["config_version"] = CONFIG_VERSION
        return data

    @classmethod
    def path(cls) -> Path:
        return app_data_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("config.json is not a JSON object")
                changed = _version(data) < CONFIG_VERSION
                data = cls._migrate(data)
                known = {f for f in cls.__dataclass_fields__}
                clean = {k: v for k, v in data.items() if k in known}
                if "item_types" in clean:
                    clean["item_types"] = tuple(clean["item_types"])
                cfg = cls(**clean)
                if cfg.pending_embedding_model:
                    cfg.use_model(cfg.pending_embedding_model)
                    cfg.pending_embedding_model = ""
                    changed = True
                if changed:
                    try:
                        cfg.save()
                    except OSError:
                        # Read-only settings must not stop the app starting.
                        pass
                return cfg
            except (json.JSONDecodeError, TypeError, ValueError):
                # Corrupt config should never crash the app; fall back to defaults.
                pass
        cfg = cls()
        cfg.save()
        return cfg

    def save(self) -> None:
        d = asdict(self)
        d["item_types"] = list(self.item_types)
        self.path().write_text(json.dumps(d, indent=2, ensure_ascii=False),
                               encoding="utf-8")

    # --- derived paths ---
    @property
    def index_path(self) -> Path:
        return app_data_dir() / "index.faiss"

    @property
    def meta_path(self) -> Path:
        return app_data_dir() / "metadata.json"

    @property
    def db_path(self) -> Path:
        return app_data_dir() / "library.db"

    @property
    def local_library_dir(self) -> Path:
        d = app_data_dir() / "library"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def model_cache_dir(self) -> Path:
        d = app_data_dir() / "models"
        d.mkdir(parents=True, exist_ok=True)
        return d
