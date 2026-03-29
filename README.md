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
- `prompt_builder.py`: Builds prompts dynamically from JSON schema files.
- `schemas/`
- `robot_command_v1.json`: Default output contract and examples for the LLM.
- `registry.py`: Loads and validates schema JSON files.
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

## Schema-Driven Output (JSON)

LLM output format is defined in JSON files under `schemas/`.

- Active schema is selected with `ACTIVE_OUTPUT_SCHEMA` in `config.py`.
- You can override with environment variable:
- `OUTPUT_SCHEMA=robot_command_v1`

Each schema JSON contains:

- `name`: schema identifier.
- `description`: human-readable purpose.
- `json_schema`: top-level output shape.
- `rules`: constraints added to the prompt.
- `examples`: input/output examples used for in-context learning.

This allows non-Python users to tune output structure by editing JSON only.

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