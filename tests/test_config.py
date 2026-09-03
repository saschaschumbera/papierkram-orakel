"""Domain-Konfiguration und -Discovery."""
import pytest

import core.config as config
from core.config import (
    _domain_dir,
    delete_domain,
    discover_domains,
    load_domain,
    set_domain_model,
    slugify,
)


def test_slugify_handles_umlauts_and_spaces():
    assert slugify("Verträge & Versicherungen") == "vertraege_versicherungen"
    assert slugify("Möbel-Aufbau") == "moebel_aufbau"
    assert slugify("  Steuer 2025  ") == "steuer_2025"


def test_example_domains_are_discovered():
    slugs = {d.slug for d in discover_domains()}
    assert {"anleitungen", "vertraege", "garantien", "rezepte"} <= slugs


def test_load_domain_reads_yaml_fields():
    d = load_domain("rezepte")
    assert d.display_name == "Rezepte"
    assert d.emoji == "🍲"
    assert d.llm_model  # aus domain.yaml oder Default


def test_create_domain_writes_scaffold(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOMAINS_DIR", tmp_path)
    d = config.create_domain("Test Domain", emoji="🧪", description="nur ein Test")
    assert d.slug == "test_domain"
    assert (tmp_path / "test_domain" / "domain.yaml").exists()
    assert (tmp_path / "test_domain" / "raw").is_dir()


def test_set_domain_model_persists_to_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOMAINS_DIR", tmp_path)
    config.create_domain("Notizen", slug="notizen")
    d = set_domain_model("notizen", "opus")
    assert d.llm_model == "opus"
    assert load_domain("notizen").llm_model == "opus"


def test_set_domain_model_only_touches_one_line(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOMAINS_DIR", tmp_path)
    yaml_text = (
        'display_name: "Test"\n'
        "persona: |\n"
        "  Zeile eins.\n"
        "\n"
        "  Zeile zwei mit Absatz.\n"
        "llm_model: haiku\n"
    )
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "domain.yaml").write_text(yaml_text, encoding="utf-8")
    (tmp_path / "t" / "raw").mkdir()

    set_domain_model("t", "sonnet")

    assert (tmp_path / "t" / "domain.yaml").read_text(encoding="utf-8") == yaml_text.replace(
        "llm_model: haiku", "llm_model: sonnet"
    )


def test_delete_domain_removes_folder_and_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOMAINS_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    config.create_domain("Wegwerf", slug="wegwerf")
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "wegwerf.db").write_bytes(b"x")

    delete_domain("wegwerf")

    assert not (tmp_path / "wegwerf").exists()
    assert not (tmp_path / "data" / "wegwerf.db").exists()


def test_delete_domain_rejects_path_traversal():
    with pytest.raises(ValueError):
        _domain_dir("../evil")


def test_delete_missing_domain_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOMAINS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        delete_domain("gibtsnicht")
