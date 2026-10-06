"""AIEngine: discovery, loading, streaming, cancellation, fallbacks.

``llama_cpp`` itself is not installed in CI, so a minimal stand-in module is
registered in ``sys.modules``.  The stand-in only mimics the *public* API the
engine calls (``Llama(...)`` and ``create_chat_completion(..., stream=True)``),
so every line of :mod:`lifeboard.ai.engine` under test is the real one.
"""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

from lifeboard.ai.engine import (
    AIEngine,
    EngineError,
    _extract_delta,
    env_diagnostics,
    list_models,
    resolve_model,
)

TOKENS = ["Rest", " ", "today", ".", " ", "Tonnage", " ", "fell", " ", "10%"]


class FakeLlama:
    """Minimal llama-cpp-python stand-in."""

    instances: list["FakeLlama"] = []

    def __init__(self, model_path: str, n_ctx: int = 4096, n_gpu_layers: int = 0,
                 verbose: bool = False, n_threads: int | None = None) -> None:
        if "broken" in Path(model_path).name:
            raise RuntimeError("cublas64_12.dll not found")
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.n_threads = n_threads
        self.calls: list[dict] = []
        FakeLlama.instances.append(self)

    def create_chat_completion(self, messages, stream=False, max_tokens=512,
                               temperature=0.7, top_p=0.9, repeat_penalty=1.1,
                               **_kwargs):
        self.calls.append({"messages": messages, "stream": stream,
                           "max_tokens": max_tokens, "temperature": temperature})
        if "boom" in messages[-1]["content"]:
            raise RuntimeError("model exploded mid-generation")
        for token in TOKENS:
            yield {"choices": [{"delta": {"content": token}}]}
        yield {"choices": [{"delta": {}}]}          # trailing empty delta


@pytest.fixture
def fake_llama_module(monkeypatch):
    module = types.ModuleType("llama_cpp")
    module.Llama = FakeLlama
    module.__version__ = "0.0.0-test"
    FakeLlama.instances.clear()
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    return module


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "phi-3-mini-4k-instruct-q4_k_m.gguf").write_bytes(b"\x00" * 4096)
    (directory / "broken-model.gguf").write_bytes(b"\x00" * 1024)
    (directory / "llama-3-8b-instruct-q4_k_m.gguf").write_bytes(b"\x00" * 8192)
    (directory / "notes.txt").write_text("not a model")
    return directory


def _engine(state: dict, models_dir: Path) -> AIEngine:
    settings = state["settings"]
    return AIEngine(lambda: settings, models_dir=models_dir,
                    state_provider=lambda: state)


# ---------------------------------------------------------------- discovery
def test_list_models_finds_only_gguf_and_sorts_by_size(models_dir: Path):
    models = list_models(models_dir)
    assert [m.name for m in models] == [
        "llama-3-8b-instruct-q4_k_m.gguf",
        "phi-3-mini-4k-instruct-q4_k_m.gguf",
        "broken-model.gguf",
    ]
    assert models[0].family == "Llama 3"
    assert models[1].family == "Phi-3"
    assert "8.0 KB" in models[0].label


def test_list_models_on_a_missing_directory(tmp_path: Path):
    assert list_models(tmp_path / "nope") == []


def test_resolve_model_accepts_bare_name_absolute_path_and_gives_up(
        state, models_dir: Path):
    assert resolve_model("phi-3-mini-4k-instruct-q4_k_m.gguf",
                         models_dir).name == "phi-3-mini-4k-instruct-q4_k_m.gguf"
    absolute = models_dir / "llama-3-8b-instruct-q4_k_m.gguf"
    assert resolve_model(str(absolute), models_dir) == absolute
    assert resolve_model("ghost-model.gguf", models_dir) is None
    assert resolve_model("", models_dir) is None


# -------------------------------------------------------------------- load
def test_load_without_any_model_explains_where_to_put_one(state, tmp_path: Path):
    engine = _engine(state, tmp_path / "empty")
    with pytest.raises(EngineError) as info:
        engine.load()
    assert "No .gguf model found" in str(info.value)
    assert engine.status().available is False
    assert engine.status().backend == "heuristic"


def test_load_picks_the_largest_model_when_none_configured(
        state, models_dir: Path, fake_llama_module):
    engine = _engine(state, models_dir)
    engine.load()
    assert engine.loaded_model.name == "llama-3-8b-instruct-q4_k_m.gguf"
    status = engine.status()
    assert status.available is True
    assert status.backend == "llama.cpp"
    assert FakeLlama.instances[0].n_ctx == 4096


def test_load_failure_is_reported_as_a_status_message(
        state, models_dir: Path, fake_llama_module):
    engine = _engine(state, models_dir)
    with pytest.raises(EngineError) as info:
        engine.load(models_dir / "broken-model.gguf")
    assert "cublas64_12.dll" in str(info.value)
    status = engine.status()
    assert status.available is False
    assert "Could not load" in status.message


def test_missing_llama_cpp_package_degrades_cleanly(state, models_dir: Path,
                                                    monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)   # forces ImportError
    engine = _engine(state, models_dir)
    with pytest.raises(EngineError) as info:
        engine.load()
    assert "llama-cpp-python is not usable here" in str(info.value)
    assert engine.status().backend == "heuristic"


# ------------------------------------------------------------------ stream
def test_stream_yields_tokens_and_marks_the_model_available(
        state, models_dir: Path, fake_llama_module):
    engine = _engine(state, models_dir)
    engine.load()
    messages = engine.chat_messages([], "Should I train today?", state=state)
    collected: list[str] = []
    # Generators are lazy: the callback only fires while we consume.
    text = "".join(engine.stream(messages, on_token=collected.append))
    assert text == "Rest today. Tonnage fell 10%"
    assert collected == TOKENS
    assert FakeLlama.instances[0].calls[0]["messages"][0]["role"] == "system"


def test_stream_can_be_cancelled_mid_generation(
        state, models_dir: Path, fake_llama_module):
    engine = _engine(state, models_dir)
    engine.load()
    messages = engine.chat_messages([], "train?", state=state)
    cancel = threading.Event()
    out: list[str] = []
    for token in engine.stream(messages, cancel=cancel):
        out.append(token)
        if len(out) == 3:
            cancel.set()
    assert len(out) <= 4
    assert "".join(out) != "Rest today. Tonnage fell 10%"


def test_generation_crash_reverts_to_heuristic(
        state, models_dir: Path, fake_llama_module):
    engine = _engine(state, models_dir)
    engine.load()
    messages = engine.chat_messages([], "boom please", state=state)
    with pytest.raises(EngineError) as info:
        list(engine.stream(messages))
    assert "Generation failed" in str(info.value)
    assert engine.status().backend == "heuristic"
    assert engine.loaded_model is None


def test_heuristic_fallback_answers_from_the_local_log(
        state, week_of_logs, models_dir: Path):
    logged, _end = week_of_logs
    engine = AIEngine(lambda: logged["settings"], models_dir=models_dir,
                      state_provider=lambda: logged)
    answer = engine.heuristic_answer("how am I doing")
    assert answer.startswith("[heuristic mode")
    assert "RAW CONTEXT" in answer
    assert "GOALS" in answer


def test_heuristic_stream_produces_the_same_text(state, models_dir: Path):
    engine = _engine(state, models_dir)
    streamed = "".join(engine.stream([{"role": "user", "content": "hi"}]))
    assert streamed.strip() == engine.heuristic_answer("hi").strip()


# ---------------------------------------------------------------- messages
def test_chat_messages_hide_the_serialised_life_data(state, week_of_logs,
                                                     models_dir: Path):
    logged, end = week_of_logs
    engine = AIEngine(lambda: logged["settings"], models_dir=models_dir,
                      state_provider=lambda: logged)
    from datetime import timedelta
    day = (end - timedelta(days=1)).isoformat()
    messages = engine.chat_messages(
        [{"role": "user", "content": "earlier"},
         {"role": "assistant", "content": "noted"}],
        "Why did my tonnage drop?", state=logged, day=day)
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "Why did my tonnage drop?"}
    assert messages[1:-1] == [{"role": "user", "content": "earlier"},
                              {"role": "assistant", "content": "noted"}]
    assert "2,250 kg" in messages[0]["content"]
    assert "kcal 2,600" in messages[0]["content"]


def test_briefing_messages_carry_the_heuristic_text(state, week_of_logs,
                                                    models_dir: Path):
    logged, end = week_of_logs
    engine = AIEngine(lambda: logged["settings"], models_dir=models_dir,
                      state_provider=lambda: logged)
    messages, fallback = engine.briefing_messages(state=logged)
    assert messages[0]["role"] == "system"
    assert "morning briefing" in messages[1]["content"].lower()
    assert "Tonnage dropped by 10.0%" in fallback


# ------------------------------------------------------------------- misc
def test_extract_delta_is_defensive():
    assert _extract_delta({"choices": [{"delta": {"content": "x"}}]}) == "x"
    assert _extract_delta({"choices": [{"text": "y"}]}) == "y"
    assert _extract_delta({"choices": []}) == ""
    assert _extract_delta({}) == ""
    assert _extract_delta(None) == ""
    assert _extract_delta({"choices": [{"delta": {}}]}) == ""


def test_env_diagnostics_reports_the_environment(models_dir: Path):
    facts = env_diagnostics()
    assert set(facts) >= {"models_dir", "models_found", "LIFEBOARD_MODELS",
                          "frozen", "llama_cpp"}


def test_status_before_any_load_mentions_the_available_model(
        state, models_dir: Path):
    status = _engine(state, models_dir).status()
    assert status.available is False
    assert status.model == "llama-3-8b-instruct-q4_k_m.gguf"
    assert "not loaded" in status.message


def test_unload_releases_the_handle(state, models_dir: Path, fake_llama_module):
    engine = _engine(state, models_dir)
    engine.load()
    assert engine.loaded_model is not None
    engine.unload()
    assert engine.loaded_model is None
    assert engine.status().available is False
