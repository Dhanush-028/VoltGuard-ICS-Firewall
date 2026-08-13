"""
network_demo.py - Week 2 all-in-one demo. Starts the mock PLC and the
VoltGuard gateway as background threads (so you see all three roles'
output interleaved in one terminal), then runs real traffic through the
whole wire topology.

This is the easy button for a review/demo. For the "real" three-process
setup (closer to how you'd actually deploy this), open three terminals
and run mock_plc.py, gateway.py, and network_client.py separately - see
README.md.

Run: python network_demo.py --count 60 --malicious-ratio 0.2
"""

import argparse
import threading
import time

from mock_plc import start_plc_server
from gateway import start_gateway_server
from network_client import run as run_client


def main(count, malicious_ratio, delay):
    threading.Thread(target=start_plc_server, args=(True,), daemon=True).start()
    time.sleep(0.2)
    threading.Thread(target=start_gateway_server, args=(True,), daemon=True).start()
    time.sleep(0.3)

    print("\n=== all services up - starting live traffic over real sockets ===\n")
    run_client(count, malicious_ratio, delay)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--malicious-ratio", type=float, default=0.2)
    ap.add_argument("--delay", type=float, default=0.1)
    args = ap.parse_args()
    main(args.count, args.malicious_ratio, args.delay)
