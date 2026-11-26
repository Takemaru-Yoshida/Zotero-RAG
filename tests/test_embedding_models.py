"""Embedding model profiles, settings migration and index/model matching."""
from __future__ import annotations

import json

import numpy as np
import pytest

from src.config import CONFIG_VERSION, Config
from src.embedding_models import (DEFAULT_MODEL, LEGACY_MODEL, MODEL_PROFILES,
                                  profile_for)
from src.vector_store import VectorStore

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def app_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOTERO_RAG_HOME", str(tmp_path))
    return tmp_path


def _unit_rows(n: int, dim: int) -> np.ndarray:
    vecs = np.random.default_rng(0).normal(size=(n, dim)).astype(np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def test_default_is_qwen3_4b_with_its_dimension():
    config = Config()
    assert config.embedding_model == DEFAULT_MODEL == "Qwen/Qwen3-Embedding-4B"
    assert config.embedding_dim == 2560
    assert config.similarity_threshold == MODEL_PROFILES[DEFAULT_MODEL].default_threshold


def test_prefixes_follow_the_model_family():
    qwen, e5 = profile_for(DEFAULT_MODEL), profile_for(LEGACY_MODEL)
    assert qwen.query_prefix.startswith("Instruct: ") and qwen.passage_prefix == ""
    assert (e5.query_prefix, e5.passage_prefix) == ("query: ", "passage: ")


def test_unknown_model_keeps_configured_dimension_and_no_prefix():
    config = Config(embedding_model="BAAI/bge-m3", embedding_dim=1024)
    assert config.embedding_dim == 1024
    assert profile_for("BAAI/bge-m3", 1024).query_prefix == ""


def test_old_saved_config_moves_to_the_new_default(app_home):
    Config.path().write_text(json.dumps({
        "embedding_model": LEGACY_MODEL, "embedding_dim": 1024,
        "similarity_threshold": 0.78, "top_k": 50}), encoding="utf-8")
    config = Config.load()
    assert config.embedding_model == DEFAULT_MODEL
    assert config.embedding_dim == 2560
    assert config.similarity_threshold == MODEL_PROFILES[DEFAULT_MODEL].default_threshold
    assert config.top_k == 50                      # other settings survive
    saved = json.loads(Config.path().read_text(encoding="utf-8"))
    assert saved["config_version"] == CONFIG_VERSION


def test_model_chosen_after_migration_is_kept(app_home):
    config = Config()
    config.use_model(LEGACY_MODEL)
    config.save()
    again = Config.load()
    assert again.embedding_model == LEGACY_MODEL
    assert again.embedding_dim == 1024
    assert again.similarity_threshold == 0.78


def test_model_picked_in_settings_applies_at_next_start(app_home):
    config = Config()
    config.similarity_threshold = 0.6          # tuned for the running model
    config.pending_embedding_model = LEGACY_MODEL
    config.save()
    # The running session is untouched ...
    assert (config.embedding_model, config.similarity_threshold) == (DEFAULT_MODEL, 0.6)
    # ... and the next start switches model, size and threshold together.
    again = Config.load()
    assert again.embedding_model == LEGACY_MODEL
    assert again.embedding_dim == 1024
    assert again.similarity_threshold == 0.78
    assert again.pending_embedding_model == ""
    assert Config.load().embedding_model == LEGACY_MODEL


def test_unreadable_version_does_not_reset_other_settings(app_home):
    Config.path().write_text(json.dumps({
        "config_version": None, "embedding_model": "BAAI/bge-m3",
        "embedding_dim": 1024, "top_k": 7}), encoding="utf-8")
    config = Config.load()
    assert (config.embedding_model, config.top_k) == ("BAAI/bge-m3", 7)


def test_index_of_another_model_is_not_loaded(app_home):
    old = Config()
    old.use_model(LEGACY_MODEL)
    store = VectorStore(old)
    store.add_paper({"key": "A", "title": "t"}, _unit_rows(3, 1024))
    store.save()

    same = VectorStore(old)
    assert same.load() and same.n_vectors == 3 and not same.model_changed

    new = VectorStore(Config())
    assert not new.load()
    assert new.model_changed and new.n_vectors == 0 and new.n_papers == 0


def test_index_without_model_tag_counts_as_legacy(app_home):
    old = Config()
    old.use_model(LEGACY_MODEL)
    store = VectorStore(old)
    store.add_paper({"key": "A", "title": "t"}, _unit_rows(2, 1024))
    store.save()
    meta = json.loads(old.meta_path.read_text(encoding="utf-8"))
    del meta["embedding_model"]
    old.meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert VectorStore(old).load()
    assert not VectorStore(Config()).load()
