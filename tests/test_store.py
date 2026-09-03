"""Hybrid-Store: nutzt echtes SQLite + sqlite-vec, aber Fake-Vektoren
(keine Embedding-Modelle noetig)."""
import pytest

from core.chunking import Chunk
from core.embeddings import EMBEDDING_DIM
from core.store import (
    _fts_query,
    add_chunks,
    all_chunks,
    count_chunks,
    hybrid_search,
    reset_db,
    total_chars,
)


def _vec(*weights: float) -> list[float]:
    """Vektor der Dimension EMBEDDING_DIM, nur die ersten Stellen gesetzt."""
    v = [0.0] * EMBEDDING_DIM
    for i, w in enumerate(weights):
        v[i] = w
    return v


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test.db"
    reset_db(path)
    chunks = [
        Chunk(text="Waschprogramm Wolle bei 30 Grad", source="bosch.md", location="Programme", index=0),
        Chunk(text="Fehlercode E04 bedeutet Unwucht", source="bosch.md", location="Fehler", index=1),
        Chunk(text="Apfelkuchen mit 300 g Mehl backen", source="kochbuch.md", location="Kuchen", index=2),
    ]
    embeddings = [_vec(1, 0), _vec(0, 1), _vec(0.7, 0.7)]
    add_chunks(path, chunks, embeddings)
    return path


def test_reset_and_count(db):
    assert count_chunks(db) == 3


def test_all_chunks_returns_document_order(db):
    rows = all_chunks(db)
    assert [r.location for r in rows] == ["Programme", "Fehler", "Kuchen"]


def test_total_chars_sums_chunk_text(db):
    assert total_chars(db) == sum(
        len(t) for t in [
            "Waschprogramm Wolle bei 30 Grad",
            "Fehlercode E04 bedeutet Unwucht",
            "Apfelkuchen mit 300 g Mehl backen",
        ]
    )


def test_fts_query_builds_or_of_quoted_tokens():
    assert _fts_query("Wolle 30 Grad") == '"wolle" OR "30" OR "grad"'


def test_fts_query_drops_stopwords():
    assert _fts_query("wie viele Steckdosen pro Etage") == '"steckdosen" OR "etage"'


def test_fts_query_keeps_all_tokens_if_only_stopwords():
    assert _fts_query("wie viele pro") == '"wie" OR "viele" OR "pro"'


def test_fts_query_handles_empty_input():
    assert _fts_query("   ") == '""'


def test_lexical_hit_wins_on_exact_term(db):
    results = hybrid_search(db, "Unwucht", _vec(0, 0), top_k_vector=3, top_k_fts=3, top_k_final=1)
    assert results[0].source == "bosch.md"
    assert results[0].location == "Fehler"


def test_vector_hit_wins_without_lexical_overlap(db):
    # Frage-Text ohne gemeinsame Tokens, aber Vektor zeigt auf Chunk 0
    results = hybrid_search(db, "xyzxyz", _vec(1, 0), top_k_vector=3, top_k_fts=3, top_k_final=1)
    assert results[0].location == "Programme"


def test_final_pool_is_capped(db):
    results = hybrid_search(db, "Mehl Grad Unwucht", _vec(0.7, 0.7), top_k_vector=3, top_k_fts=3, top_k_final=2)
    assert len(results) == 2
