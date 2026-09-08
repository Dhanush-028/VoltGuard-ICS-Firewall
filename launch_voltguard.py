"""
launch_voltguard.py - Week 4 deliverable: one command instead of four
terminals. Starts the PLC, the gateway (Rust if built, Python if not),
continuous traffic, and the Qt dashboard together - and shuts everything
down cleanly on Ctrl+C.

This does NOT merge the components into a single process - that would
throw away the actual point of the earlier weeks (independently testable,
independently verifiable pieces in three languages). It orchestrates them,
the way a real deployment's supervisor/init system would - not a rewrite,
a coordinator.

Run: python launch_voltguard.py
Options:
  --gateway {auto,python,rust}   which gateway to run (default: auto -
                                  prefers the Rust build if it exists)
  --rate FLOAT                   continuous traffic rate, commands/sec (default 2)
  --malicious-ratio FLOAT        default 0.15
  --no-dashboard                 skip trying to launch the Qt dashboard
  --qt-path PATH                 override the Qt executable path if autodetect fails
"""

import argparse
import os
import platform
import subprocess
import sys
import time
import signal

HERE = os.path.dirname(os.path.abspath(__file__))
IS_WINDOWS = platform.system() == "Windows"

# force line-buffering even when stdout isn't a real terminal (e.g. piped
# or redirected) - this is an orchestrator script meant to be watched
# live, so status messages (especially "shutting down") must never sit
# in a buffer waiting to flush
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass  # older Python - not critical, just a nicety


def _exe_name(base):
    return base + ".exe" if IS_WINDOWS else base


def find_rust_gateway():
    """Looks for the compiled Rust gateway in the usual place next to this script."""
    candidates = [
        os.path.join(HERE, "rust_gateway", "target", "release", _exe_name("voltguard_rs")),
        os.path.join(HERE, "..", "rust_gateway", "target", "release", _exe_name("voltguard_rs")),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def find_qt_dashboard():
    """Searches common CMake/Qt Creator build output locations for the compiled dashboard."""
    search_roots = [
        os.path.join(HERE, "qt_dashboard", "build"),
        os.path.join(HERE, "qt_dashboard"),
    ]
    exe_name = _exe_name("voltguard_qt")
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            if exe_name in filenames:
                return os.path.join(dirpath, exe_name)
    return None


class Launcher:
    def __init__(self):
        self.processes = []  # list of (name, Popen)

    def start(self, name, args, cwd=None, new_console=False):
        print(f"[LAUNCHER] starting {name}: {' '.join(args)}")
        kwargs = {}
        if cwd:
            kwargs["cwd"] = cwd
        if IS_WINDOWS and new_console:
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        try:
            p = subprocess.Popen(args, **kwargs)
        except FileNotFoundError as e:
            print(f"[LAUNCHER] FAILED to start {name}: {e}")
            return None
        self.processes.append((name, p))
        return p

    def shutdown(self):
        print("\n[LAUNCHER] shutting down all components...")
        for name, p in reversed(self.processes):
            if p.poll() is None:  # still running
                print(f"[LAUNCHER] stopping {name}")
                try:
                    if IS_WINDOWS:
                        p.terminate()
                    else:
                        p.send_signal(signal.SIGINT)
                except Exception:
                    pass
        # give them a moment to exit cleanly, then force if needed
        time.sleep(1.5)
        for name, p in self.processes:
            if p.poll() is None:
                print(f"[LAUNCHER] force-stopping {name}")
                p.kill()
        print("[LAUNCHER] all stopped")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", choices=["auto", "python", "rust"], default="auto")
    ap.add_argument("--rate", type=float, default=2.0)
    ap.add_argument("--malicious-ratio", type=float, default=0.15)
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--qt-path", default=None)
    args = ap.parse_args()

    py = sys.executable

    # the Qt dashboard's "Stop All" button writes this file to ask the
    # launcher to shut everything down, since a separate GUI process
    # can't directly reach into another process's Ctrl+C handling - a
    # shared file is a simple, reliable signal that needs no sockets or
    # IPC libraries. Clear out any leftover from a previous run first,
    # or the new run would think a stop was already requested.
    stop_signal_path = os.path.join(HERE, "voltguard.stop")
    if os.path.exists(stop_signal_path):
        os.remove(stop_signal_path)

    launcher = Launcher()

    print("=== VoltGuard - one launcher, all components ===\n")

    # 1. PLC
    launcher.start("PLC (mock_plc.py)", [py, os.path.join(HERE, "mock_plc.py")], new_console=True)
    time.sleep(1.0)

    # 2. Gateway - decide which one
    rust_bin = find_rust_gateway()
    use_rust = (args.gateway == "rust") or (args.gateway == "auto" and rust_bin is not None)

    if use_rust:
        if rust_bin is None:
            print("[LAUNCHER] Rust gateway requested but not found (did you `cargo build --release`?) - "
                  "falling back to Python gateway")
            use_rust = False
        else:
            gateway_port = 15040
            # cwd=HERE (not the exe's own folder) - the gateway writes
            # voltguard_log.csv relative to its working directory, and it
            # needs to land in the same folder the Qt dashboard watches,
            # or you get two separate CSV files and a dashboard showing
            # stale data from a previous run instead of this one
            launcher.start("Gateway (Rust)", [rust_bin], cwd=HERE, new_console=True)

    if not use_rust:
        gateway_port = 5020
        launcher.start("Gateway (Python)", [py, os.path.join(HERE, "gateway.py")], new_console=True)

    time.sleep(1.0)

    # 3. Continuous traffic
    launcher.start(
        "Continuous traffic",
        [py, os.path.join(HERE, "continuous_traffic.py"),
         "--port", str(gateway_port), "--rate", str(args.rate),
         "--malicious-ratio", str(args.malicious_ratio)],
        new_console=True,
    )
    time.sleep(1.0)

    # 4. Qt dashboard
    if not args.no_dashboard:
        qt_path = args.qt_path or find_qt_dashboard()
        if qt_path:
            # run it with cwd set to HERE so it finds voltguard_log.csv in the
            # same place the gateway (Rust or Python) writes it
            launcher.start("Dashboard (Qt/C++)", [qt_path], cwd=HERE)
        else:
            print("[LAUNCHER] Qt dashboard not found - build it first (see qt_dashboard/README.md), "
                  "or pass --qt-path to point at it directly. Continuing without it.")

    print("\n[LAUNCHER] all components started. Press Ctrl+C here to stop everything.\n")

    try:
        while True:
            time.sleep(1)

            if os.path.exists(stop_signal_path):
                print("\n[LAUNCHER] stop signal received from dashboard")
                break

            # if the gateway or PLC died on their own, say so rather than
            # silently leaving a half-working system running
            for name, p in launcher.processes:
                if p.poll() is not None and name not in getattr(main, "_reported_dead", set()):
                    print(f"[LAUNCHER] warning: {name} exited on its own (code {p.returncode})")
                    main._reported_dead = getattr(main, "_reported_dead", set()) | {name}
    except KeyboardInterrupt:
        pass
    finally:
        launcher.shutdown()
        if os.path.exists(stop_signal_path):
            os.remove(stop_signal_path)


if __name__ == "__main__":
    main()
