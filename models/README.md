# models/ — where the local brain lives

Drop **quantised GGUF** model files in this folder. Nothing is downloaded,
nothing is uploaded: the advisor runs entirely on your machine.

## Recommended models

| Model | Quant | Size | Notes |
|---|---|---|---|
| Llama-3-8B-Instruct | Q4_K_M | ~4.9 GB | best advice quality, needs ~8 GB RAM free |
| Llama-3-8B-Instruct | Q3_K_M | ~3.7 GB | good compromise |
| Phi-3-mini-4k-instruct | Q4_K_M | ~2.2 GB | fast, excellent on CPU-only machines |
| Qwen2.5-7B-Instruct | Q4_K_M | ~4.7 GB | strong at terse structured answers |

Get them from Hugging Face (search `<model name> GGUF`), e.g. the
`bartowski`, `TheBloke` or `lmstudio-community` repositories.

## After copying a file

1. Start LifeBoard AI.
2. Open **☾ Rites & Config → Local AI Engine**.
3. Press **⟳** to rescan, pick the model, then **⚡ LOAD MODEL**.
4. The status strip should read `engine: llama.cpp · model: <file>.gguf`.

Until a model is loaded the advisor runs in **heuristic mode**: it still
analyses your log and produces the morning briefing, but the text is computed
from rules rather than generated.

## Models on another drive

Models are large. Instead of duplicating them next to the exe, point the app at
an existing folder:

```bat
setx LIFEBOARD_MODELS "D:\AI\models"
```

(Restart the app afterwards.)

## GPU acceleration

The default `llama-cpp-python` install is CPU-only. For CUDA:

```bat
build_windows.bat --cuda
```

or by hand:

```bat
pip install llama-cpp-python --force-reinstall --no-cache-dir ^
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

Then set **GPU layers** to `-1` (offload everything) in the settings page.
You also need the matching CUDA runtime (`cudart64_*.dll`, `cublas64_*.dll`) on
the machine — the CUDA wheels ship them and `LifeBoard.spec` copies them into
the build.

## Sizing the context window

`context window` (n_ctx) is how much text the model can see at once. LifeBoard
injects roughly 2–3 KB of your own log per request, so:

* **2048** — fine for quick questions on a small model
* **4096** — the default, comfortable
* **8192+** — only if you ask long questions; it costs RAM
