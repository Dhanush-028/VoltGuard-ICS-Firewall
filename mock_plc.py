"""
mock_plc.py - Week 2 deliverable: stands in for the actual pump controller
on the factory floor. Listens on a real TCP socket and does exactly what a
dumb PLC does: obeys whatever Modbus command it receives, no questions
asked. This is deliberately naive - it's the thing VoltGuard exists to
protect, not the thing doing the protecting.

Run standalone: python mock_plc.py
Or import start_plc_server() and run it in a thread (see network_demo.py).
"""

import socket
import threading
import time

from protocol import parse_frame, build_success_response

HOST = "127.0.0.1"
PLC_PORT = 5021


def _handle_client(conn, addr, verbose):
    with conn:
        while True:
            raw = conn.recv(256)
            if not raw:
                break
            try:
                parsed = parse_frame(raw)
            except ValueError:
                break  # a real PLC would just drop garbage too

            if verbose:
                print(f"[PLC] received command -> pump now set to {parsed['rpm']} RPM "
                      f"(no safety check - this is the raw hardware interface)")

            resp = build_success_response(
                parsed["transaction_id"], parsed["unit_id"],
                parsed["register_addr"], parsed["rpm"],
            )
            conn.sendall(resp)


def start_plc_server(verbose=True):
    """Blocking call - run this in its own thread if you need it alongside other code."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PLC_PORT))
    srv.listen(5)
    if verbose:
        print(f"[PLC] mock PLC listening on {HOST}:{PLC_PORT}")

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle_client, args=(conn, addr, verbose), daemon=True).start()


if __name__ == "__main__":
    start_plc_server()
