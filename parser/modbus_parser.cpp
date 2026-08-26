/*
 * VoltGuard - Week 1 - Packet Interceptor / Protocol Parser
 * ============================================================
 * A low-level parser for raw Modbus/TCP frames.
 *
 * This is the C++ half of Week 1. It reads length-prefixed frames from
 * traffic.bin (produced by generate_traffic.py), parses the Modbus/TCP
 * MBAP header + PDU by hand (byte-level, big-endian, no external libs),
 * and prints a structured decode of each command.
 *
 * This deliberately does NOT do the "physics firewall" logic yet -
 * that's the Decision Engine (Rust) + Physics Engine (Python), coming
 * in later weeks. Week 1's job is just: can we reliably rip apart raw
 * bytes into meaningful ICS commands? That's the foundation everything
 * else builds on.
 *
 * Build:
 *   g++ -std=c++17 -O2 -o modbus_parser modbus_parser.cpp
 * Run:
 *   ./modbus_parser ../traffic_gen/traffic.bin
 */

#include <iostream>
#include <fstream>
#include <vector>
#include <cstdint>
#include <iomanip>
#include <stdexcept>

// ---- Modbus function codes we understand (extend as needed) ----
enum class FunctionCode : uint8_t {
    WriteSingleRegister = 0x06,
    ReadHoldingRegisters = 0x03,
    Unknown = 0xFF
};

// ---- Physical safety context (mirrors the Python physics model's
//      limits so the parser can flag obviously dangerous commands
//      even before the real Physics Engine is wired in) ----
constexpr uint16_t PUMP_SPEED_REGISTER = 0x0001;
constexpr uint16_t SAFE_MAX_RPM = 3000;

struct ModbusTcpFrame {
    uint16_t transaction_id;
    uint16_t protocol_id;
    uint16_t length;
    uint8_t  unit_id;
    uint8_t  function_code;
    uint16_t register_addr;
    uint16_t register_value;
};

// Reads a big-endian uint16 from a byte buffer at offset `pos`.
static uint16_t read_u16_be(const std::vector<uint8_t>& buf, size_t pos) {
    if (pos + 2 > buf.size()) {
        throw std::runtime_error("Truncated frame: not enough bytes for uint16");
    }
    return (static_cast<uint16_t>(buf[pos]) << 8) | buf[pos + 1];
}

// Reads a big-endian uint32 from a byte buffer at offset `pos`.
static uint32_t read_u32_be(const std::vector<uint8_t>& buf, size_t pos) {
    if (pos + 4 > buf.size()) {
        throw std::runtime_error("Truncated frame: not enough bytes for uint32");
    }
    return (static_cast<uint32_t>(buf[pos]) << 24) |
           (static_cast<uint32_t>(buf[pos + 1]) << 16) |
           (static_cast<uint32_t>(buf[pos + 2]) << 8) |
           static_cast<uint32_t>(buf[pos + 3]);
}

// Parses a single raw Modbus/TCP frame (MBAP header + PDU).
// Throws std::runtime_error on malformed input - a real-world SCADA
// bridge needs to be defensive about this since attackers may also
// send malformed frames to crash naive parsers.
ModbusTcpFrame parse_modbus_tcp_frame(const std::vector<uint8_t>& buf) {
    if (buf.size() < 8) {
        throw std::runtime_error("Frame too short to contain MBAP header + function code");
    }

    ModbusTcpFrame frame{};
    frame.transaction_id = read_u16_be(buf, 0);
    frame.protocol_id    = read_u16_be(buf, 2);
    frame.length         = read_u16_be(buf, 4);
    frame.unit_id        = buf[6];
    frame.function_code  = buf[7];

    if (frame.protocol_id != 0x0000) {
        throw std::runtime_error("Invalid protocol ID (expected 0x0000 for Modbus)");
    }

    // We only handle Write Single Register (0x06) for now.
    if (frame.function_code == static_cast<uint8_t>(FunctionCode::WriteSingleRegister)) {
        if (buf.size() < 12) {
            throw std::runtime_error("Frame too short for Write Single Register PDU");
        }
        frame.register_addr  = read_u16_be(buf, 8);
        frame.register_value = read_u16_be(buf, 10);
    } else {
        frame.register_addr = 0;
        frame.register_value = 0;
    }

    return frame;
}

// A crude first-pass physical sanity check. Real logic belongs in the
// Rust Decision Engine talking to the Python physics simulation, but
// even the parser layer can catch "obviously impossible" values fast.
static std::string quick_physical_assessment(const ModbusTcpFrame& f) {
    if (f.function_code == static_cast<uint8_t>(FunctionCode::WriteSingleRegister) &&
        f.register_addr == PUMP_SPEED_REGISTER) {
        if (f.register_value > SAFE_MAX_RPM) {
            return "SUSPICIOUS (exceeds safe RPM ceiling)";
        }
        return "OK";
    }
    return "N/A";
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <traffic.bin>\n";
        return 1;
    }

    std::ifstream file(argv[1], std::ios::binary);
    if (!file) {
        std::cerr << "Could not open file: " << argv[1] << "\n";
        return 1;
    }

    int total = 0, suspicious = 0, malformed = 0;

    std::cout << std::left
              << std::setw(6)  << "Txn"
              << std::setw(10) << "FuncCode"
              << std::setw(10) << "RegAddr"
              << std::setw(10) << "Value"
              << std::setw(28) << "Assessment"
              << "\n";
    std::cout << std::string(64, '-') << "\n";

    while (file) {
        // Read the 4-byte length prefix written by generate_traffic.py
        std::vector<uint8_t> len_buf(4);
        file.read(reinterpret_cast<char*>(len_buf.data()), 4);
        if (file.gcount() < 4) break;  // clean EOF

        uint32_t frame_len = read_u32_be(len_buf, 0);
        std::vector<uint8_t> frame_buf(frame_len);
        file.read(reinterpret_cast<char*>(frame_buf.data()), frame_len);
        if (static_cast<uint32_t>(file.gcount()) < frame_len) {
            std::cerr << "Warning: truncated frame at end of file, stopping.\n";
            break;
        }

        total++;
        try {
            ModbusTcpFrame f = parse_modbus_tcp_frame(frame_buf);
            std::string assessment = quick_physical_assessment(f);
            if (assessment.substr(0, 10) == "SUSPICIOUS") suspicious++;

            std::cout << std::left
                      << std::setw(6)  << f.transaction_id
                      << "0x" << std::hex << std::setw(8) << static_cast<int>(f.function_code) << std::dec
                      << std::setw(10) << f.register_addr
                      << std::setw(10) << f.register_value
                      << std::setw(28) << assessment
                      << "\n";
        } catch (const std::exception& e) {
            malformed++;
            std::cerr << "Failed to parse frame #" << total << ": " << e.what() << "\n";
        }
    }

    std::cout << std::string(64, '-') << "\n";
    std::cout << "Total frames: " << total
              << " | Suspicious (RPM ceiling): " << suspicious
              << " | Malformed: " << malformed << "\n";

    return 0;
}