from opcua import Client, ua

client = Client("opc.tcp://192.168.1.5:4880/FANUC/NanoUaServer")
client.connect()

try:
    hr_node = client.get_node("ns=1;i=304")

    # Read R[1] current value
    current = hr_node.get_value()
    print(f"R[1] current value: {current[0]}")

    # Read full array, modify index 0 (R[1]), write back
    values = list(hr_node.get_value())
    values[0] = 200  # Set R[1] = 99

    hr_node.set_value(ua.Variant(values, ua.VariantType.Int16))
    print("Written 99 to R[1]")

    # Confirm
    updated = hr_node.get_value()
    print(f"R[1] after write: {updated[0]}")

finally:
    client.disconnect()