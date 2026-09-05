//! physics_client.rs
//!
//! Thin async client that talks to your Week 2 physics engine (Python/OpenModelica).
//!
//! ADAPT THIS FILE to match however your Week 1-2 engine is actually exposed.
//! Right now it assumes the physics engine is a small TCP/JSON service on
//! 127.0.0.1:9000 (e.g. a lightweight Python `socketserver` or Flask app
//! wrapping your OpenModelica model). If your engine instead exposes a
//! Python C-extension, a REST endpoint, or a named pipe, only this file
//! needs to change -- main.rs doesn't care how evaluate() gets its answer.

use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::timeout;

/// Mirrors whatever your Week 1 parser hands off per Modbus/DNP3 command.
/// Extend fields to match your actual parser's struct.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModbusCommand {
    pub function_code: u8,
    pub register_addr: u16,
    pub value: i32,
    pub timestamp_ms: u128,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Verdict {
    Safe,
    Catastrophic,
}

/// What the physics engine returns: its verdict plus the state values
/// the dashboard needs to plot (predicted vs. actual).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PhysicsResult {
    pub verdict: Verdict,
    pub predicted_state: f64, // e.g. predicted pressure/valve RPM after applying the command
    pub actual_state: f64,    // current measured state before the command is applied
    pub reason: Option<String>,
}

#[derive(Debug, Serialize)]
struct PhysicsRequest<'a> {
    function_code: u8,
    register_addr: u16,
    value: i32,
    // helps your engine correlate replies if you pipeline requests
    id: &'a str,
}

pub struct PhysicsClient {
    engine_addr: String,
    /// Hard budget for the round trip. Total IPS decision budget is 10ms;
    /// we reserve a slice of that for parsing/queueing overhead.
    pub timeout_budget: Duration,
}

impl PhysicsClient {
    pub fn new(engine_addr: impl Into<String>) -> Self {
        Self {
            engine_addr: engine_addr.into(),
            timeout_budget: Duration::from_millis(8),
        }
    }

    /// Sends a command to the physics engine and awaits a verdict.
    /// On timeout or connection failure we fail CLOSED (treat as Catastrophic)
    /// -- for a safety system, "drop when unsure" is the correct default,
    /// never "forward when unsure".
    pub async fn evaluate(&self, cmd: &ModbusCommand) -> PhysicsResult {
        match timeout(self.timeout_budget, self.evaluate_inner(cmd)).await {
            Ok(Ok(result)) => result,
            Ok(Err(e)) => Self::fail_closed(format!("engine error: {e}")),
            Err(_) => Self::fail_closed("physics engine timeout (>8ms budget)".to_string()),
        }
    }

    async fn evaluate_inner(&self, cmd: &ModbusCommand) -> std::io::Result<PhysicsResult> {
        let mut stream = TcpStream::connect(&self.engine_addr).await?;

        let req = PhysicsRequest {
            function_code: cmd.function_code,
            register_addr: cmd.register_addr,
            value: cmd.value,
            id: "voltguard",
        };
        let mut payload = serde_json::to_vec(&req).unwrap();
        payload.push(b'\n'); // engine should read newline-delimited JSON
        stream.write_all(&payload).await?;

        let mut buf = vec![0u8; 4096];
        let n = stream.read(&mut buf).await?;
        let result: PhysicsResult = serde_json::from_slice(&buf[..n])?;
        Ok(result)
    }

    fn fail_closed(reason: String) -> PhysicsResult {
        PhysicsResult {
            verdict: Verdict::Catastrophic,
            predicted_state: f64::NAN,
            actual_state: f64::NAN,
            reason: Some(reason),
        }
    }
}