"""
dashboard.py - operator-facing native desktop dashboard for VoltGuard.
Pure Tkinter + embedded matplotlib, dark mode, no web components.

Built for a factory-floor operator who does NOT know what "peak_psi" means
at 2am during an alarm - so the top of the screen is a big glanceable
status banner and running counters, not a data table. The detailed log
table is still there underneath for anyone who wants to dig in.

Needs tkinter (ships with python.org installer and Anaconda on Windows).
Linux: sudo apt install python3-tk

Run: python dashboard.py
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import random

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from protocol import generate_normal_command, generate_malicious_command
from decision_engine import inspect_packet
from physics_engine import PRESSURE_SAFE_LIMIT, simulate_pressure_curve

BG = "#1e1e1e"
PANEL_BG = "#141414"
FG = "#e0e0e0"
MUTED = "#888888"
ACCENT_SAFE = "#3ddc84"
ACCENT_DROP = "#ff4d4d"
ACCENT_WARN = "#ffb300"
BANNER_SAFE_BG = "#0f3d24"
BANNER_DROP_BG = "#4a1414"


class VoltGuardDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VoltGuard - OT Physics Firewall")
        self.geometry("1080x760")
        self.configure(bg=BG)
        self.running = False
        self.counts = {"ALLOW": 0, "DROP": 0, "MALFORMED": 0}

        self._build_layout()
        self._flash_job = None

    # ---------------- UI layout ----------------
    def _build_layout(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 6))

        tk.Label(header, text="VoltGuard", font=("Segoe UI", 22, "bold"),
                 fg=ACCENT_SAFE, bg=BG).pack(side="left")
        tk.Label(header, text="  physics-aware ICS/SCADA firewall",
                 font=("Segoe UI", 11), fg=MUTED, bg=BG).pack(side="left")

        self.start_btn = tk.Button(header, text="Start Monitoring", command=self.toggle_run,
                                    bg="#2d2d2d", fg=FG, activebackground="#3a3a3a",
                                    font=("Segoe UI", 11, "bold"),
                                    relief="flat", padx=18, pady=8)
        self.start_btn.pack(side="right")

        # ---- big glanceable status banner ----
        self.banner = tk.Label(self, text="SYSTEM IDLE - PRESS START MONITORING",
                                font=("Segoe UI", 18, "bold"), fg=FG, bg="#2a2a2a",
                                pady=16)
        self.banner.pack(fill="x", padx=14, pady=(4, 10))

        # ---- running counters ----
        stats = tk.Frame(self, bg=BG)
        stats.pack(fill="x", padx=14, pady=(0, 10))

        self.stat_allow = self._make_stat_box(stats, "COMMANDS ALLOWED", ACCENT_SAFE)
        self.stat_drop = self._make_stat_box(stats, "COMMANDS BLOCKED", ACCENT_DROP)
        self.stat_total = self._make_stat_box(stats, "TOTAL INSPECTED", FG)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=6)

        # left: live log (detail view, secondary to the banner)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="Detailed Traffic Log", font=("Segoe UI", 12, "bold"),
                 fg=FG, bg=BG).pack(anchor="w")

        cols = ("time", "verdict", "rpm", "peak_psi", "reason")
        headers = ("Time", "Verdict", "Pump RPM", "Predicted PSI", "Plain-language reason")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=16)
        for c, h, w in zip(cols, headers, (80, 80, 90, 100, 300)):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True, pady=6)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2a2a2a", foreground=FG,
                         fieldbackground="#2a2a2a", rowheight=24, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#3a3a3a")])
        self.tree.tag_configure("DROP", foreground=ACCENT_DROP)
        self.tree.tag_configure("ALLOW", foreground=ACCENT_SAFE)
        self.tree.tag_configure("WARN", foreground=ACCENT_WARN)

        # right: gauge + graph
        right = tk.Frame(body, bg=BG, width=380)
        right.pack(side="right", fill="y")

        tk.Label(right, text="Current Pipe Pressure", font=("Segoe UI", 12, "bold"),
                 fg=FG, bg=BG).pack(anchor="w")
        self.gauge = tk.Canvas(right, width=360, height=46, bg=PANEL_BG,
                                highlightthickness=1, highlightbackground="#444")
        self.gauge.pack(pady=(4, 12))
        self._draw_gauge(0)

        tk.Label(right, text="Predicted Pressure Curve (last command)",
                 font=("Segoe UI", 12, "bold"), fg=FG, bg=BG).pack(anchor="w")

        self.fig = Figure(figsize=(4.2, 3.8), dpi=90, facecolor=BG)
        self.ax = self.fig.add_subplot(111, facecolor=PANEL_BG)
        self.ax.tick_params(colors=FG)
        for spine in self.ax.spines.values():
            spine.set_color("#444")
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=6)

        self.status = tk.Label(self, text="idle", fg=MUTED, bg=BG, anchor="w",
                                font=("Segoe UI", 9))
        self.status.pack(fill="x", padx=14, pady=(0, 8))

    def _make_stat_box(self, parent, label, color):
        box = tk.Frame(parent, bg="#2a2a2a", padx=18, pady=12)
        box.pack(side="left", fill="x", expand=True, padx=6)
        value = tk.Label(box, text="0", font=("Segoe UI", 24, "bold"), fg=color, bg="#2a2a2a")
        value.pack()
        tk.Label(box, text=label, font=("Segoe UI", 9), fg=MUTED, bg="#2a2a2a").pack()
        return value

    def _draw_gauge(self, psi):
        self.gauge.delete("all")
        w, h = 360, 46
        max_scale = PRESSURE_SAFE_LIMIT * 1.6
        frac = max(0.0, min(1.0, psi / max_scale))
        # background track
        self.gauge.create_rectangle(0, 0, w, h, fill=PANEL_BG, outline="")
        # limit marker position
        limit_x = int((PRESSURE_SAFE_LIMIT / max_scale) * w)
        # fill color by zone
        color = ACCENT_SAFE if psi < PRESSURE_SAFE_LIMIT * 0.85 else (
            ACCENT_WARN if psi < PRESSURE_SAFE_LIMIT else ACCENT_DROP)
        self.gauge.create_rectangle(0, 0, int(frac * w), h, fill=color, outline="")
        self.gauge.create_line(limit_x, 0, limit_x, h, fill="#ffffff", width=2)
        self.gauge.create_text(w - 6, h // 2, anchor="e",
                                text=f"{psi:,.0f} psi  (limit {PRESSURE_SAFE_LIMIT:.0f})",
                                fill="#ffffff", font=("Segoe UI", 10, "bold"))

    # ---------------- control ----------------
    def toggle_run(self):
        self.running = not self.running
        self.start_btn.config(text="Stop Monitoring" if self.running else "Start Monitoring")
        if self.running:
            self._set_banner_safe()
            threading.Thread(target=self._traffic_loop, daemon=True).start()
        else:
            self.banner.config(text="SYSTEM IDLE - PRESS START MONITORING", bg="#2a2a2a", fg=FG)

    def _traffic_loop(self):
        while self.running:
            frame = generate_malicious_command() if random.random() < 0.2 else generate_normal_command()
            verdict, parsed, physics = inspect_packet(frame)
            self.after(0, self._on_verdict, verdict, parsed, physics)
            time.sleep(0.6)

    def _set_banner_safe(self):
        self.banner.config(text="ALL SYSTEMS NORMAL - NO THREATS DETECTED",
                            bg=BANNER_SAFE_BG, fg=ACCENT_SAFE)

    def _flash_alarm_banner(self, rpm, psi):
        self.banner.config(
            text=f"COMMAND BLOCKED - would have driven the pump to {psi:,.0f} psi "
                 f"and likely burst the pipe",
            bg=BANNER_DROP_BG, fg=ACCENT_DROP)
        # revert back to the safe banner after 4 seconds, unless another alarm interrupts it
        if self._flash_job:
            self.after_cancel(self._flash_job)
        self._flash_job = self.after(4000, self._set_banner_safe)

    def _on_verdict(self, verdict, parsed, physics):
        self.counts[verdict] += 1
        self.stat_allow.config(text=str(self.counts["ALLOW"]))
        self.stat_drop.config(text=str(self.counts["DROP"]))
        self.stat_total.config(text=str(sum(self.counts.values())))

        if verdict == "MALFORMED":
            self.status.config(text="malformed packet dropped at parser")
            return

        plain_reason = (
            f"would exceed the pipe's safety limit ({physics.peak_predicted_pressure:,.0f} psi predicted)"
            if verdict == "DROP" else "safe - well within normal operating pressure"
        )

        tag = "DROP" if verdict == "DROP" else ("WARN" if physics.warning else "ALLOW")
        self.tree.insert("", 0, values=(
            time.strftime("%H:%M:%S"), verdict, parsed["rpm"],
            f"{physics.peak_predicted_pressure:.1f}",
            plain_reason,
        ), tags=(tag,))

        self._draw_gauge(physics.peak_predicted_pressure)

        if verdict == "DROP":
            self.status.config(text=f"ALARM: dropped command for {parsed['rpm']} RPM "
                                     f"(predicted {physics.peak_predicted_pressure:.0f} psi)")
            self.bell()
            self._flash_alarm_banner(parsed["rpm"], physics.peak_predicted_pressure)
        else:
            self.status.config(text="monitoring...")

        self._update_graph(parsed["rpm"])

    def _update_graph(self, rpm):
        times, pressures = simulate_pressure_curve(0.0, rpm)
        self.ax.clear()
        self.ax.plot(times, pressures, color=ACCENT_SAFE, linewidth=1.6, label="predicted")
        self.ax.axhline(PRESSURE_SAFE_LIMIT, color=ACCENT_DROP, linestyle="--",
                         linewidth=1, label="safety limit")
        self.ax.set_ylim(0, max(PRESSURE_SAFE_LIMIT * 1.3, max(pressures) * 1.1))
        self.ax.tick_params(colors=FG, labelsize=8)
        self.ax.legend(fontsize=7, facecolor=PANEL_BG, labelcolor=FG)
        self.canvas.draw()


if __name__ == "__main__":
    app = VoltGuardDashboard()
    app.mainloop()
