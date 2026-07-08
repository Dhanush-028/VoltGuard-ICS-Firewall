"""
modbus_parser.py
Reads a fake Modbus command (dict) and extracts a clean,
human-readable command for the rest of the pipeline to use.
"""

def parse_command(raw_command):
    if raw_command["function"] != "write_register":
        raise ValueError(f"Unsupported function: {raw_command['function']}")

    return {
        "register": raw_command["register"],
        "rpm": raw_command["value"]
    }


if __name__ == "__main__":
    from test_packets import normal_commands, attack_commands

    print("Parsed normal commands:")
    for cmd in normal_commands:
        print(" ", parse_command(cmd))

    print("\nParsed attack commands:")
    for cmd in attack_commands:
        print(" ", parse_command(cmd))