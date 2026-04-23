"""
fanuc_register_opcua.py
-----------------------
Function library for reading and writing FANUC robot registers via OPC UA.
Uses the opcua library (pip install opcua).

Node ID reference (from FANUC B-83284EN-2/10 manual):
    ns=1;i=301  DiscreteInput    (Boolean[], READ only)  -> DI[]
    ns=1;i=302  Coils            (Boolean[], READ-WRITE) -> DO[]
    ns=1;i=303  InputRegisters   (UInt16[],  READ only)  -> AI[], GI[]
    ns=1;i=304  HoldingRegisters (Int16[],   READ-WRITE) -> R[], PR[]
    ns=1;i=305  Command          (String[])

Address mapping (OPC UA index = Modbus address - 1):
    R[n]   -> HoldingRegisters index n-1   (default assignment)
    DO[n]  -> Coils index n-1
    DI[n]  -> DiscreteInput index n-1
"""

from opcua import Client, ua


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def connect(ip: str, port: int = 4880) -> Client:
    """
    Connect to the FANUC OPC UA server and return the client.

    Args:
        ip:   Robot controller IP address (e.g. "192.168.1.5")
        port: OPC UA port (FANUC default is 4880)

    Returns:
        Connected opcua.Client instance.

    Example:
        client = connect("192.168.1.5")
    """
    url = f"opc.tcp://{ip}:{port}/FANUC/NanoUaServer"
    client = Client(url)
    client.connect()
    return client


def disconnect(client: Client) -> None:
    """
    Safely disconnect from the OPC UA server.

    Args:
        client: Connected opcua.Client instance.
    """
    try:
        client.disconnect()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_holding_registers(client: Client) -> list:
    """Return the full HoldingRegisters array as a Python list."""
    node = client.get_node("ns=1;i=304")
    return list(node.get_value())


def _set_holding_registers(client: Client, values: list) -> None:
    """Write a full list back to HoldingRegisters."""
    node = client.get_node("ns=1;i=304")
    node.set_value(ua.Variant(values, ua.VariantType.Int16))


def _get_coils(client: Client) -> list:
    """Return the full Coils (DO[]) array as a Python list of bools."""
    node = client.get_node("ns=1;i=302")
    return list(node.get_value())


def _set_coils(client: Client, values: list) -> None:
    """Write a full list back to Coils (DO[])."""
    node = client.get_node("ns=1;i=302")
    node.set_value(ua.Variant(values, ua.VariantType.Boolean))


def _get_discrete_inputs(client: Client) -> list:
    """Return the full DiscreteInput (DI[]) array as a Python list of bools."""
    node = client.get_node("ns=1;i=301")
    return list(node.get_value())


# ---------------------------------------------------------------------------
# Numeric Registers  R[]
# ---------------------------------------------------------------------------

def read_register(client: Client, index: int) -> int:
    """
    Read a single numeric register R[index].

    Args:
        client: Connected opcua.Client instance.
        index:  Register number (1-based, e.g. 1 for R[1]).

    Returns:
        Integer value of R[index]. Range: -32768 to 32767.

    Example:
        val = read_register(client, 1)   # reads R[1]
    """
    values = _get_holding_registers(client)
    return values[index - 1]


def write_register(client: Client, index: int, value: int) -> None:
    """
    Write a value to a single numeric register R[index].

    Args:
        client: Connected opcua.Client instance.
        index:  Register number (1-based, e.g. 1 for R[1]).
        value:  Integer value to write. Range: -32768 to 32767.

    Example:
        write_register(client, 1, 150)   # sets R[1] = 150
    """
    if not (-32768 <= value <= 32767):
        raise ValueError(f"Value {value} out of 16-bit signed range (-32768 to 32767). "
                         "Configure $MULTIPLY=0 in $SNPX_ASG for REAL support.")
    values = _get_holding_registers(client)
    values[index - 1] = int(value)
    _set_holding_registers(client, values)


def read_registers(client: Client, start: int, count: int) -> list:
    """
    Read multiple consecutive numeric registers starting at R[start].

    Args:
        client: Connected opcua.Client instance.
        start:  First register number (1-based).
        count:  Number of registers to read.

    Returns:
        List of integer values, e.g. [R[1], R[2], R[3]].

    Example:
        vals = read_registers(client, 1, 5)  # reads R[1] through R[5]
    """
    values = _get_holding_registers(client)
    return values[start - 1 : start - 1 + count]


def write_registers(client: Client, start: int, values: list) -> None:
    """
    Write multiple consecutive numeric registers starting at R[start].

    Args:
        client: Connected opcua.Client instance.
        start:  First register number (1-based).
        values: List of integer values to write.

    Example:
        write_registers(client, 1, [10, 20, 30])  # R[1]=10, R[2]=20, R[3]=30
    """
    for i, v in enumerate(values):
        if not (-32768 <= v <= 32767):
            raise ValueError(f"Value at R[{start + i}] = {v} out of range (-32768 to 32767).")
    all_values = _get_holding_registers(client)
    for i, v in enumerate(values):
        all_values[start - 1 + i] = int(v)
    _set_holding_registers(client, all_values)


# ---------------------------------------------------------------------------
# Digital Outputs  DO[]
# ---------------------------------------------------------------------------

def read_do(client: Client, index: int) -> bool:
    """
    Read a single digital output DO[index].

    Args:
        client: Connected opcua.Client instance.
        index:  DO number (1-based, e.g. 1 for DO[1]).

    Returns:
        True if ON, False if OFF.

    Example:
        state = read_do(client, 1)
    """
    coils = _get_coils(client)
    return bool(coils[index - 1])


def write_do(client: Client, index: int, state: bool) -> None:
    """
    Write a digital output DO[index].

    Args:
        client: Connected opcua.Client instance.
        index:  DO number (1-based).
        state:  True to turn ON, False to turn OFF.

    Example:
        write_do(client, 1, True)   # DO[1] ON
        write_do(client, 2, False)  # DO[2] OFF
    """
    coils = _get_coils(client)
    coils[index - 1] = bool(state)
    _set_coils(client, coils)


# ---------------------------------------------------------------------------
# Digital Inputs  DI[]  (read only)
# ---------------------------------------------------------------------------

def read_di(client: Client, index: int) -> bool:
    """
    Read a single digital input DI[index] (read-only).

    Args:
        client: Connected opcua.Client instance.
        index:  DI number (1-based, e.g. 1 for DI[1]).

    Returns:
        True if ON, False if OFF.

    Example:
        state = read_di(client, 1)
    """
    inputs = _get_discrete_inputs(client)
    return bool(inputs[index - 1])


# ---------------------------------------------------------------------------
# Robot information  (RobotInformation node)
# ---------------------------------------------------------------------------

def read_robot_info(client: Client) -> dict:
    """
    Read basic robot information from the RobotInformation node.

    Returns a dict with keys: model, serial_number, version,
    servo_state, operation_state, mode_state, program_speed.

    Example:
        info = read_robot_info(client)
        print(info['model'])   # e.g. "R-2000iC/165F"
    """
    def _get(path):
        try:
            return client.get_node(path).get_value()
        except Exception:
            return None

    # Navigate via browse path under Objects
    base = "ns=1;s=RobotInformation/"
    return {
        "model":           _get(base + "Model"),
        "serial_number":   _get(base + "SerialNumber"),
        "version":         _get(base + "Version"),
        "servo_state":     _get(base + "ServoState"),
        "operation_state": _get(base + "OperationState"),
        "mode_state":      _get(base + "ModeState"),
        "program_speed":   _get(base + "ProgramSpeed"),
    }