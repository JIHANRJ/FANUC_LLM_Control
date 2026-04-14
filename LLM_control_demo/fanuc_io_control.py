import sys
import rclpy
from rclpy.node import Node
from fanuc_msgs.srv import GetBoolIO, SetBoolIO
from fanuc_msgs.msg import IOType

class FanucIOClient(Node):
    """
    A reusable ROS 2 client for reading and writing FANUC robot I/O via RMI.
    """
    def __init__(self, node_name='fanuc_io_client_node'):
        super().__init__(node_name)
        
        self.get_client = self.create_client(GetBoolIO, '/fanuc_gpio_controller/get_bool_io')
        self.set_client = self.create_client(SetBoolIO, '/fanuc_gpio_controller/set_bool_io')

        self.get_logger().info('Waiting for FANUC I/O services to become available...')
        self.get_client.wait_for_service()
        self.set_client.wait_for_service()
        self.get_logger().info('Successfully connected to FANUC I/O services.')

    def read_io(self, io_type: str, index: int) -> bool:
        req = GetBoolIO.Request()
        req.io_type = IOType(type=io_type.upper())
        req.index = index
        
        future = self.get_client.call_async(req)
        rclpy.spin_until_future_complete(self, future)
        res = future.result()
        
        if res is not None and res.result == 0:
            return res.value
        else:
            err_code = res.result if res else 'Socket/Connection Drop'
            self.get_logger().error(f"Read failed for {io_type}[{index}]. RMI Error: {err_code}")
            return None

    def write_io(self, io_type: str, index: int, value: bool) -> bool:
        req = SetBoolIO.Request()
        req.io_type = IOType(type=io_type.upper())
        req.index = index
        req.value = bool(value)
        
        future = self.set_client.call_async(req)
        rclpy.spin_until_future_complete(self, future)
        res = future.result()
        
        if res is not None and res.result == 0:
            return True
        else:
            err_code = res.result if res else 'Socket/Connection Drop'
            self.get_logger().error(f"Write failed for {io_type}[{index}]. RMI Error: {err_code}")
            return False

def main(args=None):
    rclpy.init(args=args)
    
    print("\n--- Starting FANUC I/O Monitor ---")
    client_node = FanucIOClient()
    
    try:
        while True:
            print("\n" + "="*35)
            print(" FANUC I/O Live Control Panel")
            print("="*35)
            print("[R] Read an I/O pin (DI, DO, RI, RO)")
            print("[W] Write an I/O pin (DO, RO)")
            print("[Q] Quit")
            print("-" * 35)
            
            choice = input("Select an option (R/W/Q): ").strip().upper()
            
            if choice == 'Q':
                print("Exiting CLI...")
                break
                
            elif choice == 'R':
                io_type = input("Enter I/O Type (e.g., DI, DO): ").strip().upper()
                try:
                    index = int(input("Enter Pin Index (e.g., 1): ").strip())
                    print(f"Reading {io_type}[{index}]...")
                    
                    value = client_node.read_io(io_type, index)
                    if value is not None:
                        state = "ON [True]" if value else "OFF [False]"
                        print(f"\n>>> RESULT: {io_type}[{index}] is currently {state} <<<")
                except ValueError:
                    print("\n[!] Error: Index must be a valid integer.")
                    
            elif choice == 'W':
                io_type = input("Enter I/O Type to write (e.g., DO, RO): ").strip().upper()
                if io_type in ['DI', 'RI']:
                    print("\n[!] Warning: You generally cannot override physical inputs (DI/RI) via software.")
                
                try:
                    index = int(input("Enter Pin Index (e.g., 1): ").strip())
                    val_input = input("Enter Value (1 for ON, 0 for OFF): ").strip()
                    
                    if val_input not in ['0', '1']:
                        print("\n[!] Error: Value must be 1 or 0.")
                        continue
                        
                    value_to_set = (val_input == '1')
                    print(f"Writing {value_to_set} to {io_type}[{index}]...")
                    
                    success = client_node.write_io(io_type, index, value_to_set)
                    if success:
                        state = "ON" if value_to_set else "OFF"
                        print(f"\n>>> SUCCESS: Set {io_type}[{index}] to {state} <<<")
                    else:
                        print(f"\n[!] FAILURE: Could not write to {io_type}[{index}].")
                        
                except ValueError:
                    print("\n[!] Error: Index must be a valid integer.")
            else:
                print("\n[!] Invalid selection. Please enter R, W, or Q.")
                
    except KeyboardInterrupt:
        print("\nProcess interrupted by user (Ctrl+C). Exiting...")
    finally:
        # Clean up ROS 2 nodes gracefully
        client_node.destroy_node()
        rclpy.try_shutdown()

if __name__ == '__main__':
    main()
