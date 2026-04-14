# LLM-based I/O Controller Demo

This demo integrates natural language understanding (via Ollama LLM) with FANUC robot I/O control.

## Overview

- **Input**: Natural language commands (e.g., "Move to red box", "Go to blue box", "Move home")
- **Processing**: Ollama LLM parses the command to identify the target
- **Output**: Activates FANUC I/O pins (RO outputs) to direct the robot

## Features

- ✅ Natural language understanding of box targets
- ✅ Exclusive I/O control (only one RO active at a time)
- ✅ Simulation mode (no ROS2 required)
- ✅ Real mode with ROS2 I/O integration
- ✅ State tracking

## Available Commands

| Command | Action | I/O Effect |
|---------|--------|-----------|
| Move to red box | Navigate to red box | RO1 ON, RO2 OFF |
| Move to blue box | Navigate to blue box | RO1 OFF, RO2 ON |
| Move home | Return to home position | RO1 OFF, RO2 OFF |

## Requirements

- Python 3.8+
- Ollama with `llama3.1:8b` model
- (Optional) ROS2 with `fanuc_msgs` for real I/O control

## Quick Start (Simulation Mode)

```bash
# Start Ollama in another terminal
ollama serve

# Run the controller in simulation mode
python llm_io_controller.py --simulation
```

Then interact with the CLI:
```
You> move to red box
```

## Usage

### Simulation Mode (No ROS2 Required)
```bash
python llm_io_controller.py --simulation
```

### Real Mode (Requires ROS2)
```bash
python llm_io_controller.py
```

### Options
```
usage: llm_io_controller.py [-h] [--temperature TEMPERATURE] [--timeout TIMEOUT] [--simulation] [model]

positional arguments:
  model                 Ollama model name (default: llama3.1:8b)

optional arguments:
  -h, --help           show this help message and exit
  --temperature        Model temperature (default: 0.1)
  --timeout            Request timeout in seconds (default: 60.0)
  --simulation         Run in simulation mode (no ROS2)
```

## Examples

```
You> move to red box
🤔 Processing with LLM...
📍 Parsed target: red_box
✅ Moving to Red Box (RO1 ON) [SIM MODE]

You> status
Current state: {'active_output': 'RO1', 'active_pin': 1}
Active output: RO1

You> go home
🤔 Processing with LLM...
📍 Parsed target: home
🏠 Home position set (all RO outputs OFF) [SIM MODE]

You> exit
Goodbye!
```

## Architecture

### Components

1. **llm_io_controller.py**: Main controller script
   - Accepts natural language input
   - Uses Ollama for command parsing
   - Manages I/O state
   - Controls FANUC outputs

2. **fanuc_io_control.py**: ROS2 I/O interface
   - FanucIOClient class for read/write operations
   - Interfaces with `/fanuc_gpio_controller/` services
   - Handles RO/DI/DO/RI pin control

3. **config.py**: Shared configuration (from parent directory)
   - Ollama API URL and model settings
   - Timeout configuration

### Data Flow

```
User Input
    ↓
LLM (Ollama) → JSON Parsing
    ↓
Target Extraction (red_box, blue_box, home)
    ↓
I/O State Management
    ↓
FANUC I/O (RO1, RO2)
```

## Configuration

Edit `BOX_CONFIG` in `llm_io_controller.py` to add or modify targets:

```python
BOX_CONFIG = {
    "red": {"output": "RO", "pin": 1, "description": "Red Box"},
    "blue": {"output": "RO", "pin": 2, "description": "Blue Box"},
    "green": {"output": "RO", "pin": 3, "description": "Green Box"},  # Add new target
}
```

## Troubleshooting

### "Connection refused" error
- Ensure Ollama is running: `ollama serve` in another terminal
- Check Ollama API URL in config (default: `http://127.0.0.1:11434/api/generate`)

### "Could not parse target" error
- Try rephrasing: "move to red box", "go to blue", "return home"
- Increase LLM temperature for more creative parsing: `--temperature 0.5`

### ROS2 connection issues
- Use `--simulation` flag to test without ROS2
- Ensure ROS2 nodes are running and FANUC services are available

## Notes

- **Exclusive I/O**: When moving to a new box, the previous output is turned off first
- **State Tracking**: The current active output is tracked in `CURRENT_STATE`
- **Error Handling**: Commands fail gracefully with clear error messages
- **Timeout**: Default timeout is 60 seconds (adjustable via `--timeout`)

## Future Enhancements

- Multi-pin activation (multiple RO outputs simultaneously)
- Custom confirmation/validation steps
- Logging to file
- Web UI dashboard
- Integration with motion planning
