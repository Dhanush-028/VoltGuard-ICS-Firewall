//! physics.rs - the physics firewall's brain, ported from physics_engine.py.
//! Same affinity-law model, same first-order lag, same impossible-state
//! check. Constants are loaded from a config file instead of hardcoded -
//! a real deployment has a different pump and a different pipe than this
//! demo's tuning, and shouldn't need a recompile to change that.

use std::fs;

#[derive(Debug, Clone, Copy)]
pub struct PhysicsConfig {
    pub k_pump: f64,
    pub tau_seconds: f64,
    pub pressure_safe_limit: f64,
    pub pressure_warning_margin: f64,
}

impl Default for PhysicsConfig {
    fn default() -> Self {
        // same tuning as physics_engine.py's defaults
        PhysicsConfig {
            k_pump: 0.00001,
            tau_seconds: 0.6,
            pressure_safe_limit: 150.0,
            pressure_warning_margin: 0.85,
        }
    }
}

impl PhysicsConfig {
    /// Loads from a simple `key = value` text file (one per line, `#` comments
    /// allowed). Deliberately not a TOML/YAML dependency - keeps this binary
    /// standard-library-only, same philosophy as the C++ parser. Falls back
    /// to defaults if the file is missing, so it never fails to start.
    pub fn load_or_default(path: &str) -> Self {
        let mut cfg = PhysicsConfig::default();
        let Ok(contents) = fs::read_to_string(path) else {
            return cfg;
        };
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let Some((key, value)) = line.split_once('=') else { continue };
            let key = key.trim();
            let Ok(value) = value.trim().parse::<f64>() else { continue };
            match key {
                "k_pump" => cfg.k_pump = value,
                "tau_seconds" => cfg.tau_seconds = value,
                "pressure_safe_limit" => cfg.pressure_safe_limit = value,
                "pressure_warning_margin" => cfg.pressure_warning_margin = value,
                _ => {}
            }
        }
        cfg
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PhysicsVerdict {
    pub rpm: i64,
    pub target_pressure: f64,
    pub peak_predicted_pressure: f64,
    pub catastrophic: bool,
    pub warning: bool,
    pub impossible_state: bool,
}

pub fn target_pressure_for_rpm(cfg: &PhysicsConfig, rpm: f64) -> f64 {
    cfg.k_pump * rpm * rpm
}

/// Euler-integrates the first-order lag forward, same as
/// physics_engine.py's simulate_pressure_curve, and returns the peak.
pub fn simulate_peak_pressure(cfg: &PhysicsConfig, current_pressure: f64, rpm: f64) -> f64 {
    let target = target_pressure_for_rpm(cfg, rpm);
    let dt = 0.02;
    let horizon = 3.0;
    let steps = (horizon / dt) as usize;

    let mut p = current_pressure;
    let mut peak = p;
    for _ in 0..steps {
        let dp = (target - p) / cfg.tau_seconds * dt;
        p += dp;
        if p > peak {
            peak = p;
        }
    }
    peak
}

pub fn evaluate_command(cfg: &PhysicsConfig, rpm: i64, current_pressure: f64) -> PhysicsVerdict {
    if current_pressure < 0.0 {
        return PhysicsVerdict {
            rpm,
            target_pressure: target_pressure_for_rpm(cfg, rpm as f64),
            peak_predicted_pressure: current_pressure,
            catastrophic: true,
            warning: false,
            impossible_state: true,
        };
    }

    let peak = simulate_peak_pressure(cfg, current_pressure, rpm as f64);
    let target = target_pressure_for_rpm(cfg, rpm as f64);

    let catastrophic = peak > cfg.pressure_safe_limit;
    let warning = !catastrophic && peak > cfg.pressure_safe_limit * cfg.pressure_warning_margin;

    PhysicsVerdict {
        rpm,
        target_pressure: target,
        peak_predicted_pressure: peak,
        catastrophic,
        warning,
        impossible_state: false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Parity checks against physics_engine.py's actual printed output -
    /// same numbers, not just "the Rust math runs without crashing."
    #[test]
    fn matches_python_normal_case() {
        let cfg = PhysicsConfig::default();
        let v = evaluate_command(&cfg, 2800, 0.0);
        // Python printed: target=78.4 psi peak=77.9 psi catastrophic=False
        assert!((v.target_pressure - 78.4).abs() < 0.1);
        assert!((v.peak_predicted_pressure - 77.9).abs() < 0.1);
        assert!(!v.catastrophic);
    }

    #[test]
    fn matches_python_catastrophic_case() {
        let cfg = PhysicsConfig::default();
        let v = evaluate_command(&cfg, 50000, 0.0);
        // Python printed: target=25000.0 psi peak=24845.3 psi catastrophic=True
        assert!((v.target_pressure - 25000.0).abs() < 1.0);
        assert!((v.peak_predicted_pressure - 24845.3).abs() < 1.0);
        assert!(v.catastrophic);
    }

    #[test]
    fn impossible_negative_pressure_rejected() {
        let cfg = PhysicsConfig::default();
        let v = evaluate_command(&cfg, 1200, -50.0);
        assert!(v.impossible_state);
        assert!(v.catastrophic);
    }
}
