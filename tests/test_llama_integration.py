"""Integration checks against the *real* llama-cpp-python, when installed.

Skipped automatically on machines without the package (the app degrades to the
heuristic advisor there).  These tests are what stop the engine drifting away
from the upstream API: they call the genuine library, not a stand-in.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

llama_cpp = pytest.importorskip(
    "llama_cpp", reason="llama-cpp-python is not installed in this environment")

from lifeboard.ai.engine import AIEngine, EngineError  # noqa: E402

#: Every keyword the engine passes to the real library.
LLAMA_INIT_KWARGS = ("model_path", "n_ctx", "n_gpu_layers", "n_threads", "verbose")
CHAT_KWARGS = ("messages", "stream", "max_tokens", "temperature", "top_p",
               "repeat_penalty")


def test_llama_cpp_is_importable_and_versioned():
    assert hasattr(llama_cpp, "Llama")
    assert getattr(llama_cpp, "__version__", "")


@pytest.mark.parametrize("name", LLAMA_INIT_KWARGS)
def test_constructor_accepts_every_kwarg_we_pass(name):
    assert name in inspect.signature(llama_cpp.Llama.__init__).parameters


@pytest.mark.parametrize("name", CHAT_KWARGS)
def test_chat_completion_accepts_every_kwarg_we_pass(name):
    signature = inspect.signature(llama_cpp.Llama.create_chat_completion)
    assert name in signature.parameters, (
        f"llama-cpp-python {llama_cpp.__version__} no longer accepts {name!r}; "
        "update AIEngine.stream")


def test_loading_a_bogus_gguf_surfaces_as_engine_error(tmp_path: Path, state):
    """Real library, real failure -> our error type with an actionable message."""
    models = tmp_path / "models"
    models.mkdir()
    bogus = models / "not-really-a-model.gguf"
    bogus.write_bytes(b"this is not a GGUF file at all")

    engine = AIEngine(lambda: state["settings"], models_dir=models,
                      state_provider=lambda: state)
    with pytest.raises(EngineError) as info:
        engine.load(bogus)
    message = str(info.value)
    assert "Could not load" in message
    assert bogus.name in message
    status = engine.status()
    assert status.available is False
    assert status.backend == "heuristic"
    assert status.model == bogus.name


def test_generation_without_a_model_stays_on_the_heuristic_path(tmp_path: Path,
                                                                state):
    engine = AIEngine(lambda: state["settings"], models_dir=tmp_path,
                      state_provider=lambda: state)
    assert engine.status().available is False
    answer = "".join(engine.stream([{"role": "user", "content": "train today?"}]))
    assert "heuristic mode" in answer


def test_load_progress_callback_is_invoked(tmp_path: Path, state):
    """Progress reporting must fire before the (failing) load completes."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "stub.gguf").write_bytes(b"\x00" * 16)
    engine = AIEngine(lambda: state["settings"], models_dir=models,
                      state_provider=lambda: state)
    seen: list[str] = []
    with pytest.raises(EngineError):
        engine.load(models / "stub.gguf", progress=seen.append)
    assert any("loading stub.gguf" in line for line in seen)


def test_env_diagnostics_sees_the_installed_library():
    from lifeboard.ai.engine import env_diagnostics

    facts = env_diagnostics()
    assert facts["llama_cpp"] == llama_cpp.__version__
    assert sys.version_info >= (3, 9)
