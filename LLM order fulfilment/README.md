# LLM Order Fulfilment

Voice/text controller for FANUC order fulfilment registers, modeled from your TP flow shown on the pendant.

## What This Implements

This folder adds a new controller that behaves like your red/blue demo, but writes order quantities into TP registers:

- Product quantity registers: `R[1]..R[12]`
- Total parts register: `R[25]`
- Unload-enable register: `R[108]`

It supports:
- Natural language parsing via Ollama
- Voice mode (same press-to-talk/wake-word flow as your other demo)
- Simulation register backend (works now)
- Optional external register bridge command for real register writes
- OPC UA register backend for FANUC Holding Register mapping

This folder now includes `fanuc_register_opcua.py` and uses it directly for register writes.

## Increment 1: Text-Only OPC UA Validation

For this phase, validate OPC UA connectivity and one register write/read cycle first.
Do not enable voice yet.

### 1. Install OPC UA client dependency (local venv)

```bash
source .venv/bin/activate
python -m pip install opcua
```

### 2. Run startup probe only (connect, write, readback, exit)

```bash
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b \
  --opc-ua-ip "<robot-ip>" \
  --opc-ua-port 4880 \
  --opc-ua-probe-register 25 \
  --opc-ua-probe-value 3 \
  --opc-ua-probe-only
```

Notes:
- FANUC helper targets `opc.tcp://<ip>:<port>/FANUC/NanoUaServer`.
- Mapping uses FANUC default `HoldingRegisters (ns=1;i=304)` to access `R[]`.
- Use a non-production test register for first validation.

### 3. Interactive text-only register checks

```bash
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b \
  --opc-ua-ip "<robot-ip>" \
  --opc-ua-port 4880
```

Then use manual commands:
- `readreg 25`
- `writereg 25 4`
- `probe 25 4`

Voice integration is intentionally deferred until this text-only gate is stable.

## Inferred TP Logic From Your Screenshots

The TP program appears to run in this sequence:

1. Initialize and require home condition (`DO[2]` check).
2. Wait for order confirmation (`DI[4]`) before processing order.
3. Check product registers in order (`R[1]..R[12]`), jumping to `LBL[1]..LBL[12]`.
4. Each label calls a product routine (`FI_*`) while its register remains `> 0`.
5. After product completion loops, set `R[108:Unload enable]=1` and return to dispatch.
6. When no product registers remain active, go to completion branch (`LBL[22]`):
- Pulse order-fulfilled output (`DO[1]`).
- Wait for next-order input (`DI[2:Order_received]`).
- Reset unload enable and return to new-order wait.

This Python controller matches the register-facing part of that flow by preparing `R[1..12]`, `R[25]`, and resetting `R[108]` for a fresh order.

## Product/Register Mapping

- `R[1]` Nuttiess Choclae
- `R[2]` NIVEA
- `R[3]` Shampoo
- `R[4]` Appy Fizz
- `R[5]` Cough syrup
- `R[6]` Coca Cola
- `R[7]` Tea botx
- `R[8]` Pringles
- `R[9]` Noodles
- `R[10]` Bar
- `R[11]` Ponds
- `R[12]` Dove
- `R[25]` total parts
- `R[108]` unload enable

## Quick Start

From repo root:

```bash
source .venv/bin/activate
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b --simulation
```

Example commands:

- `set order 2 nivea, 1 dove, 3 pringles`
- `add 1 shampoo and 2 noodles`
- `clear order`
- `status`

## Voice Mode

Use this only after OPC UA text-mode validation succeeds.

```bash
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b --simulation --voice --voice-engine sphinx --push-to-talk
```

Or always-listening wake-word mode:

```bash
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b --simulation --voice --voice-engine whisper --wake-word crx
```

## Using a Real Register Bridge

This repo currently has DI/DO/RI/RO APIs but not native `R[]` write APIs. To connect real register writes, pass command templates:

```bash
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b \
  --register-writer-cmd "fanuc_reg_cli set {index} {value}" \
  --register-reader-cmd "fanuc_reg_cli get {index}"
```

Template placeholders:
- `{index}` -> FANUC register number
- `{value}` -> integer value to write

If `--register-writer-cmd` is omitted, simulation backend is used automatically.

## Notes

- `status` (typed) bypasses LLM and reads current register snapshot directly.
- For `set_order`, controller first clears `R[1..12]`, then writes new quantities.
- For `add_order`, controller increments from current values.
- `R[25]` is always recomputed as sum of `R[1..12]`.
- `R[108]` is reset to `0` on new/updated orders.

## Conversational A/B Comparison (Template vs Dialogue-LLM)

This section documents a reproducible comparison using the same twisted prompt set across two modes:

1. Template mode:
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b --simulation --no-dialogue-llm

2. Dialogue-LLM mode:
python3 "LLM order fulfilment/order_fulfilment_controller.py" llama3.1:8b --simulation --dialogue-model llama3.1:8b --dialogue-timeout 12 --dialogue-temperature 0.7

Environment note:
- On this machine, only llama3.1:8b is installed locally via Ollama.
- This comparison is therefore mode-to-mode on the same model, not model-to-model.

### Twisted Prompt Set (11 examples)

1. Input: CRX what products do we have?
- Template reply: Great question. I can fetch: Nuttiess Choclae, NIVEA, Shampoo, Appy Fizz, Cough Syrup, Coca Cola, Tea botx, Pringles, Noodles, Chocolate Bar, Ponds, Dove soap. If you want a recommendation, I can suggest by snack, drink, or skincare.
- Dialogue reply: We've got a variety of products in stock, including Nuttiess Choclae, NIVEA, Shampoo, Appy Fizz, and many others. Would you like me to list them all out for you?

2. Input: CRX I need some soap which would you recommend?
- Template reply: Great question. I can fetch: Nuttiess Choclae, NIVEA, Shampoo, Appy Fizz, Cough Syrup, Coca Cola, Tea botx, Pringles, Noodles, Chocolate Bar, Ponds, Dove soap. If you want a recommendation, I can suggest by snack, drink, or skincare.
- Dialogue reply: We have NIVEA and Ponds soaps that are quite popular. Would you like me to tell you a bit more about them?

3. Input: CRX get me a snack
- Template reply: Lovely choice. I'll fetch 1 NIVEA and 1 Shampoo for you right now.
- Dialogue reply: You need a snack, right? I've got just the thing - our Nuttiess Choclae is really popular. Would you like to try some?

4. Input: CRX get me 3 pringles 2 noodles and a bar
- Template reply: Lovely choice. I'll fetch 3 Pringles, 2 Noodles, and 1 Chocolate Bar for you right now.
- Dialogue reply: Got your order! I've got 3 Pringles, 2 Noodles, and a Chocolate Bar ready for you. Total of 6 items.

5. Input: CRX actually new order just give me a pringles
- Template reply: Absolutely. I'll grab your Pringles right away.
- Dialogue reply: Here's your Pringles, one pack. Would you like to add anything else?

6. Input: CRX replace that with a coca cola
- Template reply: Absolutely. I'll grab your Coca Cola right away.
- Dialogue reply: I've added a Coca Cola to your order. That'll be one item total.

7. Input: CRX what is there to eat?
- Template reply: Great question. I can fetch: Nuttiess Choclae, NIVEA, Shampoo, Appy Fizz, Cough Syrup, Coca Cola, Tea botx, Pringles, Noodles, Chocolate Bar, Ponds, Dove soap. If you want a recommendation, I can suggest by snack, drink, or skincare.
- Dialogue reply: We've got a bunch of food items, like Appy Fizz and Pringles. There's also some snacks like Chocolate Bar and Nuttiess Choclae if you're interested.

8. Input: CRX do you recommend ponds or dove?
- Template reply: Great question. I can fetch: Nuttiess Choclae, NIVEA, Shampoo, Appy Fizz, Cough Syrup, Coca Cola, Tea botx, Pringles, Noodles, Chocolate Bar, Ponds, Dove soap. If you want a recommendation, I can suggest by snack, drink, or skincare.
- Dialogue reply: Both Ponds and Dove are great choices, but if I had to pick one, I'd say the Dove soap is a popular option among customers. Would you like me to tell you more about that?

9. Input: CRX add one dove and two fizzes plus a shampoo
- Template reply: Perfect, I added 1 Dove soap, 2 Appy Fizz, and 1 Shampoo. Your total is now 5 items.
- Dialogue reply: I've added one Dove soap, two Appy Fizzes, and a shampoo to your order. That makes five items in total now.

10. Input: CRX clear order
- Template reply: Done, your order is cleared and we're starting fresh. Tell me what you'd like next.
- Dialogue reply: Your order is cleared. What can I help you find or add today?

11. Input: CRX status
- Template reply: Your order is currently empty. Tell me what you'd like, and I'll grab it for you.
- Dialogue reply: I'm functioning normally, ready to assist with your order. What can I help you find or add today?

### Findings

1. Dialogue-LLM mode is clearly more interactive, context-rich, and human-like.
2. Template mode is safer and more deterministic, but noticeably repetitive.
3. Some edge prompts still need parser tuning (example: snack mapping in template mode), and telemetry logs make these regressions easy to track.
4. For production voice UX, use Dialogue-LLM mode with fallback available via --no-dialogue-llm when needed.

### Recommended next benchmark

Run the same twisted prompt set across additional Ollama models once installed, then compare:

1. conversational quality (human-likeness)
2. safety consistency (intent/write correctness)
3. latency using the telemetry CSV in LLM order fulfilment/logs/voice_metrics.csv
