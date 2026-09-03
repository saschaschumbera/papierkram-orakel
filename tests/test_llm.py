"""LLM-Aufruf: Prompt über stdin (nicht argv -- Windows kappt die
Kommandozeile bei ~32k), Antwort + Token-Nutzung aus dem JSON-Output."""
import json
import subprocess

import core.llm as llm
from core.config import DomainConfig
from core.store import SearchResult


def _results():
    return [SearchResult(1, "f.md", "S. 1", "x" * 50_000, 0.0)]


def _fake_cli(result="Antwort", usage=None, is_error=False):
    payload = json.dumps(
        {"result": result, "is_error": is_error, "usage": usage or {}}
    )

    def fake_run(cmd, **kwargs):
        fake_run.cmd = cmd
        fake_run.input = kwargs.get("input")

        class R:
            returncode = 0
            stdout = payload
            stderr = ""

        return R()

    return fake_run


def test_prompt_goes_via_stdin_not_argv(monkeypatch):
    fake = _fake_cli(
        usage={"input_tokens": 12, "cache_creation_input_tokens": 40_000,
               "cache_read_input_tokens": 16_000, "output_tokens": 300},
    )
    monkeypatch.setattr(subprocess, "run", fake)

    d = DomainConfig(slug="d", display_name="D", persona="sei knapp")
    results = _results()
    out = llm.generate_answer(d, "Frage?", results, model="sonnet")

    assert out.text == "Antwort"
    # Dokument-Kontext wird aus dem Prompt geschätzt (~1 Token/4 Zeichen)
    assert out.context_tokens == len(llm.build_prompt("Frage?", results)) // 4
    assert out.context_tokens > 10_000
    assert out.cached_tokens == 16_000   # cache_read_input_tokens aus dem JSON
    assert out.output_tokens == 300
    # großer Prompt in stdin, nirgends in der Argumentliste
    assert len(fake.input) > 40_000
    assert not any(len(str(a)) > 10_000 for a in fake.cmd)
    assert fake.cmd[:3] == ["claude", "-p", "--model"]
    assert "--output-format" in fake.cmd and "sonnet" in fake.cmd


def test_cli_is_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_cli(result="Rate limit", is_error=True))
    d = DomainConfig(slug="d", display_name="D")
    try:
        llm.generate_answer(d, "Frage?", _results())
    except RuntimeError as exc:
        assert "Rate limit" in str(exc)
    else:
        raise AssertionError("RuntimeError erwartet")


def test_empty_results_skips_cli(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess sollte nicht aufgerufen werden")

    monkeypatch.setattr(subprocess, "run", boom)
    d = DomainConfig(slug="d", display_name="D")
    assert "nichts" in llm.generate_answer(d, "Frage?", []).text.lower()
