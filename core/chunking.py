"""Paragraph-aware recursive chunking, matching the video's guidance:
target ~800 chars, small (~10%) overlap -- not 50%, that's overkill.
Splits on paragraph boundaries where possible so we don't cut mid-sentence.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.parsing import Section


@dataclass
class Chunk:
    text: str
    source: str
    location: str
    index: int


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    def flush(tail_overlap: bool) -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = current[-overlap:] if (tail_overlap and overlap) else ""

    for para in paragraphs:
        if len(para) > chunk_size:
            flush(tail_overlap=False)
            step = max(chunk_size - overlap, 1)
            for i in range(0, len(para), step):
                chunks.append(para[i : i + chunk_size])
            continue

        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            flush(tail_overlap=True)
            current = f"{current}\n\n{para}".strip() if current else para

    if current:
        chunks.append(current)
    return chunks


def chunk_document(
    source: str, sections: list[Section], chunk_size: int, overlap: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for location, text in sections:
        for piece in split_text(text, chunk_size, overlap):
            chunks.append(Chunk(text=piece, source=source, location=location, index=idx))
            idx += 1
    return chunks
