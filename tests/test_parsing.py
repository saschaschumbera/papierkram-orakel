"""Parser fuer die text-basierten Formate (PDF-OCR wird separat im
End-to-End-Lauf geprueft)."""
import pytest

from core.parsing import PARSERS, parse_document, parse_markdown, parse_txt


def test_markdown_splits_on_headings(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("Intro-Text\n\n# Erster Teil\n\nInhalt A\n\n## Zweiter Teil\n\nInhalt B", encoding="utf-8")
    sections = parse_markdown(p)
    labels = [label for label, _ in sections]
    assert labels == ["Einleitung", "Erster Teil", "Zweiter Teil"]
    assert sections[1][1] == "Inhalt A"


def test_txt_returns_single_section(tmp_path):
    p = tmp_path / "doc.txt"
    p.write_text("Nur etwas Text.", encoding="utf-8")
    assert parse_txt(p) == [("", "Nur etwas Text.")]


def test_empty_txt_yields_nothing(tmp_path):
    p = tmp_path / "leer.txt"
    p.write_text("   \n", encoding="utf-8")
    assert parse_txt(p) == []


def test_unknown_suffix_raises(tmp_path):
    p = tmp_path / "tabelle.xlsx"
    p.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError, match="Kein Parser"):
        parse_document(p)


def test_expected_formats_are_registered():
    for suffix in (".pdf", ".md", ".txt", ".docx", ".jpg", ".png", ".heic"):
        assert suffix in PARSERS
