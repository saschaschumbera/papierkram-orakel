# Papierkram-Orakel — technische Dokumentation

*Für Entwickler und technisch Interessierte. Die vereinfachte Version liegt in
[ANLEITUNG_EINFACH.md](ANLEITUNG_EINFACH.md).*

## Überblick

Lokales RAG-System (Retrieval Augmented Generation) mit domänenbasierter
Wissensorganisation. Pro Domain eine SQLite-Datei als Hybrid-Store; ein LLM
wird ausschließlich für die finale Antwortformulierung eingesetzt — Retrieval
und Ranking laufen komplett lokal und LLM-frei.

```
Indexierung (ingest):   parse → chunk → embed → store
Retrieval (ask):        embed query → hybrid search (Vektor + BM25, RRF)
                        → cross-encoder rerank → LLM-Generierung mit Zitatpflicht
```

Orchestrierung: `core/rag.py` (`ingest_domain()`, `answer_question()`).
Einstiegspunkte: `cli.py` (list/ingest/ask), `webapp.py` (FastAPI),
`eval.py` (Regressions-Testset).

## Pipeline im Detail

### 1. Parsing — `core/parsing.py`

Registry-Pattern: `PARSERS`-Dict mappt Dateiendung → Parser-Funktion.
Jeder Parser liefert `list[Section]` = `(location, text)`-Tupel, wobei
`location` die spätere Zitatquelle ist (PDF-Seite, Markdown-Überschrift, …).

| Format | Verfahren |
|---|---|
| PDF (digital) | PyMuPDF, seitenweise Textextraktion |
| PDF (Scan, keine Textebene) | Tesseract-OCR-Fallback (`deu`), Location wird als `S. n (OCR)` markiert |
| DOCX | python-docx inkl. Tabellen |
| MD / TXT | abschnittsweise nach Überschriften |
| JPG / PNG / HEIC | direkt Tesseract-OCR (Handyfoto-Fall) |

### 2. Chunking — `core/chunking.py`

Absatzbewusstes, rekursives Chunking: Absätze (`\n\n`-getrennt) werden zu
Chunks bis `chunk_size` (Default 700 Zeichen) aggregiert; beim Flush wird ein
Tail-Overlap von `chunk_overlap` (Default 70 Zeichen, ~10%) an den nächsten
Chunk vererbt. Überlange Einzelabsätze werden hart mit Sliding Window
(`step = chunk_size - overlap`) gesplittet. Jeder Chunk behält
`source`, `location` und einen Laufindex.

### 3. Embeddings & Reranking — `core/embeddings.py`

| Rolle | Modell | Eigenschaften |
|---|---|---|
| Bi-Encoder (Embeddings) | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 Dim., multilingual, normalisierte Vektoren, CPU |
| Cross-Encoder (Reranking) | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | scored (query, chunk)-Paare, multilingual |

Beide Modelle werden lazy geladen (`lru_cache`), damit `cli.py --help` ohne
Modell-Load auskommt. Austausch gegen Ollama-/API-Modelle: nur die Konstanten
bzw. Funktionen hier ersetzen — `store.py`/`rag.py` sehen nur Vektoren und
Scores.

### 4. Hybrid-Store — `core/store.py`

Eine SQLite-Datei pro Domain (`data/<slug>.db`) mit drei Tabellen, die sich
die Row-ID teilen:

```sql
chunks      (id, source, location, chunk_index, text)   -- Klartext + Metadaten
fts_chunks  FTS5(text)                                   -- BM25-Volltextindex
vec_chunks  vec0(embedding float[384])                   -- sqlite-vec KNN-Index
```

`hybrid_search()` führt beide Suchen aus und fusioniert per **Reciprocal Rank
Fusion**:

```
score(chunk) = Σ über beide Rankings  1 / (k + rank),   k = 60
```

Nur der *Rang* zählt, nie der rohe Score — damit sind Cosine-Distanz und
BM25-Score kommensurabel, ohne Normalisierungs-Magie. Ein Chunk, der in beiden
Listen vorn liegt, gewinnt; die FTS-Seite rettet exakte Treffer
(Artikelnummern, Eigennamen), bei denen semantische Nähe systematisch
fehlgreift.

FTS-Query-Building: Die Frage wird tokenisiert, deutsche Hochfrequenzwörter
(`wie`, `viele`, `pro`, `werden`, …) fliegen raus, der Rest wird als
`"t1" OR "t2" OR …` angesetzt (Phrase-Quoting verhindert FTS5-Syntaxfehler
durch Sonderzeichen). Ohne den Stoppwort-Filter verwässern die Füllwörter
den einen seltenen Fachbegriff in der BM25-Bewertung. Bestehen nur aus
Stoppwörtern, bleiben alle Tokens erhalten.

### 5. Retrieval-Orchestrierung — `core/rag.py:answer_question()`

**Kurzschluss, wenn die Domain ins Kontextfenster passt:** ist
`store.total_chars(db) <= full_context_max_chars` (Default 500 000 ≈ 125k
Token), wird die Suche komplett übersprungen und `store.all_chunks()` liefert
*alle* Chunks in Dokumentreihenfolge ans LLM (`retrieval="ganzes-dokument"`,
Quellen = beteiligte Dateien). Das trifft praktisch jede private
Dokumentensammlung. Grund: Retrieval ist dann nur Verlustquelle — für
Aufzähl-Fragen ("wie viele Steckdosen pro Etage", "liste alle Firmen") muss
über einen ganzen Abschnitt summiert werden, und eine auf `top_k_final`
gekürzte, gerankte Auswahl (der Cross-Encoder bewertet knappe
Stichpunktlisten systematisch zu niedrig) liefert Lücken.
`full_context_max_chars: 0` erzwingt immer die Hybrid-Suche.

Andernfalls (`retrieval="hybrid-suche"`, nur bei Beständen jenseits des
Kontextfensters):

1. Frage embedden (gleiches Modell wie Ingest).
2. `hybrid_search` mit vergrößertem Kandidaten-Pool: bei aktivem Reranking
   `top_k_vector + top_k_fts` (Default 15+15=30) statt nur `top_k_final`,
   damit der Cross-Encoder Auswahl hat.
3. Cross-Encoder scored alle Kandidaten, Neusortierung nach Score.
4. Cut auf `top_k_final` (Default 12) → an LLM.

Ein optionales `model`-Argument überschreibt `domain.llm_model` für den
einzelnen Aufruf (die Web-UI schickt darüber die Modellauswahl mit).

### 6. LLM-Generierung — `core/llm.py`

Subprocess-Aufruf der Claude-Code-CLI im Headless-Modus. Der **Prompt geht
über stdin**, nicht als Argument — der Ganzes-Dokument-Pfad erzeugt Prompts
von >100k Zeichen, und Windows begrenzt die Kommandozeile auf ~32k:

```
echo <prompt> | claude -p --model <model> --system-prompt <domain.persona>
                --no-session-persistence --disallowed-tools Bash,Edit,Write,...
```

- Läuft über die bestehende Claude-Code-Subscription, kein API-Key.
- Alle Tools deaktiviert, keine Session-Persistenz, 180 s Timeout.
- `--output-format json` → `generate_answer()` gibt ein `LlmResult` zurück
  (`text`, `context_tokens` = geschätzte Dokument-Kontextgröße aus der
  Prompt-Länge, `cached_tokens` = `cache_read_input_tokens` aus der API,
  `output_tokens`). CLI und Web-UI zeigen das pro Antwort an. Der
  Prompt-Cache der CLI (1 h TTL) senkt die Kosten von Folgefragen an
  dieselbe Domain auf ~10 %.
- Prompt-Kontrakt: Kontextblöcke im Format `[Quelle: datei | ort]\n<text>`,
  Anweisung: nur auf Basis der Ausschnitte antworten, Nichtwissen zugeben,
  jede Aussage mit `[Quelle: …]` belegen.
- Leere Trefferliste → statische Antwort ohne LLM-Call.
- Austauschbar: `rag.py` ruft nur `generate_answer(domain, question, results)`
  — direkter Anthropic-/OpenAI-/Ollama-Call wäre ein Drop-in.

## Domain-Konfiguration

`domains/<slug>/domain.yaml` steuert alles pro Domain, Kern-Code bleibt
unangetastet:

```yaml
display_name: "Bedienungsanleitungen"
emoji: "📖"
description: "..."          # für Domain-Listen/UI
persona: |                  # System-Prompt des LLM-Aufrufs
  Du bist ein Assistent für ...
chunk_size: 700
chunk_overlap: 70
top_k_vector: 15            # Kandidaten aus Vektor-Suche   (Hybrid-Pfad)
top_k_fts: 15              # Kandidaten aus BM25            (Hybrid-Pfad)
top_k_final: 12            # Chunks, die ans LLM gehen      (Hybrid-Pfad)
rerank: true
llm_model: haiku          # haiku | sonnet | opus
full_context_max_chars: 500000  # Domain-Gesamttext <= X Zeichen -> alles ans LLM; 0 = nie
```

Domain-Discovery läuft über das Dateisystem (`core/config.py`): Ordner mit
`domain.yaml` unter `domains/` = Domain. Neue Domain = Ordner + YAML + Dateien
in `raw/` + `python cli.py ingest <slug>`. Alternativ komplett über die
Web-UI.

**Web-UI-Endpunkte** (`webapp.py`): `GET /api/status` (was läuft lokal vs.
über die claude-CLI), `POST/DELETE /api/domains[/{slug}]`,
`PATCH /api/domains/{slug}/model`, `POST/DELETE /api/domains/{slug}/files`,
`POST /api/upload`, `POST /api/ingest`, `POST /api/chat`. Slugs aus URL-
Parametern werden gegen `^[a-z0-9_]+$` validiert (kein Path-Traversal).

## Qualitätssicherung

`python eval.py` prüft 20 Testfragen gegen erwartete Quellen und Stichworte —
zwei Metriken: Retrieval-Trefferquote (richtige Quelle unter den finalen
Chunks?) und Antwort-Korrektheit (erwartete Stichworte in der Antwort?).
Bewusst enthaltene harte Fälle:

- Fast identische Ersatzteile mit unterschiedlichen Artikelnummern — die
  *exakte* Artikelnummer muss stimmen, nicht die bedeutungsähnlichste.
- Ein synthetisch gescanntes PDF ohne Textebene (testet den OCR-Fallback
  end-to-end).

Stand: 20/20 Retrieval, 20/20 Antworten — eigenes, kleines Testset, kein
unabhängiger Benchmark. Die vier Beispiel-Domains sind klein genug für den
Ganzes-Dokument-Modus; die Hybrid-Suche + RRF + Stoppwort-FTS-Query decken
die Unit-Tests (`tests/test_store.py`, `tests/test_rag.py`) deterministisch ab.

## Betrieb & Grenzen

- **Ingest ist destruktiv**: `reset_db()` löscht die Domain-DB und baut neu
  auf — kein inkrementelles Update. Bei großen Korpora entsprechend teuer.
- **Erstlauf** lädt ~500 MB Modelle in den HF-Cache; OCR erfordert lokale
  Tesseract-Installation mit `deu`-Sprachpaket (ohne: Scans liefern leeren Text).
- **Ganzes-Dokument-Modus kostet Tokens**: eine 90k-Token-Domain × viele
  Fragen summiert sich gegen die Subscription-Limits. Für ein großes,
  häufig befragtes Archiv `full_context_max_chars` senken und die
  Hybrid-Suche nutzen — oder pro Frage auf `sonnet`/`opus` wechseln, wenn
  über einen langen Kontext zuverlässig gezählt werden muss.
- **Hybrid-Pfad ungetestet gegen echte Adversarial-Fälle** jenseits des
  Kontextfensters; sqlite-vec macht Brute-Force-KNN, was bis in den
  fünfstelligen Chunk-Bereich unproblematisch ist, danach wäre ein
  ANN-Index zu erwägen. Überschriften-bewusstes Chunking (statt seitenweise
  bei PDFs) und Nachbar-Chunk-Expansion wären die nächsten Schritte.
- **Kein GraphRAG**: bewusst weggelassen; für Multi-Hop-Entitätsfragen wäre
  ein zusätzlicher Store neben `store.py` der Ansatzpunkt.
