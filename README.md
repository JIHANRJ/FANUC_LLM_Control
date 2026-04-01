# FANUC_LLM_Control

Local Python framework for converting natural language into safe robot actions.

Design principle:

- LLM decides the command structure.
- Core runtime validates and safely dispatches.
- Actions execute robot code (simulator today, hardware later).

## Repository Structure

- `llm/`: all model-side logic, including `RobotControlLLM`.
- `core/`: parse, normalize, validate, dispatch pipeline.
- `actions/`: executable robot action handlers.
- `config/`: declarative framework configuration.
	- `config/schemas/`: output schema JSON contracts.
	- `config/prompts/`: curated action prompt packs.
	- `config/action_catalog_v1.json`: command/action catalog.
- `skills/`: capability catalog for future action selection stages.
- `pit/`: playground scripts and smoke tests.
- `main.py`: thin CLI entrypoint.

## Command Contract

Preferred contract:

```json
{
	"command_name": "joint_move",
	"parameters": {
		"joint": 1,
		"delta": 30
	}
}
```

Compatibility note:

- Legacy `intent` is still accepted and normalized to `command_name`.

## Setup

```bash
cd /Users/rakesh/Desktop/FANUC_2026/FANUC_LLM_Control
/opt/homebrew/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start Ollama in a separate terminal:

```bash
ollama serve
```

Pull model if needed:

```bash
ollama pull llama3.1:8b
```

## Run CLI

```bash
source .venv/bin/activate
python main.py --model llama3.1:8b --timeout 60
```

Heavier model example:

```bash
python main.py --model gpt-oss:20b --timeout 180
```

## RobotControlLLM Usage

`RobotControlLLM` now lives in `llm/robot_control_llm.py`.

`TextCommand(...)` supports optional execution callback and always returns:

- parsed output
- execution result (or skipped)
- model name
- elapsed time

Example:

```python
from llm.robot_control_llm import RobotControlLMM

schema = {
		"command_name": "string",
		"parameters": {"joint": "integer", "delta": "number"},
}

result = RobotControlLMM.TextCommand(
		model_name="llama3.1:8b",
		model_parameters={"temperature": 0.1, "stream": False, "timeout_seconds": 60},
		output_json=schema,
		prompt="move joint one by 30 degrees",
)

print(result)
```

Playground test:

```bash
python pit/test_text_command.py llama3.1:8b
```

Playground parse + execute test:

```bash
python pit/test_text_command.py llama3.1:8b --execute --prompt "move joint one by 10 degrees"
```

## Adding a New Action

1. Add action metadata entry in `config/action_catalog_v1.json`.
2. Add curated prompt pack in `config/prompts/actions/`.
3. Add action handler function in `actions/`.
4. Register handler name in `core/action_registry.py`.
5. Run PIT/CLI smoke tests.

## Notes

- If `ollama serve` exits with code 1, Ollama is usually already running.
- `skills/` is scaffolded for later-stage action/capability routing.