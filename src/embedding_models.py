"""Registry of the embedding models the app knows how to drive.

Each model family expects its own input format (E5 wants ``query:`` /
``passage:`` prefixes, Qwen3-Embedding wants an instruction in front of the
query only) and produces cosine scores on its own scale, so the prefixes, the
vector size and a sensible similarity threshold are kept together here.

Any other sentence-transformers model can still be named in the config; it is
run without prefixes (see ``profile_for``).
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MODEL = "Qwen/Qwen3-Embedding-4B"
# The model every index was built with before the model was recorded in it.
LEGACY_MODEL = "intfloat/multilingual-e5-large"

LIGHT_MODEL = "Qwen/Qwen3-Embedding-0.6B"
# Offered when the app starts for the first time, best quality first.
FIRST_RUN_MODELS = (DEFAULT_MODEL, LIGHT_MODEL)
# Memory below which the 4B model (about 8 GB of weights) is not recommended.
LARGE_MODEL_MEMORY_GB = 16

_QWEN_QUERY = ("Instruct: Given a web search query, retrieve relevant passages "
               "that answer the query\nQuery:")


@dataclass(frozen=True)
class ModelProfile:
    name: str
    dim: int
    query_prefix: str = ""
    passage_prefix: str = ""
    # Cosine below which a passage is treated as unrelated to the query.
    default_threshold: float = 0.5
    # Load the weights as float16 on GPU (halves memory; needed for the
    # multi-billion-parameter models on a laptop).
    half_precision: bool = False
    # Last-token pooling models need the padding on the left.
    left_padding: bool = False
    label: str = ""


MODEL_PROFILES: dict[str, ModelProfile] = {p.name: p for p in (
    ModelProfile(
        name="Qwen/Qwen3-Embedding-4B", dim=2560, query_prefix=_QWEN_QUERY,
        default_threshold=0.45, half_precision=True, left_padding=True,
        label="Qwen3-Embedding-4B（高精度・約 8 GB）"),
    ModelProfile(
        name=LIGHT_MODEL, dim=1024, query_prefix=_QWEN_QUERY,
        default_threshold=0.45, half_precision=True, left_padding=True,
        label="Qwen3-Embedding-0.6B（軽量・約 1.2 GB）"),
    ModelProfile(
        name=LEGACY_MODEL, dim=1024, query_prefix="query: ",
        passage_prefix="passage: ", default_threshold=0.78,
        label="multilingual-e5-large（従来・約 2.1 GB）"),
)}


def profile_for(name: str, dim: int = 0) -> ModelProfile:
    """Profile of ``name``; an unknown model runs without prefixes at ``dim``."""
    known = MODEL_PROFILES.get(name)
    if known is not None:
        return known
    return ModelProfile(name=name, dim=dim, label=name)


def recommended_model(memory_gb: float) -> str:
    """The first-run model that suits a machine with this much memory."""
    return DEFAULT_MODEL if memory_gb >= LARGE_MODEL_MEMORY_GB else LIGHT_MODEL
