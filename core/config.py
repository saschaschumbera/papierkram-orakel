"""Domain configuration: each domain is a self-contained plug-in.

A domain is just a folder under domains/<slug>/ with:
  - domain.yaml   (this file's schema)
  - raw/          (source documents: .pdf, .md, .txt)

No core code needs to change to add a new domain.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

DOMAINS_DIR = Path(__file__).resolve().parent.parent / "domains"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DEFAULT_PERSONA = (
    "Du bist ein hilfreicher Assistent, der ausschließlich auf Basis der "
    "bereitgestellten Quellenausschnitte antwortet und jede Aussage mit der "
    "Quelle belegt."
)


@dataclass
class DomainConfig:
    slug: str
    display_name: str
    emoji: str = "📄"
    description: str = ""
    persona: str = DEFAULT_PERSONA
    chunk_size: int = 800
    chunk_overlap: int = 80
    top_k_vector: int = 15
    top_k_fts: int = 15
    top_k_final: int = 12
    rerank: bool = True
    llm_model: str = "haiku"
    # Passt der gesamte Domain-Text in dieses Zeichen-Budget (~4 Zeichen/Token,
    # 500k ~= 125k Token, viel Reserve unter Claudes 200k), geht er komplett
    # ans LLM statt durch die Suche. Deckt praktisch jede private
    # Dokumentensammlung ab. 0 = immer Hybrid-Suche.
    full_context_max_chars: int = 500_000

    @property
    def raw_dir(self) -> Path:
        return DOMAINS_DIR / self.slug / "raw"

    @property
    def db_path(self) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DATA_DIR / f"{self.slug}.db"


def load_domain(slug: str) -> DomainConfig:
    path = DOMAINS_DIR / slug / "domain.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Domain '{slug}' hat keine domain.yaml unter {path}"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DomainConfig(slug=slug, **raw)


def discover_domains() -> list[DomainConfig]:
    if not DOMAINS_DIR.exists():
        return []
    domains = []
    for entry in sorted(DOMAINS_DIR.iterdir()):
        if (entry / "domain.yaml").exists():
            domains.append(load_domain(entry.name))
    return domains


_UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def slugify(name: str) -> str:
    text = name.strip().lower()
    for umlaut, replacement in _UMLAUTE.items():
        text = text.replace(umlaut, replacement)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "domain"


def create_domain(
    display_name: str,
    emoji: str = "📄",
    description: str = "",
    persona: str | None = None,
    slug: str | None = None,
) -> DomainConfig:
    slug = slugify(slug or display_name)
    domain_dir = DOMAINS_DIR / slug
    if (domain_dir / "domain.yaml").exists():
        raise FileExistsError(f"Domain '{slug}' existiert bereits.")

    (domain_dir / "raw").mkdir(parents=True, exist_ok=True)
    data: dict = {"display_name": display_name, "emoji": emoji, "description": description}
    if persona:
        data["persona"] = persona
    (domain_dir / "domain.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return load_domain(slug)


_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def _domain_dir(slug: str) -> Path:
    """Slug validieren (kein Path-Traversal aus URL-Parametern) und Ordner liefern."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"Ungültiger Domain-Name: {slug!r}")
    return DOMAINS_DIR / slug


def delete_domain(slug: str) -> None:
    domain_dir = _domain_dir(slug)
    if not (domain_dir / "domain.yaml").exists():
        raise FileNotFoundError(f"Domain '{slug}' existiert nicht.")
    shutil.rmtree(domain_dir)
    db = DATA_DIR / f"{slug}.db"
    if db.exists():
        db.unlink()


def set_domain_model(slug: str, model: str) -> DomainConfig:
    path = _domain_dir(slug) / "domain.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Domain '{slug}' existiert nicht.")
    # Nur die eine Zeile ersetzen, statt die YAML durch safe_dump zu jagen --
    # das wuerde Blockskalar-Personas und Kommentare zerschiessen.
    text = path.read_text(encoding="utf-8")
    line = f"llm_model: {model}"
    if re.search(r"(?m)^llm_model:.*$", text):
        text = re.sub(r"(?m)^llm_model:.*$", line, text)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text, encoding="utf-8")
    return load_domain(slug)
