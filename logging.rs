//! logging.rs - writes to the exact same voltguard_log.csv format
//! decision_engine.py already writes to, so the Python dashboard and the
//! Qt dashboard both keep working no matter which language's gateway
//! generated the traffic.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::physics::PhysicsVerdict;

pub fn ensure_log_header(path: &str) {
    if !Path::new(path).exists() {
        if let Ok(mut f) = OpenOptions::new().create(true).write(true).open(path) {
            let _ = writeln!(f, "timestamp,verdict,rpm,target_pressure,peak_predicted_pressure,actual_pressure,reason");
        }
    }
}

fn timestamp() -> String {
    // proper UTC calendar timestamp, standard-library only (no chrono
    // dependency) - uses Howard Hinnant's well-known civil_from_days
    // algorithm to convert days-since-epoch into a Y/M/D calendar date.
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    let secs = now.as_secs();
    let days = (secs / 86400) as i64;
    let rem = secs % 86400;
    let (h, m, s) = (rem / 3600, (rem % 3600) / 60, rem % 60);

    let (y, mo, d) = civil_from_days(days);
    format!("{y:04}-{mo:02}-{d:02} {h:02}:{m:02}:{s:02}")
}

/// Howard Hinnant's constant-time algorithm for converting a day count
/// (days since 1970-01-01) into a proleptic Gregorian (year, month, day).
/// http://howardhinnant.github.io/date_algorithms.html#civil_from_days
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; // [0, 399]
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32; // [1, 12]
    let y = if m <= 2 { y + 1 } else { y };
    (y, m, d)
}

pub fn log_verdict(path: &str, verdict: &str, v: &PhysicsVerdict, reason: &str, actual_pressure: Option<f64>) {
    ensure_log_header(path);
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(path) {
        let actual_field = match actual_pressure {
            Some(p) => format!("{p:.2}"),
            None => String::new(),
        };
        let _ = writeln!(
            f,
            "{},{},{},{:.2},{:.2},{},{}",
            timestamp(), verdict, v.rpm, v.target_pressure, v.peak_predicted_pressure, actual_field, reason
        );
    }
}
