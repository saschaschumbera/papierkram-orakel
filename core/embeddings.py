"""Local, free stand-ins for the usual hosted Embed / Rerank APIs.

Both models are multilingual (German included), run on CPU and are loaded
lazily so `python cli.py --help` doesn't pay the download/load cost.
Swap EMBEDDING_MODEL_NAME / RERANKER_MODEL_NAME for an Ollama or API-based
model without touching store.py or rag.py -- they only see plain vectors
and float scores.
"""
from __future__ import annotations

import os
import warnings

# Force the torch backend: avoids transformers pulling in an incompatible
# TensorFlow/Keras install that may happen to sit on this machine.
os.environ.setdefault("USE_TF", "0")
warnings.filterwarnings("ignore", message="`clean_up_tokenization_spaces`")

from functools import lru_cache

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANKER_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANKER_MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = _embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def rerank(query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    pairs = [(query, doc) for doc in documents]
    scores = _reranker().predict(pairs)
    return [float(s) for s in scores]
