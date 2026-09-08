//! protocol.rs - Modbus/TCP framing, byte-for-byte identical to protocol.py
//! and modbus_parser.cpp. Three languages, one wire format - that's the
//! actual proof this is a real protocol, not three incompatible toys.

pub const FUNC_WRITE_SINGLE_REGISTER: u8 = 0x06;
pub const EXCEPTION_BIT: u8 = 0x80;
pub const EXC_SERVER_DEVICE_FAILURE: u8 = 0x04;
pub const PUMP_RPM_REGISTER: u16 = 0x0001;

#[derive(Debug, Clone, Copy)]
pub struct ParsedFrame {
    pub transaction_id: u16,
    pub unit_id: u8,
    pub function_code: u8,
    pub register_addr: u16,
    pub rpm: u16,
}

#[allow(dead_code)] // used by tests; kept public for a future Rust traffic-generator utility
pub fn build_write_register_command(txn_id: u16, unit_id: u8, rpm: u16) -> Vec<u8> {
    let mut pdu = Vec::with_capacity(5);
    pdu.push(FUNC_WRITE_SINGLE_REGISTER);
    pdu.extend_from_slice(&PUMP_RPM_REGISTER.to_be_bytes());
    pdu.extend_from_slice(&rpm.to_be_bytes());

    let length: u16 = (pdu.len() + 1) as u16; // +1 for unit_id

    let mut frame = Vec::with_capacity(7 + pdu.len());
    frame.extend_from_slice(&txn_id.to_be_bytes());
    frame.extend_from_slice(&0u16.to_be_bytes()); // protocol_id
    frame.extend_from_slice(&length.to_be_bytes());
    frame.push(unit_id);
    frame.extend_from_slice(&pdu);
    frame
}

#[allow(dead_code)] // kept for parity/completeness with protocol.py and modbus_parser.cpp,
                     // even though this gateway currently relays the real PLC's own reply
pub fn build_success_response(txn_id: u16, unit_id: u8, reg_addr: u16, reg_value: u16) -> Vec<u8> {
    let mut pdu = Vec::with_capacity(5);
    pdu.push(FUNC_WRITE_SINGLE_REGISTER);
    pdu.extend_from_slice(&reg_addr.to_be_bytes());
    pdu.extend_from_slice(&reg_value.to_be_bytes());
    let length = (pdu.len() + 1) as u16;

    let mut frame = Vec::with_capacity(7 + pdu.len());
    frame.extend_from_slice(&txn_id.to_be_bytes());
    frame.extend_from_slice(&0u16.to_be_bytes());
    frame.extend_from_slice(&length.to_be_bytes());
    frame.push(unit_id);
    frame.extend_from_slice(&pdu);
    frame
}

pub fn build_exception_response(txn_id: u16, unit_id: u8) -> Vec<u8> {
    let pdu = vec![FUNC_WRITE_SINGLE_REGISTER | EXCEPTION_BIT, EXC_SERVER_DEVICE_FAILURE];
    let length = (pdu.len() + 1) as u16;

    let mut frame = Vec::with_capacity(7 + pdu.len());
    frame.extend_from_slice(&txn_id.to_be_bytes());
    frame.extend_from_slice(&0u16.to_be_bytes());
    frame.extend_from_slice(&length.to_be_bytes());
    frame.push(unit_id);
    frame.extend_from_slice(&pdu);
    frame
}

#[derive(Debug)]
pub enum ParseError {
    TooShort,
    BadProtocolId(u16),
    LengthMismatch,
    UnsupportedFunctionCode(u8),
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            ParseError::TooShort => write!(f, "frame too short to be a valid Modbus/TCP ADU"),
            ParseError::BadProtocolId(p) => write!(f, "unexpected protocol_id {p}, expected 0"),
            ParseError::LengthMismatch => write!(f, "length field doesn't match actual payload size"),
            ParseError::UnsupportedFunctionCode(fc) => write!(f, "unsupported function code 0x{fc:02x}"),
        }
    }
}

pub fn parse_frame(raw: &[u8]) -> Result<ParsedFrame, ParseError> {
    if raw.len() < 8 {
        return Err(ParseError::TooShort);
    }

    let transaction_id = u16::from_be_bytes([raw[0], raw[1]]);
    let protocol_id = u16::from_be_bytes([raw[2], raw[3]]);
    let length = u16::from_be_bytes([raw[4], raw[5]]);
    let unit_id = raw[6];

    if protocol_id != 0 {
        return Err(ParseError::BadProtocolId(protocol_id));
    }

    let pdu_size = raw.len() - 7;
    if pdu_size != (length as usize).wrapping_sub(1) {
        return Err(ParseError::LengthMismatch);
    }

    let function_code = raw[7];
    if function_code != FUNC_WRITE_SINGLE_REGISTER {
        return Err(ParseError::UnsupportedFunctionCode(function_code));
    }

    let register_addr = u16::from_be_bytes([raw[8], raw[9]]);
    let rpm = u16::from_be_bytes([raw[10], raw[11]]);

    Ok(ParsedFrame { transaction_id, unit_id, function_code, register_addr, rpm })
}

#[derive(Debug)]
pub enum ResponseOutcome {
    Ok { rpm: u16, actual_pressure: Option<f64> },
    Exception { exception_code: u8 },
}

/// Parses whatever comes back from the PLC - success echo (optionally with
/// actual-pressure telemetry appended) or a Modbus exception response.
pub fn parse_response(raw: &[u8]) -> Result<ResponseOutcome, ParseError> {
    if raw.len() < 8 {
        return Err(ParseError::TooShort);
    }
    let pdu = &raw[7..];
    let func_code = pdu[0];

    if func_code & EXCEPTION_BIT != 0 {
        return Ok(ResponseOutcome::Exception { exception_code: pdu[1] });
    }

    let rpm = u16::from_be_bytes([pdu[3], pdu[4]]);
    let actual_pressure = if pdu.len() >= 7 {
        let actual_x10 = u16::from_be_bytes([pdu[5], pdu[6]]);
        Some(actual_x10 as f64 / 10.0)
    } else {
        None
    };
    Ok(ResponseOutcome::Ok { rpm, actual_pressure })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_matches_python_frame() {
        // this exact hex was produced by protocol.py for txn_id=1, unit_id=1,
        // register_addr=1, rpm=2800 - same parity check used for the C++ parser
        let known_good = hex_decode("000100000006010600010af0");
        let parsed = parse_frame(&known_good).expect("should parse");
        assert_eq!(parsed.transaction_id, 1);
        assert_eq!(parsed.unit_id, 1);
        assert_eq!(parsed.register_addr, 1);
        assert_eq!(parsed.rpm, 2800);
    }

    #[test]
    fn build_then_parse_round_trip() {
        let raw = build_write_register_command(42, 1, 50000);
        let parsed = parse_frame(&raw).expect("should parse");
        assert_eq!(parsed.transaction_id, 42);
        assert_eq!(parsed.rpm, 50000);
    }

    #[test]
    fn rejects_short_frame() {
        assert!(matches!(parse_frame(&[0x00, 0x01, 0x02]), Err(ParseError::TooShort)));
    }

    fn hex_decode(s: &str) -> Vec<u8> {
        (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
    }
}
