"""
test_packets.py
Generates fake Modbus-style commands for testing VoltGuard's pipeline.
"""

def generate_command(register, value, description=""):
    """Creates a fake Modbus 'write register' command."""
    return {
        "function": "write_register",
        "register": register,
        "value": value,
        "description": description
    }


normal_commands = [
    generate_command(register=3, value=1200, description="Normal pump speed"),
    generate_command(register=3, value=1500, description="Normal pump speed"),
    generate_command(register=3, value=800, description="Low pump speed, safe"),
]

attack_commands = [
    generate_command(register=3, value=50000, description="Malicious - absurd RPM"),
    generate_command(register=3, value=-500, description="Malicious - negative RPM"),
    generate_command(register=3, value=99999, description="Malicious - overflow attempt"),
]

if __name__ == "__main__":
    print("Normal commands:")
    for cmd in normal_commands:
        print(" ", cmd)

    print("\nAttack commands:")
    for cmd in attack_commands:
        print(" ", cmd)