"""
mid_project_review.py - proves both mid-project review requirements from
the project PDF in one runnable script:

  1. "Parsing Audit: Prove the engine accurately reads Modbus hexadecimal
      payloads."
  2. "Simulation Test: Prove the engine catches an impossible physics
      command (e.g., negative valve pressure)."

Built to run live in front of an audience - no setup beyond the repo
already being here, prints clearly labeled PASS/FAIL for each check.

Run: python mid_project_review.py
"""

from protocol import (
    build_write_register_command, parse_frame,
    generate_normal_command, generate_malicious_command,
)
from physics_engine import evaluate_command, PRESSURE_SAFE_LIMIT

PASS = "PASS"
FAIL = "FAIL"


def parsing_audit():
    print("=" * 70)
    print("REQUIREMENT 1: Parsing Audit")
    print('  "Prove the engine accurately reads Modbus hexadecimal payloads"')
    print("=" * 70)

    checks = []

    # a known frame built fresh right now, so the hex isn't hardcoded
    # from memory - this is a live encode/decode round trip
    raw = build_write_register_command(rpm=2800, unit_id=1)
    hex_payload = raw.hex()
    print(f"\nBuilt frame for rpm=2800 -> hex payload: {hex_payload}")

    parsed = parse_frame(raw)
    print(f"Decoded back: {parsed}")
    ok = parsed["rpm"] == 2800 and parsed["unit_id"] == 1
    checks.append(ok)
    print(f"[{PASS if ok else FAIL}] round-trip encode/decode matches exactly")

    # decode the exact 50,000 RPM problem-statement scenario from raw hex
    raw2 = build_write_register_command(rpm=50000, unit_id=1)
    hex2 = raw2.hex()
    print(f"\nDecoding the problem statement's 50,000 RPM hex payload: {hex2}")
    parsed2 = parse_frame(raw2)
    ok2 = parsed2["rpm"] == 50000
    checks.append(ok2)
    print(f"[{PASS if ok2 else FAIL}] correctly extracts rpm=50000 from raw hex bytes")

    # malformed payload gets rejected, not silently misread
    print("\nFeeding a truncated/garbage payload: 0001")
    try:
        parse_frame(bytes.fromhex("0001"))
        checks.append(False)
        print(f"[{FAIL}] should have rejected a too-short frame")
    except ValueError as e:
        checks.append(True)
        print(f"[{PASS}] correctly rejected malformed payload: {e}")

    return all(checks)


def simulation_test():
    print("\n" + "=" * 70)
    print("REQUIREMENT 2: Simulation Test")
    print('  "Prove the engine catches an impossible physics command')
    print('   (e.g., negative valve pressure)"')
    print("=" * 70)

    checks = []

    # case A: the overspeed scenario from the problem statement
    print(f"\n--- Case A: overspeed command (50,000 RPM) ---")
    v = evaluate_command(rpm=50000)
    ok = v.catastrophic and v.peak_predicted_pressure > PRESSURE_SAFE_LIMIT
    checks.append(ok)
    print(f"predicted peak: {v.peak_predicted_pressure:,.1f} psi  "
          f"(limit: {PRESSURE_SAFE_LIMIT:.0f} psi)")
    print(f"[{PASS if ok else FAIL}] impossible/unsafe command correctly flagged catastrophic")

    # case B: the literal PDF example - negative valve/sensor pressure
    print(f"\n--- Case B: negative valve pressure (impossible sensor state) ---")
    v = evaluate_command(rpm=1200, current_pressure=-50.0)
    ok = v.impossible_state and v.catastrophic
    checks.append(ok)
    print(f"reported starting pressure: -50.0 psi (cannot exist in reality)")
    print(f"[{PASS if ok else FAIL}] impossible physical state correctly rejected "
          f"regardless of the RPM command riding along with it")

    # case C: negative RPM - defense in depth, not representable on the
    # real wire protocol (Modbus registers are unsigned), but proves the
    # physics math itself doesn't rely on sign to catch danger
    print(f"\n--- Case C: negative RPM command (defense-in-depth check) ---")
    v = evaluate_command(rpm=-50000)
    ok = v.catastrophic
    checks.append(ok)
    print(f"predicted peak: {v.peak_predicted_pressure:,.1f} psi")
    print(f"[{PASS if ok else FAIL}] affinity law squares rpm, so sign doesn't matter - "
          f"still caught")

    return all(checks)


if __name__ == "__main__":
    r1 = parsing_audit()
    r2 = simulation_test()

    print("\n" + "=" * 70)
    print("MID-PROJECT REVIEW SUMMARY")
    print("=" * 70)
    print(f"Parsing Audit:    {'PASSED' if r1 else 'FAILED'}")
    print(f"Simulation Test:  {'PASSED' if r2 else 'FAILED'}")
    print(f"\nOverall: {'ALL REQUIREMENTS MET' if (r1 and r2) else 'ISSUES FOUND'}")
