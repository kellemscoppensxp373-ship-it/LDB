"""Qt-side plumbing: QThread generation workers and the AI controller.

Every call into the local model happens on a worker thread.  The GUI thread
only ever touches signals, so a 30-second generation on a CPU-only laptop
cannot freeze the window — and the user can abort it at any token boundary.

Thread lifecycle is owned by :class:`AiController`: exactly one generation may
be in flight, workers are kept referenced until they report ``finished`` (a
QThread deleted while running is a hard crash), and the cancel event is shared
with the engine's generator loop.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from ..i18n import tr
from .engine import AIEngine, EngineError


class GenerationWorker(QThread):
    """Streams one completion and reports the full text when done."""

    token = Signal(str)
    progress = Signal(str)
    succeeded = Signal(str, str)      # (full_text, tag)
    failed = Signal(str, str)         # (message, tag)

    def __init__(self, engine: AIEngine, messages: list[dict[str, str]],
                 tag: str = "chat", *, cancel: threading.Event | None = None,
                 fallback: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._messages = messages
        self._tag = tag
        self._cancel = cancel or threading.Event()
        self._fallback = fallback
        self._chunks: list[str] = []

    # -- control -----------------------------------------------------------
    @property
    def tag(self) -> str:
        return self._tag

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def cancel(self) -> None:
        """Ask the generator loop to stop at the next token."""
        self._cancel.set()

    # -- work --------------------------------------------------------------
    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            for piece in self._engine.stream(self._messages, cancel=self._cancel):
                if self._cancel.is_set():
                    break
                self._chunks.append(piece)
                self.token.emit(piece)
        except EngineError as exc:
            if self._fallback:
                # The engine already degraded to heuristic output; keep the
                # user's answer and report the reason separately.
                self.succeeded.emit(self._fallback, self._tag)
            self.failed.emit(str(exc), self._tag)
            return
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(tr(f"Unexpected error: {type(exc).__name__}: {exc}",
                                f"Непредвиденная ошибка: {type(exc).__name__}: {exc}"),
                             self._tag)
            return
        text = "".join(self._chunks).strip()
        if not text and self._fallback:
            text = self._fallback
        if self._cancel.is_set() and not text:
            self.failed.emit(tr("Generation cancelled.", "Генерация отменена."),
                             self._tag)
            return
        self.succeeded.emit(text, self._tag)


class ModelLoadWorker(QThread):
    """Loads (or unloads) the GGUF model off the GUI thread."""

    progress = Signal(str)
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine: AIEngine, model_path: str | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._model_path = model_path

    def run(self) -> None:  # noqa: D102
        try:
            if self._model_path == "":
                self._engine.unload()
                self.progress.emit(tr("model unloaded", "модель выгружена"))
            else:
                self._engine.load(self._model_path,
                                  progress=lambda text: self.progress.emit(text))
            status = self._engine.status()
            self.succeeded.emit(status.to_dict())
        except EngineError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class AiController(QObject):
    """Single entry point for every AI request in the app."""

    token = Signal(str, str)          # (piece, tag)
    response = Signal(str, str)       # (full text, tag)
    error = Signal(str, str)          # (message, tag)
    busyChanged = Signal(bool, str)
    statusChanged = Signal(dict)

    def __init__(self, engine: AIEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._worker: GenerationWorker | None = None
        self._load_worker: ModelLoadWorker | None = None

    # ---------------------------------------------------------------- state
    @property
    def engine(self) -> AIEngine:
        return self._engine

    def status(self) -> dict[str, Any]:
        return self._engine.status().to_dict()

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def current_tag(self) -> str | None:
        return self._worker.tag if self.busy else None

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    # ------------------------------------------------------------ lifecycle
    def _start(self, worker: GenerationWorker) -> bool:
        if self.busy:
            self.error.emit(tr("The advisor is still working on the previous "
                               "request. Stop it first.",
                               "Советник ещё обрабатывает предыдущий запрос. "
                               "Сначала остановите его."), worker.tag)
            return False
        self._worker = worker
        worker.token.connect(self._on_token)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self.busyChanged.emit(True, worker.tag)
        worker.start()
        return True

    def _on_token(self, piece: str) -> None:
        tag = self._worker.tag if self._worker else "chat"
        self.token.emit(piece, tag)

    def _on_succeeded(self, text: str, tag: str) -> None:
        self.response.emit(text, tag)

    def _on_failed(self, message: str, tag: str) -> None:
        self.error.emit(message, tag)

    def _on_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.busyChanged.emit(False, "")

    # -------------------------------------------------------------- requests
    def ask(self, question: str, *, history: list[dict[str, str]],
            state: dict[str, Any], day: str | None = None, tag: str = "chat") -> bool:
        """Chat turn with the hidden context prompt attached."""
        if not question.strip():
            return False
        messages = self._engine.chat_messages(history, question, state=state, day=day)
        return self._start(GenerationWorker(self._engine, messages, tag))

    def briefing(self, *, state: dict[str, Any], day: str | None = None,
                 tag: str = "briefing") -> str:
        """Proactive analysis of the previous day.

        Returns the deterministic text immediately (so the dashboard is never
        empty) and, when a model is loaded, replaces it with generated prose.
        """
        from .briefing import briefing_text, build_briefing

        anchor = date.fromisoformat((day or date.today().isoformat())[:10])
        heuristic = briefing_text(build_briefing(state, today=anchor))
        messages, _ = self._engine.briefing_messages(state=state, day=day)
        started = self._start(GenerationWorker(
            self._engine, messages, tag, fallback=heuristic))
        if not started:
            self.response.emit(heuristic, tag)
        return heuristic

    def editor_action(self, kind: str, body: str, *, state: dict[str, Any],
                      day: str | None = None, tag: str = "editor") -> bool:
        """Summarize / improve / ideas for the diary editor."""
        from .context import build_context
        from .prompts import default_persona, editor_prompt, system_prompt

        context = build_context(state, day=day, query=body[:400], max_chars=1200)
        persona = str(self._engine._ai().get("persona") or default_persona())
        messages = [
            {"role": "system", "content": system_prompt(persona, context)},
            {"role": "user", "content": editor_prompt(kind, body)},
        ]
        return self._start(GenerationWorker(self._engine, messages, tag))

    # ----------------------------------------------------------- model mgmt
    def load_model(self, model_path: str | None = None) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self._load_worker = ModelLoadWorker(self._engine, model_path)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.succeeded.connect(self._on_load_done)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.finished.connect(self._on_load_finished)
        self.busyChanged.emit(True, "model")
        self._load_worker.start()

    def unload_model(self) -> None:
        self.load_model("")

    def _on_load_progress(self, message: str) -> None:
        self.statusChanged.emit({"message": message, "pending": True})

    def _on_load_done(self, status: dict) -> None:
        self.statusChanged.emit(status)

    def _on_load_failed(self, message: str) -> None:
        self.statusChanged.emit({**self._engine.status().to_dict(), "message": message})
        self.error.emit(message, "model")

    def _on_load_finished(self) -> None:
        worker = self._load_worker
        self._load_worker = None
        if worker is not None:
            worker.deleteLater()
        self.busyChanged.emit(False, "")

    def shutdown(self) -> None:
        """Cancel in-flight work and wait for the threads to join."""
        self.cancel()
        for worker in (self._worker, self._load_worker):
            if worker is None:
                continue
            worker.cancel() if hasattr(worker, "cancel") else None
            worker.wait(4000)
