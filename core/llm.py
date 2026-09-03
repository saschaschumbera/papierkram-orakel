"""Answer generation via the Claude Code CLI in headless print mode.

Uses the user's existing Claude subscription instead of a separate,
separately-billed API key -- swap this module for a raw Anthropic/OpenAI/
Ollama call if you'd rather use an API key; rag.py only calls
`generate_answer(domain, question, results)` and doesn't care how.

Der Prompt geht ueber stdin, nicht als CLI-Argument: der Ganzes-Dokument-
Pfad erzeugt Prompts von >100k Zeichen, und Windows begrenzt die
Kommandozeile auf ~32k. `--output-format json` liefert zusaetzlich die
Token-Nutzung (inkl. Cache-Anteil), die die UI pro Antwort anzeigt.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from core.config import DomainConfig
from core.store import SearchResult

DISALLOWED_TOOLS = "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit"
TIMEOUT_SECONDS = 180

# In der Web-UI waehlbare Claude-Modelle (Alias -> Anzeigename).
AVAILABLE_MODELS = {
    "haiku": "Claude Haiku (schnell)",
    "sonnet": "Claude Sonnet (ausgewogen)",
    "opus": "Claude Opus (gründlich)",
}


@dataclass
class LlmResult:
    text: str
    context_tokens: int = 0  # geschätzte Größe des Dokument-Kontexts (steigt mit den Dateien)
    cached_tokens: int = 0   # tatsächlich aus dem Prompt-Cache gelesen (~10% des Preises)
    output_tokens: int = 0


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def build_prompt(question: str, results: list[SearchResult]) -> str:
    blocks = [f"[Quelle: {r.source} | {r.location}]\n{r.text}" for r in results]
    context = "\n\n---\n\n".join(blocks)
    return (
        f"Kontextausschnitte aus der Wissensbasis:\n\n{context}\n\n---\n\n"
        f"Frage: {question}\n\n"
        "Beantworte die Frage ausschließlich auf Basis der obigen Ausschnitte. "
        "Wenn die Antwort dort nicht enthalten ist, sag das ehrlich, statt zu raten. "
        "Belege jede Aussage mit [Quelle: Dateiname | Ort]."
    )


def generate_answer(
    domain: DomainConfig,
    question: str,
    results: list[SearchResult],
    model: str | None = None,
) -> LlmResult:
    if not results:
        return LlmResult("Dazu habe ich nichts in der Wissensbasis dieser Domain gefunden.")

    prompt = build_prompt(question, results)
    cmd = [
        "claude",
        "-p",
        "--model",
        model or domain.llm_model,
        "--system-prompt",
        domain.persona,
        "--no-session-persistence",
        "--disallowed-tools",
        DISALLOWED_TOOLS,
        "--output-format",
        "json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Die 'claude' CLI wurde nicht gefunden. Ist Claude Code installiert und im PATH?"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Die Antwortgenerierung hat zu lange gedauert (Timeout).") from exc

    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI Fehler: {proc.stderr.strip()}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Unerwartete Antwort der claude CLI: {proc.stdout[:200]}"
        ) from exc

    if data.get("is_error"):
        raise RuntimeError(f"claude CLI Fehler: {data.get('result', '')}")

    usage = data.get("usage") or {}
    return LlmResult(
        text=(data.get("result") or "").strip(),
        # Nur der von uns geschickte Dokument-Kontext -- die (konstante)
        # Claude-Code-Systemprompt-Last drumherum interessiert den Nutzer nicht.
        context_tokens=_estimate_tokens(prompt),
        cached_tokens=usage.get("cache_read_input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )
