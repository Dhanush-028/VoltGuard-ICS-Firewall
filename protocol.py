"""
protocol.py - minimal Modbus/TCP framing for VoltGuard

Real Modbus/TCP ADU layout:
  MBAP header (7 bytes): transaction_id(2) protocol_id(2) length(2) unit_id(1)
  PDU: function_code(1) + payload

We only implement function code 0x06 (Write Single Register), since that's
the one used to command pump RPM in the mock pipeline. Good enough for
week 1 - swap in pymodbus or a real Scapy dissector later if you need the
full function code set.
"""

import struct
import random

FUNC_WRITE_SINGLE_REGISTER = 0x06
PUMP_RPM_REGISTER = 0x0001  # the register address that represents pump RPM

_txn_counter = 0


def _next_txn_id():
    global _txn_counter
    _txn_counter = (_txn_counter + 1) % 65535
    return _txn_counter


def build_write_register_command(rpm, unit_id=1):
    """Build a raw Modbus/TCP frame commanding the pump to spin at `rpm`."""
    if not (0 <= rpm <= 65535):
        raise ValueError("rpm must fit in a 16-bit register (0-65535)")

    txn_id = _next_txn_id()
    protocol_id = 0
    pdu = struct.pack(">BHH", FUNC_WRITE_SINGLE_REGISTER, PUMP_RPM_REGISTER, rpm)
    length = len(pdu) + 1  # +1 for unit_id
    mbap = struct.pack(">HHHB", txn_id, protocol_id, length, unit_id)
    return mbap + pdu


def parse_frame(raw):
    """Parse a raw Modbus/TCP frame back into its fields. Raises ValueError on garbage."""
    if len(raw) < 8:
        raise ValueError("frame too short to be a valid Modbus/TCP ADU")

    txn_id, protocol_id, length, unit_id = struct.unpack(">HHHB", raw[:7])
    pdu = raw[7:]

    if protocol_id != 0:
        raise ValueError(f"unexpected protocol_id {protocol_id}, expected 0")
    if len(pdu) != length - 1:
        raise ValueError("length field doesn't match actual payload size")

    func_code = pdu[0]
    if func_code != FUNC_WRITE_SINGLE_REGISTER:
        raise ValueError(f"unsupported function code 0x{func_code:02x}")

    reg_addr, reg_value = struct.unpack(">HH", pdu[1:5])

    return {
        "transaction_id": txn_id,
        "unit_id": unit_id,
        "function_code": func_code,
        "register_addr": reg_addr,
        "rpm": reg_value,
    }


EXCEPTION_BIT = 0x80
EXC_SERVER_DEVICE_FAILURE = 0x04  # what we return when VoltGuard drops a command


def build_success_response(txn_id, unit_id, reg_addr, reg_value):
    """A real Modbus write-single-register success reply just echoes the
    request's address and value back - that's the wire-level 'ack'."""
    pdu = struct.pack(">BHH", FUNC_WRITE_SINGLE_REGISTER, reg_addr, reg_value)
    length = len(pdu) + 1
    mbap = struct.pack(">HHHB", txn_id, 0, length, unit_id)
    return mbap + pdu


def build_exception_response(txn_id, unit_id, exception_code=EXC_SERVER_DEVICE_FAILURE):
    """What VoltGuard sends back instead of forwarding a dangerous command -
    a real Modbus exception response, function code with the high bit set."""
    pdu = struct.pack(">BB", FUNC_WRITE_SINGLE_REGISTER | EXCEPTION_BIT, exception_code)
    length = len(pdu) + 1
    mbap = struct.pack(">HHHB", txn_id, 0, length, unit_id)
    return mbap + pdu


def parse_response(raw):
    """Parse whatever comes back from the gateway/PLC - success echo or exception."""
    txn_id, protocol_id, length, unit_id = struct.unpack(">HHHB", raw[:7])
    pdu = raw[7:]
    func_code = pdu[0]
    if func_code & EXCEPTION_BIT:
        return {"ok": False, "transaction_id": txn_id, "exception_code": pdu[1]}
    reg_addr, reg_value = struct.unpack(">HH", pdu[1:5])
    return {"ok": True, "transaction_id": txn_id, "register_addr": reg_addr, "rpm": reg_value}


def generate_normal_command():
    """A command a real plant operator would actually send."""
    rpm = random.randint(500, 2800)
    return build_write_register_command(rpm)


def generate_malicious_command():
    """A syntactically valid but physically dangerous command - the kind an
    IT firewall waves straight through because nothing about the packet
    itself is malformed."""
    rpm = random.choice([
        random.randint(15000, 30000),
        50000,  # the exact scenario from the problem statement
        random.randint(40000, 65535),
    ])
    return build_write_register_command(rpm)


if __name__ == "__main__":
    normal = generate_normal_command()
    malicious = generate_malicious_command()
    print("normal frame:", normal.hex(), "->", parse_frame(normal))
    print("malicious frame:", malicious.hex(), "->", parse_frame(malicious))
