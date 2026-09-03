"""Orchestrates the two phases from the video:

  1. Indexing   (ingest_domain):  parse -> chunk -> embed -> store
  2. Retrieval  (answer_question): embed query -> hybrid search -> rerank
                                    -> generate cited answer

Passt der gesamte Domain-Text in domain.full_context_max_chars, ueberspringt
answer_question die Suche komplett und schickt alles ans LLM. Das ist bei
kleinen bis mittleren Bestaenden strikt besser als eine Retrieval-Auswahl --
besonders bei "wie viele ..."- / "liste alle ..."-Fragen, die ueber einen
ganzen Abschnitt zusammenzaehlen muessen.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.chunking import chunk_document
from core.config import DomainConfig
from core.embeddings import embed_query, embed_texts, rerank as rerank_fn
from core.llm import generate_answer
from core.parsing import parse_document
from core.store import (
    add_chunks,
    all_chunks,
    count_chunks,
    hybrid_search,
    reset_db,
    total_chars,
)


def ingest_domain(domain: DomainConfig) -> int:
    reset_db(domain.db_path)
    raw_files = sorted(p for p in domain.raw_dir.glob("*") if p.is_file())
    if not raw_files:
        raise FileNotFoundError(
            f"Keine Dateien in {domain.raw_dir} - lege dort .pdf/.md/.txt Dateien ab."
        )

    chunks = []
    for path in raw_files:
        sections = parse_document(path)
        chunks.extend(
            chunk_document(path.name, sections, domain.chunk_size, domain.chunk_overlap)
        )

    if not chunks:
        raise ValueError(f"Keine extrahierbaren Inhalte in {domain.raw_dir}.")

    embeddings = embed_texts([c.text for c in chunks])
    add_chunks(domain.db_path, chunks, embeddings)
    return len(chunks)


@dataclass
class Source:
    source: str
    location: str
    excerpt: str


@dataclass
class Answer:
    text: str
    sources: list[Source]
    model: str
    retrieval: str  # "ganzes-dokument" | "hybrid-suche"
    context_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0


def _answer(llm, sources, model, retrieval) -> "Answer":
    return Answer(
        text=llm.text,
        sources=sources,
        model=model,
        retrieval=retrieval,
        context_tokens=llm.context_tokens,
        cached_tokens=llm.cached_tokens,
        output_tokens=llm.output_tokens,
    )


def answer_question(
    domain: DomainConfig, question: str, model: str | None = None
) -> Answer:
    n = count_chunks(domain.db_path) if domain.db_path.exists() else 0
    if n == 0:
        raise RuntimeError(
            f"Domain '{domain.slug}' wurde noch nicht indexiert. "
            f"Führe zuerst 'python cli.py ingest {domain.slug}' aus."
        )

    used_model = model or domain.llm_model

    budget = domain.full_context_max_chars
    if budget and total_chars(domain.db_path) <= budget:
        chunks = all_chunks(domain.db_path)
        llm = generate_answer(domain, question, chunks, model=used_model)
        # Quellen sind hier die beteiligten Dateien, nicht alle Chunks.
        files = list(dict.fromkeys(c.source for c in chunks))
        sources = [Source(f, "gesamtes Dokument", "") for f in files]
        return _answer(llm, sources, used_model, "ganzes-dokument")

    # Domain zu groß fürs Kontextfenster -> Hybrid-Suche
    query_vector = embed_query(question)
    pool_size = (
        domain.top_k_vector + domain.top_k_fts
        if domain.rerank
        else domain.top_k_final
    )
    candidates = hybrid_search(
        domain.db_path,
        question,
        query_vector,
        top_k_vector=domain.top_k_vector,
        top_k_fts=domain.top_k_fts,
        top_k_final=pool_size,
    )

    if domain.rerank and candidates:
        scores = rerank_fn(question, [c.text for c in candidates])
        candidates = [
            c
            for _, c in sorted(zip(scores, candidates), key=lambda p: p[0], reverse=True)
        ]

    final = candidates[: domain.top_k_final]
    llm = generate_answer(domain, question, final, model=used_model)
    sources = [Source(c.source, c.location, c.text[:220]) for c in final]
    return _answer(llm, sources, used_model, "hybrid-suche")
