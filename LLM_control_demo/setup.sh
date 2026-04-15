#!/bin/bash

# Quick setup guide for LLM I/O Controller Demo

set -e

echo "========================================="
echo "LLM I/O Controller - Quick Setup"
echo "========================================="

cd "$(dirname "$0")"

echo ""
echo "Checking Ollama..."
if ! command -v ollama &> /dev/null; then
    echo "Error: Ollama not found. Please install Ollama first."
    exit 1
fi

echo "Ollama is installed"

echo ""
echo "Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found."
    exit 1
fi

echo "Python 3 is available"

echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. In one terminal, start Ollama:"
echo "   $ ollama serve"
echo ""
echo "2. In another terminal, run the controller:"
echo "   $ cd LLM_control_demo"
echo "   $ python3 llm_io_controller.py --simulation"
echo ""
echo "3. Try these commands:"
echo "   > move to red box"
echo "   > go to blue box"  
echo "   > move home"
echo "   > status"
echo ""
echo "For real ROS2 mode (requires ROS2 + FANUC packages):"
echo "   $ python3 llm_io_controller.py"
echo ""
