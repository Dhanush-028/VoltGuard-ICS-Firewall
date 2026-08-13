// modbus_parser.cpp - VoltGuard's C++ Modbus/TCP parser, per the project
// PDF's literal Week 1 requirement: "Build a C++ script to parse mock
// Modbus/TCP traffic. Create a script generating normal and malicious
// industrial commands."
//
// Same wire format as protocol.py (the Python side): a 7-byte MBAP header
// (transaction id, protocol id, length, unit id) followed by a function
// code 0x06 (Write Single Register) PDU carrying the commanded pump RPM.
// Deliberately kept to the C++ standard library only - no Qt, no external
// deps - so it compiles anywhere with just g++.
//
// Build (MinGW on Windows, using the g++ that ships with Qt Creator or
// any other MinGW install):
//   g++ -std=c++17 -O2 modbus_parser.cpp -o modbus_parser.exe
//
// Build (Linux/macOS):
//   g++ -std=c++17 -O2 modbus_parser.cpp -o modbus_parser
//
// Run with no arguments for the built-in self-test (round-trip generation/
// parsing + a parity check against a known-good frame produced by the
// Python side), or pass a hex string to decode an arbitrary frame:
//   ./modbus_parser --hex 0001000000060106000B0AF0

#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace modbus {

constexpr uint8_t FUNC_WRITE_SINGLE_REGISTER = 0x06;
constexpr uint16_t PUMP_RPM_REGISTER = 0x0001;

struct ParsedFrame {
    uint16_t transaction_id;
    uint16_t protocol_id;
    uint8_t unit_id;
    uint8_t function_code;
    uint16_t register_addr;
    uint16_t rpm;
};

// simple big-endian helpers - Modbus/TCP is big-endian on the wire,
// same as struct.pack(">...") on the Python side
void push_u16(std::vector<uint8_t> &buf, uint16_t v) {
    buf.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    buf.push_back(static_cast<uint8_t>(v & 0xFF));
}

uint16_t read_u16(const std::vector<uint8_t> &buf, size_t offset) {
    return static_cast<uint16_t>((buf[offset] << 8) | buf[offset + 1]);
}

class FrameBuilder {
public:
    std::vector<uint8_t> build_write_register_command(uint16_t rpm, uint8_t unit_id = 1) {
        uint16_t txn_id = next_txn_id();

        std::vector<uint8_t> pdu;
        pdu.push_back(FUNC_WRITE_SINGLE_REGISTER);
        push_u16(pdu, PUMP_RPM_REGISTER);
        push_u16(pdu, rpm);

        uint16_t length = static_cast<uint16_t>(pdu.size() + 1); // +1 for unit_id

        std::vector<uint8_t> frame;
        push_u16(frame, txn_id);
        push_u16(frame, 0); // protocol_id
        push_u16(frame, length);
        frame.push_back(unit_id);
        frame.insert(frame.end(), pdu.begin(), pdu.end());
        return frame;
    }

private:
    uint16_t txn_counter = 0;
    uint16_t next_txn_id() { return ++txn_counter; }
};

ParsedFrame parse_frame(const std::vector<uint8_t> &raw) {
    if (raw.size() < 8) {
        throw std::runtime_error("frame too short to be a valid Modbus/TCP ADU");
    }

    ParsedFrame f{};
    f.transaction_id = read_u16(raw, 0);
    f.protocol_id = read_u16(raw, 2);
    uint16_t length = read_u16(raw, 4);
    f.unit_id = raw[6];

    if (f.protocol_id != 0) {
        std::ostringstream msg;
        msg << "unexpected protocol_id " << f.protocol_id << ", expected 0";
        throw std::runtime_error(msg.str());
    }

    size_t pdu_size = raw.size() - 7;
    if (pdu_size != static_cast<size_t>(length - 1)) {
        throw std::runtime_error("length field doesn't match actual payload size");
    }

    f.function_code = raw[7];
    if (f.function_code != FUNC_WRITE_SINGLE_REGISTER) {
        std::ostringstream msg;
        msg << "unsupported function code 0x" << std::hex << static_cast<int>(f.function_code);
        throw std::runtime_error(msg.str());
    }

    f.register_addr = read_u16(raw, 8);
    f.rpm = read_u16(raw, 10);
    return f;
}

std::string to_hex(const std::vector<uint8_t> &raw) {
    std::ostringstream ss;
    for (uint8_t b : raw) {
        ss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(b);
    }
    return ss.str();
}

std::vector<uint8_t> from_hex(const std::string &hex) {
    std::vector<uint8_t> out;
    for (size_t i = 0; i + 1 < hex.size(); i += 2) {
        out.push_back(static_cast<uint8_t>(std::stoi(hex.substr(i, 2), nullptr, 16)));
    }
    return out;
}

// --- traffic generators, matching protocol.py's ranges exactly ---
std::mt19937 &rng() {
    static std::mt19937 gen(std::random_device{}());
    return gen;
}

std::vector<uint8_t> generate_normal_command(FrameBuilder &fb) {
    std::uniform_int_distribution<int> dist(500, 2800);
    return fb.build_write_register_command(static_cast<uint16_t>(dist(rng())));
}

std::vector<uint8_t> generate_malicious_command(FrameBuilder &fb) {
    std::uniform_int_distribution<int> choice(0, 2);
    uint16_t rpm;
    switch (choice(rng())) {
        case 0: { std::uniform_int_distribution<int> d(15000, 30000); rpm = static_cast<uint16_t>(d(rng())); break; }
        case 1: { rpm = 50000; break; } // the exact scenario from the problem statement
        default: { std::uniform_int_distribution<int> d(40000, 65535); rpm = static_cast<uint16_t>(d(rng())); break; }
    }
    return fb.build_write_register_command(rpm);
}

void print_parsed(const ParsedFrame &f) {
    std::cout << "  transaction_id=" << f.transaction_id
              << "  unit_id=" << static_cast<int>(f.unit_id)
              << "  function_code=0x" << std::hex << static_cast<int>(f.function_code) << std::dec
              << "  register_addr=" << f.register_addr
              << "  rpm=" << f.rpm << "\n";
}

} // namespace modbus

// ---------------------------------------------------------------------
// self-test / demo
// ---------------------------------------------------------------------
int run_self_test() {
    using namespace modbus;
    FrameBuilder fb;
    int failures = 0;

    std::cout << "=== round-trip test: normal commands ===\n";
    for (int i = 0; i < 5; ++i) {
        auto raw = generate_normal_command(fb);
        auto parsed = parse_frame(raw);
        std::cout << to_hex(raw) << " ->\n";
        print_parsed(parsed);
        if (parsed.rpm < 500 || parsed.rpm > 2800) {
            std::cout << "  FAIL: rpm out of expected normal range\n";
            failures++;
        }
    }

    std::cout << "\n=== round-trip test: malicious commands ===\n";
    for (int i = 0; i < 5; ++i) {
        auto raw = generate_malicious_command(fb);
        auto parsed = parse_frame(raw);
        std::cout << to_hex(raw) << " ->\n";
        print_parsed(parsed);
        if (parsed.rpm < 15000) {
            std::cout << "  FAIL: rpm not in malicious range\n";
            failures++;
        }
    }

    std::cout << "\n=== parity check against Python-generated frame ===\n";
    // this exact hex was produced by the Python side (protocol.py) for
    // transaction_id=1, unit_id=1, register_addr=1, rpm=2800 (0x0AF0) -
    // proves the two implementations agree on the wire format byte for
    // byte, not just "each works on its own."
    std::string known_good_hex = "00010000000601060001" "0AF0";
    auto raw = from_hex(known_good_hex);
    try {
        auto parsed = parse_frame(raw);
        print_parsed(parsed);
        bool ok = parsed.transaction_id == 1 && parsed.unit_id == 1 &&
                  parsed.register_addr == 1 && parsed.rpm == 2800;
        std::cout << (ok ? "  PASS: matches Python-generated frame exactly\n"
                          : "  FAIL: fields don't match expected values\n");
        if (!ok) failures++;
    } catch (const std::exception &e) {
        std::cout << "  FAIL: " << e.what() << "\n";
        failures++;
    }

    std::cout << "\n=== malformed frame handling ===\n";
    try {
        parse_frame({0x00, 0x01, 0x02}); // too short
        std::cout << "  FAIL: should have thrown on short frame\n";
        failures++;
    } catch (const std::exception &e) {
        std::cout << "  correctly rejected: " << e.what() << "\n";
    }

    std::cout << "\n--- " << (failures == 0 ? "ALL CHECKS PASSED" : "FAILURES DETECTED") << " ---\n";
    return failures == 0 ? 0 : 1;
}

int main(int argc, char *argv[]) {
    using namespace modbus;

    if (argc >= 3 && std::string(argv[1]) == "--hex") {
        try {
            auto raw = from_hex(argv[2]);
            auto parsed = parse_frame(raw);
            std::cout << "parsed frame:\n";
            print_parsed(parsed);
            return 0;
        } catch (const std::exception &e) {
            std::cerr << "error: " << e.what() << "\n";
            return 1;
        }
    }

    return run_self_test();
}
