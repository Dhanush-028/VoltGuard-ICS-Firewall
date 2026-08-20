\# VoltGuard — Week 1 Deliverables



Week 1 goal (from your plan): parse mock Modbus/TCP traffic in C++, generate

normal/malicious industrial commands, and build a baseline fluid/pressure

physics model.



\## What's here



```

voltguard/

├── traffic\_gen/

│   ├── generate\_traffic.py   # builds real Modbus/TCP frames by hand

│   ├── traffic.bin            # 23 generated frames (20 normal, 3 malicious)

│   └── traffic\_log.csv        # ground-truth answer key for each frame

├── parser/

│   ├── modbus\_parser.cpp      # C++ parser: decodes MBAP header + PDU

│   └── modbus\_parser          # compiled binary

└── physics\_engine/

&#x20;   ├── pipe\_model.py           # SciPy/NumPy pump+pipe pressure model

&#x20;   └── pressure\_vs\_rpm.png     # visualization of the danger curve

```



\## How to run it yourself



```bash

\# 1. Generate traffic (writes traffic.bin + traffic\_log.csv)

cd traffic\_gen

python3 generate\_traffic.py



\# 2. Compile and run the C++ parser against it

cd ../parser

g++ -std=c++17 -O2 -Wall -o modbus\_parser modbus\_parser.cpp

./modbus\_parser ../traffic\_gen/traffic.bin



\# 3. Run the physics engine standalone

cd ../physics\_engine

python3 pipe\_model.py

```



\## What each piece actually does



\*\*Traffic generator (`generate\_traffic.py`)\*\*

Builds real Modbus/TCP frames byte-for-byte with `struct` (no library

shortcuts), so you understand exactly what's on the wire: a 7-byte MBAP

header (transaction ID, protocol ID, length, unit ID) followed by a PDU

(function code + register address + register value). It mixes normal

pump-speed commands with a "perfectly formatted but physically insane"

50,000 RPM command — literally the attack from your problem statement.



\*\*Parser (`modbus\_parser.cpp`)\*\*

Reads the length-prefixed frames, decodes the MBAP header and PDU by hand

(big-endian byte math, no external Modbus library — this is the "low-level

network bridge" your plan calls for), and does a first-pass sanity check

against a hardcoded RPM ceiling. It correctly flagged all 3 injected

malicious frames with zero false positives.



\*\*Physics engine (`pipe\_model.py`)\*\*

Models the mock pipeline using real relations: pump affinity laws

(flow ∝ RPM, head ∝ RPM²) and Darcy-Weisbach friction loss, converted to

actual kPa pressure at the pipe wall. It classifies each commanded RPM as

SAFE / WARNING / CATASTROPHIC against a pipe burst rating.



\*\*The interesting result:\*\* the parser's naive hardcoded ceiling (3000 RPM)

and the physics engine's \*derived\* real ceiling (\~4450 RPM) don't match.

That's not a bug — it's the whole thesis of your project. A dumb rule-based

ceiling is just a guess; VoltGuard's actual value is running the real

physics simulation instead of trusting a fixed threshold. `pressure\_vs\_rpm.png`

visualizes this gap directly.



\## Suggested next steps (bridges into Week 2)



\- Have the C++ parser call the Python physics model per-command (e.g. via a

&#x20; small IPC pipe, or by porting `simulate\_pump\_command` logic into the

&#x20; eventual Rust Decision Engine) instead of using its own hardcoded ceiling.

\- Extend the physics model to more than one pipe segment / junction, since

&#x20; a real plant isn't one straight pipe.

\- Add more Modbus function codes to the parser (0x03 Read Holding Registers

&#x20; is already stubbed) so VoltGuard can also observe plant \*state\*, not just

&#x20; commands.

