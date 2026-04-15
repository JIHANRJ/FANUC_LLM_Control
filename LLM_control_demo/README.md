# LLM-based FANUC I/O Controller Demo

A natural language interface for controlling FANUC robot I/O outputs via Ollama LLM. Parse English commands like "move to red box" and automatically activate the correct robot I/O pins.

## Overview

This demo showcases:
- **Natural Language Understanding**: Use Ollama LLM to interpret varied English phrasings (e.g., "move to the red box on the side", "send it to blue", "take me home")
- **Semantic Interpretation**: The LLM handles phrasing variations; the controller validates and executes I/O commands
- **Multi-Command Sequences**: Parse complex instructions like "red then blue then home then blue again" (supports any sequence length)
- **Exclusive I/O Control**: Only one output active at a time; automatically turns off previous outputs when moving to a new target
- **Simulation & Real Modes**: Test without ROS2 or integrate with real FANUC I/O services

## Quick Start

### Prerequisites

1. **Ollama** installed and running: `ollama serve`
2. **Python 3.10+** with venv (from parent project)
3. **llama3.2:1b** model pulled: `ollama pull llama3.2:1b`

### Run in Simulation Mode (Recommended for Testing)

```bash
cd LLM_control_demo
source ../.venv/bin/activate
python3 llm_io_controller.py llama3.2:1b --simulation
```

### Example Interaction

```
You> move the robot to the red box on the side
[INFO] Processing with LLM...
[PARSED] 1 target(s): red
  Step 1/1: Moving to red
[OK] Moving to Red Box (RO1 ON) [SIM MODE]

You> now go to blue, then take me home
[INFO] Processing with LLM...
[PARSED] 2 target(s): blue, home
  Step 1/2: Moving to blue
[OK] Moving to Blue Box (RO2 ON) [SIM MODE]
  Step 2/2: Moving to home
[HOME] Home position set (all RO outputs OFF) [SIM MODE]

You> status
Current state: {'active_output': None, 'active_pin': None}
Active output: None

You> exit
Goodbye!
```

## Features

| Feature | Description |
|---------|-------------|
| **Natural Language** | Accepts varied English phrasing, not just keywords |
| **Multi-Step Sequences** | Parse "red then blue then home" as 3 separate commands |
| **Repeating Targets** | Handles "red then red then blue" correctly |
| **Exclusive I/O** | Only one RO output active at a time |
| **State Tracking** | Tracks current active output |
| **Simulation Mode** | No ROS2 required for testing |
| **Real Mode** | Full ROS2 I/O integration when available |
| **Configurable Delay** | Add delays between command executions |

## Command-Line Usage

```bash
# Default (llama3.1:8b, 2s command delay)
python3 llm_io_controller.py

# Specify model
python3 llm_io_controller.py llama3.2:1b

# Simulation mode (no ROS2)
python3 llm_io_controller.py llama3.2:1b --simulation

# Custom model temperature (0.1 = more deterministic, 0.5 = more creative)
python3 llm_io_controller.py llama3.2:1b --temperature 0.3

# Custom delay between commands (in seconds)
python3 llm_io_controller.py llama3.2:1b --simulation --command-delay 3.0

# Custom Ollama timeout
python3 llm_io_controller.py llama3.2:1b --timeout 120

# Full usage help
python3 llm_io_controller.py --help
```

## Architecture

### Data Flow

```
┌─────────────────┐
│  User Input     │  "Move to red, then blue, then home"
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  LLM Semantic Interpreter   │  Ollama llama3.2:1b
│  (Handles natural language) │  Returns JSON with 3 commands
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  JSON Parser                │  Extract target names
│  _parse_llm_response()      │  Validate keywords
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Target Normalizer          │  "home" → "home"
│  _normalize_target()        │  "red_box" → "red"
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  I/O Executor               │  Turn on RO1 (red)
│  _execute_io_command()      │  With 2s delay
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Robot I/O State            │  RO1=ON, RO2=OFF
│  (Sim or ROS2 backend)      │
└─────────────────────────────┘
```

### Key Components

#### 1. **llm_io_controller.py** - Main Controller
The central script that orchestrates everything:

```python
def _process_command(user_input: str, args, io_client, schema, schema_prompt):
    """
    Main command processing flow:
    1. Send user input + schema to Ollama
    2. Parse JSON response
    3. Extract and normalize targets
    4. Execute each target sequentially with delays
    """
    llm_result = RobotControlLLM.TextCommand(
        model_name=args.model,
        model_parameters={
            "temperature": args.temperature,
            "stream": False,
            "timeout_seconds": args.timeout,
            "num_predict": 1024,  # Allow longer output
            "top_k": 40,          # Control generation diversity
            "top_p": 0.9,         # Nucleus sampling
        },
        output_json=schema,
        prompt=schema_prompt + f"\nUser input: {user_input}\nOutput:",
    )
    
    targets = _parse_llm_response(llm_result)
    for i, target in enumerate(targets, 1):
        result = _execute_io_command(target, io_client)
        # Wait between commands to allow robot execution
        if i < len(targets):
            time.sleep(args.command_delay)
```

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `_normalize_target()` | Convert raw LLM output to canonical target names |
| `_build_io_schema()` | Create JSON schema that tells LLM what format to return |
| `_get_io_schema_prompt()` | The core LLM prompt with semantic interpretation rules |
| `_execute_io_command()` | Turn on/off FANUC I/O pins or manage simulation state |
| `_parse_llm_response()` | Extract list of targets from LLM JSON response |
| `_process_command()` | Orchestrate entire command flow |

#### 2. **LLM Prompt Engineering** - The Semantic Layer
The prompt is the key to parsing varied natural language:

```python
def _get_io_schema_prompt() -> str:
    return """You are the primary natural-language interpreter for a FANUC I/O controller.

Your job is to read a normal English sentence and infer ALL intended robot destinations.

CRITICAL RULES:
1. Parse the ENTIRE input from start to finish. NEVER stop early.
2. Return ALL destinations mentioned, INCLUDING repeats, in order.
3. When you see "then" or "next", there's ANOTHER command coming - keep parsing.
4. Commands CAN repeat: "red then red then blue" → [red, red, blue]

Examples:
- "move to red box" → {"commands":[{"target":"red",...}]}
- "red then blue then home then blue again" → [red, blue, home, blue]

Map:
- Red destination → "red"
- Blue destination → "blue"
- Return/reset command → "home"

Return ONLY valid JSON..."""
```

**Why this works:**
- Tells the LLM to handle **sequences** and **repeats**
- Emphasizes parsing **entire input** (prevents truncation)
- Gives **specific examples** of multi-step commands
- **Explicit instructions** prevent the model from stopping early

#### 3. **Input Normalization** - The Validation Layer
After LLM parses, we validate to reject malformed outputs:

```python
def _normalize_target(raw_target: str) -> Optional[str]:
    """Convert raw LLM "red_box" → "red", reject invalid inputs"""
    if not raw_target:
        return None
    
    target = raw_target.lower().strip().strip(".,;:!?")
    
    # Direct match: "red" → "red"
    if target in BOX_CONFIG:
        return target
    
    # Strip suffixes: "red_box" → "red"
    for suffix in ["_box", " box", "_pin", " pin", "_position"]:
        if target.endswith(suffix):
            target = target[: -len(suffix)].strip()
    
    if target in BOX_CONFIG:
        return target
    
    # Exact keyword matching only (reject "red|blue|home" strings)
    for color, keywords in COLOR_KEYWORDS.items():
        for keyword in keywords:
            if target == keyword and color in BOX_CONFIG:
                return color
    
    return None  # Reject malformed output
```

**Validation Strategy:**
- **Thin layer** - Let LLM do semantic work, Python does constraint checking
- **Exact matching** - Rejects substring matches that could break parsing
- **Flexible but strict** - Accepts "red_box" / "Red Box", rejects "red|blue|home"

#### 4. **I/O Execution** - The Output Layer
Activates robot I/O or simulates:

```python
def _execute_io_command(target: str, io_client: Optional[FanucIOClient]) -> dict:
    """Execute I/O command: activate RO pin or manage home state"""
    target = target.lower().strip()
    target_key = target.replace("_box", "").replace(" box", "").strip()
    
    if target_key not in BOX_CONFIG:
        return {"success": False, "message": f"Unknown target: {target}"}
    
    config = BOX_CONFIG[target_key]
    
    # Home: turn off all RO outputs
    if target_key == "home":
        if not ROS2_AVAILABLE or io_client is None:
            # Simulation mode
            CURRENT_STATE["active_output"] = None
            CURRENT_STATE["active_pin"] = None
            return {
                "success": True,
                "message": "[HOME] Home position set (all RO outputs OFF) [SIM MODE]",
            }
        else:
            # Real mode: turn off both pins
            io_client.write_io("RO", 1, False)
            io_client.write_io("RO", 2, False)
            return {"success": True, ...}
    
    # Box target: exclusive I/O (turn off others, turn on target)
    output_type = config["output"]
    pin = config["pin"]
    
    if not ROS2_AVAILABLE or io_client is None:
        # Simulation mode
        CURRENT_STATE["active_output"] = f"{output_type}{pin}"
        CURRENT_STATE["active_pin"] = pin
        return {
            "success": True,
            "message": f"[OK] Moving to {config['description']} ({output_type}{pin} ON) [SIM MODE]",
        }
    else:
        # Real mode: ensure exclusive I/O
        for key, cfg in BOX_CONFIG.items():
            if key != "home" and cfg["pin"] is not None and cfg["pin"] != pin:
                io_client.write_io("RO", cfg["pin"], False)  # Turn off others
        
        io_client.write_io(output_type, pin, True)  # Turn on target
        return {"success": True, ...}
```

**Exclusive I/O Pattern:**
- **Before activating new output**: Turn off all other RO pins
- **Prevents conflicts**: Only one RO active at a time
- **Simulation & Real**: Same logic, different backend (state vs. ROS2)

## Configuration

### Available Targets
Edit `BOX_CONFIG` to add/modify robot destinations:

```python
BOX_CONFIG = {
    "red": {"output": "RO", "pin": 1, "description": "Red Box"},
    "blue": {"output": "RO", "pin": 2, "description": "Blue Box"},
    "home": {"output": None, "pin": None, "description": "Home Position (all RO off)"},
}
```

**Add a new target:**
```python
BOX_CONFIG = {
    "red": {"output": "RO", "pin": 1, "description": "Red Box"},
    "blue": {"output": "RO", "pin": 2, "description": "Blue Box"},
    "green": {"output": "RO", "pin": 3, "description": "Green Station"},  # NEW
    "home": {"output": None, "pin": None, "description": "Home Position (all RO off)"},
}
```

Then update the prompt example to include the new target when editing `_get_io_schema_prompt()`.

### Model Selection

**Recommended Models by Use Case:**

| Model | Use Case | RAM | Speed |
|-------|----------|-----|-------|
| `llama3.2:1b` | Testing, limited resources | 1.3 GB | Fast (~10s) |
| `llama3.1:8b` | Balance of quality/speed | 4.8 GB | Medium (~15s) |
| `llama2:13b` | Best quality | 7+ GB | Slow (~20s) |

```bash
# For machines with ≤4 GB RAM
python3 llm_io_controller.py llama3.2:1b

# For machines with 8+ GB RAM
python3 llm_io_controller.py llama3.1:8b
```

## Test Files

### **test_llm_io.py** - Basic LLM Integration Tests
```bash
python3 test_llm_io.py
```
Tests that Ollama is reachable and can parse simple commands.

### **test_complex_commands.py** - Multi-Step Command Tests
```bash
python3 test_complex_commands.py
```
Tests parsing of complex sequences:
- `"red then blue then home"` → `[red, blue, home]`
- `"red then red then blue"` → `[red, red, blue]` (repeats)
- `"home then red then blue"` → May reorder based on semantics

## Troubleshooting

### ❌ "Connection refused" Error
**Problem:** Ollama is not running
```
ConnectionError: Failed to reach Ollama at http://127.0.0.1:11434/api/generate
```
**Solution:**
```bash
# In another terminal
ollama serve
```

### ❌ "Could Not Parse Targets" or Only Gets First Few Commands
**Problem:** Either model has small context, or token limit too low
```
[ERROR] Could not parse any targets from your command.
```
**Solutions:**
1. Use longer sequence examples with repeats in the prompt
2. Increase `num_predict` in the model parameters
3. Try a larger model: `llama3.1:8b` instead of `1b`

### ❌ Model Takes Too Long
**Problem:** Model is too large for available RAM
**Solution:** Use a smaller model
```bash
python3 llm_io_controller.py llama3.2:1b
```

### ❌ Commands Parse But Don't Execute in Real Mode
**Problem:** ROS2 services not available
**Solution:**
1. Verify ROS2 FANUC I/O services are running
2. Use `--simulation` flag to test I/O logic
3. Check ROS2 with: `ros2 service list | grep fanuc`

## Advanced Usage

### Custom Model Parameters
Modify `_process_command()` to adjust LLM behavior:

```python
model_parameters={
    "temperature": 0.1,      # Lower = more deterministic
    "num_predict": 2048,     # More tokens for longer sequences
    "top_k": 40,            # Diversity control
    "top_p": 0.9,           # Nucleus sampling
}
```

### Extending Targets
1. Add target to `BOX_CONFIG`
2. Update prompt examples in `_get_io_schema_prompt()`
3. Map recognition keywords in `COLOR_KEYWORDS` (optional)

### Custom Command Delays
```bash
# 5-second delay between commands (for slow robots)
python3 llm_io_controller.py llama3.2:1b --simulation --command-delay 5.0

# 0.5-second delay for fast robots
python3 llm_io_controller.py llama3.2:1b --simulation --command-delay 0.5
```

## Performance Notes

- **First command**: ~55 seconds (Ollama loads model into RAM)
- **Subsequent commands**: ~10-15 seconds (model cached)
- **I/O execution**: <100ms (immediate)
- **Delay overhead**: Configurable (default 2s between commands)

**Optimization tips:**
- Use `llama3.2:1b` for real-time interactive control
- Keep Ollama running in background to avoid reload
- Adjust `--temperature` for faster/slower generation (higher = slower)

## Files in This Demo

| File | Purpose |
|------|---------|
| `llm_io_controller.py` | Main controller - orchestrates LLM + I/O |
| `fanuc_io_control.py` | ROS2 I/O client (if ROS2 available) |
| `config_examples.py` | Example configurations |
| `test_llm_io.py` | Basic tests |
| `test_complex_commands.py` | Multi-step command tests |
| `setup.sh` | Quick setup verification |
| `README.md` | This file |

## Limitations & Future Work

### Current Limitations
- ✓ Only 3 targets (red, blue, home) - easily extensible
- ✓ Small 1b model occasionally misses on first call - warmup effect
- ✓ No confirmation/validation dialogs
- ✓ No logging to persistent storage

### Future Enhancements
- [ ] Web UI dashboard with real-time status
- [ ] Logging to file with timestamps
- [ ] Multi-pin activation support
- [ ] Integration with motion planning
- [ ] Voice input/output
- [ ] Undo/history of commands
- [ ] Custom confirmation workflows

## Contributing

To improve the prompt or add features:
1. Test your changes with `test_complex_commands.py`
2. Verify parsing with various phrasings
3. Update prompt examples if adding new targets

## License

Part of the FANUC_LLM_Control project. See parent directory for license.
