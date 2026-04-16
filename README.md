# FANUC_LLM_Control

Simple local framework for converting natural language into robot action calls.

## Quick Start (5 Minutes)

### 1. Install Dependencies (First Time Only)

```bash
cd /Users/rakesh/Desktop/FANUC_2026/FANUC_LLM_Control
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start Ollama (In a New Terminal)

Ollama must be running before you use the chat scripts.

```bash
ollama serve
```

**Wait for the startup message** that includes "listening on" to confirm it's running. You should see output like:

```
time=2026-04-02T... msg="listening on 127.0.0.1:11435"
```

### 3. Run Local Simulator Chat (New Terminal)

From your repo directory with venv activated:

```bash
source .venv/bin/activate
./.venv/bin/python pit/chat_text_command.py llama3.1:8b --action move_joint
```

Type a command:

```
You> move joint 2 by 30 degrees
```

Press `Enter`, then type `exit` to quit.

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

## Run Modes

### Mode 0: Voice Capture Only (No LLM/Robot)

Use this to iterate on microphone quality and speech recognition independently.

```bash
source .venv/bin/activate
./.venv/bin/python pit/test_voice_capture.py --engine sphinx
```

Press and hold `R` to record, release to transcribe. Say or type `exit` to quit.

### Mode 1: Local Simulator (No VM Required)

Use this to test the LLM parsing and action framework locally without a VM.

**One-shot test:**

```bash
./.venv/bin/python pit/test_text_command.py llama3.1:8b --action move_joint --prompt "move joint 1 by 20 degrees"
```

**Interactive chat:**

```bash
./.venv/bin/python pit/chat_text_command.py llama3.1:8b --action move_joint
```

Type commands like:
- `move joint 1 by 45 degrees`
- `rotate joint 3 and 4 by 90 degrees`
- `move joint 6 back 30`

### Mode 2: ROS2 VM Motion (Current-State Delta Mode)

Parse in macOS, apply delta on top of current joint state, execute in ROS2 VM.

**One-shot test:**

```bash
export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm
./.venv/bin/python pit/test_text_command_from_current.py llama3.1:8b --prompt "move joint 2 by 15 degrees"
```

**Interactive chat:**

```bash
export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm
./.venv/bin/python pit/test_text_command_from_current.py llama3.1:8b
```

Type commands like:
- `move joint 1 by 30 degrees`
- `move joints 2 and 3 by 45 degrees`
- `move all joints back to zero`

### Mode 3: ROS2 VM Absolute Targets

Parse in macOS, use absolute joint targets, execute in ROS2 VM.

**One-shot test:**

```bash
export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm
./.venv/bin/python pit/test_text_command.py llama3.1:8b --action ros2_demo --prompt "move joint 3 by 40 degrees"
```

**Interactive chat:**

```bash
export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm
./.venv/bin/python pit/chat_text_command.py llama3.1:8b --action ros2_demo
```

## ROS2 VM Setup (Required for Modes 2 & 3)

### Prerequisites

- Linux UTM VM with ROS2 Humble and MoveIt already installed
- SSH key-based auth from macOS to VM (no password prompt)
- MoveIt launch file ready

### VM Setup Steps

**1. (Linux VM) Start MoveIt in one terminal** (keep running):

```bash
source /opt/ros/humble/setup.bash
source ~/ws_fanuc/install/setup.bash
ros2 launch fanuc_moveit_config fanuc_moveit.launch.py robot_model:=crx10ia_l use_mock:=true use_rviz:=true
```

**Important**: This terminal must stay open while you run commands from macOS. Motion will fail if MoveIt is not running.

**2. (macOS) Set up SSH key** (one time):

Create an SSH key if you don't have one:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_vm -N ""
```

Copy the public key to the VM:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_vm jihanrj@192.168.64.9
```

Test the connection:

```bash
ssh -i ~/.ssh/id_ed25519_vm jihanrj@192.168.64.9 "echo SSH_OK"
```

You should see `SSH_OK` printed. If you get a password prompt, the key wasn't installed correctly.

**3. (macOS) Export SSH key for each session**:

```bash
export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm
```

Or add to your `.bashrc` or `.zshrc` to persist it:

```bash
echo 'export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm' >> ~/.zshrc
source ~/.zshrc
```

## Environment Variables

### Ollama Configuration

- `OLLAMA_API_URL` default: `http://127.0.0.1:11434/api/generate`

If Ollama is on a different machine or port:

```bash
export OLLAMA_API_URL=http://192.168.1.100:11435/api/generate
```

### ROS2 VM Configuration

- `FANUC_VM_HOST` default: `192.168.64.9`
- `FANUC_VM_USER` default: `jihanrj`
- `FANUC_VM_PORT` default: `22`
- `FANUC_VM_SSH_KEY` default: empty (required for VM modes)
- `FANUC_VM_TIMEOUT` default: `120` seconds
- `FANUC_VM_ROS_DISTRO` default: `humble`
- `FANUC_VM_WS_ROOT` default: `/home/jihanrj/ws_fanuc`
- `FANUC_VM_PACKAGE` default: `fanuc_tools`
- `FANUC_VM_EXECUTABLE` default: `modular_joint_demo`

Example with custom VM:

```bash
export FANUC_VM_HOST=192.168.1.50
export FANUC_VM_USER=robot
export FANUC_VM_SSH_KEY=~/.ssh/robot_key
```

## Troubleshooting

### "Failed to reach Ollama" / Connection Refused

**Problem**: Chat script cannot connect to Ollama.

**Solution**:
1. Check if Ollama is running:
   ```bash
   lsof -i -P -n | grep ollama
   ```
   You should see a process listening on a port (usually 11435 or 11434).

2. If Ollama is not running, start it:
   ```bash
   ollama serve
   ```
   Wait for the "listening on" message, then go back to your chat terminal.

3. If Ollama is running on a different port, find it:
   ```bash
   lsof -i -P -n | grep LISTEN | grep ollama
   ```
   Note the port number, then set:
   ```bash
   export OLLAMA_API_URL=http://127.0.0.1:<port>/api/generate
   ```

### "LLM timeout" Error

**Problem**: LLM response is taking too long.

**Solution**:
1. For heavy models like `gpt-oss:20b`, increase the timeout:
   ```bash
   ./.venv/bin/python pit/chat_text_command.py gpt-oss:20b --action move_joint --timeout 300
   ```

2. If timeouts persist, your Ollama may be swapping to disk. Ensure 8GB+ free RAM.

### "Permission denied (publickey)" for SSH

**Problem**: Cannot connect to VM via SSH.

**Solution**:
1. Verify the SSH key exists and has correct permissions:
   ```bash
   ls -la ~/.ssh/id_ed25519_vm
   chmod 600 ~/.ssh/id_ed25519_vm
   ```

2. Test SSH connection directly:
   ```bash
   ssh -i ~/.ssh/id_ed25519_vm jihanrj@192.168.64.9 "echo TEST"
   ```
   You should see `TEST` printed without a password prompt.

3. If this fails, regenerate the key:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_vm -N ""
   ssh-copy-id -i ~/.ssh/id_ed25519_vm jihanrj@192.168.64.9
   ```

4. Try the test again.

### "MoveIt action server unavailable" Error

**Problem**: ROS2 VM motion fails because MoveIt is not running.

**Solution**:
1. On the Linux VM, in a new terminal, start MoveIt:
   ```bash
   source /opt/ros/humble/setup.bash
   source ~/ws_fanuc/install/setup.bash
   ros2 launch fanuc_moveit_config fanuc_moveit.launch.py robot_model:=crx10ia_l use_mock:=true use_rviz:=true
   ```

2. **Keep this terminal open** while running commands from macOS.

3. Try the motion command again.

### "Could not read current joint state" Error

**Problem**: Current-state delta mode cannot fetch `/joint_states` from VM.

**Solution**:
1. Ensure MoveIt is running on the VM (see above).

2. Test joint state reading directly on the VM:
   ```bash
   source /opt/ros/humble/setup.bash
   source ~/ws_fanuc/install/setup.bash
   ros2 topic echo /joint_states --once
   ```
   You should see joint names and positions.

3. Test SSH + ROS command from macOS:
   ```bash
   export FANUC_VM_SSH_KEY=~/.ssh/id_ed25519_vm
   ssh -i ~/.ssh/id_ed25519_vm jihanrj@192.168.64.9 \
     "source /opt/ros/humble/setup.bash && source ~/ws_fanuc/install/setup.bash && ros2 topic echo /joint_states --once"
   ```
   If this works, the issue is with environment variables. Check they are set:
   ```bash
   echo $FANUC_VM_SSH_KEY
   ```

### Chat Prompt Not Understood

**Problem**: The LLM produces incorrect JSON or doesn't parse the command correctly.

**Solution**:
1. Try simpler, more explicit commands:
   - Good: `move joint 1 by 30 degrees`
   - Bad: `j1 move 30`

2. Use available models and test with a lighter one first:
   ```bash
   ./.venv/bin/python pit/chat_text_command.py llama3.1:8b --action move_joint
   ```

3. If the issue persists, check the parsed JSON output for clues about what the model understood.

## Action Envelope Contract

Every action returns a standard response:

```json
{
  "accepted": true,
  "success": true,
  "message": "...",
  "data": {}
}
```
