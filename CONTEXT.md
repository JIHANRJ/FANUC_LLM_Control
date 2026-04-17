# FANUC_LLM_Control Context

This document is the handoff for any future coding agent working in this repository. It captures the project purpose, current behavior, runtime assumptions, and the important decisions already made so work can resume without rediscovering the setup.

## Project Purpose

This repository is a local FANUC control playground that converts natural language into robot actions.

The codebase currently supports:
- LLM-driven text command parsing through Ollama
- Local simulation paths for development
- ROS2-backed FANUC I/O control for real robot I/O
- Optional voice input for press-to-talk workflows
- Sequence execution from a single user instruction, including repeated targets

The main design principle is: keep the Python side thin, deterministic, and explicit. The LLM interprets language; Python validates and executes only the allowed robot actions.

## Current State As Of 2026-04-17

The following is the current working state that future agents should assume unless they intentionally change it:
- Python virtual environment exists at [.venv](.venv)
- Dependencies are installed for the voice and LLM flow, including `SpeechRecognition`, `PyAudio`, `pynput`, `pocketsphinx`, and `faster-whisper`
- Ollama is installed and expected to run on `http://127.0.0.1:11434`
- ROS2 Humble is in use for real FANUC I/O integration
- FANUC ROS2 packages require sourcing `/opt/ros/humble/setup.bash` and `/home/faunc/FANUC_ROS2/install/setup.bash`
- `fanuc_msgs` is only available after sourcing the FANUC ROS2 workspace
- The integrated IO controller lives at [LLM_control_demo/llm_io_controller.py](LLM_control_demo/llm_io_controller.py)
- The current home behavior is: both RO states OFF

## Important Behavioral Decisions

These decisions are already encoded in the controller and should not be changed casually:

- Red means `RO1 ON` and `RO2 OFF`
- Blue means `RO2 ON` and `RO1 OFF`
- Home means `RO1 OFF` and `RO2 OFF`
- Home is used as the neutral state for TP logic and should not be treated as "leave state unchanged"
- Only the following targets are valid: `red`, `blue`, `home`
- Sequences are supported and must preserve order, including repeats
- The LLM prompt must tell the model to parse the entire sentence and return all targets in order
- Python code must reject malformed or unknown targets instead of trying to infer extra meaning

## Repository Layout

- [main.py](main.py): top-level entry point if present for the current workflow
- [config.py](config.py): Ollama and environment configuration
- [llm/robot_control_llm.py](llm/robot_control_llm.py): LLM request/response handling
- [core/parser.py](core/parser.py): JSON extraction / parsing utilities
- [core/normalizer.py](core/normalizer.py): canonicalization helpers
- [actions/](actions): robot action executors
- [fanuc_io_control.py](fanuc_io_control.py): ROS2 FANUC I/O client at repo root
- [LLM_control_demo/fanuc_io_control.py](LLM_control_demo/fanuc_io_control.py): demo-local copy of the FANUC I/O client
- [LLM_control_demo/llm_io_controller.py](LLM_control_demo/llm_io_controller.py): integrated LLM + I/O controller
- [pit/](pit): playground scripts and text-command experiments
- [LLM_control_demo/](LLM_control_demo): demo-specific voice and I/O entry points

## Runtime Flow

The controller flow is:

1. User speaks or types a command
2. The text is sent to Ollama with a schema-guided prompt
3. Ollama returns JSON describing one or more targets
4. Python normalizes each target to `red`, `blue`, or `home`
5. The controller executes the targets in order
6. The real ROS2 path writes I/O through FANUC services when available

The key implementation detail is that the LLM is not allowed to choose arbitrary actions. It may only map language into the supported command set.

## Current IO Semantics

The IO controller currently behaves like this:

- `red`
  - turn `RO2` off first
  - turn `RO1` on
- `blue`
  - turn `RO1` off first
  - turn `RO2` on
- `home`
  - turn `RO1` off
  - turn `RO2` off
  - reset internal active state

This is intentional and matches the TP logic requirement that home be a clearly detectable off-state.

## Voice Support

Voice input is already integrated into the IO controller.

Current voice options support:
- `whisper`
- `sphinx`
- `google`

The whisper path uses `faster-whisper` and was added to the main controller CLI so the same script can be used with typed or spoken input.

## Environment Requirements

### Python
- Python 3.10 is the known working version in the current workspace
- The repo expects a virtual environment at [.venv](.venv)

### LLM / Ollama
- Ollama must be running before using the text or voice controllers
- Default API endpoint: `http://127.0.0.1:11434/api/generate`
- If Ollama is moved, `OLLAMA_API_URL` must be updated

### ROS2
- ROS2 Humble is the target ROS version
- Real-mode I/O requires FANUC ROS2 services to be available
- Source both ROS environments before running real hardware or service-backed tests
- If `fanuc_msgs` is missing, the controller cannot run real ROS mode

### Audio / Voice
- `PyAudio` depends on PortAudio
- The workspace previously required a local PortAudio build because system headers were unavailable
- ALSA warnings may appear on Linux audio startup and do not necessarily indicate failure

## Important Commands

### Activate the environment
```bash
source /home/faunc/FANUC_LLM_Control/.venv/bin/activate
```

### Source ROS2 for real FANUC control
```bash
source /opt/ros/humble/setup.bash
source /home/faunc/FANUC_ROS2/install/setup.bash
```

### Run the integrated IO controller in simulation mode
```bash
source /home/faunc/FANUC_LLM_Control/.venv/bin/activate
python /home/faunc/FANUC_LLM_Control/LLM_control_demo/llm_io_controller.py llama3.1:8b --simulation
```

### Run the integrated IO controller in real ROS mode
```bash
source /opt/ros/humble/setup.bash
source /home/faunc/FANUC_ROS2/install/setup.bash
source /home/faunc/FANUC_LLM_Control/.venv/bin/activate
python /home/faunc/FANUC_LLM_Control/LLM_control_demo/llm_io_controller.py llama3.1:8b
```

### Syntax check a changed file
```bash
source /home/faunc/FANUC_LLM_Control/.venv/bin/activate
python -m py_compile /home/faunc/FANUC_LLM_Control/LLM_control_demo/llm_io_controller.py
```

## Notes For Future Agents

- Do not assume the repo is a generic robot project; this one is specifically organized around LLM-to-target parsing plus FANUC I/O execution
- Preserve the strict command vocabulary unless the user explicitly asks for expansion
- Preserve sequence order and repeats in the prompt and parser
- Keep home as an actual off-state, not a no-op
- Prefer minimal, explicit changes over broad refactors
- If you change ROS behavior, verify both simulation and real-mode paths
- If you touch voice code, remember the script may be used interactively with press-and-talk input
- If a ROS import fails, check whether the workspace has been sourced before changing code

## Known Constraints / Risks

- Real I/O readback is not always reliable in this environment, so write acknowledgments have been used pragmatically where needed
- ROS environment sourcing is mandatory for real hardware mode
- Some setup steps depend on local machine state outside this repository
- Ollama startup and model availability are external prerequisites

## Working Assumptions

When continuing from here, assume the user wants:
- practical changes that work in the current repo rather than a redesign
- direct code edits instead of only advice
- compatibility with the existing controller flow
- the current home semantics to stay as both outputs off unless explicitly changed

## If You Need To Resume Fast

Start with these files:
- [LLM_control_demo/llm_io_controller.py](LLM_control_demo/llm_io_controller.py)
- [LLM_control_demo/fanuc_io_control.py](LLM_control_demo/fanuc_io_control.py)
- [fanuc_io_control.py](fanuc_io_control.py)
- [llm/robot_control_llm.py](llm/robot_control_llm.py)
- [README.md](README.md)

Those files describe the execution path, runtime dependencies, and the current semantics most future changes will touch.
