"""
VoltGuard - Week 1 - Traffic Generator
========================================
Builds raw Modbus/TCP frames by hand (no external libs) so we fully
control the bytes and can generate both "normal" and "malicious"
industrial commands for the C++ parser to consume.

Modbus/TCP frame structure (this is what the parser has to decode):

  MBAP Header (7 bytes)                PDU (variable)
  -----------------------------------  --------------------------
  Transaction ID (2 bytes)
  Protocol ID    (2 bytes, always 0)
  Length         (2 bytes) --> byte count of everything AFTER this field
  Unit ID        (1 byte)
                                        Function Code (1 byte)
                                        Data (depends on function code)

We'll focus on Function Code 0x06 (Write Single Register), which is a
realistic way an attacker (or a legitimate SCADA master) would tell a
pump/VFD (Variable Frequency Drive) to spin at a target RPM by writing
a value into its speed-setpoint register.

  PDU for Write Single Register (0x06):
     Function Code   (1 byte)  = 0x06
     Register Addr   (2 bytes) = e.g. 0x0001 (pump speed setpoint register)
     Register Value  (2 bytes) = target RPM (0-65535, since it's a 16-bit reg)

Output: writes raw frames to traffic.bin, one after another, each
prefixed with a 4-byte length so the C++ side can split them apart
easily. Also writes a human-readable traffic_log.csv describing what
each frame *means*, so you can verify the parser's output later.
"""

import struct
import random
import csv

# Modbus register we're pretending controls the water pump's speed (RPM)
PUMP_SPEED_REGISTER = 0x0001

# Physically safe operating range for this mock pump, defined by the
# "physical constraints" the Week 1 physics model will also use.
SAFE_MIN_RPM = 0
SAFE_MAX_RPM = 3000        # anything above this risks over-pressurizing the pipe
ATTACK_RPM   = 50000       # the "perfectly formatted but physically insane" command


def build_modbus_tcp_frame(transaction_id: int, unit_id: int,
                            function_code: int, register_addr: int,
                            register_value: int) -> bytes:
    """
    Hand-builds a single Modbus/TCP 'Write Single Register' (0x06) frame.
    Returns the raw bytes exactly as they'd appear on the wire.
    """
    protocol_id = 0x0000  # always 0 for Modbus

    # PDU = function code + address + value = 5 bytes
    pdu = struct.pack(">BHH", function_code, register_addr, register_value)

    # Length field = everything after the length field itself
    # = unit_id (1 byte) + PDU (5 bytes) = 6
    length = 1 + len(pdu)

    mbap = struct.pack(">HHHB", transaction_id, protocol_id, length, unit_id)

    return mbap + pdu


def make_normal_frame(txn_id: int) -> tuple[bytes, str]:
    """A legitimate, physically-safe pump command."""
    rpm = random.randint(500, SAFE_MAX_RPM)
    frame = build_modbus_tcp_frame(txn_id, unit_id=1, function_code=0x06,
                                    register_addr=PUMP_SPEED_REGISTER,
                                    register_value=rpm)
    label = f"NORMAL   | set pump speed = {rpm} RPM (within safe range 0-{SAFE_MAX_RPM})"
    return frame, label


def make_malicious_frame(txn_id: int) -> tuple[bytes, str]:
    """
    A SYNTACTICALLY PERFECT Modbus frame that is physically catastrophic.
    This is exactly the attack scenario from the problem statement:
    a standard IT firewall would allow this because nothing about the
    packet *format* is wrong.
    """
    frame = build_modbus_tcp_frame(txn_id, unit_id=1, function_code=0x06,
                                    register_addr=PUMP_SPEED_REGISTER,
                                    register_value=ATTACK_RPM)
    label = f"MALICIOUS| set pump speed = {ATTACK_RPM} RPM (exceeds safe max {SAFE_MAX_RPM} -> pipe burst risk)"
    return frame, label


def main():
    random.seed(42)  # reproducible test traffic

    frames_meta = []
    txn_id = 1

    # Generate a realistic mix: mostly normal traffic, with malicious
    # commands sprinkled in, similar to how an attacker would hide
    # among legitimate SCADA polling traffic.
    for _ in range(15):
        frame, label = make_normal_frame(txn_id)
        frames_meta.append((txn_id, frame, label))
        txn_id += 1

    # Inject malicious frames at specific points
    for _ in range(3):
        frame, label = make_malicious_frame(txn_id)
        frames_meta.append((txn_id, frame, label))
        txn_id += 1

    for _ in range(5):
        frame, label = make_normal_frame(txn_id)
        frames_meta.append((txn_id, frame, label))
        txn_id += 1

    random.shuffle(frames_meta)  # mix normal/malicious like real traffic

    # Write raw frames, each length-prefixed (4-byte big-endian uint32)
    # so the C++ parser can read them one at a time from a single file
    # (this mimics reading frames off a live TCP stream).
    with open("traffic.bin", "wb") as f:
        for _, frame, _ in frames_meta:
            f.write(struct.pack(">I", len(frame)))
            f.write(frame)

    # Write a human-readable ground-truth log for verification
    with open("traffic_log.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["transaction_id", "frame_hex", "description"])
        for txn, frame, label in frames_meta:
            writer.writerow([txn, frame.hex(), label])

    print(f"Generated {len(frames_meta)} frames -> traffic.bin")
    print(f"Ground-truth log -> traffic_log.csv")
    print(f"  Normal:    {sum(1 for _,_,l in frames_meta if l.startswith('NORMAL'))}")
    print(f"  Malicious: {sum(1 for _,_,l in frames_meta if l.startswith('MALICIOUS'))}")


if __name__ == "__main__":
    main()