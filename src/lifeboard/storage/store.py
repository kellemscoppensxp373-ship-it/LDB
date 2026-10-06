"""Atomic JSON persistence with a rolling 5-slot backup vault.

Write protocol
--------------
1. Serialise the document to ``data.json.tmp`` **in the same directory**.
2. ``flush()`` + ``os.fsync()`` so the bytes are on the platter.
3. ``os.replace()`` — atomic on both NTFS and POSIX, so a crash mid-write can
   never leave a half-written ``data.json``.
4. Optionally rotate the previous good file into ``backups/`` and prune to the
   5 newest states.

Read protocol
-------------
If ``data.json`` is missing → create defaults.  If it exists but is not valid
JSON (power cut, full disk, user edit) → recover from the newest intact backup
and surface a :class:`CorruptionRecovered` exception to the caller so the UI
can tell the user what happened instead of silently starting from zero.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from .. import paths
from .schema import (
    iso_day,
    new_id,
    now_iso,
    sanitize_state,
)

BACKUP_KEEP = 5
BACKUP_PREFIX = "data-"
TMP_SUFFIX = ".tmp"


class StoreError(RuntimeError):
    """Raised when the data file cannot be read or written."""


class CorruptionRecovered(StoreError):
    """``data.json`` was unreadable; state was rebuilt (possibly from backup)."""

    def __init__(self, message: str, recovered_from: Path | None = None):
        super().__init__(message)
        self.recovered_from = recovered_from


def _fsync_dir(directory: Path) -> None:
    """Best-effort directory fsync (POSIX only; a no-op on Windows)."""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class Store:
    """Owns ``data.json``: load, mutate, atomic save, backup, restore."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        backup_keep: int = BACKUP_KEEP,
        auto_backup: bool = True,
        backup_min_interval: float = 30.0,
        today: Callable[[], str] | None = None,
    ) -> None:
        self.path = Path(path) if path else paths.data_path()
        self.backup_dir = self.path.parent / paths.BACKUP_DIRNAME
        self.backup_keep = max(1, int(backup_keep))
        self.auto_backup = auto_backup
        self.backup_min_interval = float(backup_min_interval)
        self.today = today or (lambda: iso_day())
        self._lock = threading.RLock()
        self._last_backup_at = 0.0
        self.last_error: str | None = None
        self.data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------ load
    def load(self) -> dict[str, Any]:
        with self._lock:
            self.last_error = None
            if not self.path.exists():
                self.data = sanitize_state({})
                self.save(write_backup=False)
                return self.data
            try:
                raw = self._read_json(self.path)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                backup = self.newest_healthy_backup()
                if backup is not None:
                    try:
                        self.data = sanitize_state(self._read_json(backup))
                    except Exception as exc2:  # pragma: no cover - defensive
                        self.data = sanitize_state({})
                        raise CorruptionRecovered(
                            f"data.json and backup {backup.name} are both unreadable "
                            f"({exc}, {exc2}); started from defaults.",
                            recovered_from=None,
                        ) from exc2
                    self.save(write_backup=False)
                    raise CorruptionRecovered(
                        f"data.json was unreadable ({exc}); restored from "
                        f"{backup.name}.",
                        recovered_from=backup,
                    ) from exc
                self.data = sanitize_state({})
                self.save(write_backup=False)
                raise CorruptionRecovered(
                    f"data.json was unreadable ({exc}) and no backup existed; "
                    "started from defaults.",
                    recovered_from=None,
                ) from exc
            self.data = sanitize_state(raw)
            return self.data

    @staticmethod
    def _read_json(path: Path) -> Any:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    # ------------------------------------------------------------------ save
    def save(self, *, write_backup: bool | None = None) -> Path:
        """Atomically persist the current document; returns the written path."""
        with self._lock:
            self.data["updated"] = now_iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + TMP_SUFFIX)
            payload = json.dumps(self.data, indent=2, ensure_ascii=False, sort_keys=False)
            try:
                with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                if write_backup or (write_backup is None and self.auto_backup):
                    self._maybe_backup()
                os.replace(tmp, self.path)
                _fsync_dir(self.path.parent)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                self.last_error = str(exc)
                raise StoreError(f"Could not write {self.path}: {exc}") from exc
            self.last_error = None
            return self.path

    def _maybe_backup(self) -> None:
        """Rotate the on-disk file into ``backups/`` at most every N seconds."""
        if not self.path.exists():
            return
        now = time.time()
        if now - self._last_backup_at < self.backup_min_interval:
            return
        if self.snapshot() is not None:
            self._last_backup_at = now

    # --------------------------------------------------------------- backups
    def snapshot(self, reason: str = "") -> Path | None:
        """Copy the current ``data.json`` into ``backups/`` and prune.

        Returns the created backup path, or ``None`` if there is nothing to
        back up yet.
        """
        with self._lock:
            if not self.path.exists():
                return None
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            suffix = f"-{reason}" if reason else ""
            target = self.backup_dir / f"{BACKUP_PREFIX}{stamp}{suffix}.json"
            try:
                shutil.copy2(self.path, target)
            except OSError as exc:
                self.last_error = str(exc)
                return None
            self.prune_backups()
            return target

    def list_backups(self) -> list[Path]:
        """Newest-first list of backup files."""
        if not self.backup_dir.is_dir():
            return []
        files = [
            p for p in self.backup_dir.glob(f"{BACKUP_PREFIX}*.json") if p.is_file()
        ]
        return sorted(files, key=lambda p: p.name, reverse=True)

    def prune_backups(self) -> list[Path]:
        """Delete everything beyond the newest ``backup_keep`` states."""
        stale = self.list_backups()[self.backup_keep:]
        for path in stale:
            try:
                path.unlink()
            except OSError:
                pass
        return stale

    def newest_healthy_backup(self) -> Path | None:
        """Newest backup that parses as JSON."""
        for candidate in self.list_backups():
            try:
                self._read_json(candidate)
            except Exception:
                continue
            return candidate
        return None

    def restore(self, backup: Path | str) -> dict[str, Any]:
        """Restore from a backup file (the live file is backed up first)."""
        backup = Path(backup)
        if not backup.is_file():
            raise StoreError(f"Backup not found: {backup}")
        payload = sanitize_state(self._read_json(backup))
        with self._lock:
            self.snapshot("pre-restore")
            self.data = payload
            self.save(write_backup=False)
        return self.data

    # ------------------------------------------------------------- threading
    def snapshot_data(self) -> dict[str, Any]:
        """Deep copy of the document — safe to hand to the AI worker thread."""
        import copy

        with self._lock:
            return copy.deepcopy(self.data)

    def mutate(self, fn: Callable[[dict[str, Any]], Any], *, save: bool = True) -> Any:
        """Apply ``fn`` to the document under the lock, then persist."""
        with self._lock:
            result = fn(self.data)
            if save:
                self.save()
            return result

    # --------------------------------------------------------------- queries
    @property
    def settings(self) -> dict[str, Any]:
        return self.data["settings"]

    @property
    def goals(self) -> dict[str, Any]:
        return self.data["settings"]["goals"]

    def day(self, day: str | None = None) -> dict[str, Any]:
        """Everything logged for one day, in a stable shape."""
        day = iso_day(day)
        workout = self.data["workout_log"].get(day, {"name": "", "notes": "", "entries": []})
        diet = self.data["diet_log"].get(day, {"meals": []})
        return {
            "date": day,
            "habits": dict(self.data["habit_log"].get(day, {})),
            "meals": list(diet.get("meals", [])),
            "workout_name": workout.get("name", ""),
            "workout_notes": workout.get("notes", ""),
            "workout_entries": list(workout.get("entries", [])),
            "diary": self.data["diary"].get(day, {}),
        }

    def logged_days(self) -> Iterator[str]:
        """Every day with any activity, oldest first."""
        days: set[str] = set()
        days.update(self.data["habit_log"])
        days.update(self.data["diet_log"])
        days.update(self.data["workout_log"])
        days.update(self.data["diary"])
        return iter(sorted(days))

    # ------------------------------------------------------------- mutations
    def set_habit(self, habit_id: str, done: bool, day: str | None = None) -> None:
        day = iso_day(day or self.today())

        def apply(data: dict[str, Any]) -> None:
            data["habit_log"].setdefault(day, {})[habit_id] = 1 if done else 0

        self.mutate(apply)

    def add_meal(self, meal: dict[str, Any], day: str | None = None) -> dict[str, Any]:
        day = iso_day(day or self.today())
        meal = dict(meal)
        meal.setdefault("id", new_id("m"))

        def apply(data: dict[str, Any]) -> None:
            data["diet_log"].setdefault(day, {"meals": []})["meals"].append(meal)

        self.mutate(apply)
        return meal

    def remove_meal(self, meal_id: str, day: str | None = None) -> bool:
        day = iso_day(day or self.today())

        def apply(data: dict[str, Any]) -> None:
            meals = data["diet_log"].get(day, {}).get("meals", [])
            data["diet_log"][day]["meals"] = [m for m in meals if m.get("id") != meal_id]

        before = len(self.data["diet_log"].get(day, {}).get("meals", []))
        self.mutate(apply)
        return len(self.data["diet_log"].get(day, {}).get("meals", [])) < before

    def save_workout(self, entries: list[dict[str, Any]], day: str | None = None,
                     name: str = "", notes: str = "") -> None:
        day = iso_day(day or self.today())

        def apply(data: dict[str, Any]) -> None:
            if entries:
                data["workout_log"][day] = {"name": name, "notes": notes, "entries": entries}
            else:
                data["workout_log"].pop(day, None)

        self.mutate(apply)

    def save_diary(self, html: str, text: str, day: str | None = None, title: str = "") -> None:
        day = iso_day(day or self.today())

        def apply(data: dict[str, Any]) -> None:
            if html.strip() or text.strip():
                data["diary"][day] = {
                    "html": html,
                    "text": text,
                    "title": title,
                    "updated": now_iso(),
                }
            else:
                data["diary"].pop(day, None)

        self.mutate(apply)

    def add_chat_message(self, role: str, content: str) -> dict[str, Any]:
        message = {"role": role, "content": content, "ts": now_iso()}

        def apply(data: dict[str, Any]) -> None:
            data["ai"]["chat"].append(message)
            data["ai"]["chat"] = data["ai"]["chat"][-400:]

        self.mutate(apply)
        return message

    def replace_last_assistant_message(self, content: str) -> None:
        """Finalise the streaming placeholder.

        ``content`` empty means the turn produced nothing (cancelled or failed),
        so the placeholder is dropped instead of persisting a blank bubble.
        """
        def apply(data: dict[str, Any]) -> None:
            chat = data["ai"]["chat"]
            for index in range(len(chat) - 1, -1, -1):
                if chat[index].get("role") == "assistant":
                    if content.strip():
                        chat[index]["content"] = content
                        chat[index]["ts"] = now_iso()
                    else:
                        del chat[index]
                    return

        self.mutate(apply)

    def clear_chat(self) -> None:
        self.mutate(lambda data: data["ai"]["chat"].clear())

    def set_briefing(self, text: str, day: str | None = None) -> None:
        day = iso_day(day or self.today())
        if not text.strip():
            return

        def apply(data: dict[str, Any]) -> None:
            data["ai"]["briefings"][day] = text.strip()

        self.mutate(apply)

    def add_book(self, book: dict[str, Any]) -> dict[str, Any]:
        book = dict(book)
        book.setdefault("id", new_id("b"))

        def apply(data: dict[str, Any]) -> None:
            data["library"].append(book)

        self.mutate(apply)
        return book

    def update_book(self, book_id: str, **fields: Any) -> None:
        def apply(data: dict[str, Any]) -> None:
            for book in data["library"]:
                if book["id"] == book_id:
                    book.update(fields)

        self.mutate(apply)

    def remove_book(self, book_id: str) -> None:
        def apply(data: dict[str, Any]) -> None:
            data["library"] = [b for b in data["library"] if b["id"] != book_id]

        self.mutate(apply)

    def add_exercise(self, exercise: dict[str, Any]) -> dict[str, Any]:
        exercise = dict(exercise)
        exercise.setdefault("id", new_id("x"))

        def apply(data: dict[str, Any]) -> None:
            data["exercises"].append(exercise)

        self.mutate(apply)
        return exercise

    def remove_exercise(self, exercise_id: str) -> None:
        def apply(data: dict[str, Any]) -> None:
            data["exercises"] = [e for e in data["exercises"] if e["id"] != exercise_id]

        self.mutate(apply)

    def add_habit(self, name: str, glyph: str = "✧") -> dict[str, Any]:
        habit = {"id": new_id("h"), "name": name.strip()[:120], "glyph": glyph[:4] or "✧",
                 "active": True, "created": now_iso()}

        def apply(data: dict[str, Any]) -> None:
            data["habits"].append(habit)

        self.mutate(apply)
        return habit

    def remove_habit(self, habit_id: str) -> None:
        def apply(data: dict[str, Any]) -> None:
            data["habits"] = [h for h in data["habits"] if h["id"] != habit_id]
            for entries in data["habit_log"].values():
                entries.pop(habit_id, None)

        self.mutate(apply)

    def update_settings(self, **fields: Any) -> None:
        """Shallow-update top-level settings keys (``goals``/``ai`` merge)."""
        def apply(data: dict[str, Any]) -> None:
            for key, value in fields.items():
                if key in ("goals", "ai") and isinstance(value, dict):
                    data["settings"][key].update(value)
                else:
                    data["settings"][key] = value
            data["settings"] = sanitize_state({"settings": data["settings"]})["settings"]

        self.mutate(apply)

    def shutdown(self) -> None:
        """Final save + guaranteed backup on app exit."""
        with self._lock:
            self.save(write_backup=False)
            self._last_backup_at = 0.0
            self.snapshot("exit")
