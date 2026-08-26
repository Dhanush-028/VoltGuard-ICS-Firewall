# VoltGuard — Week 1 Deliverables

Parses mock Modbus/TCP traffic in C++, generates normal/malicious industrial
commands, and builds a baseline fluid/pressure physics model.

## Structure

voltguard/
├── traffic_gen/       # generates Modbus/TCP frames (traffic.bin, traffic_log.csv)
├── parser/             # C++ parser: decodes MBAP header + PDU
└── physics_engine/     # pump+pipe pressure model (pipe_model.py)

## Run it

cd traffic_gen && python3 generate_traffic.py
cd ../parser && g++ -std=c++17 -O2 -Wall -o modbus_parser modbus_parser.cpp
./modbus_parser ../traffic_gen/traffic.bin
cd ../physics_engine && python3 pipe_model.py

## What it does

- **Traffic generator**: builds real Modbus/TCP frames byte-for-byte, mixing
  normal pump commands with a "valid but physically insane" 50,000 RPM attack.
- **Parser**: decodes MBAP + PDU by hand, flags commands against a hardcoded
  RPM ceiling. Caught all 3 malicious frames, zero false positives.
- **Physics engine**: models pump affinity laws + Darcy-Weisbach friction loss
  to classify RPM as SAFE / WARNING / CATASTROPHIC.

**Key finding:** the parser's hardcoded ceiling (3000 RPM) doesn't match the
physics-derived real ceiling (~4450 RPM) — proving rule-based limits are a
guess, while physics simulation gives the real answer.

## Next (Week 2)

- Wire the C++ parser into the physics model per-command instead of a fixed ceiling
- Extend physics to multi-segment pipes
- Add more Modbus function codes (e.g. Read Holding Registers)