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

    # --- Embedding model (free, lightweight, multilingual EN+JA) ---
    # multilingual-e5-large: strong MTEB scores for both English and Japanese.
    # E5 models REQUIRE the "query:" / "passage:" prefixes used in this app.
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024
    max_seq_length: int = 512           # tokens per chunk fed to the encoder
    chunk_overlap_tokens: int = 64
    device: str = "auto"                # auto | cpu | cuda | mps

    # --- Retrieval ---
    top_k: int = 10                     # max results shown
    similarity_threshold: float = 0.78  # cosine; results below are hidden
    # Aggregate per-document score from its chunk scores: "max" or "mean".
    score_aggregation: str = "max"

    # --- Indexing ---
    item_types: tuple = ("journalArticle", "preprint", "conferencePaper",
                         "book", "bookSection", "report", "thesis")
    batch_size: int = 16

    @classmethod
    def path(cls) -> Path:
        return app_data_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                known = {f for f in cls.__dataclass_fields__}
                clean = {k: v for k, v in data.items() if k in known}
                if "item_types" in clean:
                    clean["item_types"] = tuple(clean["item_types"])
                return cls(**clean)
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
    def model_cache_dir(self) -> Path:
        d = app_data_dir() / "models"
        d.mkdir(parents=True, exist_ok=True)
        return d
