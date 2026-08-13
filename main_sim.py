"""
main_sim.py - Week 1 deliverable: run mock SCADA traffic through the whole
pipeline (protocol parser -> physics engine -> decision engine) and print a
summary. This is your "Parsing Audit" / mid-project review proof.

Run: python main_sim.py --count 200 --malicious-ratio 0.15
"""

import argparse
import random

from protocol import generate_normal_command, generate_malicious_command
from decision_engine import inspect_packet, LOG_PATH


def run(count, malicious_ratio):
    results = {"ALLOW": 0, "DROP": 0, "MALFORMED": 0}

    for _ in range(count):
        if random.random() < malicious_ratio:
            frame = generate_malicious_command()
        else:
            frame = generate_normal_command()

        verdict, parsed, physics = inspect_packet(frame)
        results[verdict] += 1

        if verdict == "DROP":
            print(f"[DROPPED]  rpm={parsed['rpm']:>6}  "
                  f"predicted peak={physics.peak_predicted_pressure:8.1f} psi  "
                  f"-> ALARM: physical safety violation")

    print("\n--- summary ---")
    total = sum(results.values())
    for k, v in results.items():
        print(f"{k:10}: {v:4} ({v/total*100:.1f}%)")
    print(f"\nfull log: {LOG_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--malicious-ratio", type=float, default=0.15)
    args = ap.parse_args()
    run(args.count, args.malicious_ratio)
