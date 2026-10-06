"""Packaging guarantees: the PyInstaller spec and the frozen-path logic.

The Windows ``.exe`` cannot be produced on a Linux CI box, but the two things
that actually break packaged builds can be checked here:

1. ``LifeBoard.spec`` is executed for real (with PyInstaller's globals stubbed)
   and the arguments it passes to ``EXE``/``COLLECT``/``Analysis`` are asserted
   — onedir, windowed, QSS bundled, llama.cpp hidden imports present.
2. ``lifeboard.paths`` is driven in simulated frozen mode, which is the code
   that decides where ``data.json``, ``models/`` and the bundled QSS live.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lifeboard import paths

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "LifeBoard.spec"


# --------------------------------------------------------------------------- #
# spec file
# --------------------------------------------------------------------------- #
class _Recorder:
    """Stands in for PyInstaller's build objects and records every argument."""

    def __init__(self) -> None:
        self.calls: dict[str, dict[str, Any]] = {}

    def _factory(self, name: str):
        def call(*args: Any, **kwargs: Any) -> SimpleNamespace:
            self.calls[name] = {"args": args, "kwargs": kwargs}
            # Analysis results are attribute-accessed later in the spec
            # (a.pure, a.scripts, a.binaries, a.datas).
            return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[],
                                   zipfiles=[], name=name)

        return call


@pytest.fixture
def spec_run() -> dict[str, Any]:
    """Execute LifeBoard.spec with PyInstaller's injected globals stubbed."""
    pytest.importorskip("PyInstaller", reason="PyInstaller is not installed")
    recorder = _Recorder()
    environment = {
        "__name__": "__main__",
        "__file__": str(SPEC),
        "SPECPATH": str(SPEC.parent),
        "SPEC": str(SPEC),
        "workpath": "/tmp/lb-work",
        "DISTPATH": "/tmp/lb-dist",
        "Analysis": recorder._factory("Analysis"),
        "PYZ": recorder._factory("PYZ"),
        "EXE": recorder._factory("EXE"),
        "COLLECT": recorder._factory("COLLECT"),
        "BUNDLE": recorder._factory("BUNDLE"),
    }
    code = compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec")
    exec(code, environment)          # noqa: S102 - executing our own spec
    return recorder.calls


def test_spec_exists_at_the_repository_root():
    assert SPEC.is_file()


def test_spec_targets_onedir_and_a_windowed_exe(spec_run):
    exe = spec_run["EXE"]["kwargs"]
    assert exe["console"] is False, "the app must not spawn a console window"
    assert exe["exclude_binaries"] is True, "exclude_binaries=False means onefile"
    assert exe["name"] == "LifeBoard"
    assert exe["upx"] is False, "UPX corrupts CUDA/ggml DLLs"
    assert spec_run["COLLECT"]["kwargs"]["name"] == "LifeBoard"


def test_spec_bundles_the_qss_theme(spec_run):
    datas = spec_run["Analysis"]["kwargs"]["datas"]
    destinations = {destination for _source, destination in datas}
    assert "assets" in destinations, "assets/theme.qss would be missing at runtime"
    sources = {Path(source).name for source, _destination in datas}
    assert "theme.qss" in sources


def test_spec_bundles_the_models_readme(spec_run):
    datas = spec_run["Analysis"]["kwargs"]["datas"]
    assert any(destination == "models" for _source, destination in datas)


def test_spec_declares_llama_hidden_imports(spec_run):
    hidden = spec_run["Analysis"]["kwargs"]["hiddenimports"]
    for required in ("llama_cpp", "diskcache", "jinja2", "numpy"):
        assert required in hidden


def test_spec_keeps_src_on_the_module_path(spec_run):
    pathex = spec_run["Analysis"]["kwargs"]["pathex"]
    assert str(ROOT / "src") in pathex
    assert spec_run["Analysis"]["args"][0] == [str(ROOT / "main.py")]


def test_spec_excludes_the_browser_stack(spec_run):
    excludes = spec_run["Analysis"]["kwargs"]["excludes"]
    for forbidden in ("PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                      "PySide6.QtQml", "PySide6.QtQuick"):
        assert forbidden in excludes


def test_spec_collects_llama_native_libraries(spec_run):
    """CPU wheels ship libllama/ggml; CUDA wheels also ship cudart/cublas."""
    binaries = spec_run["Analysis"]["kwargs"]["binaries"]
    assert binaries, "no llama.cpp native libraries were collected"
    names = " ".join(Path(source).name.lower() for source, _dest in binaries)
    assert "llama" in names or "ggml" in names


# --------------------------------------------------------------------------- #
# frozen path resolution
# --------------------------------------------------------------------------- #
@pytest.fixture
def frozen(tmp_path: Path, monkeypatch):
    """Pretend we are ``dist/LifeBoard/LifeBoard.exe`` with an _internal bundle."""
    exe_dir = tmp_path / "LifeBoard"
    bundle = exe_dir / "_internal"
    (bundle / "assets").mkdir(parents=True)
    (exe_dir / "LifeBoard.exe").write_bytes(b"MZ")
    (bundle / "assets" / "theme.qss").write_text("/* bundled theme */",
                                                 encoding="utf-8")
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(exe_dir / "LifeBoard.exe"),
                        raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.delenv("LIFEBOARD_MODELS", raising=False)
    return exe_dir, bundle


def test_is_frozen_detects_the_bundle(frozen):
    assert paths.is_frozen() is True


def test_frozen_writes_next_to_the_executable(frozen):
    exe_dir, _bundle = frozen
    assert paths.app_root() == exe_dir
    assert paths.data_path() == exe_dir / "data.json"
    assert paths.backup_dir() == exe_dir / "backups"
    assert paths.image_dir() == exe_dir / "assets" / "images"


def test_frozen_reads_the_qss_from_the_bundle(frozen):
    exe_dir, bundle = frozen
    assert paths.resource_root() == bundle
    assert paths.theme_path() == bundle / "assets" / "theme.qss"
    assert paths.theme_path().read_text(encoding="utf-8") == "/* bundled theme */"


def test_frozen_models_folder_is_next_to_the_exe(frozen):
    exe_dir, _bundle = frozen
    assert paths.model_dir() == exe_dir / "models"


def test_models_env_override_wins_over_the_exe_folder(frozen, tmp_path, monkeypatch):
    elsewhere = tmp_path / "big-disk-models"
    monkeypatch.setenv("LIFEBOARD_MODELS", str(elsewhere))
    assert paths.model_dir() == elsewhere


def test_ensure_runtime_dirs_creates_everything(frozen):
    exe_dir, _bundle = frozen
    created = paths.ensure_runtime_dirs()
    assert created["backups"].is_dir()
    assert created["images"].is_dir()
    assert created["models"].is_dir()
    assert created["root"] == exe_dir


def test_theme_falls_back_to_the_repo_when_not_bundled(tmp_path, monkeypatch):
    """A bundle without assets/ must still find the repo copy, not crash."""
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable",
                        str(tmp_path / "LifeBoard.exe"), raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(tmp_path / "empty"),
                        raising=False)
    assert paths.theme_path() == ROOT / "assets" / "theme.qss"
    assert paths.theme_path().is_file()


def test_human_size_rendering():
    assert paths.human_size(512) == "512 B"
    assert paths.human_size(2048) == "2.0 KB"
    assert paths.human_size(5_000_000_000) == "4.7 GB"
