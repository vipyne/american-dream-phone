"""offline_config.py — OFFLINE-mode flag, model paths, and preflight checks.

Import this module BEFORE any pipecat / HuggingFace import: Hugging Face
freezes its cache root (``HF_HOME``) at ``huggingface_hub`` import time, so
the ``os.environ.setdefault`` calls below must run first. This module itself
imports nothing from pipecat and loads no models.

OFFLINE=true swaps the bot's STT/TTS/LLM from cloud services
(Deepgram/Cartesia/Anthropic) to local ones (Whisper-MLX/Kokoro/Ollama).
The Daily transport is unchanged — "offline" means no paid AI APIs, not no
network. Model weights default to the sibling ``locat`` repo's downloads.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
# Reuse the weights already downloaded by the sibling locat repo (~10 GB).
LOCAT_MODELS = REPO_ROOT.parent / "locat" / "models"
KOKORO_DIR = LOCAT_MODELS / "kokoro"

# Load .env first so user overrides win over the setdefaults below.
load_dotenv(REPO_ROOT / ".env")

OFFLINE = os.getenv("OFFLINE", "false").strip().lower() in ("true", "1", "yes")

if OFFLINE:
    # HuggingFace cache root (Whisper-MLX weights). Must be set pre-import.
    os.environ.setdefault("HF_HOME", str(LOCAT_MODELS / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("KOKORO_MODEL_PATH", str(KOKORO_DIR / "kokoro-v1.0.onnx"))
    os.environ.setdefault("KOKORO_VOICES_PATH", str(KOKORO_DIR / "voices-v1.0.bin"))

DEFAULT_WHISPER_MODEL = "LARGE_V3_TURBO"
DEFAULT_LLM_MODEL = "qwen2.5:14b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_KOKORO_VOICE = "af_heart"


def _get(name: str, default: str) -> str:
    """Return env var ``name`` (stripped), or ``default`` when unset/blank."""
    return os.getenv(name, "").strip() or default


def whisper_model() -> str:
    """``MLXModel`` member name for Whisper-MLX STT (default LARGE_V3_TURBO).

    Other members: TINY, MEDIUM, LARGE_V3.
    """
    return _get("WHISPER_MODEL", DEFAULT_WHISPER_MODEL)


def llm_model() -> str:
    """Ollama model tag for the LLM (default ``qwen2.5:14b``)."""
    return _get("LLM_MODEL", DEFAULT_LLM_MODEL)


def ollama_base_url() -> str:
    """OpenAI-compatible Ollama endpoint (default ``http://localhost:11434/v1``).

    Note the trailing ``/v1``: the OpenAI-compat path, not the native API root.
    """
    return _get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)


def kokoro_voice() -> str:
    """Kokoro voice id (default ``af_heart``).

    Kokoro's shipped ``Settings.voice`` default is ``None`` (unsynthesizable),
    so an explicit id is always supplied.
    """
    return _get("KOKORO_VOICE", DEFAULT_KOKORO_VOICE)


def kokoro_model_path() -> str:
    """Path to the Kokoro ONNX model."""
    return _get("KOKORO_MODEL_PATH", str(KOKORO_DIR / "kokoro-v1.0.onnx"))


def kokoro_voices_path() -> str:
    """Path to the Kokoro voices bundle."""
    return _get("KOKORO_VOICES_PATH", str(KOKORO_DIR / "voices-v1.0.bin"))


def preflight_ollama() -> None:
    """Fail fast with actionable guidance if OFFLINE mode isn't runnable.

    A missing Ollama server or un-pulled model otherwise fails silently
    mid-call (the LLM call errors and nothing is spoken). Missing Kokoro
    weights would trigger a silent network auto-download instead of staying
    offline, so those are checked too. No-op when OFFLINE is false.
    """
    if not OFFLINE:
        return

    base_url = ollama_base_url()
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (localhost)
            models = json.load(resp).get("data", [])
    except (urllib.error.URLError, OSError) as exc:
        sys.exit(
            f"\n✖ OFFLINE=true but cannot reach the local LLM server at {base_url}\n"
            f"  Start Ollama first:  ./scripts/run_ollama.sh   (or: ollama serve)\n"
            f"  Details: {exc}\n"
        )

    model = llm_model()
    available = {str(m.get("id", "")) for m in models}
    # Ollama reports tags like 'llama3:latest'; match the bare name too.
    if not any(model == m or model.split(":")[0] == m.split(":")[0] for m in available):
        listed = ", ".join(sorted(available)) or "(none)"
        sys.exit(
            f"\n✖ LLM model '{model}' is not available in Ollama at {base_url}\n"
            f"  Pull it:            ollama pull {model}\n"
            f"  Or set LLM_MODEL in .env to one you have: {listed}\n"
        )

    missing = [p for p in (kokoro_model_path(), kokoro_voices_path()) if not Path(p).is_file()]
    if missing:
        paths = "\n    ".join(missing)
        sys.exit(
            f"\n✖ OFFLINE=true but Kokoro TTS weights are missing:\n    {paths}\n"
            f"  Expected the sibling locat repo's downloads (../locat/models/kokoro),\n"
            f"  or set KOKORO_MODEL_PATH / KOKORO_VOICES_PATH in .env.\n"
        )

    print(f"✓ OFFLINE preflight OK: '{model}' at {base_url}, Kokoro weights found")
