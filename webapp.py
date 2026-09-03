"""FastAPI web app: serves the chat UI and the /api endpoints it calls."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import (
    create_domain,
    delete_domain,
    discover_domains,
    load_domain,
    set_domain_model,
)
from core.embeddings import EMBEDDING_MODEL_NAME, RERANKER_MODEL_NAME
from core.llm import AVAILABLE_MODELS
from core.parsing import PARSERS
from core.rag import answer_question, ingest_domain
from core.store import count_chunks

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Papierkram-Orakel")


class ChatRequest(BaseModel):
    domain: str
    question: str
    model: str | None = None


class SourceOut(BaseModel):
    source: str
    location: str
    excerpt: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    model: str
    retrieval: str
    context_tokens: int
    cached_tokens: int
    output_tokens: int


class CreateDomainRequest(BaseModel):
    display_name: str
    emoji: str = "📄"
    description: str = ""
    persona: str | None = None


class IngestRequest(BaseModel):
    domain: str


class ModelRequest(BaseModel):
    model: str


def _domain_info(d) -> dict:
    return {
        "slug": d.slug,
        "display_name": d.display_name,
        "emoji": d.emoji,
        "description": d.description,
        "llm_model": d.llm_model,
        "chunks": count_chunks(d.db_path) if d.db_path.exists() else 0,
    }


@app.get("/api/status")
def status():
    """Woher kommt was: Suche/Ranking laufen lokal, die Antwort immer über
    die claude-CLI (Cloud, bestehende Subscription)."""
    try:
        proc = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=10
        )
        claude_version = (proc.stdout or proc.stderr).strip() or None
        claude_ok = proc.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        claude_version, claude_ok = None, False

    return {
        "retrieval": {
            "location": "lokal",
            "embedding_model": EMBEDDING_MODEL_NAME,
            "reranker_model": RERANKER_MODEL_NAME,
        },
        "answer": {
            "backend": "claude-cli",
            "location": "Cloud (Claude-Subscription)",
            "available": claude_ok,
            "version": claude_version,
        },
        "models": AVAILABLE_MODELS,
    }


@app.get("/api/domains")
def list_domains():
    return [_domain_info(d) for d in discover_domains()]


@app.post("/api/domains")
def create_domain_endpoint(req: CreateDomainRequest):
    try:
        domain = create_domain(req.display_name, req.emoji, req.description, req.persona)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _domain_info(domain)


@app.delete("/api/domains/{slug}")
def delete_domain_endpoint(slug: str):
    try:
        delete_domain(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": slug}


@app.patch("/api/domains/{slug}/model")
def set_model_endpoint(slug: str, req: ModelRequest):
    if req.model not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekanntes Modell '{req.model}'. Erlaubt: {', '.join(AVAILABLE_MODELS)}",
        )
    try:
        domain = set_domain_model(slug, req.model)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _domain_info(domain)


@app.get("/api/domains/{slug}/files")
def list_files(slug: str):
    try:
        domain = load_domain(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    files = sorted(p.name for p in domain.raw_dir.glob("*") if p.is_file())
    return {"files": files, "chunks": count_chunks(domain.db_path) if domain.db_path.exists() else 0}


@app.delete("/api/domains/{slug}/files")
def delete_file(slug: str, name: str):
    try:
        domain = load_domain(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    target = domain.raw_dir / Path(name).name
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Datei '{name}' nicht gefunden.")
    target.unlink()
    return {"deleted": target.name, "reindex_required": True}


@app.post("/api/upload")
async def upload_files(domain: str = Form(...), files: list[UploadFile] = File(...)):
    try:
        cfg = load_domain(domain)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    cfg.raw_dir.mkdir(parents=True, exist_ok=True)
    saved, skipped = [], []
    for upload in files:
        name = Path(upload.filename or "").name
        suffix = Path(name).suffix.lower()
        if not name or suffix not in PARSERS:
            skipped.append(upload.filename)
            continue
        dest = cfg.raw_dir / name
        with dest.open("wb") as out:
            shutil.copyfileobj(upload.file, out)
        saved.append(name)

    return {"saved": saved, "skipped": skipped}


@app.post("/api/ingest")
def ingest_endpoint(req: IngestRequest):
    try:
        cfg = load_domain(req.domain)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        n = ingest_domain(cfg)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"chunks": n}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        domain = load_domain(req.domain)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if req.model is not None and req.model not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unbekanntes Modell '{req.model}'.")

    try:
        result = answer_question(domain, req.question, model=req.model)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatResponse(
        answer=result.text,
        model=result.model,
        retrieval=result.retrieval,
        context_tokens=result.context_tokens,
        cached_tokens=result.cached_tokens,
        output_tokens=result.output_tokens,
        sources=[
            SourceOut(source=s.source, location=s.location, excerpt=s.excerpt)
            for s in result.sources
        ],
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
