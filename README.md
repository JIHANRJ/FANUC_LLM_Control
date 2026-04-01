# FANUC_LLM_Control

Simple local framework for converting natural language into robot action calls.

## Current Structure

- `llm/`: LLM parsing logic (`RobotControlLLM.TextCommand`)
- `core/`: JSON parser and normalizer utilities
- `actions/`: executable actions
- `pit/`: playground scripts

## Core Flow

1. `RobotControlLLM.TextCommand(...)` parses and normalizes prompt output.
2. PIT script chooses which action to execute.
3. Action runs and returns a standard envelope.

No dispatcher/skills layer is required for this version.

## Setup (macOS)

```bash
cd /Users/rakesh/Desktop/FANUC_2026/FANUC_LLM_Control
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Start Ollama in another terminal if needed:

```bash
ollama serve
```

## Run Modes

- Local simulator mode (`move_joint`): no VM required.
- ROS2 VM mode (`ros2_demo`): parse on macOS, execute on Linux VM via SSH.

## Local Simulator Usage

One-shot test:

```bash
python pit/test_text_command.py llama3.1:8b --action move_joint --prompt "move joint 1 by 20 degrees"
```

Interactive chat:

```bash
python pit/chat_text_command.py llama3.1:8b --action move_joint
```

## ROS2 VM Usage

### Step 1 (Linux VM): start MoveIt in a separate terminal and keep it running

This terminal must stay running while commands are sent from macOS:

```bash
source /opt/ros/humble/setup.bash && source /home/jihanrj/ws_fanuc/install/setup.bash && ros2 launch fanuc_moveit_config fanuc_moveit.launch.py robot_model:=crx10ia_l use_mock:=true use_rviz:=true
```

If this is not running, motion execution can fail because the MoveIt action server is unavailable.

### Step 2 (macOS): verify SSH key auth

```bash
ssh -i ~/.ssh/id_ed25519_vm -o IdentitiesOnly=yes jihanrj@192.168.64.9 "echo SSH_OK"
```

### Step 3 (macOS): export SSH key for framework action

```bash
export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm
```

### Step 4 (macOS): run one-shot ROS2 command

```bash
python pit/test_text_command.py llama3.1:8b --action ros2_demo --prompt "move joint 3 by 40 degrees"
```

### Step 5 (macOS): run interactive ROS2 chat

```bash
python pit/chat_text_command.py llama3.1:8b --action ros2_demo
```

Example prompts:

- `move joint 2 by 3 degrees with vel 0.1 and acc 0.1`
- `move all the joints back to 30 please with vel 0.5 and acc 0.5`

### Step 6 (macOS): verify non-interactive SSH (optional but recommended)

```bash
ssh -p 22 -o BatchMode=yes -i ~/.ssh/id_ed25519_vm -o IdentitiesOnly=yes jihanrj@192.168.64.9 "echo NON_INTERACTIVE_OK"
```

## Environment Variables for ROS2 VM Action

- `FANUC_VM_HOST` default: `192.168.64.9`
- `FANUC_VM_USER` default: `jihanrj`
- `FANUC_VM_PORT` default: `22`
- `FANUC_VM_SSH_KEY` default: empty
- `FANUC_VM_TIMEOUT` default: `120`
- `FANUC_VM_ROS_DISTRO` default: `humble`
- `FANUC_VM_WS_ROOT` default: `/home/jihanrj/ws_fanuc`
- `FANUC_VM_PACKAGE` default: `fanuc_tools`
- `FANUC_VM_EXECUTABLE` default: `modular_joint_demo`

## Full End-to-End Quick Start

1. Linux VM terminal A: run and keep MoveIt launch command active.
2. macOS terminal B: activate venv and export `FANUC_VM_SSH_KEY`.
3. macOS terminal B: run either:
   - `python pit/test_text_command.py ... --action ros2_demo ...`
   - `python pit/chat_text_command.py ... --action ros2_demo`

## Action Envelope Contract

Every action should return:

```json
{
  "accepted": true,
  "success": true,
  "message": "...",
  "data": {}
}
```

## Notes

- ROS2 VM action supports both:
  - single joint delta (`joint`, `delta`)
  - full absolute targets (`target_deg.joint_1` ... `target_deg.joint_6`)
- For single-joint commands, non-mentioned joints use the configured defaults in the action.
