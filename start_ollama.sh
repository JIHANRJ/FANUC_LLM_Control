#!/usr/bin/env bash

set -euo pipefail

# Script to start Ollama reliably by stopping any conflicting services and processes.

OLLAMA_HOST_ADDR="${OLLAMA_HOST:-127.0.0.1:11434}"
OLLAMA_VERSION_URL="http://${OLLAMA_HOST_ADDR}/api/version"

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

ollama_is_ready() {
    curl -fsS --max-time 2 "$OLLAMA_VERSION_URL" >/dev/null 2>&1
}

can_use_passwordless_sudo() {
    sudo -n true >/dev/null 2>&1
}

OLLAMA_BIN_PATH="$(resolve_ollama_bin)" || {
    echo "Error: Ollama is not installed or not on PATH."
    echo "Install Ollama first, or set OLLAMA_BIN=/path/to/ollama before running this script."
    exit 1
}

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    if can_use_passwordless_sudo; then
        echo "Stopping Ollama systemd service if running..."
        sudo systemctl stop ollama 2>/dev/null || echo "Service not running or failed to stop"
    else
        echo "Skipping systemd service stop because sudo requires a password."
    fi
fi

echo "Killing any existing Ollama processes..."
pkill -x ollama 2>/dev/null || true
pkill -f 'ollama runner' 2>/dev/null || true

echo "Waiting for port 11434 to free up..."
sleep 2

if command -v ss >/dev/null 2>&1 && ss -tulpn 2>/dev/null | grep -q ':11434'; then
    if ollama_is_ready; then
        echo "Ollama is already running and ready at ${OLLAMA_HOST_ADDR}."
        exit 0
    fi

    echo "Port 11434 still in use by another process."
    if can_use_passwordless_sudo; then
        echo "Trying to force kill the process on port 11434..."
        sudo fuser -k 11434/tcp 2>/dev/null || echo "Failed to kill process on port"
    else
        echo "Sudo is required to force-kill a process bound to 11434."
        echo "If this is the ollama system service, run: sudo systemctl restart ollama"
        exit 1
    fi
    sleep 1
fi

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    if can_use_passwordless_sudo; then
        echo "Starting Ollama via systemd service..."
        sudo systemctl start ollama

        for _ in {1..10}; do
            if ollama_is_ready; then
                echo "Ollama is ready at ${OLLAMA_HOST_ADDR}."
                exit 0
            fi
            sleep 1
        done

        echo "Error: Ollama service started but API did not become ready in time."
        exit 1
    fi
fi

echo "Starting Ollama server using: $OLLAMA_BIN_PATH"
exec "$OLLAMA_BIN_PATH" serve