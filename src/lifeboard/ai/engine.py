"""llama-cpp-python wrapper with a graceful offline fallback.

Design rules:

* ``llama_cpp`` is imported **lazily** inside :meth:`AIEngine.load`.  A machine
  without the package (or without the CUDA DLLs) still gets a fully functional
  app — the engine reports ``backend="heuristic"`` and answers from the local
  data instead of a transformer.
* Generation is a *generator*, so the Qt worker thread can push tokens to the
  UI as they arrive and can bail out mid-stream when the user hits stop.
* All errors are converted to :class:`EngineError` with a human-readable
  message; the GUI never sees a raw llama.cpp traceback.
"""

from __future__ import annotations

import importlib
import os
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator

from .. import paths
from .briefing import briefing_text, build_briefing
from .context import build_context
from ..i18n import fmt_num, is_ru, tr
from .prompts import default_persona, system_prompt, trim_history

MODEL_GLOBS = ("*.gguf",)


class EngineError(RuntimeError):
    """Model discovery, load or generation failed in a recoverable way."""


@dataclass(frozen=True)
class ModelInfo:
    path: Path
    name: str
    size_bytes: int

    @property
    def label(self) -> str:
        return f"{self.name}  ·  {paths.human_size(self.size_bytes)}"

    @property
    def family(self) -> str:
        lowered = self.name.lower()
        for token, pretty in (
            ("llama-3", "Llama 3"), ("llama3", "Llama 3"), ("llama-2", "Llama 2"),
            ("phi-3", "Phi-3"), ("phi3", "Phi-3"), ("phi-4", "Phi-4"),
            ("mistral", "Mistral"), ("qwen", "Qwen"), ("gemma", "Gemma"),
            ("deepseek", "DeepSeek"), ("tinyllama", "TinyLlama"),
        ):
            if token in lowered:
                return pretty
        return "GGUF"

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "name": self.name,
                "size_bytes": self.size_bytes, "label": self.label,
                "family": self.family}


@dataclass
class EngineStatus:
    available: bool
    backend: str                 # "llama.cpp" | "heuristic"
    model: str
    message: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "backend": self.backend,
                "model": self.model, "message": self.message, "params": self.params}


def list_models(models_dir: Path | str | None = None) -> list[ModelInfo]:
    """Every GGUF file in the models directory, largest first."""
    root = Path(models_dir) if models_dir else paths.model_dir()
    if not root.is_dir():
        return []
    found: list[ModelInfo] = []
    for pattern in MODEL_GLOBS:
        for candidate in root.glob(pattern):
            if candidate.is_file():
                found.append(ModelInfo(path=candidate.resolve(),
                                       name=candidate.name,
                                       size_bytes=candidate.stat().st_size))
    found.sort(key=lambda info: -info.size_bytes)
    return found


def resolve_model(setting: str, models_dir: Path | str | None = None) -> Path | None:
    """Resolve the configured ``model_file`` to an existing path (or None)."""
    if not setting:
        return None
    root = Path(models_dir) if models_dir else paths.model_dir()
    candidate = Path(setting).expanduser()
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    local = root / Path(setting).name
    if local.is_file():
        return local
    # Last resort: prefix match on the bare name.
    for info in list_models(root):
        if info.name == Path(setting).name:
            return info.path
    return None


class AIEngine:
    """Owns the model handle and exposes streaming generation."""

    def __init__(
        self,
        settings: Callable[[], dict[str, Any]],
        *,
        models_dir: Path | str | None = None,
        state_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._state = state_provider
        self._models_dir = Path(models_dir) if models_dir else paths.model_dir()
        self._llm: Any = None
        self._model_path: Path | None = None
        self._attempted: Path | None = None
        self._load_error: str | None = None
        self._lock = threading.RLock()
        self._llama_module: Any = None

    # ------------------------------------------------------------- discovery
    @property
    def models_dir(self) -> Path:
        return self._models_dir

    def list_models(self) -> list[ModelInfo]:
        return list_models(self._models_dir)

    def configured_model(self) -> Path | None:
        return resolve_model(str(self._ai().get("model_file", "")), self._models_dir)

    def _ai(self) -> dict[str, Any]:
        return self._settings().get("ai", {})

    # ------------------------------------------------------------------ load
    def load(self, model: Path | str | None = None, *,
             progress: Callable[[str], None] | None = None) -> None:
        """Load a GGUF model.  Raises :class:`EngineError` with a useful message."""
        target = Path(model).expanduser() if model else self.configured_model()
        if target is None:
            available = self.list_models()
            if not available:
                raise EngineError(tr(
                    f"No .gguf model found in {self._models_dir}. Drop a "
                    "quantised model (Llama-3-8B-Instruct Q4_K_M or Phi-3-mini) "
                    "into that folder, or point LIFEBOARD_MODELS at one.",
                    f"В {self._models_dir} нет модели .gguf. Положите туда "
                    "квантованную модель (Llama-3-8B-Instruct Q4_K_M или Phi-3-mini) "
                    "или укажите папку через LIFEBOARD_MODELS."))
            target = available[0].path
        if not target.is_file():
            self._attempted = target
            raise EngineError(tr(f"Model file not found: {target}",
                                 f"Файл модели не найден: {target}"))
        self._attempted = target

        with self._lock:
            if self._model_path == target and self._llm is not None:
                return
            self.unload()
            ai = self._ai()
            if self._llama_module is None:
                try:
                    self._llama_module = importlib.import_module("llama_cpp")
                except Exception as exc:  # ImportError, OSError (missing DLL)
                    self._load_error = tr(
                        f"llama-cpp-python is not usable here ({type(exc).__name__}: "
                        f"{exc}). Run `pip install llama-cpp-python` (add "
                        "`--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121` "
                        "for CUDA). The advisor stays in heuristic mode meanwhile.",
                        f"llama-cpp-python здесь недоступен ({type(exc).__name__}: "
                        f"{exc}). Выполните `pip install llama-cpp-python` (для CUDA "
                        "добавьте `--extra-index-url "
                        "https://abetlen.github.io/llama-cpp-python/whl/cu121`). "
                        "Пока советник работает в режиме эвристики.")
                    raise EngineError(self._load_error) from exc
            if progress:
                progress(tr(f"loading {target.name} …",
                            f"загрузка {target.name} …"))
            kwargs: dict[str, Any] = {
                "model_path": str(target),
                "n_ctx": int(ai.get("n_ctx", 4096)),
                "n_gpu_layers": int(ai.get("n_gpu_layers", 0)),
                "verbose": False,
            }
            threads = int(ai.get("n_threads", 0) or 0)
            if threads > 0:
                kwargs["n_threads"] = threads
            try:
                self._llm = self._llama_module.Llama(**kwargs)
            except Exception as exc:
                self._load_error = tr(
                    f"Could not load {target.name}: {type(exc).__name__}: {exc}. "
                    "Try fewer GPU layers (n_gpu_layers=0) or a smaller quant.",
                    f"Не удалось загрузить {target.name}: {type(exc).__name__}: {exc}. "
                    "Попробуйте меньше слоёв на GPU (n_gpu_layers=0) или более "
                    "компактный квант.")
                raise EngineError(self._load_error) from exc
            self._model_path = target
            self._load_error = None
            if progress:
                progress(f"{target.name} ready")

    def unload(self) -> None:
        with self._lock:
            self._llm = None
            self._model_path = None

    @property
    def loaded_model(self) -> Path | None:
        return self._model_path

    def status(self) -> EngineStatus:
        ai = self._ai()
        params = {
            "n_ctx": ai.get("n_ctx"),
            "n_gpu_layers": ai.get("n_gpu_layers"),
            "temperature": ai.get("temperature"),
            "top_p": ai.get("top_p"),
            "max_tokens": ai.get("max_tokens"),
        }
        if self._llm is not None and self._model_path is not None:
            return EngineStatus(True, "llama.cpp", self._model_path.name,
                                tr("model resident in memory", "модель в памяти"),
                                params)
        configured = self.configured_model() or self._attempted
        if self._load_error:
            return EngineStatus(False, "heuristic", configured.name if configured else "",
                                self._load_error, params)
        if configured is None:
            models = self.list_models()
            if not models:
                return EngineStatus(
                    False, "heuristic", "",
                    tr(f"No model in {self._models_dir} — advisor runs on the "
                       "built-in rule engine.",
                       f"В {self._models_dir} моделей нет — советник работает на "
                       "встроенном правиле-движке."), params)
            return EngineStatus(
                False, "heuristic", models[0].name,
                tr("Model found but not loaded yet — press Load in Settings.",
                   "Модель найдена, но не загружена — нажмите «Загрузить» "
                   "в настройках."), params)
        return EngineStatus(False, "heuristic", configured.name,
                            tr("Model selected but not loaded.",
                               "Модель выбрана, но не загружена."), params)

    # ------------------------------------------------------------ generation
    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        cancel: threading.Event | None = None,
        on_token: Callable[[str], None] | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """Yield completion tokens.  Falls back to the heuristic engine."""
        if self._llm is None:
            yield from self._heuristic_stream(messages)
            return
        ai = self._ai()
        kwargs: dict[str, Any] = {
            "messages": messages,
            "stream": True,
            "max_tokens": int(ai.get("max_tokens", 512)),
            "temperature": float(ai.get("temperature", 0.7)),
            "top_p": float(ai.get("top_p", 0.92)),
            "repeat_penalty": float(ai.get("repeat_penalty", 1.1)),
        }
        if overrides:
            kwargs.update(overrides)
        try:
            completion = self._llm.create_chat_completion(**kwargs)
            for chunk in completion:
                if cancel is not None and cancel.is_set():
                    break
                piece = _extract_delta(chunk)
                if not piece:
                    continue
                if on_token:
                    on_token(piece)
                yield piece
        except EngineError:
            raise
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._load_error = tr(
                f"Generation failed ({message}). Reverted to heuristic mode.",
                f"Генерация не удалась ({message}). Возврат к режиму эвристики.")
            self.unload()
            raise EngineError(self._load_error) from exc

    def complete(self, messages: list[dict[str, str]], *,
                 cancel: threading.Event | None = None,
                 overrides: dict[str, Any] | None = None) -> str:
        return "".join(self.stream(messages, cancel=cancel, overrides=overrides)).strip()

    # ------------------------------------------------------------- heuristics
    def _heuristic_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        """Deterministic answer built from the serialised local data."""
        question = next((m["content"] for m in reversed(messages)
                         if m.get("role") == "user"), "")
        answer = self.heuristic_answer(question)
        # Streamed in word-sized chunks so the UI behaves identically.
        buffer = ""
        for char in answer:
            buffer += char
            if buffer in (" ", "\n"):
                yield buffer
                buffer = ""
        if buffer:
            yield buffer

    def heuristic_answer(self, question: str = "") -> str:
        """Rule-based advisor used when no model is loaded."""
        state = self._state() if self._state else {}
        if not state:
            return tr("No data file is open, so there is nothing to advise on yet. "
                      "Log a habit, a meal or a set and ask again.",
                      "Файл данных не открыт, поэтому советовать пока нечего. "
                      "Запишите обряд, приём пищи или сет и спросите снова.")
        today = date.today().isoformat()
        lines = build_briefing(state, today=date.today())
        context = build_context(state, day=today, query=question, max_chars=1400)
        body = briefing_text(lines)
        header = tr("[heuristic mode — no GGUF model loaded; this answer is "
                    "computed from your own log, not generated]\n\n",
                    "[режим эвристики — GGUF-модель не загружена; этот ответ "
                    "вычислен по вашему журналу, а не сгенерирован]\n\n")
        return f"{header}{body}\n\n" + tr("RAW CONTEXT", "ИСХОДНЫЕ ДАННЫЕ") \
            + f"\n{context}"

    # --------------------------------------------------------------- helpers
    def chat_messages(self, history: list[dict[str, str]], question: str, *,
                      state: dict[str, Any] | None = None,
                      day: str | None = None,
                      max_context_chars: int = 2600) -> list[dict[str, str]]:
        """Build the message list sent to the model: system + trimmed history."""
        state = state if state is not None else (self._state() if self._state else {})
        context = build_context(state, day=day, query=question,
                                max_chars=max_context_chars)
        persona = str(self._ai().get("persona") or default_persona())
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt(persona, context)}
        ]
        messages.extend(trim_history(history))
        messages.append({"role": "user", "content": question.strip()})
        return messages

    def briefing_messages(self, *, state: dict[str, Any] | None = None,
                          day: str | None = None) -> tuple[list[dict[str, str]], str]:
        """Messages for the proactive briefing + the heuristic fallback text."""
        from .prompts import editor_prompt

        state = state if state is not None else (self._state() if self._state else {})
        day = day or date.today().isoformat()
        context = build_context(state, day=day, max_chars=2000)
        persona = str(self._ai().get("persona") or default_persona())
        metrics_block = briefing_text(build_briefing(
            state, today=date.fromisoformat(day[:10])))
        messages = [
            {"role": "system", "content": system_prompt(persona, context)},
            {"role": "user", "content": editor_prompt("briefing", metrics_block)},
        ]
        return messages, metrics_block


def _extract_delta(chunk: Any) -> str:
    """Pull the text delta out of a llama-cpp-python streaming chunk."""
    try:
        choices = chunk["choices"]
        if not choices:
            return ""
        choice = choices[0]
        delta = choice.get("delta") or {}
        text = delta.get("content")
        if text is None:
            text = choice.get("text")
        return str(text or "")
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def env_diagnostics() -> dict[str, str]:
    """Small facts the settings page shows for support requests."""
    info = {
        "models_dir": str(paths.model_dir()),
        "models_found": ", ".join(m.name for m in list_models()) or "(none)",
        "LIFEBOARD_MODELS": os.environ.get("LIFEBOARD_MODELS", "(unset)"),
        "frozen": str(paths.is_frozen()),
    }
    try:
        module = importlib.import_module("llama_cpp")
        info["llama_cpp"] = str(getattr(module, "__version__", "unknown"))
    except Exception as exc:
        info["llama_cpp"] = f"unavailable ({type(exc).__name__})"
    return info
