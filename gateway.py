"""
gateway.py - Week 2's actual deliverable: VoltGuard as a real bump-in-the-
wire, not a Python function call.

Topology:
    client (operator / attacker) --TCP--> gateway.py --TCP--> mock_plc.py

Every command physically travels over a socket to get here. The gateway
parses it, asks decision_engine for a verdict, and either:
  - ALLOW: opens a connection to the real PLC, forwards the exact bytes,
    relays the PLC's reply back to the client, and logs the PLC's real
    measured pressure alongside the prediction (week 3 addition)
  - DROP: never touches the PLC at all - sends a Modbus exception response
    straight back to the client and logs the alarm

This is the literal difference between "simulates traffic" (week 1) and
"intercepts traffic" (week 2): the frame bytes are indistinguishable from
what a real Modbus master/slave conversation looks like on the wire.
"""

import socket
import threading

from protocol import parse_frame, build_exception_response, parse_response
from decision_engine import inspect_packet, log_verdict
from mock_plc import HOST, PLC_PORT

GATEWAY_PORT = 5020


def _forward_to_plc(raw):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as plc_sock:
        plc_sock.connect((HOST, PLC_PORT))
        plc_sock.sendall(raw)
        return plc_sock.recv(256)


def _handle_client(conn, addr, verbose):
    with conn:
        while True:
            raw = conn.recv(256)
            if not raw:
                break

            # auto_log=False: we log ourselves below, once we know whether
            # there's real PLC telemetry to attach to this same row
            verdict, parsed, physics = inspect_packet(raw, auto_log=False)

            if verdict == "MALFORMED":
                if verbose:
                    print(f"[GATEWAY] malformed frame from {addr}, dropping connection")
                break

            if verdict == "ALLOW":
                try:
                    plc_reply = _forward_to_plc(raw)
                    resp = parse_response(plc_reply)
                    actual_pressure = resp.get("actual_pressure")
                    if verbose:
                        actual_str = f"{actual_pressure:.1f} psi" if actual_pressure is not None else "n/a"
                        print(f"[GATEWAY] ALLOW  rpm={parsed['rpm']:>6}  "
                              f"predicted={physics.peak_predicted_pressure:8.1f} psi  "
                              f"actual={actual_str}  -> forwarded to PLC")
                    log_verdict("ALLOW", physics, "within physical safety envelope",
                                actual_pressure=actual_pressure)
                    conn.sendall(plc_reply)
                except (ConnectionRefusedError, OSError) as e:
                    if verbose:
                        print(f"[GATEWAY] could not reach PLC: {e}")
                    break
            else:  # DROP
                reason = ("physically impossible sensor reading - rejected regardless of command"
                          if physics.impossible_state else
                          f"predicted peak {physics.peak_predicted_pressure:.1f} psi exceeds safety limit")
                if verbose:
                    print(f"[GATEWAY] DROP   rpm={parsed['rpm']:>6}  "
                          f"predicted={physics.peak_predicted_pressure:8.1f} psi  "
                          f"-> ALARM, command never reached the PLC")
                log_verdict("DROP", physics, reason)
                exc = build_exception_response(parsed["transaction_id"], parsed["unit_id"])
                conn.sendall(exc)


def start_gateway_server(verbose=True):
    """Blocking call - run this in its own thread if you need it alongside other code."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, GATEWAY_PORT))
    srv.listen(5)
    if verbose:
        print(f"[GATEWAY] VoltGuard bump-in-the-wire listening on {HOST}:{GATEWAY_PORT}")
        print(f"[GATEWAY] forwarding safe traffic to PLC at {HOST}:{PLC_PORT}")

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle_client, args=(conn, addr, verbose), daemon=True).start()


if __name__ == "__main__":
    try:
        start_gateway_server()
    except KeyboardInterrupt:
        print("\n[GATEWAY] shutting down")
