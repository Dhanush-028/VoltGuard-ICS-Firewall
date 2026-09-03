# VoltGuard - Hardware Deployment Guide (Raspberry Pi)

**Read this line first: nothing in this document has been tested on
physical hardware.** There's no Raspberry Pi available to test on. This
is reasoned guidance based on how the Rust and Qt toolchains actually
work, not a verified walkthrough - if you get access to a Pi, treat this
as a starting point to debug from, not a guarantee. Anywhere this differs
from something *actually* tested (the whole rest of this project), it's
said plainly here.

## The actual goal

Deploy the gateway as a real physical bump-in-the-wire: the Pi sits
between the network and the PLC, with the gateway's decision logic
running on the Pi itself instead of a desktop machine. Two ways to wire
this, depending on what hardware you have:

**One Pi, two network interfaces** (e.g. built-in Ethernet + a USB
Ethernet adapter): the Pi bridges between them, gateway software listens
on one interface and forwards to the other.

**One Pi, one interface**: simulate the two sides with two ports on the
same interface - which is exactly the topology already built and tested
in this project (`gateway.py`/`voltguard_rs` on one port,
`mock_plc.py`/a real PLC on another). This is the more realistic option
if you don't have a second network adapter.

## Cross-compiling the Rust gateway for a Pi

Raspberry Pi (most models) run ARM, not the x86_64 this was built and
tested on. Rust supports cross-compilation via `rustup target add`:

```powershell
rustup target add aarch64-unknown-linux-gnu    # 64-bit Pi OS (most common now)
# or:
rustup target add armv7-unknown-linux-gnueabihf  # 32-bit Pi OS, older Pi models
```

Cross-compiling for Linux from Windows needs a linker for the target, which
`rustup target add` alone doesn't provide. The realistic options, in order
of how much friction they involve:

1. **Build directly on the Pi itself** - copy `rust_gateway/` over (SCP,
   USB drive, git clone), install Rust on the Pi the normal way
   (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`),
   then `cargo build --release` natively. Slower (Pi's CPU is much weaker
   than a desktop), but zero cross-compilation toolchain headaches. This
   is the option to try first.
2. **`cross`** (https://github.com/cross-rs/cross) - a wrapper that
   builds inside a Docker container with the right toolchain
   preinstalled. Needs Docker Desktop installed on Windows. Would replace
   `cargo build --release` with `cross build --release --target
   aarch64-unknown-linux-gnu`.
3. **Manual cross-toolchain setup** - installing an ARM GCC linker and
   configuring `.cargo/config.toml` to point at it. More control, more
   to get wrong; not recommended as a first attempt.

## Cross-compiling / running the Qt dashboard on a Pi

This one's more involved than the Rust side. Realistic options:

- **Run the dashboard on your Windows machine, not the Pi** - the Pi only
  needs to run the gateway (the actual inline decision-maker); the
  dashboard just tails `voltguard_log.csv`. If the Pi and your desktop
  are on the same network, you could sync the log file over (rsync,
  Samba share, or even just periodically copying it) and watch it from
  your desktop instead of running Qt on the Pi itself. This sidesteps
  the whole cross-compilation problem for the GUI.
- **If you do want it running directly on the Pi**: Raspberry Pi OS
  ships `qtbase5-dev`/`qt6-base-dev` and `qtcharts` packages via `apt`,
  the same way this project's Linux sandbox installed them - so building
  natively on the Pi (`cmake .. && make`, same as this project's Linux
  builds) is more realistic than cross-compiling a GUI toolchain from
  Windows.

## The mock PLC and continuous traffic on a Pi

Both are plain Python with no OS-specific code - `mock_plc.py` and
`continuous_traffic.py` should run unmodified on Pi OS's default Python 3
install, no changes needed.

## What to actually verify first, if you get a Pi

In order of "most likely to reveal a real problem":

1. Does `cargo build --release` even complete on the Pi's CPU in a
   reasonable time (could be much slower than the desktop's ~15-30s
   build)?
2. Does the compiled gateway binary correctly bind to a network port and
   see traffic from another machine on the same network (not just
   `127.0.0.1` - this project has only ever been tested on localhost)?
3. Does the physics math produce the same numbers on ARM as it did on
   x86_64? (It should - the same IEEE 754 floating point standard applies
   on both - but "should" isn't "verified," and this is exactly the kind
   of thing worth confirming with the parity tests before trusting it.)
4. Latency: is the sub-10ms decision computation still comfortably fast
   on a Pi's much weaker CPU? Almost certainly yes given the ~9,000x
   margin measured on desktop hardware, but this is unverified, not
   assumed-safe.

If you get a Pi and work through this, the parity tests
(`cargo test` in `rust_gateway/`) are the first thing to run on the new
hardware - they'll catch anything that's actually different about ARM
before you trust any of the rest.
