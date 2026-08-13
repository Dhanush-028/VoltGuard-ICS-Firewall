"""
network_client.py - stands in for an operator workstation (or an attacker)
talking to the plant over the network. Every command here is real bytes
sent down a real socket to gateway.py - nothing in-process anymore.

Run standalone once mock_plc.py and gateway.py are already running:
    python network_client.py --count 50 --malicious-ratio 0.2
"""

import argparse
import random
import socket
import time

from protocol import (
    generate_normal_command, generate_malicious_command, parse_response,
)
from gateway import GATEWAY_PORT
from mock_plc import HOST


def run(count, malicious_ratio, delay):
    results = {"forwarded": 0, "blocked": 0}

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, GATEWAY_PORT))

        for _ in range(count):
            frame = generate_malicious_command() if random.random() < malicious_ratio else generate_normal_command()
            sock.sendall(frame)
            reply = sock.recv(256)
            resp = parse_response(reply)

            if resp["ok"]:
                results["forwarded"] += 1
                print(f"[CLIENT] command accepted -> PLC confirmed pump at {resp['rpm']} RPM")
            else:
                results["blocked"] += 1
                print(f"[CLIENT] command REJECTED by gateway "
                      f"(exception code {resp['exception_code']}) - never reached the PLC")

            time.sleep(delay)

    print("\n--- summary ---")
    for k, v in results.items():
        print(f"{k:10}: {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--malicious-ratio", type=float, default=0.2)
    ap.add_argument("--delay", type=float, default=0.15)
    args = ap.parse_args()
    run(args.count, args.malicious_ratio, args.delay)
