"""Routing in answer_question: passt der Domain-Text ins Budget -> ganzes
Dokument, sonst Hybrid-Suche. Ohne Modelle/CLI (alles gemockt)."""
import core.config as config
import core.rag as rag
from core.config import DomainConfig
from core.llm import LlmResult
from core.rag import answer_question
from core.store import SearchResult

BUDGET = DomainConfig(slug="x", display_name="X").full_context_max_chars


def _llm(text="Antwort", **usage):
    return LlmResult(text=text, **usage)


def _result(text: str, source: str = "f.md") -> SearchResult:
    return SearchResult(1, source, "S. 1", text, 0.0)


def _domain(tmp_path, monkeypatch, slug="doc"):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / f"{slug}.db").touch()
    return DomainConfig(slug=slug, display_name="Doc", llm_model="haiku")


def _fail(*_a, **_k):
    raise AssertionError("dieser Pfad hätte nicht laufen dürfen")


def test_domain_within_budget_sends_whole_document(tmp_path, monkeypatch):
    d = _domain(tmp_path, monkeypatch)
    everything = [
        _result("a", "cv.pdf"),
        _result("b", "cv.pdf"),
        _result("c", "anschreiben.pdf"),
    ]
    monkeypatch.setattr(rag, "count_chunks", lambda _p: 3)
    monkeypatch.setattr(rag, "total_chars", lambda _p: BUDGET)  # genau am Limit
    monkeypatch.setattr(rag, "all_chunks", lambda _p: everything)
    monkeypatch.setattr(rag, "hybrid_search", _fail)
    monkeypatch.setattr(rag, "embed_query", _fail)

    captured = {}

    def fake_gen(dom, q, results, model=None):
        captured["results"] = results
        captured["model"] = model
        return _llm(context_tokens=30_000, cached_tokens=28_000, output_tokens=250)

    monkeypatch.setattr(rag, "generate_answer", fake_gen)

    ans = answer_question(d, "bei welchen firmen hat er gearbeitet?")

    assert ans.retrieval == "ganzes-dokument"
    assert captured["results"] is everything  # das ganze Dokument geht ans LLM
    assert captured["model"] == "haiku"
    # Quellen = beteiligte Dateien (dedupliziert), nicht alle Chunks
    assert [s.source for s in ans.sources] == ["cv.pdf", "anschreiben.pdf"]
    assert all(s.location == "gesamtes Dokument" for s in ans.sources)
    # Token-Nutzung wird durchgereicht
    assert (ans.context_tokens, ans.cached_tokens, ans.output_tokens) == (30_000, 28_000, 250)


def test_domain_over_budget_uses_hybrid_search(tmp_path, monkeypatch):
    d = _domain(tmp_path, monkeypatch)
    monkeypatch.setattr(rag, "count_chunks", lambda _p: 9999)
    monkeypatch.setattr(rag, "total_chars", lambda _p: BUDGET + 1)
    monkeypatch.setattr(rag, "all_chunks", _fail)
    monkeypatch.setattr(rag, "embed_query", lambda _q: [0.0])
    monkeypatch.setattr(rag, "hybrid_search", lambda *a, **k: [_result(str(i)) for i in range(20)])
    monkeypatch.setattr(rag, "rerank_fn", lambda _q, docs: list(range(len(docs))))
    monkeypatch.setattr(rag, "generate_answer", lambda *a, **k: _llm())

    ans = answer_question(d, "was bedeutet fehlercode e04?", model="sonnet")

    assert ans.retrieval == "hybrid-suche"
    assert ans.model == "sonnet"
    assert len(ans.sources) == d.top_k_final


def test_budget_zero_forces_hybrid(tmp_path, monkeypatch):
    d = DomainConfig(slug="doc", display_name="Doc", full_context_max_chars=0)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "doc.db").touch()
    monkeypatch.setattr(rag, "count_chunks", lambda _p: 2)
    monkeypatch.setattr(rag, "total_chars", _fail)  # darf gar nicht erst gefragt werden
    monkeypatch.setattr(rag, "all_chunks", _fail)
    monkeypatch.setattr(rag, "embed_query", lambda _q: [0.0])
    monkeypatch.setattr(rag, "hybrid_search", lambda *a, **k: [_result("x")])
    monkeypatch.setattr(rag, "rerank_fn", lambda _q, docs: [0.0])
    monkeypatch.setattr(rag, "generate_answer", lambda *a, **k: _llm())

    ans = answer_question(d, "frage")

    assert ans.retrieval == "hybrid-suche"


def test_unindexed_domain_raises(tmp_path, monkeypatch):
    d = _domain(tmp_path, monkeypatch)
    monkeypatch.setattr(rag, "count_chunks", lambda _p: 0)
    try:
        answer_question(d, "irgendwas")
    except RuntimeError as exc:
        assert "indexiert" in str(exc)
    else:
        raise AssertionError("RuntimeError erwartet")
