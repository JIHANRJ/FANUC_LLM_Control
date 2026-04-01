# FANUC LLM Control - Framework

**Simplified, minimal, and clear.**

## Structure

```
actions/          - Robot command executors
  move_joint_action.py    - Move a single joint by angle
  __init__.py             - Action module

config/           - Configuration (currently empty, ready for expansion)

core/             - Parsing utilities
  parser.py               - JSON extraction from LLM response
  normalizer.py           - Canonicalize commands (e.g., move → joint_move)

llm/              - LLM integration
  robot_control_llm.py    - Main SDK: RobotControlLLM.TextCommand()

pit/              - Playground for testing
  test_text_command.py    - Example usage script

config.py         - Ollama configuration
requirements.txt  - Dependencies
```

## Usage Pattern

**Simple, one-method interface:**

```python
from llm.robot_control_llm import RobotControlLLM
from actions import move_joint_action

# Define what you want the LLM to output
output_schema = {
    "command_name": "string",
    "parameters": {"joint": "integer", "delta": "number"}
}

# Call TextCommand to parse + normalize
result = RobotControlLLM.TextCommand(
    model_name="llama3.1:8b",
    model_parameters={"temperature": 0.1},
    output_json=output_schema,
    prompt="move joint 1 by 30 degrees"
)

# You get back: {parsed_output, normalized_output, model, elapsed_ms}

# Call the action function directly
parameters = result["normalized_output"]["parameters"]
action_result = move_joint_action.execute(parameters)
```

## What TextCommand Does

1. **Parse** - Calls Ollama with your schema, extracts JSON
2. **Normalize** - Canonicalizes aliases (move → joint_move)
3. **Return** - Gives you parsed + normalized output

**That's it.** No routing, no dispatching, no callbacks. Clean.

## Adding New Actions

1. Create action in `actions/my_action.py`:
   ```python
   def execute(parameters: dict) -> dict:
       return {"accepted": True, "success": True, "message": "..."}
   ```

2. Use it in your pit script:
   ```python
   from actions import my_action
   result = my_action.execute(parameters)
   ```

## Testing

```bash
python pit/test_text_command.py llama3.1:8b --prompt "move joint 1 by 20 degrees"
```

**Output shows:**
- What the LLM parsed
- What normalization canonicalized it to
- What the action executed returned
