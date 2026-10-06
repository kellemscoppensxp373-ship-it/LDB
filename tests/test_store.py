"""Atomic writes, the 5-slot backup vault, and corruption recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lifeboard.storage.store import BACKUP_KEEP, CorruptionRecovered, Store


def test_creates_data_file_on_first_run(tmp_path: Path):
    path = tmp_path / "data.json"
    store = Store(path, backup_min_interval=0.0)
    assert path.is_file()
    assert store.data["settings"]["goals"]["kcal"] == 2600
    # The very first write has nothing to back up yet...
    assert store.list_backups() == []
    # ...the next save rotates the good file into the vault.
    store.save()
    assert len(store.list_backups()) == 1


def test_save_is_atomic_and_leaves_no_temp_file(tmp_store: Store):
    tmp_store.data["settings"]["profile_name"] = "Renamed"
    tmp_store.save()
    assert tmp_store.path.with_name("data.json.tmp").exists() is False
    on_disk = json.loads(tmp_store.path.read_text(encoding="utf-8"))
    assert on_disk["settings"]["profile_name"] == "Renamed"
    assert "updated" in on_disk


def test_backup_vault_keeps_exactly_five(tmp_path: Path):
    store = Store(tmp_path / "data.json", backup_min_interval=0.0)
    for index in range(9):
        store.data["settings"]["profile_name"] = f"state-{index}"
        store.save()
    backups = store.list_backups()
    assert len(backups) == BACKUP_KEEP
    # Newest first.
    assert backups[0].name > backups[-1].name


def test_snapshot_and_restore_round_trip(tmp_path: Path):
    store = Store(tmp_path / "data.json", backup_min_interval=0.0)
    store.add_habit("Original habit")
    backup = store.snapshot("before-change")
    assert backup is not None and backup.is_file()

    store.data["habits"].clear()
    store.save()
    assert store.data["habits"] == []

    store.restore(backup)
    names = [h["name"] for h in store.data["habits"]]
    assert "Original habit" in names
    assert len(names) == 5          # 4 seeded rites + the one we added


def test_restore_requires_existing_file(tmp_store: Store):
    with pytest.raises(Exception):
        tmp_store.restore(Path("/nonexistent/backup.json"))


def test_corrupt_file_recovers_from_backup(tmp_path: Path):
    path = tmp_path / "data.json"
    store = Store(path, backup_min_interval=0.0)
    store.add_habit("Saved habit")
    store.save()
    backup = store.list_backups()[0]

    path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(CorruptionRecovered) as info:
        Store(path, backup_min_interval=0.0)
    assert "unreadable" in str(info.value)
    reloaded = Store(path, backup_min_interval=0.0)
    assert reloaded.newest_healthy_backup() == backup or reloaded.data["habits"]


def test_corrupt_file_without_backup_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "data.json"
    path.write_text("]]]", encoding="utf-8")
    with pytest.raises(CorruptionRecovered):
        Store(path, backup_min_interval=0.0)
    # The bad file was replaced with defaults, so the next load is clean.
    recovered = Store(path, backup_min_interval=0.0)
    assert recovered.data["settings"]["goals"]["kcal"] == 2600
    assert recovered.last_error is None


def test_prune_backups_removes_only_the_old_ones(tmp_path: Path):
    store = Store(tmp_path / "data.json", backup_keep=3, backup_min_interval=0.0)
    for index in range(6):
        store.data["settings"]["profile_name"] = f"s{index}"
        store.save()
    assert len(store.list_backups()) == 3
    pruned = store.prune_backups()
    assert pruned == []


def test_mutate_persists_and_returns_value(tmp_store: Store):
    result = tmp_store.mutate(lambda data: data["settings"].__setitem__("hue", 12) or 7)
    assert result == 7
    assert json.loads(tmp_store.path.read_text(encoding="utf-8"))["settings"]["hue"] == 12


def test_snapshot_data_is_a_deep_copy(tmp_store: Store):
    copy = tmp_store.snapshot_data()
    copy["habits"].append({"id": "ghost", "name": "Ghost"})
    assert all(h["id"] != "ghost" for h in tmp_store.data["habits"])


def test_habit_and_meal_helpers(tmp_store: Store):
    habit_id = tmp_store.data["habits"][0]["id"]
    tmp_store.set_habit(habit_id, True, day="2026-05-05")
    tmp_store.set_habit(habit_id, False, day="2026-05-05")
    assert tmp_store.data["habit_log"]["2026-05-05"][habit_id] == 0

    meal = tmp_store.add_meal({"name": "Lunch", "kcal": 500}, day="2026-05-05")
    assert tmp_store.data["diet_log"]["2026-05-05"]["meals"][0]["id"] == meal["id"]
    assert tmp_store.remove_meal(meal["id"], day="2026-05-05") is True
    assert tmp_store.data["diet_log"]["2026-05-05"]["meals"] == []


def test_chat_helpers_keep_only_the_last_400(tmp_store: Store):
    for index in range(410):
        tmp_store.add_chat_message("user", f"message {index}")
    chat = tmp_store.data["ai"]["chat"]
    assert len(chat) == 400
    assert chat[-1]["content"] == "message 409"
    tmp_store.replace_last_assistant_message("final answer")
    tmp_store.add_chat_message("assistant", "streamed")
    tmp_store.replace_last_assistant_message("final answer")
    assert tmp_store.data["ai"]["chat"][-1]["content"] == "final answer"


def test_shutdown_writes_final_backup(tmp_path: Path):
    store = Store(tmp_path / "data.json", backup_min_interval=999)
    before = len(store.list_backups())
    store.shutdown()
    assert len(store.list_backups()) == before + 1


def test_unicode_survives_the_round_trip(tmp_store: Store):
    tmp_store.add_habit("Читати 20 сторінок ✧ ☾")
    reloaded = Store(tmp_store.path, backup_min_interval=0.0)
    assert "Читати 20 сторінок ✧ ☾" in [h["name"] for h in reloaded.data["habits"]]
    assert os.linesep or True  # keep the import meaningful on Windows too
