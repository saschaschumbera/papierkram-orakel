#!/usr/bin/env python
"""Papierkram-Orakel CLI.

Beispiele:
    python cli.py list
    python cli.py ingest anleitungen
    python cli.py ingest --all
    python cli.py ask anleitungen "Welches Waschprogramm fuer Wolle?"
"""
from __future__ import annotations

import argparse
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.config import discover_domains, load_domain
from core.rag import answer_question, ingest_domain


def cmd_list(_args: argparse.Namespace) -> None:
    domains = discover_domains()
    if not domains:
        print("Keine Domains gefunden. Lege einen Ordner domains/<name>/domain.yaml an.")
        return
    for d in domains:
        print(f"{d.emoji}  {d.slug:15s} {d.display_name} - {d.description}")


def cmd_ingest(args: argparse.Namespace) -> None:
    if args.all:
        targets = discover_domains()
    elif args.domain:
        targets = [load_domain(args.domain)]
    else:
        print("Gib eine Domain an oder nutze --all", file=sys.stderr)
        sys.exit(2)

    for d in targets:
        print(f"Indexiere {d.emoji} {d.display_name} ...")
        n = ingest_domain(d)
        print(f"  -> {n} Chunks gespeichert in {d.db_path}")


def cmd_ask(args: argparse.Namespace) -> None:
    d = load_domain(args.domain)
    print(f"{d.emoji} {d.display_name} | Frage: {args.question}\n")
    answer = answer_question(d, args.question)
    print(answer.text)
    print("\nQuellen:")
    for s in answer.sources:
        print(f"  - {s.source} | {s.location}")
    if answer.context_tokens:
        cached = " | Prompt-Cache aktiv" if answer.cached_tokens else ""
        print(
            f"\n[{answer.retrieval} | {answer.model} | "
            f"~{answer.context_tokens} Token Dokument-Kontext{cached}]"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Verfuegbare Domains anzeigen").set_defaults(func=cmd_list)

    p_ingest = sub.add_parser("ingest", help="Domain(s) parsen, chunken, einbetten, speichern")
    p_ingest.add_argument("domain", nargs="?", help="Domain-Slug, z.B. anleitungen")
    p_ingest.add_argument("--all", action="store_true", help="Alle Domains indexieren")
    p_ingest.set_defaults(func=cmd_ingest)

    p_ask = sub.add_parser("ask", help="Frage an eine Domain stellen")
    p_ask.add_argument("domain")
    p_ask.add_argument("question")
    p_ask.set_defaults(func=cmd_ask)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
