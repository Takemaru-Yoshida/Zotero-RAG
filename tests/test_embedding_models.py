"""Embedding model profiles, settings migration and index/model matching."""
from __future__ import annotations

import json

import numpy as np
import pytest

from src.config import CONFIG_VERSION, Config
from src.embedding_models import (DEFAULT_MODEL, FIRST_RUN_MODELS, LEGACY_MODEL,
                                  LIGHT_MODEL, MODEL_PROFILES, profile_for,
                                  recommended_model)
from src.ui.model_choice import needs_model_choice
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


# -- choosing the model at the first start ---------------------------------- #
def test_light_model_profile():
    light = profile_for(LIGHT_MODEL)
    assert light.name == "Qwen/Qwen3-Embedding-0.6B" and light.dim == 1024
    assert light.query_prefix == profile_for(DEFAULT_MODEL).query_prefix
    assert light.left_padding and light.passage_prefix == ""
    assert FIRST_RUN_MODELS == (DEFAULT_MODEL, LIGHT_MODEL)


def test_recommendation_follows_memory():
    assert recommended_model(8) == LIGHT_MODEL
    assert recommended_model(16) == DEFAULT_MODEL
    assert recommended_model(24) == DEFAULT_MODEL


def test_new_install_is_asked_for_the_model(app_home):
    config = Config.load()                      # no config.json yet
    assert not config.model_chosen
    assert needs_model_choice(config)


def test_answer_is_remembered(app_home):
    config = Config.load()
    config.use_model(LIGHT_MODEL)
    config.model_chosen = True
    config.save()
    again = Config.load()
    assert not needs_model_choice(again)
    assert (again.embedding_model, again.embedding_dim) == (LIGHT_MODEL, 1024)
    assert again.similarity_threshold == MODEL_PROFILES[LIGHT_MODEL].default_threshold


def test_install_from_before_the_question_is_not_asked(app_home):
    Config.path().write_text(json.dumps({
        "config_version": 2, "embedding_model": LEGACY_MODEL}), encoding="utf-8")
    (app_home / "metadata.json").write_text(
        json.dumps({"embedding_model": LEGACY_MODEL}), encoding="utf-8")
    config = Config.load()
    assert config.model_chosen and not needs_model_choice(config)
    assert config.embedding_model == LEGACY_MODEL
    assert json.loads(Config.path().read_text(encoding="utf-8"))["model_chosen"]


def test_old_install_without_index_is_asked(app_home):
    Config.path().write_text(json.dumps({
        "config_version": 2, "embedding_model": DEFAULT_MODEL}), encoding="utf-8")
    assert needs_model_choice(Config.load())


def test_lost_settings_keep_the_model_of_the_index(app_home):
    (app_home / "metadata.json").write_text(
        json.dumps({"embedding_model": LIGHT_MODEL}), encoding="utf-8")
    config = Config.load()                      # no config.json: defaults
    assert not needs_model_choice(config)
    again = Config.load()
    assert again.model_chosen
    assert (again.embedding_model, again.embedding_dim) == (LIGHT_MODEL, 1024)
