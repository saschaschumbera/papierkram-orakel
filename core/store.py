"""Per-domain hybrid store: one SQLite file with two search paths, mirroring
the video's Hybrid Search:

  - vec_chunks (sqlite-vec):  semantic / cosine-ish nearest-neighbour search
  - fts_chunks (SQLite FTS5): BM25 lexical search (exact terms, IDs, names)

Results from both are merged with Reciprocal Rank Fusion (RRF), exactly the
mathematical trick named in the video.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from core.chunking import Chunk
from core.embeddings import EMBEDDING_DIM


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.row_factory = sqlite3.Row
    return con


def init_db(db_path: Path) -> None:
    con = _connect(db_path)
    con.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            location TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
            text
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            embedding float[{EMBEDDING_DIM}]
        );
        """
    )
    con.commit()
    con.close()


def reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)


def add_chunks(db_path: Path, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    con = _connect(db_path)
    cur = con.cursor()
    for chunk, vector in zip(chunks, embeddings):
        cur.execute(
            "INSERT INTO chunks (source, location, chunk_index, text) VALUES (?, ?, ?, ?)",
            (chunk.source, chunk.location, chunk.index, chunk.text),
        )
        row_id = cur.lastrowid
        cur.execute("INSERT INTO fts_chunks (rowid, text) VALUES (?, ?)", (row_id, chunk.text))
        cur.execute(
            "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
            (row_id, sqlite_vec.serialize_float32(vector)),
        )
    con.commit()
    con.close()


def count_chunks(db_path: Path) -> int:
    con = _connect(db_path)
    n = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    con.close()
    return n


def all_chunks(db_path: Path) -> list["SearchResult"]:
    """Alle Chunks in Dokumentreihenfolge -- fuer kleine Domains, bei denen
    das ganze Dokument statt einer Retrieval-Auswahl ans LLM geht."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT id, source, location, text FROM chunks ORDER BY chunk_index"
        ).fetchall()
    finally:
        con.close()
    return [SearchResult(r["id"], r["source"], r["location"], r["text"], 0.0) for r in rows]


def total_chars(db_path: Path) -> int:
    """Gesamtlaenge des Domain-Texts -- entscheidet, ob die Domain komplett
    ins Kontextfenster passt."""
    con = _connect(db_path)
    try:
        return con.execute("SELECT COALESCE(SUM(LENGTH(text)), 0) FROM chunks").fetchone()[0]
    finally:
        con.close()


@dataclass
class SearchResult:
    id: int
    source: str
    location: str
    text: str
    score: float


def _row_to_result(row: sqlite3.Row, score: float) -> SearchResult:
    return SearchResult(row["id"], row["source"], row["location"], row["text"], score)


def vector_search(con: sqlite3.Connection, query_vector: list[float], top_k: int) -> list[SearchResult]:
    rows = con.execute(
        """
        SELECT c.id, c.source, c.location, c.text, v.distance AS distance
        FROM vec_chunks v
        JOIN chunks c ON c.id = v.rowid
        WHERE v.embedding MATCH ? AND k = ?
        ORDER BY v.distance
        """,
        (sqlite_vec.serialize_float32(query_vector), top_k),
    ).fetchall()
    return [_row_to_result(r, r["distance"]) for r in rows]


# Hochfrequente Frage-Wörter, die als OR-Token die seltenen Fachbegriffe
# in der BM25-Bewertung nur verwässern.
_FTS_STOPWORDS = {
    "der", "die", "das", "dem", "den", "des", "ein", "eine", "einen", "einem", "einer",
    "und", "oder", "aber", "ist", "sind", "war", "waren", "wird", "werden", "wurde",
    "hat", "haben", "habe", "kann", "muss", "soll", "will",
    "wie", "was", "wer", "wo", "wann", "warum", "welche", "welcher", "welches",
    "viel", "viele", "pro", "je", "für", "von", "mit", "auf", "in", "im", "an", "am",
    "zu", "zum", "zur", "bei", "aus", "nach", "über", "unter", "vor",
    "ich", "du", "er", "sie", "es", "wir", "man", "mein", "meine", "meinen",
    "sich", "nicht", "auch", "noch", "nur", "denn", "dann",
}


def _fts_query(text: str) -> str:
    tokens = [t for t in text.lower().replace('"', " ").split() if t]
    if not tokens:
        return '""'
    kept = [t for t in tokens if t not in _FTS_STOPWORDS] or tokens
    return " OR ".join(f'"{t}"' for t in kept)


def fts_search(con: sqlite3.Connection, query_text: str, top_k: int) -> list[SearchResult]:
    rows = con.execute(
        """
        SELECT c.id, c.source, c.location, c.text, bm25(fts_chunks) AS rank
        FROM fts_chunks
        JOIN chunks c ON c.id = fts_chunks.rowid
        WHERE fts_chunks MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (_fts_query(query_text), top_k),
    ).fetchall()
    return [_row_to_result(r, r["rank"]) for r in rows]


def hybrid_search(
    db_path: Path,
    query_text: str,
    query_vector: list[float],
    top_k_vector: int,
    top_k_fts: int,
    top_k_final: int,
    rrf_k: int = 60,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion of vector + lexical search, as in the video:
    score(doc) = sum over both rankings of 1 / (rrf_k + rank)."""
    con = _connect(db_path)
    try:
        vec_hits = vector_search(con, query_vector, top_k_vector)
        fts_hits = fts_search(con, query_text, top_k_fts)
    finally:
        con.close()

    fused_scores: dict[int, float] = {}
    lookup: dict[int, SearchResult] = {}
    for rank, hit in enumerate(vec_hits, start=1):
        fused_scores[hit.id] = fused_scores.get(hit.id, 0.0) + 1.0 / (rrf_k + rank)
        lookup[hit.id] = hit
    for rank, hit in enumerate(fts_hits, start=1):
        fused_scores[hit.id] = fused_scores.get(hit.id, 0.0) + 1.0 / (rrf_k + rank)
        lookup[hit.id] = hit

    ranked_ids = sorted(fused_scores, key=lambda i: fused_scores[i], reverse=True)[:top_k_final]
    return [_row_to_result_from_lookup(lookup[i], fused_scores[i]) for i in ranked_ids]


def _row_to_result_from_lookup(hit: SearchResult, score: float) -> SearchResult:
    return SearchResult(hit.id, hit.source, hit.location, hit.text, score)
