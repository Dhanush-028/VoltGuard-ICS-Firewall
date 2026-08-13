"""
decision_engine.py - the IPS logic. Parses a raw frame, asks the physics
engine what would happen if we let it through, and returns ALLOW or DROP.

This is the piece the project plan wants rewritten in Rust for sub-10ms
inline latency in week 3 (see rust_decision_engine/ for that port). The
Python version here is functionally identical - same interface, same
verdicts - so you can validate the logic first and port it once it's right,
instead of debugging physics AND Rust ownership at the same time.
"""

import csv
import time
import os

from protocol import parse_frame
from physics_engine import evaluate_command

LOG_PATH = os.path.join(os.path.dirname(__file__), "voltguard_log.csv")


def _ensure_log_header():
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp", "verdict", "rpm", "target_pressure",
                "peak_predicted_pressure", "reason"
            ])


def log_verdict(verdict_str, physics_result, reason):
    _ensure_log_header()
    with open(LOG_PATH, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            verdict_str,
            physics_result.rpm,
            round(physics_result.target_pressure, 2),
            round(physics_result.peak_predicted_pressure, 2),
            reason,
        ])


def inspect_packet(raw_frame: bytes):
    """Full pipeline: raw bytes in -> (verdict, parsed, physics_result) out.

    verdict is one of "ALLOW", "DROP", "MALFORMED".
    """
    try:
        parsed = parse_frame(raw_frame)
    except ValueError as e:
        log_verdict("MALFORMED", type("_", (), {
            "rpm": -1, "target_pressure": 0, "peak_predicted_pressure": 0
        })(), str(e))
        return "MALFORMED", None, None

    result = evaluate_command(parsed["rpm"])

    if result.catastrophic:
        if result.impossible_state:
            reason = "physically impossible sensor reading - rejected regardless of command"
        else:
            reason = (f"predicted peak {result.peak_predicted_pressure:.1f} psi "
                       f"exceeds safety limit")
        log_verdict("DROP", result, reason)
        return "DROP", parsed, result

    reason = "within physical safety envelope"
    if result.warning:
        reason = (f"within limit but predicted peak "
                   f"{result.peak_predicted_pressure:.1f} psi is close to the ceiling")
    log_verdict("ALLOW", result, reason)
    return "ALLOW", parsed, result


if __name__ == "__main__":
    from protocol import generate_normal_command, generate_malicious_command

    for _ in range(3):
        v, parsed, result = inspect_packet(generate_normal_command())
        print(v, parsed, result)

    for _ in range(3):
        v, parsed, result = inspect_packet(generate_malicious_command())
        print(v, parsed, result)

    print(f"\nlog written to {LOG_PATH}")
