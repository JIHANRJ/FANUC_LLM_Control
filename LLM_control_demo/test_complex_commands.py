"""Test complex command parsing."""

import subprocess
import sys

def run_test(commands_list):
    """Run test with given commands."""
    input_data = "\n".join(commands_list) + "\n"
    
    process = subprocess.Popen(
        [sys.executable, "llm_io_controller.py", "--simulation"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/home/wh0p3/FANUC_LLM_Control/LLM_control_demo"
    )
    
    stdout, stderr = process.communicate(input=input_data, timeout=120)
    return stdout

# Test 1: Simple commands
print("TEST 1: Simple commands")
print("=" * 70)
output = run_test(["move to red box", "exit"])
print(output)

# Test 2: Complex descriptors
print("\nTEST 2: Complex descriptors")
print("=" * 70)
output = run_test(["move to red box in the corner", "exit"])
print(output)

# Test 3: Sequences
print("\nTEST 3: Command sequences")
print("=" * 70)
output = run_test(["move to red box in the corner and then the blue box in the corner", "exit"])
print(output)

# Test 4: Status check
print("\nTEST 4: Status check after sequence")
print("=" * 70)
output = run_test(["red then blue then home", "status", "exit"])
print(output)

