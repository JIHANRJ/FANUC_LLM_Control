# RSR0001 — FANUC TP Robot Program
### Order Fulfillment Pick-and-Place System

---

## Overview

`RSR0001` is a FANUC Teach Pendant program running on a robotic arm configured for **retail order fulfillment**. The robot picks products from designated bins and fulfills incoming orders by dispatching pick routines per product type. It communicates with an HMI/PLC via Digital I/O handshakes and uses integer registers to track order quantities.

- **Total Lines:** 143  
- **Frame:** UFRAME_NUM = 7  
- **Tool:** UTOOL_NUM = 9  
- **Payload Config:** PAYLOAD[1] — Order Fulfillment  
- **Speed Override:** R[200:Override]

---

## Program Flow

```
START
  │
  ▼
Set Override / Clear Flags
  │
  ▼
Call HOMEEE → Wait 200ms
  │
  ├── DO[2] (Home_position) = OFF? → UALM[1] → Loop back
  │
  ▼
LBL[21] — Wait for Order
  │
  ├── DI[4] (Order_confirmation) = OFF? → Loop (poll)
  │
  ▼
LBL[20] — Order Received
  Mask HMI Buttons (DO[225] = ON)
  │
  ▼
Scan R[1]–R[12] for quantity > 0
  │
  ├── R[1] > 0 → LBL[1]  NuttiesChocolate
  ├── R[2] > 0 → LBL[2]  Nivea
  ├── R[3] > 0 → LBL[3]  ShampooBottle
  ├── R[4] > 0 → LBL[4]  AppyFizz
  ├── R[5] > 0 → LBL[5]  CoughSyrup
  ├── R[6] > 0 → LBL[6]  CocaCola
  ├── R[7] > 0 → LBL[7]  Tea
  ├── R[8] > 0 → LBL[8]  Pringles
  ├── R[9] > 0 → LBL[9]  Noodles
  ├── R[10] > 0 → LBL[10] Bar
  ├── R[11] > 0 → LBL[11] Ponds
  └── R[12] > 0 → LBL[12] Dove
  │
  ▼ (all products done)
LBL[22] — Order Complete
  Pulse DO[1] (Order_fulfilled) for 2.0 sec
  WAIT for DI[2] (Order_received) from HMI
  CALL BIN2RACK
  JMP LBL[21] — Ready for next order
```

### Per-Product Pick Loop Pattern

Each product section (LBL[1]–LBL[12]) follows an identical pattern:

```
LBL[N]
  CALL FI_<PRODUCT>        ← Vision-guided pick subroutine
  IF R[N] > 0, JMP LBL[N] ← Still items to pick? Loop
  R[108:Unload enable] = 1 ← Signal unload ready
  JMP LBL[20]              ← Back to product scanner
```

---

## Register Map

| Register | Name | Purpose |
|----------|------|---------|
| R[1] | Nuttiess Choclae | Order quantity — Nutties Chocolate |
| R[2] | NIVEA | Order quantity — Nivea |
| R[3] | Shampoo | Order quantity — Shampoo Bottle |
| R[4] | Appy Fizz | Order quantity — Appy Fizz |
| R[5] | Cough syrup | Order quantity — Cough Syrup |
| R[6] | Coca Cola | Order quantity — Coca Cola |
| R[7] | Tea botx | Order quantity — Tea Box |
| R[8] | Pringles | Order quantity — Pringles |
| R[9] | Noodles | Order quantity — Noodles |
| R[10] | Bar | Order quantity — Bar |
| R[11] | Ponds | Order quantity — Ponds |
| R[12] | Dove | Order quantity — Dove |
| R[21] | Num_found | Vision output — number of items detected |
| R[22] | Model_ID | Vision output — detected product model ID |
| R[25] | tot.no.of.parts | Total parts counter *(logic currently commented out)* |
| R[108] | Unload enable | Handshake flag — set to 1 when product is done picking, triggers unload check |
| R[200] | Override | Robot speed override percentage |

---

## Digital I/O Map

### Outputs (DO)

| Signal | Name | Behaviour |
|--------|------|-----------|
| DO[1] | Order_fulfilled | Pulses ON for 2.0 sec when all products in an order are picked |
| DO[2] | Home_position | Robot confirms it is at the home position |
| DO[3] | Cycle_done | **Commented out** — intended to signal cycle completion to PLC |
| DO[225] | Mask Buttons | Set ON during picking to disable HMI operator buttons |

### Inputs (DI)

| Signal | Name | Behaviour |
|--------|------|-----------|
| DI[2] | Order_received | HMI/PLC acknowledges order fulfilled; also used to confirm new order ready |
| DI[4] | Order_confirmation | Rising edge triggers robot to begin picking the current order |

---

## Subroutines Called

| Subroutine | Product |
|------------|---------|
| `HOMEEE` | Move robot to home position |
| `BIN2RACK` | Return empty bin to rack after order complete |
| `FI_NUTTIES_CHOC` | Find & pick Nutties Chocolate |
| `FI_NIVEA` | Find & pick Nivea |
| `FI_SHAMPOOBOTTLE` | Find & pick Shampoo Bottle |
| `FI_APPYFIZZ` | Find & pick Appy Fizz |
| `FI_COUGHSYRUP` | Find & pick Cough Syrup |
| `FI_COCACOLA` | Find & pick Coca Cola |
| `FI_TEA` | Find & pick Tea Box |
| `FI_PRINGLES` | Find & pick Pringles |
| `FI_NOODLES` | Find & pick Noodles |
| `FI_BAR` | Find & pick Bar |
| `FI_PONDS` | Find & pick Ponds |
| `FI_DOVE` | Find & pick Dove |

> All `FI_*` subroutines are assumed to be vision-guided pick routines that decrement the corresponding order register on each successful pick.

---

## Labels Reference

| Label | Purpose |
|-------|---------|
| LBL[14] | Startup loop entry point |
| LBL[13] | Alarm state (home not confirmed) |
| LBL[21] | Main wait loop — polls for new order |
| LBL[20] | Order dispatcher — scans product registers |
| LBL[22] | Order complete handler |
| LBL[1–12] | Per-product pick loops |

---

## Known Issues & Technical Notes

### 1. R[108] Premature Trigger Risk
`R[108:Unload enable]` is set to `1` after **each individual product** finishes. On line 38, the program checks `IF R[108]=1, JMP LBL[22]`. In a multi-product order, this will trigger the order-complete sequence after only the **first product** is done, skipping remaining products.

**Recommended fix:** Only set R[108]=1 after all product registers R[1]–R[12] are confirmed = 0.

### 2. Blocking WAIT with No Timeout (Line 49)
```
WAIT (DI[2:Order_received])
```
This is an unconditional blocking wait. If the HMI/PLC never sends DI[2], the robot will stall indefinitely with no fault or alarm raised.

**Recommended fix:** Replace with a timed wait:
```
WAIT DI[2:Order_received]=ON TIMEOUT, LBL[fault_handler]
```

### 3. Commented-Out Logic (Lines 41, 45–47, 53)
Several lines are commented out with `//` suggesting the program is mid-development:
- `R[25:tot.no.of.parts]` counter logic is inactive
- `DO[3:Cycle_done]` signal is not being sent
- An alternate order-received handshake path (LBL[23]) was removed

These should be reviewed and either fully implemented or cleaned up.

### 4. Missing Alarm on Home Failure
`UALM[1]` is raised if the robot isn't at home, but the alarm description is not shown here. Ensure this alarm is configured with a meaningful operator message.

---

## Operating Sequence (Operator Guide)

1. Ensure robot is powered and at **home position**
2. Load product quantities into **R[1]–R[12]** via HMI for the new order
3. Trigger **DI[4] (Order_confirmation)** from HMI to start picking
4. Robot will pick all products sequentially; HMI buttons are locked during operation
5. When picking is complete, **DO[1] (Order_fulfilled)** pulses for 2 seconds
6. Operator or system confirms via **DI[2] (Order_received)**
7. Robot calls **BIN2RACK** and returns to wait state for next order

---

## Error States

| Condition | Response |
|-----------|----------|
| Robot not at home on startup | UALM[1] raised, loops until home confirmed |
| HMI DI[2] not received after order complete | Robot stalls at WAIT (no timeout currently) |
| Vision pick failure | Handled inside FI_* subroutines (details in sub-programs) |

---

*Program: RSR0001 | Controller: FANUC R-30iB or compatible | Last observed state: Line 142/143, PAUSED*