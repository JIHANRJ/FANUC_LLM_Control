"""
fanuc_register_client.py
------------------------
Interactive terminal interface for reading and writing FANUC robot
registers via OPC UA. Requires fanuc_register_opcua.py in the same folder.

Usage:
    python3 fanuc_register_client.py
    python3 fanuc_register_client.py --ip 192.168.1.5
    python3 fanuc_register_client.py --ip 192.168.1.5 --port 4880
"""

import argparse
import sys

try:
    import fanuc_register_opcua as fanuc
except ImportError:
    print("[ERROR] fanuc_register_opcua.py not found in the same directory.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# ANSI colours (gracefully disabled on Windows if needed)
# ---------------------------------------------------------------------------

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    DIM    = "\033[2m"


def ok(msg):    print(f"{C.GREEN}  ✔  {msg}{C.RESET}")
def err(msg):   print(f"{C.RED}  ✘  {msg}{C.RESET}")
def info(msg):  print(f"{C.CYAN}  →  {msg}{C.RESET}")
def warn(msg):  print(f"{C.YELLOW}  ⚠  {msg}{C.RESET}")


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

HELP = f"""
{C.BOLD}╔══════════════════════════════════════════════════════╗
║        FANUC Register Client  —  OPC UA              ║
╚══════════════════════════════════════════════════════╝{C.RESET}

{C.BOLD}Commands:{C.RESET}

  {C.CYAN}rr <n>{C.RESET}               Read register  R[n]
  {C.CYAN}wr <n> <value>{C.RESET}       Write register R[n] = value   (range -32768..32767)

  {C.CYAN}rr <n> <count>{C.RESET}       Read  count  registers from R[n]
  {C.CYAN}wr <n> <v1> <v2> ...{C.RESET} Write multiple registers from R[n]

  {C.CYAN}rdo <n>{C.RESET}              Read  digital output DO[n]
  {C.CYAN}wdo <n> <0|1>{C.RESET}        Write digital output DO[n]  (1=ON, 0=OFF)

  {C.CYAN}rdi <n>{C.RESET}              Read  digital input  DI[n]  (read-only)

  {C.CYAN}info{C.RESET}                 Show robot information
  {C.CYAN}help{C.RESET}                 Show this message
  {C.CYAN}exit{C.RESET} / {C.CYAN}quit{C.RESET}          Disconnect and exit

{C.DIM}Note: Register values are 16-bit signed integers by default.
Range is -32768 to 32767 unless $SNPX_ASG is configured for REAL.{C.RESET}
"""


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_rr(client, args):
    """rr <n>  or  rr <n> <count>"""
    if len(args) == 1:
        n = int(args[0])
        val = fanuc.read_register(client, n)
        ok(f"R[{n}] = {val}")
    elif len(args) == 2:
        n, count = int(args[0]), int(args[1])
        vals = fanuc.read_registers(client, n, count)
        for i, v in enumerate(vals):
            ok(f"R[{n + i}] = {v}")
    else:
        err("Usage: rr <n>  or  rr <n> <count>")


def cmd_wr(client, args):
    """wr <n> <value>  or  wr <n> <v1> <v2> ..."""
    if len(args) < 2:
        err("Usage: wr <n> <value>  or  wr <n> <v1> <v2> ...")
        return
    n = int(args[0])
    values = [int(v) for v in args[1:]]
    if len(values) == 1:
        fanuc.write_register(client, n, values[0])
        ok(f"R[{n}] = {values[0]}")
    else:
        fanuc.write_registers(client, n, values)
        for i, v in enumerate(values):
            ok(f"R[{n + i}] = {v}")


def cmd_rdo(client, args):
    """rdo <n>"""
    if len(args) != 1:
        err("Usage: rdo <n>")
        return
    n = int(args[0])
    state = fanuc.read_do(client, n)
    label = f"{C.GREEN}ON{C.RESET}" if state else f"{C.DIM}OFF{C.RESET}"
    ok(f"DO[{n}] = {label}")


def cmd_wdo(client, args):
    """wdo <n> <0|1>"""
    if len(args) != 2:
        err("Usage: wdo <n> <0|1>")
        return
    n, state = int(args[0]), bool(int(args[1]))
    fanuc.write_do(client, n, state)
    label = "ON" if state else "OFF"
    ok(f"DO[{n}] → {label}")


def cmd_rdi(client, args):
    """rdi <n>"""
    if len(args) != 1:
        err("Usage: rdi <n>")
        return
    n = int(args[0])
    state = fanuc.read_di(client, n)
    label = f"{C.GREEN}ON{C.RESET}" if state else f"{C.DIM}OFF{C.RESET}"
    ok(f"DI[{n}] = {label}")


def cmd_info(client, _args):
    robot_info = fanuc.read_robot_info(client)
    print(f"\n{C.BOLD}  Robot Information{C.RESET}")
    print(f"  {'─' * 30}")
    for key, val in robot_info.items():
        label = key.replace("_", " ").title()
        if val is not None:
            print(f"  {C.CYAN}{label:<20}{C.RESET} {val}")
        else:
            print(f"  {C.DIM}{label:<20} (unavailable){C.RESET}")
    print()


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

COMMANDS = {
    "rr":   cmd_rr,
    "wr":   cmd_wr,
    "rdo":  cmd_rdo,
    "wdo":  cmd_wdo,
    "rdi":  cmd_rdi,
    "info": cmd_info,
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FANUC OPC UA Register Client")
    parser.add_argument("--ip",   default="192.168.1.5", help="Robot IP address")
    parser.add_argument("--port", default=4880, type=int, help="OPC UA port (default 4880)")
    cli_args = parser.parse_args()

    print(HELP)
    info(f"Connecting to {cli_args.ip}:{cli_args.port} ...")

    try:
        client = fanuc.connect(cli_args.ip, cli_args.port)
    except Exception as e:
        err(f"Connection failed: {e}")
        sys.exit(1)

    ok(f"Connected to {cli_args.ip}:{cli_args.port}\n")

    while True:
        try:
            raw = input(f"{C.BOLD}fanuc>{C.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not raw:
            continue

        parts = raw.split()
        cmd, args = parts[0].lower(), parts[1:]

        if cmd in ("exit", "quit"):
            break
        elif cmd == "help":
            print(HELP)
        elif cmd in COMMANDS:
            try:
                COMMANDS[cmd](client, args)
            except ValueError as e:
                err(f"Value error: {e}")
            except IndexError:
                err("Index out of range — check register number.")
            except Exception as e:
                err(f"Error: {e}")
        else:
            err(f"Unknown command '{cmd}'. Type 'help' for available commands.")

    info("Disconnecting...")
    fanuc.disconnect(client)
    ok("Disconnected. Goodbye.")


if __name__ == "__main__":
    main()