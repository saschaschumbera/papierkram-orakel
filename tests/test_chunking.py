"""Chunking: keine Modelle, keine Netzwerkzugriffe."""
from core.chunking import chunk_document, split_text


def test_short_text_stays_one_chunk():
    assert split_text("Ein kurzer Absatz.", chunk_size=800, overlap=80) == ["Ein kurzer Absatz."]


def test_paragraphs_are_packed_up_to_chunk_size():
    text = "\n\n".join(["Absatz " + str(i) + " " + "x" * 100 for i in range(10)])
    chunks = split_text(text, chunk_size=300, overlap=30)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_oversized_paragraph_is_hard_split():
    chunks = split_text("y" * 2500, chunk_size=700, overlap=70)
    assert len(chunks) >= 4
    assert all(len(c) <= 700 for c in chunks)


def test_overlap_carries_tail_into_next_chunk():
    a, b = "A" * 200, "B" * 200
    chunks = split_text(a + "\n\n" + b, chunk_size=250, overlap=50)
    assert len(chunks) == 2
    assert chunks[1].startswith("A" * 50)


def test_chunk_document_keeps_source_and_location_and_increments_index():
    sections = [("Kapitel 1", "Text eins."), ("Kapitel 2", "Text zwei.")]
    chunks = chunk_document("handbuch.md", sections, chunk_size=800, overlap=80)
    assert [c.location for c in chunks] == ["Kapitel 1", "Kapitel 2"]
    assert all(c.source == "handbuch.md" for c in chunks)
    assert [c.index for c in chunks] == [0, 1]
