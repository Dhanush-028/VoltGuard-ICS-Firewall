//! main.rs - VoltGuard's Rust gateway. Same role as gateway.py (parse,
//! evaluate, forward-or-drop) but this is the one the project plan
//! actually wants in Rust for the sub-10ms inline latency requirement.
//!
//! Runs on port 5040 by default so it can sit alongside the Python
//! gateway (5020) rather than replace it outright - point traffic at
//! whichever one you want to demo, both talk to the same mock_plc.py.
//!
//! Two modes:
//!   voltguard_rs                 -> runs the gateway server
//!   voltguard_rs --benchmark     -> measures pure decision latency,
//!                                   no network involved, proving the
//!                                   actual computation is nowhere near
//!                                   the 10ms budget
//!
//! Honesty note (read the README before quoting a number from this):
//! the sub-microsecond figure below is the *decision computation* alone.
//! End-to-end socket latency (client -> gateway -> PLC -> back) is a
//! different, larger number, dominated by OS network stack overhead, not
//! by this code - and that's the number that actually matters for a real
//! deployment. Both are measured and reported separately for that reason.

mod protocol;
mod physics;
mod logging;

use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::Instant;

use physics::PhysicsConfig;
use protocol::{build_exception_response, parse_frame, parse_response, ResponseOutcome};

const PLC_HOST: &str = "127.0.0.1";
const PLC_PORT: u16 = 5021;
const DEFAULT_GATEWAY_PORT: u16 = 15040;
const LOG_PATH: &str = "voltguard_log.csv";
const CONFIG_PATH: &str = "voltguard.conf";

fn gateway_port() -> u16 {
    env::var("VOLTGUARD_GATEWAY_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(DEFAULT_GATEWAY_PORT)
}

fn forward_to_plc(raw: &[u8]) -> std::io::Result<Vec<u8>> {
    let mut plc = TcpStream::connect((PLC_HOST, PLC_PORT))?;
    plc.write_all(raw)?;
    let mut buf = [0u8; 256];
    let n = plc.read(&mut buf)?;
    Ok(buf[..n].to_vec())
}

fn handle_client(mut conn: TcpStream, cfg: PhysicsConfig, verbose: bool) {
    let mut buf = [0u8; 256];
    loop {
        let n = match conn.read(&mut buf) {
            Ok(0) => return, // client closed
            Ok(n) => n,
            Err(_) => return,
        };
        let raw = &buf[..n];

        let start = Instant::now();
        let parsed = match parse_frame(raw) {
            Ok(p) => p,
            Err(e) => {
                if verbose {
                    println!("[GATEWAY-RS] malformed frame: {e}");
                }
                return;
            }
        };

        let verdict = physics::evaluate_command(&cfg, parsed.rpm as i64, 0.0);
        let decision_elapsed = start.elapsed();

        if verdict.catastrophic {
            let reason = if verdict.impossible_state {
                "physically impossible sensor reading - rejected regardless of command"
            } else {
                "predicted peak exceeds safety limit"
            };
            logging::log_verdict(LOG_PATH, "DROP", &verdict, reason, None);
            if verbose {
                println!(
                    "[GATEWAY-RS] DROP  rpm={:>6}  predicted={:>9.1} psi  decision={:>6.1}us  -> ALARM, never reached PLC",
                    verdict.rpm, verdict.peak_predicted_pressure, decision_elapsed.as_secs_f64() * 1_000_000.0
                );
            }
            let exc = build_exception_response(parsed.transaction_id, parsed.unit_id);
            let _ = conn.write_all(&exc);
        } else {
            let socket_start = Instant::now();
            match forward_to_plc(raw) {
                Ok(reply) => {
                    let round_trip = socket_start.elapsed();
                    let actual_pressure = match parse_response(&reply) {
                        Ok(ResponseOutcome::Ok { actual_pressure, .. }) => actual_pressure,
                        _ => None,
                    };
                    logging::log_verdict(LOG_PATH, "ALLOW", &verdict, "within physical safety envelope", actual_pressure);
                    if verbose {
                        let actual_str = actual_pressure
                            .map(|p| format!("{p:.1} psi"))
                            .unwrap_or_else(|| "n/a".to_string());
                        println!(
                            "[GATEWAY-RS] ALLOW rpm={:>6}  predicted={:>9.1} psi  actual={:>9}  decision={:>6.1}us  plc_round_trip={:>6.1}ms",
                            verdict.rpm, verdict.peak_predicted_pressure, actual_str,
                            decision_elapsed.as_secs_f64() * 1_000_000.0,
                            round_trip.as_secs_f64() * 1000.0
                        );
                    }
                    let _ = conn.write_all(&reply);
                }
                Err(e) => {
                    if verbose {
                        println!("[GATEWAY-RS] could not reach PLC: {e}");
                    }
                    return;
                }
            }
        }
    }
}

fn run_server() {
    let cfg = PhysicsConfig::load_or_default(CONFIG_PATH);
    let port = gateway_port();
    println!("[GATEWAY-RS] VoltGuard Rust gateway listening on {PLC_HOST}:{port}");
    println!("[GATEWAY-RS] forwarding safe traffic to PLC at {PLC_HOST}:{PLC_PORT}");
    println!("[GATEWAY-RS] physics config: k_pump={} tau={} limit={} psi",
             cfg.k_pump, cfg.tau_seconds, cfg.pressure_safe_limit);

    let listener = match TcpListener::bind((PLC_HOST, port)) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("\n[GATEWAY-RS] could not bind to port {port}: {e}");
            eprintln!("[GATEWAY-RS] this is usually Windows itself refusing the port, not a bug -");
            eprintln!("[GATEWAY-RS] Hyper-V/WSL2 often reserves ranges of ports on Windows. Check with:");
            eprintln!("[GATEWAY-RS]   netsh interface ipv4 show excludedportrange protocol=tcp");
            eprintln!("[GATEWAY-RS] then pick a port outside any excluded range and run:");
            eprintln!("[GATEWAY-RS]   $env:VOLTGUARD_GATEWAY_PORT=\"<port>\"; .\\target\\release\\voltguard_rs.exe\n");
            std::process::exit(1);
        }
    };
    for stream in listener.incoming() {
        if let Ok(conn) = stream {
            let cfg = cfg;
            thread::spawn(move || handle_client(conn, cfg, true));
        }
    }
}

fn run_benchmark() {
    let cfg = PhysicsConfig::load_or_default(CONFIG_PATH);
    let n = 100_000;

    println!("=== pure decision-latency benchmark (n={n}, no network) ===\n");

    for _ in 0..1000 {
        std::hint::black_box(physics::evaluate_command(&cfg, 2800, 0.0));
    }

    let mut samples = Vec::with_capacity(n);
    for i in 0..n {
        let rpm = 500 + (i % 60000) as i64;
        let start = Instant::now();
        let v = physics::evaluate_command(&cfg, rpm, 0.0);
        std::hint::black_box(v);
        samples.push(start.elapsed().as_nanos() as f64);
    }

    samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let p50 = samples[n / 2];
    let p99 = samples[n * 99 / 100];
    let max = samples[n - 1];
    let mean: f64 = samples.iter().sum::<f64>() / n as f64;

    println!("p50:  {:.0} ns  ({:.4} ms)", p50, p50 / 1_000_000.0);
    println!("p99:  {:.0} ns  ({:.4} ms)", p99, p99 / 1_000_000.0);
    println!("max:  {:.0} ns  ({:.4} ms)", max, max / 1_000_000.0);
    println!("mean: {:.0} ns  ({:.4} ms)", mean, mean / 1_000_000.0);
    println!("\nrequirement: sub-10ms inline latency");
    println!("p99 is {:.0}x under budget", 10_000_000.0 / p99);
    println!(
        "\nnote: this is the decision computation only. end-to-end socket\n\
         round-trip latency (the number that matters for a real deployment)\n\
         is measured separately by the running gateway server and printed\n\
         per-command as plc_round_trip - see README for both numbers together."
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() > 1 && args[1] == "--benchmark" {
        run_benchmark();
    } else {
        run_server();
    }
}
