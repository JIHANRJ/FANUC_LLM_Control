Action Name:
move_joints

Goal:
Convert natural language into one safe single-joint movement command.

Allowed Command:
joint_move

Required Parameters:
- joint: integer from 1 to 6
- delta: numeric degrees from -60 to 60

Parameter Extraction Hints:
- Accept variations such as J1, j1, joint 1, joint one, first joint.
- Extract exactly one joint index and exactly one delta value.
- If multiple joints are requested, choose the first clearly specified joint and value.

Normalization Hints:
- Convert spoken number words to numeric values.
- Convert phrases like minus twenty to -20.
- Keep numbers as numeric types, not strings.

Safety Hints:
- Respect delta bounds [-60, 60].
- Do not invent missing numeric values.

Failure / Ambiguity Handling:
- If joint index is missing, request joint index in JSON by using joint = 0 and delta = 0 is NOT allowed.
- If delta is missing, request numeric delta in JSON by providing best deterministic extraction from text only.
- Never output markdown or explanations.

Examples:
- Input: move joint one by 30 degrees
  Output: {"command_name":"joint_move","parameters":{"joint":1,"delta":30}}
- Input: move J4 by minus 20
  Output: {"command_name":"joint_move","parameters":{"joint":4,"delta":-20}}
