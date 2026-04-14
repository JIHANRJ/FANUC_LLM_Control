#!/bin/bash

# Script to start Ollama reliably by stopping any conflicting services and processes

echo "Stopping Ollama systemd service if running..."
sudo systemctl stop ollama 2>/dev/null || echo "Service not running or failed to stop"

echo "Killing any existing Ollama processes..."
pkill -f ollama || echo "No processes to kill"

echo "Waiting for port to free up..."
sleep 3

# Check if port is still in use
if ss -tulpn | grep -q :11434; then
    echo "Port 11434 still in use. Trying to force kill..."
    sudo fuser -k 11434/tcp 2>/dev/null || echo "Failed to kill process on port"
    sleep 2
fi

echo "Starting Ollama server..."
exec ollama serve