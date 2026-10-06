# ✠ LifeBoard AI

A **native, fully-offline Windows desktop workbench** for tracking habits, diet,
training and reading — with a **local LLM advisor** that reads *your own log*
and coaches you. No browser, no HTML/JS/CSS, no local HTTP server, no webview.
The UI is 100 % PySide6 (Qt for Python); the advisor is
`llama-cpp-python` running a quantised GGUF model on your own machine.

```
┌─────────────┬───────────────────────────────────────────────┐
│  ✠ Command   │  [✠] Command Deck   score · heatmap · habits   │
│  ⚔ Iron      │  [⚔] Iron Library   exercise lib · set logging │
│  ❖ Librarium │  [❖] Librarium      diary editor · book shelf  │
│  ☾ Rites     │  [☾] Rites & Config hue · goals · AI · vault   │
│             │                                                 │
│  AI advisor streams on a background QThread, never blocks UI │
└─────────────┴───────────────────────────────────────────────┘
```

---

## Язык интерфейса / Interface language

Программа по умолчанию **полностью на русском**: меню, вкладки, подписи,
тепловая карта, сводка, эвристические ответы советника и даже демонстрационные
данные. Английская версия сохранена для тестов и задаётся переменной окружения:

```bat
set LIFEBOARD_LANG=en        :: English strings (the test-suite default)
set LIFEBOARD_LANG=ru        :: Русский (включено по умолчанию)
```

См. `src/lifeboard/i18n.py` и `tests/test_i18n.py`.

---

## Why this exists

Most "AI life trackers" are web apps that send your private journal to someone
else's server. LifeBoard AI is the opposite:

* **No web stack at all** — PySide6 `QWidgets`, a custom `QGraphicsView`
  heatmap, QSS theming.
* **No server** — a single `data.json` written atomically next to the `.exe`,
  with a rolling 5-slot `backups/` vault.
* **No telemetry** — the only thing the app can talk to is its own file.

---

## Quick start (Windows, from source)

```bat
run_dev.bat                :: diagnose the environment + start with a console
```

## Build a distributable .exe

```bat
build_windows.bat          :: CPU build   ->  dist\LifeBoard\LifeBoard.exe
build_windows.bat --cuda   :: CUDA build  (needs Build Tools + CUDA 12.1)
```

The output is a **single folder** (`dist\LifeBoard\`) containing the `.exe` and
every DLL it needs (including `libllama.dll` / `ggml*.dll`, and `cudart64_*.dll`
/ `cublas64_*.dll` for CUDA builds). Ship the whole folder.

### Point it at a model

1. Drop a quantised `.gguf` into `dist\LifeBoard\models\` (see
   [`models/README.md`](models/README.md) for recommendations).
2. Open **☾ Rites & Config → Local AI Engine**, press **⟳** then **⚡ LOAD MODEL**.
3. Until a model is loaded the advisor runs in **heuristic mode** — it still
   analyses your log and writes the morning briefing, from rules instead of a
   transformer.

---

## Project structure

```
ldb/
├── main.py                 # entry point (source, -m, and PyInstaller)
├── LifeBoard.spec          # PyInstaller --onedir console=False
├── build_windows.bat       # install deps + build (optional --cuda)
├── run_dev.bat             # diagnostic run from source with a console
├── requirements.txt        # PySide6, llama-cpp-python, pyinstaller
├── requirements-dev.txt    # + pytest
│
├── src/lifeboard/
│   ├── app.py              # MainWindow, theme wiring, AI plumbing, crash log
│   ├── paths.py            # frozen-aware data/models/theme resolution
│   ├── theme.py            # single-hue palette + QSS renderer (Qt-free)
│   ├── text.py             # markdown <-> rich-text bridge for the AI editor
│   ├── i18n.py             # two-language UI (ru default, en via LIFEBOARD_LANG)
│   ├── storage/
│   │   ├── schema.py       # data.json shape, defaults, defensive sanitisation
│   │   ├── store.py        # atomic writes, 5-slot backup vault, recovery
│   │   └── metrics.py      # scoring, tonnage, streaks, heatmap series
│   ├── ai/
│   │   ├── prompts.py      # hidden system prompts, instruction wrappers
│   │   ├── context.py      # RAG: serialise the log + keyword/recency search
│   │   ├── briefing.py     # deterministic proactive morning briefing
│   │   ├── engine.py       # lazy llama-cpp-python wrapper + fallbacks
│   │   └── workers.py      # QThread generation workers + AiController
│   ├── widgets/
│   │   ├── heatmap.py      # 365-day QGraphicsView contribution grid
│   │   ├── chat.py         # QListView transcript + QTextEdit composer
│   │   ├── sidebar.py      # QListWidget nav with a painted delegate
│   │   ├── trackers.py     # habit + meal rows with inline progress bars
│   │   └── common.py       # Card, StatTile, InlineBar, ScoreRing, Banner…
│   └── views/
│       ├── dashboard.py    # Command Deck
│       ├── workout.py      # Iron Library
│       ├── library.py      # Librarium (diary + book shelf)
│       └── settings.py     # Rites & Config (hue, goals, AI, data vault)
│
├── assets/
│   ├── theme.qss           # the QSS template ({{TOKEN}} placeholders)
│   └── images/             # diary images live here at runtime
├── models/                 # GGUF weights (never committed)
├── packaging/version_info.txt
├── tools/
│   ├── diagnose.py         # environment report used by run_dev.bat
│   └── seed_demo.py        # ~60 days of reproducible demo data
└── tests/                  # 182 tests: storage, metrics, briefing, RAG,
                            # theme, llama integration, GUI (offscreen)
```

---

## Architecture notes

### Data (`data.json`)
Everything lives in one document with a `schema_version`. `schema.sanitize_state()`
is the single choke-point: whatever is on disk is coerced into a valid shape, so a
hand-edited or truncated file can never crash a widget. See `storage/schema.py`.

### Atomic writes + backups
`Store.save()` writes `data.json.tmp`, `fsync`s it, then `os.replace()`s it over the
old file — a crash mid-write cannot corrupt the live file. The previous good file is
rotated into `backups/` (newest 5 kept). If `data.json` is ever unreadable, the next
launch recovers from the newest intact backup and tells you so instead of wiping
your history.

### The advisor runs on a thread
`AiController` owns exactly one in-flight `GenerationWorker (QThread)`. Tokens are
emitted as signals and streamed into the chat; the GUI thread never blocks, and the
user can abort at any token boundary (`Esc` or ■ STOP). `llama-cpp-python` is imported
**lazily**: without the package or a model the engine reports `heuristic` and answers
from a deterministic rule engine over your own data.

### Context = RAG over your own file
Before any generation, `ai/context.py` serialises the relevant slice of `data.json`
(today's macros/tonnage/habits, a rolling 7-day window, day-over-day deltas, goals)
plus a keyword+recency retrieval over diary entries and book notes, and injects it as
a hidden `system` turn. The model never sees anything it can't read back from the file.

### Proactive briefing
On startup the dashboard analyses *yesterday* against the day before and the trailing
week — tonnage deltas, calorie/protein shortfall, habit completion, rest-day detection —
and writes a severity-tagged briefing. When a model is loaded, the same metrics are
handed to it for a prose version; the deterministic text is the fallback.

---

## Development

```bash
python -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q          # full suite (offscreen, no display)
.venv/bin/python tools/seed_demo.py          # populate ./data.json with demo data
.venv/bin/python main.py                     # run with a visible window
```

On a headless box the GUI tests use Qt's `offscreen` platform automatically
(`tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`).

### Windows build: `check_hostname requires server_hostname`
If your machine is behind an `https://` proxy and ships an old pip (<22), every
`pip` call dies with `ValueError: check_hostname requires server_hostname`.
`build_windows.bat` already works around it: it rewrites the proxy scheme to
`http://` (the CONNECT tunnel is unchanged, TLS still end-to-end) and upgrades
pip via `python -m pip` (module form, since `pip.exe` cannot replace itself on
Windows). If you run pip by hand instead, do the same:

```bat
set HTTPS_PROXY=!HTTPS_PROXY:https://=http://!
python -m pip install --upgrade pip
```

### Theming
One number drives the whole look: `settings.hue`. `theme.build_palette()` derives
every background, border, text ramp, accent, semantic colour and the five heatmap
intensity levels from it; `assets/theme.qss` holds the layout in `{{TOKEN}}`
placeholders. `tests/test_theme.py` fails if a token is ever left unresolved.

---

## Testing status

`tests/` contains ~165 tests covering storage atomicity/backup/recovery, the metrics
and briefing maths, the RAG serialiser, theme rendering, llama-cpp-python integration
(against the real library when installed), and a full GUI pass on the offscreen
platform (habits, meals, set logging with tonnage, diary + AI context menu, heatmap
interaction, settings, restore) plus `tests/test_i18n.py` which flips the UI to Russian and asserts the Russian catalogue end to end. Run them with `pytest -q`.

## License

MIT — see [`LICENSE`](LICENSE).
