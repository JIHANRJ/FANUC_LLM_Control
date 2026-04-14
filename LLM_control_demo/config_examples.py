"""
Example configuration for I/O targets.
You can modify BOX_CONFIG in llm_io_controller.py to add more targets.
"""

# Standard configuration (used in llm_io_controller.py)
BOX_CONFIG_STANDARD = {
    "red": {
        "output": "RO",
        "pin": 1,
        "description": "Red Box"
    },
    "blue": {
        "output": "RO",
        "pin": 2,
        "description": "Blue Box"
    },
    "home": {
        "output": None,
        "pin": None,
        "description": "Home Position (all RO off)"
    },
}

# Extended configuration example (4 boxes)
BOX_CONFIG_EXTENDED = {
    "red": {
        "output": "RO",
        "pin": 1,
        "description": "Red Box"
    },
    "blue": {
        "output": "RO",
        "pin": 2,
        "description": "Blue Box"
    },
    "green": {
        "output": "RO",
        "pin": 3,
        "description": "Green Box"
    },
    "yellow": {
        "output": "RO",
        "pin": 4,
        "description": "Yellow Box"
    },
    "home": {
        "output": None,
        "pin": None,
        "description": "Home Position (all RO off)"
    },
}

# Multi-pin configuration example (activate multiple outputs)
# WARNING: This requires modifying _execute_io_command() logic
BOX_CONFIG_MULTI = {
    "pickup": {
        "output": "RO",
        "pins": [1, 3],  # Activate RO1 and RO3
        "description": "Pick up position"
    },
    "dropoff": {
        "output": "RO",
        "pins": [2, 4],  # Activate RO2 and RO4
        "description": "Drop off position"
    },
}

# High-precision configuration with DI feedback
BOX_CONFIG_WITH_FEEDBACK = {
    "red": {
        "output": "RO",
        "pin": 1,
        "feedback_input": "DI",
        "feedback_pin": 1,
        "description": "Red Box (with feedback)"
    },
    "blue": {
        "output": "RO",
        "pin": 2,
        "feedback_input": "DI",
        "feedback_pin": 2,
        "description": "Blue Box (with feedback)"
    },
}

# Usage in llm_io_controller.py:
# 1. Open llm_io_controller.py
# 2. Find: BOX_CONFIG = { ... }
# 3. Replace with your chosen configuration:
#    BOX_CONFIG = BOX_CONFIG_EXTENDED  # For 4-box setup
