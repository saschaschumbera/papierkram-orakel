# Das Papierkram-Orakel — einfach erklärt

*Für alle, die das System nutzen oder verstehen wollen, ohne Technik-Vorwissen.*

## Was ist das?

Stell dir eine Bibliothekarin vor, die **alle deine Unterlagen gelesen hat** —
Bedienungsanleitungen, Verträge, Garantiekarten, das Familienkochbuch. Du
stellst ihr eine ganz normale Frage:

> „Welches Waschprogramm nehme ich für Wolle?"

Und sie antwortet nicht nur, sondern **zeigt dir auch die Stelle im Dokument**,
wo das steht — Datei und Seite. Genau das macht dieses Programm, komplett auf
deinem eigenen Rechner.

## Wie benutze ich es?

**Am einfachsten im Browser:**

1. Im Projektordner starten: `uvicorn webapp:app --reload --port 8010`
2. Im Browser öffnen: http://127.0.0.1:8010
3. Oben ein Themengebiet auswählen (z.B. „Anleitungen" oder „Garantien")
   und einfach lostippen — wie in einem Chat.

**Neues Themengebiet anlegen** (z.B. „Steuerunterlagen"):

1. Im Browser auf **„+ Neue Domain"** klicken
2. Name und Beschreibung eintragen
3. Dateien per Drag & Drop hineinziehen — PDFs, Word-Dateien, Textdateien,
   sogar **Handyfotos von Belegen** funktionieren
4. Auf **„Jetzt indexieren"** klicken, kurz warten — fertig

Einzelne Dateien kannst du später über das **×** am Datei-Namen wieder
entfernen, ein ganzes Themengebiet über **„Domain löschen"**. Über das
Auswahlfeld **„Antwort-Modell"** stellst du pro Gebiet ein, wie gründlich
(und wie schnell) Claude antworten soll — Haiku ist schnell, Opus am
gründlichsten. Die Kopfzeile zeigt dir jederzeit, was auf deinem Rechner
läuft und was an Claude geht.

## Was passiert dabei hinter den Kulissen?

### Schritt 1: Das Einlesen (einmalig pro Themengebiet)

Wenn du Dokumente hinzufügst, passiert Folgendes:

1. **Lesen** — Das Programm holt den Text aus jeder Datei. Bei eingescannten
   Dokumenten oder Fotos nutzt es eine Texterkennung (wie ein sehr gründliches
   Abtippen).
2. **Zerschneiden** — Jedes Dokument wird in kleine Schnipsel von etwa einem
   Absatz Länge zerlegt. Warum? Weil die Antwort auf „Welches Programm für
   Wolle?" nur in *einem* Absatz der 80-seitigen Anleitung steht — den Rest
   braucht man nicht.
3. **Sortieren nach Bedeutung** — Jeder Schnipsel bekommt eine Art
   „Bedeutungs-Fingerabdruck" (eine lange Zahlenreihe). Der Trick: Schnipsel,
   die *inhaltlich Ähnliches* sagen, bekommen *ähnliche* Fingerabdrücke —
   auch wenn sie ganz andere Wörter benutzen. „Wolle waschen" und
   „Feinwäsche-Programm für empfindliche Textilien" landen nah beieinander.
4. **Ablegen** — Alles wandert in eine einzige Datenbank-Datei auf deinem
   Rechner. Keine Cloud, nichts verlässt deinen Computer.

### Schritt 2: Das Fragen

Wenn du eine Frage stellst:

*Das Wichtigste zuerst:* Solange ein Themengebiet insgesamt nicht riesig ist
— und das trifft auf fast jede private Sammlung zu, egal ob ein Lebenslauf,
alle Geräte-Handbücher oder ein Ordner Bauunterlagen — wird **gar nicht
gesucht**. Claude bekommt einfach *alle* Dokumente des Gebiets auf einmal.
Das ist genauer, gerade bei Fragen wie „zähl mir alle Firmen auf" oder „wie
viele Steckdosen pro Etage", wo eine Auswahl weniger Schnipsel immer etwas
übersieht. Unter jeder Antwort steht, wie viel Text dafür an Claude ging —
bei kleinen Gebieten ist das winzig, und Folgefragen ans selbe Gebiet sind
dank eines Zwischenspeichers nochmal deutlich sparsamer. Nur wenn ein Gebiet
wirklich zu groß fürs Kontextfenster wird, schaltet das Programm auf die
eigentliche Suche um:

1. Deine Frage bekommt denselben „Bedeutungs-Fingerabdruck".
2. Das Programm sucht auf **zwei Arten gleichzeitig**:
   - **Nach Bedeutung:** Welche Schnipsel sagen inhaltlich etwas Ähnliches
     wie die Frage?
   - **Nach exakten Wörtern:** Welche Schnipsel enthalten genau die Begriffe
     aus der Frage? Das ist wichtig bei Dingen wie Artikelnummern — „Teil
     4055-C" und „Teil 4055-D" *bedeuten* fast dasselbe, sind aber eben
     nicht dasselbe Teil.
3. Beide Ergebnislisten werden verrechnet, ein Feinsortierer liest die besten
   Kandidaten noch einmal genau und ordnet sie endgültig.
4. Erst jetzt kommt die KI (Claude) ins Spiel — mit einer strengen Regel:
   **„Antworte NUR mit dem, was in diesen Schnipseln steht. Wenn es da nicht
   steht, sag das ehrlich."** Deshalb steht unter jeder Aussage eine
   Quellenangabe wie `[Quelle: mietvertrag_wohnung.md | §6 Kaution]`.

## Warum kann ich den Antworten trauen?

Drei eingebaute Sicherheitsnetze:

- **Die KI darf nicht raten.** Sie bekommt nur die gefundenen Textstellen und
  die Anweisung, sich ausschließlich darauf zu stützen. Bei einem Test mit
  einer Frage, deren Antwort nicht in den Dokumenten stand, hat das System
  geantwortet: „Das steht nicht in den Unterlagen" — statt etwas zu erfinden.
- **Jede Aussage hat eine Quellenangabe.** Du kannst jederzeit im
  Originaldokument nachschlagen, ob es stimmt.
- **Alles bleibt lokal.** Die Suche läuft komplett auf deinem Rechner. Nur der
  letzte Schritt — das Formulieren der Antwort — geht an Claude, zusammen mit
  den paar gefundenen Textschnipseln.

## Was es NICHT kann

- Es weiß nur, was **in deinen Dokumenten** steht. Allgemeinwissen-Fragen
  gehören woanders hin.
- Wenn ein Scan so schlecht ist, dass die Texterkennung nichts lesen kann,
  kann auch nichts gefunden werden.
- Es beantwortet immer nur Fragen **innerhalb eines Themengebiets** — die
  Frage an „Rezepte" durchsucht nicht die Verträge.
