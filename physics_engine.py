"""
physics_engine.py - the actual "physics firewall" brain of VoltGuard.

Model: a centrifugal pump pushing water through a fixed pipe into a closed
section protected by a pressure-relief valve rated at PRESSURE_SAFE_LIMIT.

Two physics facts drive this:

1. Pump affinity laws: for a centrifugal pump, discharge pressure scales
   with the SQUARE of RPM (P ~ k * rpm^2). This is why "spin the pump a bit
   faster" is fine but "spin it 20x faster" is not a linear problem - it's
   quadratic, which is exactly what a naive IT firewall (checking rpm is
   "a number") has zero way of knowing.

2. The pipe/fluid system doesn't jump to that pressure instantly - it has
   compliance (a bit of give, air pockets, pipe wall flex), modeled here as
   a first-order lag with time constant TAU. We simulate forward from the
   current pressure toward the new target and report the peak pressure the
   system would reach if the command were allowed to execute.

Swap this for a real OpenModelica/SciPy fluid model later (per the project
plan) - the interface below (predict/classify) is what the decision engine
depends on, so the rest of the pipeline doesn't care how it's implemented.
"""

from dataclasses import dataclass

# --- physical constants (tuned for a mock small industrial pipeline) ---
K_PUMP = 0.00001         # affinity-law constant: target_pressure = K_PUMP * rpm^2
TAU_SECONDS = 0.6       # pipe/fluid response time constant
PRESSURE_SAFE_LIMIT = 150.0   # psi - relief valve / pipe rating
PRESSURE_WARNING_MARGIN = 0.85  # flag anything predicted above 85% of limit


@dataclass
class PhysicsVerdict:
    rpm: int
    target_pressure: float
    peak_predicted_pressure: float
    catastrophic: bool
    warning: bool
    impossible_state: bool = False  # the starting condition itself is physically impossible


def target_pressure_for_rpm(rpm: float) -> float:
    """Steady-state pressure this rpm would eventually settle at."""
    return K_PUMP * (rpm ** 2)


def simulate_pressure_curve(current_pressure: float, rpm: float,
                             dt: float = 0.02, horizon: float = 3.0):
    """Euler-integrate the first-order lag forward and return the
    (times, pressures) curve, so the dashboard can actually plot it."""
    target = target_pressure_for_rpm(rpm)
    steps = int(horizon / dt)
    p = current_pressure
    times, pressures = [0.0], [p]
    for i in range(1, steps + 1):
        dp = (target - p) / TAU_SECONDS * dt
        p += dp
        times.append(i * dt)
        pressures.append(p)
    return times, pressures


def evaluate_command(rpm: int, current_pressure: float = 0.0) -> PhysicsVerdict:
    """This is what the decision engine calls before letting a packet through.

    Also validates the starting state itself is physically possible. A
    pressure reading below 0 psi (absolute) cannot exist in this system -
    if one shows up, it means either a sensor fault or a spoofed reading,
    and the command should be rejected regardless of what RPM it asked
    for. This is the "impossible physics command (e.g. negative valve
    pressure)" case the project plan's mid-project review specifically
    asks to prove the engine catches.
    """
    if current_pressure < 0:
        return PhysicsVerdict(
            rpm=rpm,
            target_pressure=target_pressure_for_rpm(rpm),
            peak_predicted_pressure=current_pressure,
            catastrophic=True,
            warning=False,
            impossible_state=True,
        )

    _, pressures = simulate_pressure_curve(current_pressure, rpm)
    peak = max(pressures)
    target = target_pressure_for_rpm(rpm)

    catastrophic = peak > PRESSURE_SAFE_LIMIT
    warning = (not catastrophic) and peak > PRESSURE_SAFE_LIMIT * PRESSURE_WARNING_MARGIN

    return PhysicsVerdict(
        rpm=rpm,
        target_pressure=target,
        peak_predicted_pressure=peak,
        catastrophic=catastrophic,
        warning=warning,
    )


if __name__ == "__main__":
    print("=== normal evaluation ===")
    for test_rpm in (1800, 2800, 15000, 50000):
        v = evaluate_command(test_rpm)
        print(f"rpm={v.rpm:>6}  target={v.target_pressure:8.1f} psi  "
              f"peak={v.peak_predicted_pressure:8.1f} psi  "
              f"catastrophic={v.catastrophic}  warning={v.warning}")

    print("\n=== impossible physics command: negative sensor pressure ===")
    v = evaluate_command(rpm=1200, current_pressure=-50.0)
    print(f"rpm={v.rpm}  reported_pressure=-50.0 psi  "
          f"catastrophic={v.catastrophic}  impossible_state={v.impossible_state}")
    print("  -> correctly rejected: a real pressure sensor cannot read below 0 psi absolute; "
          "this indicates a spoofed or faulted reading, not a legitimate state")

    print("\n=== negative RPM (not representable on the wire, but defense-in-depth check) ===")
    v = evaluate_command(rpm=-50000)
    print(f"rpm={v.rpm}  target={v.target_pressure:.1f} psi  peak={v.peak_predicted_pressure:.1f} psi  "
          f"catastrophic={v.catastrophic}")
    print("  -> the affinity law squares rpm, so a negative command is exactly as dangerous "
          "as the same magnitude positive one, and gets caught the same way")
