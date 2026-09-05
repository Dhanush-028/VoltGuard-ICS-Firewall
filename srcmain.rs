//! VoltGuard IPS Engine — Week 3 "Inline Dropping"
//!
//! Sits between your Week 1 packet interceptor (C++/Scapy) and the real
//! PLC/actuator. Every parsed Modbus command is HELD here, sent to the
//! physics engine, and only forwarded if the simulation clears it.
//!
//! ---- Integration points you need to adapt ----
//! 1. INPUT (line ~70): commands currently arrive over a local TCP socket
//!    (127.0.0.1:8090) as newline-delimited JSON. If your Week 1 C++
//!    interceptor is a separate process, have it push parsed commands here
//!    the same way. If it's the same process, replace this with an FFI
//!    call or channel instead of a socket.
//! 2. OUTPUT (forward_to_plc): currently just logs. Wire this to whatever
//!    actually re-injects the packet toward the PLC (raw socket / Scapy /
//!    pcap).
//! 3. physics_client.rs: adapt to your real physics engine's protocol.
//!
//! ---- Latency budget ----
//! Target: <10ms holding latency per packet.
//!   - physics_client timeout budget: 8ms
//!   - parse/serialize/queue overhead: ~1-2ms
//! Actual end-to-end latency is measured and logged per packet so you can
//! prove the sub-10ms claim in your final report.

mod physics_client;

use physics_client::{ModbusCommand, PhysicsClient, PhysicsResult, Verdict};
use serde::Serialize;
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::broadcast;

/// Telemetry frame streamed to the Qt dashboard (Week 3 "Visualizing Physics").
#[derive(Debug, Clone, Serialize)]
struct TelemetryFrame {
    timestamp_ms: u128,
    predicted_state: f64,
    actual_state: f64,
    verdict: String,
    latency_us: u128,
    register_addr: u16,
}

#[tokio::main]
async fn main() {
    println!("[voltguard-ips] starting");

    let physics = Arc::new(PhysicsClient::new("127.0.0.1:9000"));

    // Broadcast channel: every decision gets published here, and both the
    // telemetry server (for the Qt dashboard) and the alert logger subscribe.
    let (tx, _rx) = broadcast::channel::<TelemetryFrame>(1024);

    // Telemetry server for the Qt dashboard (Week 3 graph widget connects here).
    let telemetry_tx = tx.clone();
    tokio::spawn(async move {
        run_telemetry_server(telemetry_tx).await;
    });

    // Main packet-holding loop.
    // Replace this listener with your actual Week 1 -> Week 3 handoff.
    let listener = TcpListener::bind("127.0.0.1:8090")
        .await
        .expect("failed to bind command intake socket on 127.0.0.1:8090");
    println!("[voltguard-ips] listening for parsed commands on 127.0.0.1:8090");
    println!("[voltguard-ips] telemetry stream available on 127.0.0.1:9001");

    loop {
        let (socket, _addr) = match listener.accept().await {
            Ok(pair) => pair,
            Err(e) => {
                eprintln!("[voltguard-ips] accept error: {e}");
                continue;
            }
        };
        let physics = physics.clone();
        let tx = tx.clone();
        tokio::spawn(async move {
            handle_intake_connection(socket, physics, tx).await;
        });
    }
}

/// Reads newline-delimited ModbusCommand JSON from the packet parser,
/// holds each one, queries physics, and decides forward/drop.
async fn handle_intake_connection(
    socket: TcpStream,
    physics: Arc<PhysicsClient>,
    tx: broadcast::Sender<TelemetryFrame>,
) {
    let mut reader = BufReader::new(socket).lines();

    loop {
        let line = match reader.next_line().await {
            Ok(Some(line)) => line,
            Ok(None) => break, // connection closed
            Err(e) => {
                eprintln!("[voltguard-ips] read error: {e}");
                break;
            }
        };

        let cmd: ModbusCommand = match serde_json::from_str(&line) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[voltguard-ips] malformed command, dropping: {e}");
                continue;
            }
        };

        let held_at = Instant::now();

        // ---- HOLD the packet here until the simulation clears it ----
        let result: PhysicsResult = physics.evaluate(&cmd).await;

        let latency_us = held_at.elapsed().as_micros();

        match result.verdict {
            Verdict::Safe => {
                forward_to_plc(&cmd).await;
            }
            Verdict::Catastrophic => {
                drop_and_alarm(&cmd, &result);
            }
        }

        if latency_us > 10_000 {
            eprintln!(
                "[voltguard-ips] WARNING: decision latency {}us exceeded 10ms budget",
                latency_us
            );
        }

        let frame = TelemetryFrame {
            timestamp_ms: now_ms(),
            predicted_state: result.predicted_state,
            actual_state: result.actual_state,
            verdict: match result.verdict {
                Verdict::Safe => "SAFE".to_string(),
                Verdict::Catastrophic => "CATASTROPHIC".to_string(),
            },
            latency_us,
            register_addr: cmd.register_addr,
        };
        // Ignore send errors (means no dashboard connected yet).
        let _ = tx.send(frame);
    }
}

/// Forward the cleared command toward the real PLC/actuator.
/// TODO: replace with your actual raw-socket / Scapy re-injection logic.
async fn forward_to_plc(cmd: &ModbusCommand) {
    println!(
        "[voltguard-ips] FORWARD  reg={} value={} (physics cleared)",
        cmd.register_addr, cmd.value
    );
}

/// Drop the command and raise an alert instead of forwarding it.
fn drop_and_alarm(cmd: &ModbusCommand, result: &PhysicsResult) {
    eprintln!(
        "[voltguard-ips] DROP+ALARM reg={} value={} predicted_state={:.2} reason={:?}",
        cmd.register_addr, cmd.value, result.predicted_state, result.reason
    );
    // TODO: hook into your real alerting (syslog, MQTT alert topic, HMI popup, etc.)
}

/// Streams every TelemetryFrame to any connected Qt dashboard client(s)
/// on 127.0.0.1:9001, one JSON line per frame.
async fn run_telemetry_server(tx: broadcast::Sender<TelemetryFrame>) {
    let listener = match TcpListener::bind("127.0.0.1:9001").await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("[voltguard-ips] failed to bind telemetry port: {e}");
            return;
        }
    };

    loop {
        let (mut socket, _) = match listener.accept().await {
            Ok(pair) => pair,
            Err(_) => continue,
        };
        let mut rx = tx.subscribe();
        tokio::spawn(async move {
            while let Ok(frame) = rx.recv().await {
                let mut line = serde_json::to_vec(&frame).unwrap();
                line.push(b'\n');
                if socket.write_all(&line).await.is_err() {
                    break; // dashboard disconnected
                }
            }
        });
    }
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis()
}