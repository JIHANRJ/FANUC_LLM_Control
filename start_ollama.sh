#!/usr/bin/env bash

set -euo pipefail

# Script to start Ollama reliably by stopping any conflicting services and processes.

resolve_ollama_bin() {
    if [[ -n "${OLLAMA_BIN:-}" && -x "${OLLAMA_BIN:-}" ]]; then
        printf '%s\n' "$OLLAMA_BIN"
        return 0
    fi

    local candidate
    for candidate in \
        "$(command -v ollama 2>/dev/null || true)" \
        /usr/local/bin/ollama \
        /usr/bin/ollama \
        "$HOME/.local/bin/ollama"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

OLLAMA_BIN_PATH="$(resolve_ollama_bin)" || {
    echo "Error: Ollama is not installed or not on PATH."
    echo "Install Ollama first, or set OLLAMA_BIN=/path/to/ollama before running this script."
    exit 1
}

if command -v systemctl >/dev/null 2>&1; then
    if sudo -n true >/dev/null 2>&1; then
        echo "Stopping Ollama systemd service if running..."
        sudo systemctl stop ollama 2>/dev/null || echo "Service not running or failed to stop"
    else
        echo "Skipping systemd service stop because sudo requires a password."
    fi
fi

echo "Killing any existing Ollama processes..."
pkill -x ollama 2>/dev/null || echo "No processes to kill"

echo "Waiting for port 11434 to free up..."
sleep 2

if command -v ss >/dev/null 2>&1 && ss -tulpn 2>/dev/null | grep -q ':11434'; then
    echo "Port 11434 still in use."
    if sudo -n true >/dev/null 2>&1; then
        echo "Trying to force kill the process on port 11434..."
        sudo fuser -k 11434/tcp 2>/dev/null || echo "Failed to kill process on port"
    else
        echo "Sudo is required to force-kill a process bound to 11434."
    fi
    sleep 1
fi

echo "Starting Ollama server using: $OLLAMA_BIN_PATH"
exec "$OLLAMA_BIN_PATH" serve