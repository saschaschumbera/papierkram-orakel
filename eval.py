#!/usr/bin/env python
"""Quality eval harness.

Not a rigorous benchmark, but a lot more honest than a handful of ad-hoc
spot checks: a hand-written test set with a known expected source file and
expected keyword(s) per question, checked automatically against what the
pipeline actually retrieves and answers.

Usage:
    python eval.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.config import load_domain
from core.rag import answer_question


@dataclass
class Case:
    domain: str
    question: str
    expect_source: str  # substring that must appear in a cited source filename
    expect_keywords: list[str]  # at least one must appear in the generated answer


CASES = [
    Case("anleitungen", "Welches Waschprogramm nutze ich fuer meinen Wollpullover bei der Bosch WAT28?",
         "bosch_wat28", ["Programm 4", "Wolle"]),
    Case("anleitungen", "Welche Artikelnummer hat das Trommellager-Set fuer die WAT28xxx?",
         "ersatzteilkatalog", ["119"]),
    Case("anleitungen", "Welchen Schneckenradsatz brauche ich fuer ein Geraet der Serie 6?",
         "ersatzteilkatalog", ["283"]),
    Case("anleitungen", "Was bedeutet der Fehlercode E:04 bei der Waschmaschine?",
         "bosch_wat28", ["Unwucht"]),
    Case("anleitungen", "Mein Backofen zeigt F13 an, was soll ich tun?",
         "miele", ["Kundendienst"]),
    Case("anleitungen", "Wie oft sollte ich die Bosch Waschmaschine entkalken?",
         "bosch_wat28", ["2 Monate", "zwei Monate"]),
    Case("anleitungen", "Welche Tuerdichtung passt zu einem Geraet der Serie 8?",
         "ersatzteilkatalog", ["342"]),
    Case("anleitungen", "Meine impraegnierte Regenjacke will ich waschen, welches Programm?",
         "bosch_wat28", ["Programm 6", "Outdoor"]),
    Case("vertraege", "Wie lange ist die Mindestlaufzeit meines Handyvertrags?",
         "mobilfunkvertrag", ["24 Monate"]),
    Case("vertraege", "Kann ich sofort kuendigen, wenn der Preis erhoeht wird?",
         "mobilfunkvertrag", ["Sonderkündigungsrecht", "4 Wochen"]),
    Case("vertraege", "Wie hoch ist die Kaution fuer meine Wohnung?",
         "mietvertrag", ["drei", "3"]),
    Case("vertraege", "Darf ich einen Hund in meiner Mietwohnung halten?",
         "mietvertrag", ["Zustimmung", "schriftlich"]),
    Case("garantien", "Wie lange gilt die Garantie auf den Motor meiner Waschmaschine?",
         "garantie_waschmaschine", ["10 Jahre"]),
    Case("garantien", "Ist ein Kalkschaden durch unterlassene Entkalkung abgedeckt?",
         "garantie_waschmaschine", ["ausgeschlossen", "nicht"]),
    Case("garantien", "Was steht auf meinem Kaufbeleg fuer das ThinkPad?",
         "kaufbeleg", ["1.899", "PF-77213"]),
    Case("garantien", "Ist ein Sturzschaden bei meinem Laptop abgedeckt?",
         "garantie_laptop", ["Accidental Damage", "89"]),
    Case("rezepte", "Wieviel Mehl brauche ich fuer den Apfelkuchen?",
         "familienkochbuch", ["300"]),
    Case("rezepte", "Ich habe keine Sahne, was kann ich fuer die Bolognese stattdessen nehmen?",
         "familienkochbuch", ["Butter"]),
    Case("rezepte", "Wie lange muss die Kartoffelsuppe kochen?",
         "familienkochbuch", ["20", "25"]),
    Case("rezepte", "Was kann ich als vegetarische Variante der Kartoffelsuppe machen?",
         "familienkochbuch", ["Kürbiskerne", "weglassen"]),
]


def run() -> None:
    domain_cache = {}
    retrieval_hits = 0
    answer_hits = 0

    for case in CASES:
        if case.domain not in domain_cache:
            domain_cache[case.domain] = load_domain(case.domain)
        domain = domain_cache[case.domain]

        answer = answer_question(domain, case.question)

        retrieval_hit = any(case.expect_source.lower() in s.source.lower() for s in answer.sources)
        answer_lower = answer.text.lower()
        answer_hit = any(kw.lower() in answer_lower for kw in case.expect_keywords)

        retrieval_hits += int(retrieval_hit)
        answer_hits += int(answer_hit)

        status = "OK  " if (retrieval_hit and answer_hit) else "FAIL"
        print(f"[{status}] {case.domain:12s} | {case.question}")
        if not retrieval_hit:
            got = [s.source for s in answer.sources]
            print(f"        Retrieval-Miss: erwartet Quelle '{case.expect_source}', bekommen: {got}")
        if not answer_hit:
            print(f"        Keyword-Miss: erwartet eines von {case.expect_keywords}")
            print(f"        Antwort war: {answer.text[:200]}")

    n = len(CASES)
    print()
    print(f"Retrieval-Trefferquote:        {retrieval_hits}/{n} ({100 * retrieval_hits / n:.0f}%)")
    print(f"Antwort-Keyword-Trefferquote:  {answer_hits}/{n} ({100 * answer_hits / n:.0f}%)")


if __name__ == "__main__":
    run()
