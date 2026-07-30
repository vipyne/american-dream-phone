#!/usr/bin/env bash
#
# run_ollama.sh — start a local Ollama server for OFFLINE mode, then pull the
# conversation LLM.
#
# The model store defaults to the sibling locat repo's already-downloaded
# blobs (../locat/models/ollama, ~8.4 GB qwen2.5:14b) so nothing is
# re-downloaded. Override with OLLAMA_MODELS in .env.
#
# Usage:
#   ./scripts/run_ollama.sh            # serve + pull the default model
#   LLM_MODEL=qwen2.5:7b ./scripts/run_ollama.sh
#
# The server keeps running in the foreground so you can Ctrl-C to stop it, or run
# the whole script in the background (`./scripts/run_ollama.sh &`). The bot talks
# to it over the OpenAI-compatible endpoint at http://localhost:11434/v1.

set -euo pipefail

# --- locate the repo root (parent of this script's dir) ---------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# --- load .env for overrides (LLM_MODEL, OLLAMA_HOST), if present -----------
if [[ -f "${REPO_ROOT}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a; source "${REPO_ROOT}/.env"; set +a
fi

# --- config (env-overridable) ------------------------------------------------
export OLLAMA_MODELS="${OLLAMA_MODELS:-${REPO_ROOT}/../locat/models/ollama}"
OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_HOST
LLM_MODEL="${LLM_MODEL:-qwen2.5:14b}"

mkdir -p "${OLLAMA_MODELS}"

echo "run_ollama: OLLAMA_MODELS=${OLLAMA_MODELS}"
echo "run_ollama: OLLAMA_HOST=${OLLAMA_HOST}"
echo "run_ollama: LLM_MODEL=${LLM_MODEL}"

# --- is a server already listening on this host? ----------------------------
# `ollama list` returns non-zero if it can't reach a server.
if OLLAMA_HOST="${OLLAMA_HOST}" ollama list >/dev/null 2>&1; then
  echo "run_ollama: an Ollama server is already running on ${OLLAMA_HOST}."
  echo "run_ollama: WARNING — if it was NOT started by this script, its model"
  echo "            store may differ from ${OLLAMA_MODELS}. Stop it first if you"
  echo "            want models pulled into the repo store."
  SERVER_PID=""
else
  echo "run_ollama: starting 'ollama serve' (store → ${OLLAMA_MODELS})..."
  ollama serve &
  SERVER_PID=$!

  # wait (up to ~30s) for the server to accept connections
  for _ in $(seq 1 30); do
    if OLLAMA_HOST="${OLLAMA_HOST}" ollama list >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  if ! OLLAMA_HOST="${OLLAMA_HOST}" ollama list >/dev/null 2>&1; then
    echo "run_ollama: ERROR — Ollama server did not become ready in time." >&2
    [[ -n "${SERVER_PID}" ]] && kill "${SERVER_PID}" 2>/dev/null || true
    exit 1
  fi
  echo "run_ollama: server ready (pid ${SERVER_PID})."
fi

# --- pull the model (no-op if already present) ------------------------------
echo "run_ollama: pulling '${LLM_MODEL}' (this needs network the first time)..."
OLLAMA_HOST="${OLLAMA_HOST}" ollama pull "${LLM_MODEL}"

echo "run_ollama: done. Available models:"
OLLAMA_HOST="${OLLAMA_HOST}" ollama list

# --- keep serving if we started the server ----------------------------------
if [[ -n "${SERVER_PID}" ]]; then
  echo "run_ollama: server is running in the foreground (pid ${SERVER_PID})."
  echo "            Press Ctrl-C to stop, or leave it running for the bot."
  wait "${SERVER_PID}"
fi
