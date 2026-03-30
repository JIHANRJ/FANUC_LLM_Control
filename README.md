# FANUC_LLM_Control

Modular local LLM-to-robot command interface for industrial robot control prototyping.

The system converts natural language into validated structured commands and then dispatches them to robot actions. It is designed around the principle:

- LLM decides what to do.
- The software stack decides how to do it safely.

## Repository Structure

project_root/

- `actions/`
- `joint_demo.py`: ROS2-style dummy action executor for demo joint targets.
- `core/`
- `parser.py`: Robust JSON extraction and parsing from LLM output.
- `normalizer.py`: Canonicalizes aliases and number words into machine fields.
- `validator.py`: Enforces intent schema and safety limits.
- `dispatcher.py`: Routes validated intents to executable actions.
- `intents/`
- `registry.py`: Intent names and required parameter definitions.
- `llm/`
- `base_interface.py`: Abstract interface for any LLM backend.
- `ollama_interface.py`: Ollama implementation (`/api/generate`).
- `prompt_builder.py`: Builds prompts dynamically from schema + tool registry + curated action prompt packs.
- `prompts/`
- `actions/`: One human-editable curated prompt file per action/tool.
- `templates/`: Reusable action prompt authoring template.
- `schemas/`
- `move_joints_v1.json`: Increment 1 output contract (single-joint move).
- `robot_command_v1.json`: Compatibility schema from earlier iterations.
- `registry.py`: Loads and validates schema JSON files.
- `tools/`
- `tool_registry_v1.json`: Increment 1 local tool registry (simulator-only).
- `config.py`: Runtime config (model, API URL, limits, active schema).
- `main.py`: App entrypoint and end-to-end pipeline.
- `requirements.txt`: Python dependency list.

## End-to-End Flow

1. User enters a natural language command in `main.py`.
2. `llm/ollama_interface.py` builds a schema-driven prompt.
3. Ollama returns model text.
4. `core/parser.py` safely parses/extracts JSON.
5. `core/normalizer.py` canonicalizes parameter names and numeric forms.
6. `core/validator.py` enforces intent contract and safety constraints.
7. `core/dispatcher.py` executes the matching action function.

## Schema + Tool + Prompt Modularity

LLM output format is defined in JSON files under `schemas/`.
Available callable tools are defined in JSON under `tools/`.
Per-action prompt behavior is curated in plain text/markdown under `prompts/actions/`.

- Active schema is selected with `ACTIVE_OUTPUT_SCHEMA` in `config.py`.
- Active tool registry is selected with `ACTIVE_TOOL_REGISTRY` in `config.py`.
- Prompt pack directory is selected with `PROMPT_PACK_DIR` in `config.py`.
- You can override with environment variable:
- `OUTPUT_SCHEMA=move_joints_v1`
- `TOOL_REGISTRY=tools/tool_registry_v1.json`
- `PROMPT_PACK_DIR=prompts/actions`

Each schema JSON contains:

- `name`: schema identifier.
- `description`: human-readable purpose.
- `json_schema`: top-level output shape.
- `rules`: constraints added to the prompt.
- `examples`: input/output examples used for in-context learning.

This allows non-Python users to tune behavior by editing JSON + per-action prompt files without changing core code.

## Increment 1 Scope

- ROS2 is not attached yet; all execution is simulator-only.
- Only one tool is first-class in this increment: `move_joints` -> `joint_move`.
- Goal is to stabilize modular contracts before adding more actions.

## Setup

1. Create and activate a virtual environment:

```bash
cd /Users/rakesh/Desktop/FANUC_2026/FANUC_LLM_Control
/opt/homebrew/bin/python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Start Ollama in a separate terminal:

```bash
ollama serve
```

4. Pull model if needed:

```bash
ollama pull llama3.1:8b
```

## Run

```bash
cd /Users/rakesh/Desktop/FANUC_2026/FANUC_LLM_Control
source .venv/bin/activate
python main.py
```

Example inputs:

- `Move joint 1 by 30 degrees`
- `Move joint one by -15 degrees`
- `Move robot to demo joint position`
- `J1: 30, J2: 40, J3: 60, J5: 90`

## Sample Console Output

```text
Command> move joint J1 by ten degrees
[dispatcher] Executing joint_move: joint=1, delta=10 deg

Structured command:
{'intent': 'joint_move', 'parameters': {'joint': 1, 'delta': 10}}

Dispatch result:
{'accepted': True, 'success': True, 'message': 'Simulated joint 1 move by 10 degrees.'}

Command> move joint by fourty degrees please, joint j1
[dispatcher] Executing joint_move: joint=1, delta=40 deg

Structured command:
{'intent': 'joint_move', 'parameters': {'joint': 1, 'delta': 40}}

Dispatch result:
{'accepted': True, 'success': True, 'message': 'Simulated joint 1 move by 40 degrees.'}

Command> move joint by fourty 46.2 degrees, joint 5 not joint 6 please
[dispatcher] Executing joint_move: joint=5, delta=46.2 deg

Structured command:
{'intent': 'joint_move', 'parameters': {'joint': 5, 'delta': 46.2}}

Dispatch result:
{'accepted': True, 'success': True, 'message': 'Simulated joint 5 move by 46.2 degrees.'}
```

## PIT Abstraction (Direct Function Call)

For direct SDK-style use, call the abstraction in `pit/`:

- `RobotControlLMM.TextCommand(model_name, model_parameters, output_json, prompt)`

It returns structured JSON (Python dict).

Example:

```python
from pit.robot_control_llm import RobotControlLMM

result = RobotControlLMM.TextCommand(
	model_name="llama3.1:8b",
	model_parameters={"temperature": 0.1, "stream": False},
	output_json={
		"intent": "string",
		"parameters": {"joint": "integer", "delta": "number"},
	},
	prompt="move joint one by 30 degrees",
)

print(result)
```

Quick test script:

```bash
python pit/test_text_command.py
```

## Safety and Validation

- Supported intents are defined in `intents/registry.py`.
- `joint_move` requires `joint` and `delta`.
- `joint_demo` requires `joint_1` through `joint_6`.
- Joint index range: 1 to 6.
- Delta magnitude max: 60 degrees.

Commands that violate these constraints are rejected before dispatch.

## How to Add a New Output Format

1. Create a new file in `schemas/`, for example `schemas/robot_command_v2.json`.
2. Fill `name`, `description`, `json_schema`, `rules`, `examples`.
3. Switch active schema:
	- Update `ACTIVE_OUTPUT_SCHEMA` in `config.py`, or
	- Run with `OUTPUT_SCHEMA=robot_command_v2 python main.py`.
4. If the new schema introduces new intents/fields, update:
	- `intents/registry.py`
	- `core/validator.py`
	- `core/dispatcher.py`

## Notes

- If `ollama serve` exits with code 1, Ollama is often already running.
- Startup preflight in `main.py` checks server reachability and model routing before command input.