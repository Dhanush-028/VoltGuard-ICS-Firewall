"""
VoltGuard - Week 1 - Physics Engine (baseline)
=================================================
A basic fluid-dynamics model of ONE mock industrial pipe segment fed by
a centrifugal pump. This is Week 1's job only: establish the baseline
physics and a "safe vs catastrophic" classifier. Later weeks will wire
this into the Rust Decision Engine so a Modbus command can be tested
against this model *before* it reaches real hardware.

Physical model (deliberately simple, but grounded in real relations):

1. Pump affinity law: for a centrifugal pump, flow rate scales
   linearly with impeller RPM, and pump head (dynamic pressure it can
   generate) scales with the SQUARE of RPM:

        Q  ∝ RPM
        H  ∝ RPM^2

   This is why a "small" overspeed command is dangerous: doubling RPM
   roughly QUADRUPLES the pressure the pump tries to push into the pipe.

2. Darcy-Weisbach friction loss along the pipe (energy lost to
   friction as fluid moves through it):

        h_f = f * (L/D) * (v^2 / 2g)

   where f = friction factor, L = pipe length, D = pipe diameter,
   v = flow velocity, g = gravitational acceleration.

3. Net static pressure at the pipe wall = pump head - friction loss,
   converted to real engineering units (kPa) via water density and g.

4. The pipe itself has a maximum burst pressure rating (like a real
   pipe's PN/pressure class). If the modeled pressure exceeds it,
   the simulation should be classified CATASTROPHIC.

This mirrors SAFE_MAX_RPM = 3000 used by the parser as a first-pass
proxy - here we derive it from the underlying physics instead of just
declaring a fixed number, so the two layers are consistent.
"""

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass


# ---- Mock pipeline physical constants ----
PIPE_DIAMETER_M = 0.15        # 150 mm pipe, typical for a municipal water main
PIPE_LENGTH_M = 500.0         # 500 m run from pump to first junction
FRICTION_FACTOR = 0.02        # typical Darcy friction factor for a smooth steel pipe
WATER_DENSITY = 1000.0        # kg/m^3
GRAVITY = 9.81                # m/s^2

# Pipe burst rating - this pipe is rated (per its PN class) to handle
# a maximum internal pressure before catastrophic failure.
PIPE_BURST_PRESSURE_KPA = 600.0

# Pump characteristics, calibrated so that ~3000 RPM sits right at
# the edge of the pipe's safe operating envelope (matches Week 1's
# parser-level heuristic).
PUMP_RATED_RPM = 3000.0
PUMP_RATED_HEAD_M = 55.0      # meters of head the pump produces at rated RPM
PUMP_RATED_FLOW_M3S = 0.05    # m^3/s the pump moves at rated RPM


@dataclass
class SimulationResult:
    rpm: float
    flow_rate_m3s: float
    flow_velocity_ms: float
    pump_head_m: float
    friction_loss_m: float
    net_pressure_kpa: float
    status: str  # "SAFE" | "WARNING" | "CATASTROPHIC"


def pipe_cross_section_area_m2() -> float:
    return np.pi * (PIPE_DIAMETER_M / 2) ** 2


def simulate_pump_command(rpm: float) -> SimulationResult:
    """
    Given a commanded pump RPM, run the pipe's physical response and
    classify the resulting state. This is the function VoltGuard's
    Decision Engine will call for every intercepted Modbus command.
    """
    if rpm < 0:
        raise ValueError("RPM cannot be negative")

    # --- Pump affinity laws ---
    speed_ratio = rpm / PUMP_RATED_RPM
    flow_rate = PUMP_RATED_FLOW_M3S * speed_ratio          # Q ∝ RPM
    pump_head = PUMP_RATED_HEAD_M * (speed_ratio ** 2)      # H ∝ RPM^2

    # --- Flow velocity in the pipe ---
    area = pipe_cross_section_area_m2()
    velocity = flow_rate / area

    # --- Darcy-Weisbach friction loss ---
    friction_loss = (
        FRICTION_FACTOR * (PIPE_LENGTH_M / PIPE_DIAMETER_M) *
        (velocity ** 2) / (2 * GRAVITY)
    )

    # --- Net head at pipe wall, converted to pressure (kPa) ---
    net_head_m = max(pump_head - friction_loss, 0.0)
    net_pressure_kpa = (WATER_DENSITY * GRAVITY * net_head_m) / 1000.0

    # --- Classification ---
    if net_pressure_kpa >= PIPE_BURST_PRESSURE_KPA:
        status = "CATASTROPHIC"
    elif net_pressure_kpa >= 0.85 * PIPE_BURST_PRESSURE_KPA:
        status = "WARNING"
    else:
        status = "SAFE"

    return SimulationResult(
        rpm=rpm,
        flow_rate_m3s=flow_rate,
        flow_velocity_ms=velocity,
        pump_head_m=pump_head,
        friction_loss_m=friction_loss,
        net_pressure_kpa=net_pressure_kpa,
        status=status,
    )


def print_result(r: SimulationResult) -> None:
    print(
        f"RPM={r.rpm:>8.0f} | Flow={r.flow_rate_m3s:6.3f} m3/s | "
        f"Velocity={r.flow_velocity_ms:5.2f} m/s | "
        f"Pressure={r.net_pressure_kpa:8.1f} kPa | {r.status}"
    )


def find_max_safe_rpm() -> float:
    """
    Sweeps RPM upward to find where the pipe crosses into CATASTROPHIC
    territory - i.e. derives the real physical RPM ceiling, rather
    than assuming it. Useful for sanity-checking the parser's
    hardcoded SAFE_MAX_RPM