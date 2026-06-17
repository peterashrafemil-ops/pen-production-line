"""
Ink Pen Production Cell Simulation
Advanced Programming Project

Run:
    py -3 -m pip install -r requirements.txt
    docker compose up -d
    py -3 app.py
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Optional

import tkinter as tk
from tkinter import ttk

try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
except Exception:
    InfluxDBClient = None
    Point = None
    WritePrecision = None
    SYNCHRONOUS = None


# -----------------------------
# Configuration
# -----------------------------
INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_ORG = "srh"
INFLUXDB_BUCKET = "pen_line"
INFLUXDB_TOKEN = "pen-token"
MEASUREMENT = "pen_line"
MACHINE_NAME = "Ink_Pen_Cell_01"

STATE_STOPPED = "STOPPED"
STATE_RUNNING = "RUNNING"
STATE_FAULTED = "FAULTED"
STATE_VALUE = {STATE_STOPPED: 0, STATE_RUNNING: 1, STATE_FAULTED: 2}

STATIONS = [
    ("S1", "Ink cartridge loading"),
    ("S2", "Nib press-fit"),
    ("S3", "Barrel closing"),
    ("S4", "Cap and clip mount"),
    ("S5", "Write-test inspection"),
]

DEFECTS_BY_STATION = {
    0: ["Ink cartridge missing", "Ink cartridge leakage detected"],
    1: ["Nib blocked", "Nib angle outside tolerance"],
    2: ["Barrel crack", "Barrel thread not locked"],
    3: ["Cap missing", "Clip not snapped into position"],
    4: ["Write test failed", "Final visual inspection failed"],
}


@dataclass
class Pen:
    product_id: int
    ink_cartridge_loaded: bool = False
    nib_fitted: bool = False
    barrel_closed: bool = False
    cap_clip_mounted: bool = False
    write_test_done: bool = False
    quality: str = "PENDING"
    defect_reason: str = "None"


@dataclass
class MachineSnapshot:
    state: str
    current_station: str
    current_station_index: int
    product_id: int
    produced_total: int
    good_total: int
    defective_total: int
    temperature_c: float
    last_quality: str
    last_defect_reason: str
    influx_connected: bool


class InfluxWriter:
    """InfluxDB writer. The HMI still runs even if the database is offline."""

    def __init__(self) -> None:
        self.connected = False
        self.last_error = ""
        self.client = None
        self.write_api = None
        self._connect()

    def _connect(self) -> None:
        if InfluxDBClient is None:
            self.last_error = "influxdb-client package is not installed"
            self.connected = False
            return
        try:
            self.client = InfluxDBClient(
                url=INFLUXDB_URL,
                token=INFLUXDB_TOKEN,
                org=INFLUXDB_ORG,
                timeout=3000,
            )
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            health = self.client.health()
            self.connected = health.status == "pass"
            self.last_error = "" if self.connected else f"InfluxDB health: {health.status}"
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)

    def write_snapshot(self, snapshot: MachineSnapshot) -> None:
        if not self.connected:
            self._connect()
        if not self.connected or self.write_api is None or Point is None:
            return
        try:
            point = (
                Point(MEASUREMENT)
                .tag("machine", MACHINE_NAME)
                .tag("station", snapshot.current_station)
                .field("produced_total", int(snapshot.produced_total))
                .field("good_total", int(snapshot.good_total))
                .field("defective_total", int(snapshot.defective_total))
                .field("temperature_c", float(snapshot.temperature_c))
                .field("state_value", int(STATE_VALUE.get(snapshot.state, 0)))
                .field("current_station_index", int(snapshot.current_station_index))
                .field("current_product_id", int(snapshot.product_id))
                .time(time.time_ns(), WritePrecision.NS)
            )
            self.write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            self.connected = True
            self.last_error = ""
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)


class PenProductionLine:
    def __init__(self) -> None:
        self.state = STATE_STOPPED
        self.product_id = 0
        self.current_pen: Optional[Pen] = None
        self.current_station_index = -1
        self.produced_total = 0
        self.good_total = 0
        self.defective_total = 0
        self.temperature_c = 23.8
        self.last_quality = "None"
        self.last_defect_reason = "None"
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.influx = InfluxWriter()

    def start(self) -> None:
        with self.lock:
            if self.state == STATE_FAULTED:
                return
            self.state = STATE_RUNNING
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        with self.lock:
            if self.state != STATE_FAULTED:
                self.state = STATE_STOPPED

    def reset(self) -> None:
        with self.lock:
            self.state = STATE_STOPPED
            self.product_id = 0
            self.current_pen = None
            self.current_station_index = -1
            self.produced_total = 0
            self.good_total = 0
            self.defective_total = 0
            self.temperature_c = 23.8
            self.last_quality = "None"
            self.last_defect_reason = "None"

    def acknowledge_fault(self) -> None:
        with self.lock:
            if self.state == STATE_FAULTED:
                self.state = STATE_STOPPED
                self.last_defect_reason = "Fault acknowledged - cell ready for restart"

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                running = self.state == STATE_RUNNING
            if not running:
                time.sleep(0.2)
                continue
            self._process_one_pen()

    def _process_one_pen(self) -> None:
        with self.lock:
            self.product_id += 1
            self.current_pen = Pen(product_id=self.product_id)
            self.current_station_index = 0
            self.last_defect_reason = "None"
            self.last_quality = "PENDING"

        for station_index, (_, station_name) in enumerate(STATIONS):
            with self.lock:
                if self.state != STATE_RUNNING:
                    return
                self.current_station_index = station_index
                self.temperature_c = self._simulate_temperature(station_index)
                self._apply_station(station_index)
                snapshot = self.snapshot()
            self.influx.write_snapshot(snapshot)
            time.sleep(0.65)

        with self.lock:
            if self.current_pen is None:
                return
            self.produced_total += 1
            defect = self._random_defect()
            if defect:
                self.current_pen.quality = "REJECT"
                self.current_pen.defect_reason = defect
                self.defective_total += 1
                self.last_quality = "REJECT"
                self.last_defect_reason = defect
                if random.random() < 0.07:
                    self.state = STATE_FAULTED
                    self.last_defect_reason = f"Cell fault: {defect}"
            else:
                self.current_pen.quality = "PASS"
                self.good_total += 1
                self.last_quality = "PASS"
                self.last_defect_reason = "None"
            snapshot = self.snapshot()
        self.influx.write_snapshot(snapshot)
        time.sleep(0.25)

    def _apply_station(self, station_index: int) -> None:
        if self.current_pen is None:
            return
        if station_index == 0:
            self.current_pen.ink_cartridge_loaded = True
        elif station_index == 1:
            self.current_pen.nib_fitted = True
        elif station_index == 2:
            self.current_pen.barrel_closed = True
        elif station_index == 3:
            self.current_pen.cap_clip_mounted = True
        elif station_index == 4:
            self.current_pen.write_test_done = True

    def _simulate_temperature(self, station_index: int) -> float:
        base = 23.8 + station_index * 0.35
        drift = random.uniform(-0.4, 0.7)
        if random.random() < 0.025:
            drift += random.uniform(4.0, 9.0)
        return round(base + drift, 1)

    def _random_defect(self) -> Optional[str]:
        if random.random() > 0.16:
            return None
        station_index = random.choice(list(DEFECTS_BY_STATION.keys()))
        return random.choice(DEFECTS_BY_STATION[station_index])

    def snapshot(self) -> MachineSnapshot:
        station_name = "Idle / buffer"
        if 0 <= self.current_station_index < len(STATIONS):
            station_name = STATIONS[self.current_station_index][1]
        return MachineSnapshot(
            state=self.state,
            current_station=station_name,
            current_station_index=self.current_station_index,
            product_id=self.product_id,
            produced_total=self.produced_total,
            good_total=self.good_total,
            defective_total=self.defective_total,
            temperature_c=self.temperature_c,
            last_quality=self.last_quality,
            last_defect_reason=self.last_defect_reason,
            influx_connected=self.influx.connected,
        )


class PenHMI(tk.Tk):
    """Custom dark operator panel, intentionally different from the pencil HMI."""

    BG = "#111827"
    PANEL = "#1f2937"
    PANEL_2 = "#243447"
    TEXT = "#e5e7eb"
    MUTED = "#9ca3af"
    BLUE = "#38bdf8"
    GREEN = "#22c55e"
    RED = "#ef4444"
    AMBER = "#f59e0b"
    PURPLE = "#a78bfa"

    def __init__(self, line: PenProductionLine) -> None:
        super().__init__()
        self.line = line
        self.title("Ink Pen Assembly Cell - Operator Console")
        self.geometry("1280x780")
        self.resizable(False, False)
        self.configure(bg=self.BG)

        self.value_labels: dict[str, tk.Label] = {}
        self.station_cards: list[int] = []
        self.station_leds: list[int] = []
        self.pen_body = None
        self.pen_tip = None
        self.pen_cap = None
        self.event_log: tk.Text | None = None
        self.last_logged_product = -1
        self.last_logged_defect = "None"

        self._setup_style()
        self._build_ui()
        self.after(250, self._refresh_ui)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT)
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED)
        style.configure("Panel.TLabel", background=self.PANEL, foreground=self.TEXT)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=self.BG)
        header.pack(fill="x", padx=24, pady=(18, 8))
        tk.Label(header, text="INK PEN ASSEMBLY CELL", bg=self.BG, fg=self.TEXT, font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(header, text="Python HMI  |  InfluxDB telemetry  |  Grafana monitoring", bg=self.BG, fg=self.MUTED, font=("Segoe UI", 11)).pack(side="right", pady=10)

        main = tk.Frame(self, bg=self.BG)
        main.pack(fill="both", expand=True, padx=24, pady=8)

        left = tk.Frame(main, bg=self.PANEL, width=220)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        tk.Label(left, text="CONTROL", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(18, 6))
        self._control_button(left, "START LINE", self.GREEN, self.line.start).pack(fill="x", padx=18, pady=7)
        self._control_button(left, "STOP LINE", self.AMBER, self.line.stop).pack(fill="x", padx=18, pady=7)
        self._control_button(left, "RESET COUNTERS", self.BLUE, self.line.reset).pack(fill="x", padx=18, pady=7)
        self._control_button(left, "ACKNOWLEDGE FAULT", self.RED, self.line.acknowledge_fault).pack(fill="x", padx=18, pady=7)

        tk.Frame(left, height=1, bg="#374151").pack(fill="x", padx=18, pady=20)
        tk.Label(left, text="CELL STATUS", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18)
        for label, key in [("State", "state"), ("Station", "station"), ("InfluxDB", "influx"), ("Last result", "quality")]:
            self._small_status(left, label, key)

        center = tk.Frame(main, bg=self.BG)
        center.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(center, width=760, height=430, bg="#0b1220", highlightthickness=0)
        self.canvas.pack(fill="x")
        self._draw_cell()

        log_frame = tk.Frame(center, bg=self.PANEL)
        log_frame.pack(fill="both", expand=True, pady=(14, 0))
        tk.Label(log_frame, text="EVENT LOG", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        self.event_log = tk.Text(log_frame, height=7, bg="#111827", fg=self.TEXT, insertbackground=self.TEXT, bd=0, font=("Consolas", 10))
        self.event_log.pack(fill="both", expand=True, padx=14, pady=10)
        self._log("System initialized. Start the line to assemble ink pens.")

        right = tk.Frame(main, bg=self.BG, width=255)
        right.pack(side="left", fill="y", padx=(14, 0))
        right.pack_propagate(False)
        self._kpi_card(right, "Produced", "produced", self.BLUE)
        self._kpi_card(right, "Accepted", "good", self.GREEN)
        self._kpi_card(right, "Rejected", "defective", self.RED)
        self._kpi_card(right, "Temperature", "temperature", self.PURPLE)
        self._kpi_card(right, "Product ID", "product_id", self.AMBER)

        alarm = tk.Frame(self, bg="#2b1218")
        alarm.pack(fill="x", padx=24, pady=(6, 16))
        tk.Label(alarm, text="ALARM / QUALITY MESSAGE", bg="#2b1218", fg="#fecaca", font=("Segoe UI", 11, "bold")).pack(side="left", padx=16, pady=13)
        self.value_labels["alarm"] = tk.Label(alarm, text="No active defect", bg="#2b1218", fg="#fecaca", font=("Segoe UI", 12))
        self.value_labels["alarm"].pack(side="left", padx=8)

    def _control_button(self, parent: tk.Widget, text: str, color: str, cmd) -> tk.Button:
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="white", activebackground=color, activeforeground="white", bd=0, height=2, font=("Segoe UI", 10, "bold"), cursor="hand2")

    def _small_status(self, parent: tk.Widget, label: str, key: str) -> None:
        box = tk.Frame(parent, bg=self.PANEL_2)
        box.pack(fill="x", padx=18, pady=6)
        tk.Label(box, text=label, bg=self.PANEL_2, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(6, 0))
        val = tk.Label(box, text="-", bg=self.PANEL_2, fg=self.TEXT, font=("Segoe UI", 11, "bold"), wraplength=165, justify="left")
        val.pack(anchor="w", padx=10, pady=(0, 7))
        self.value_labels[key] = val

    def _kpi_card(self, parent: tk.Widget, title: str, key: str, color: str) -> None:
        card = tk.Frame(parent, bg=self.PANEL)
        card.pack(fill="x", pady=(0, 12))
        tk.Label(card, text=title.upper(), bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        val = tk.Label(card, text="0", bg=self.PANEL, fg=color, font=("Segoe UI", 24, "bold"))
        val.pack(anchor="w", padx=16, pady=(0, 12))
        self.value_labels[key] = val

    def _draw_cell(self) -> None:
        c = self.canvas
        c.create_text(24, 22, text="Live cell layout", anchor="w", fill=self.MUTED, font=("Segoe UI", 11, "bold"))
        c.create_rectangle(55, 210, 705, 242, fill="#374151", outline="")
        c.create_text(380, 258, text="conveyor belt", fill=self.MUTED, font=("Segoe UI", 10))
        x_positions = [100, 235, 370, 505, 640]
        y = 150
        self.station_cards.clear()
        self.station_leds.clear()
        for i, ((code, name), x) in enumerate(zip(STATIONS, x_positions)):
            card = c.create_rectangle(x - 55, y - 58, x + 55, y + 54, fill="#1f2937", outline="#4b5563", width=2)
            led = c.create_oval(x - 42, y - 42, x - 24, y - 24, fill="#6b7280", outline="")
            c.create_text(x, y - 31, text=code, fill=self.TEXT, font=("Segoe UI", 18, "bold"))
            c.create_text(x, y + 8, text=name, fill=self.TEXT, font=("Segoe UI", 9), width=92)
            c.create_rectangle(x - 28, y + 34, x + 28, y + 43, fill="#111827", outline="#6b7280")
            if i < len(x_positions) - 1:
                c.create_line(x + 55, 210, x_positions[i + 1] - 55, 210, fill=self.BLUE, width=3, arrow=tk.LAST)
            self.station_cards.append(card)
            self.station_leds.append(led)
        self.pen_body = c.create_rectangle(70, 300, 150, 315, fill="#60a5fa", outline="white", width=1)
        self.pen_tip = c.create_polygon(150, 300, 172, 307, 150, 315, fill="#d1d5db", outline="white")
        self.pen_cap = c.create_rectangle(55, 298, 70, 317, fill="#f472b6", outline="white", width=1)
        c.create_text(116, 338, text="current pen", fill=self.MUTED, font=("Segoe UI", 9))

    def _log(self, message: str) -> None:
        if self.event_log is None:
            return
        stamp = time.strftime("%H:%M:%S")
        self.event_log.insert("end", f"[{stamp}] {message}\n")
        self.event_log.see("end")

    def _set_text(self, key: str, text: str, color: Optional[str] = None) -> None:
        label = self.value_labels.get(key)
        if not label:
            return
        label.config(text=text)
        if color:
            label.config(fg=color)

    def _refresh_ui(self) -> None:
        with self.line.lock:
            snap = self.line.snapshot()
            defect_reason = self.line.last_defect_reason

        state_color = self.GREEN if snap.state == STATE_RUNNING else self.RED if snap.state == STATE_FAULTED else self.AMBER
        self._set_text("state", snap.state, state_color)
        self._set_text("station", snap.current_station)
        self._set_text("influx", "Connected" if snap.influx_connected else "Offline", self.GREEN if snap.influx_connected else self.RED)
        self._set_text("quality", snap.last_quality, self.GREEN if snap.last_quality == "PASS" else self.RED if snap.last_quality == "REJECT" else self.MUTED)
        self._set_text("product_id", str(snap.product_id))
        self._set_text("produced", str(snap.produced_total))
        self._set_text("good", str(snap.good_total))
        self._set_text("defective", str(snap.defective_total))
        self._set_text("temperature", f"{snap.temperature_c:.1f} °C")

        for idx, card in enumerate(self.station_cards):
            if idx == snap.current_station_index and snap.state == STATE_RUNNING:
                self.canvas.itemconfig(card, fill="#064e3b", outline=self.GREEN)
                self.canvas.itemconfig(self.station_leds[idx], fill=self.GREEN)
            elif idx == snap.current_station_index and snap.state == STATE_FAULTED:
                self.canvas.itemconfig(card, fill="#7f1d1d", outline=self.RED)
                self.canvas.itemconfig(self.station_leds[idx], fill=self.RED)
            else:
                self.canvas.itemconfig(card, fill="#1f2937", outline="#4b5563")
                self.canvas.itemconfig(self.station_leds[idx], fill="#6b7280")

        if 0 <= snap.current_station_index < len(STATIONS):
            x_positions = [100, 235, 370, 505, 640]
            x = x_positions[snap.current_station_index]
            self.canvas.coords(self.pen_body, x - 35, 300, x + 45, 315)
            self.canvas.coords(self.pen_tip, x + 45, 300, x + 67, 307, x + 45, 315)
            self.canvas.coords(self.pen_cap, x - 50, 298, x - 35, 317)
        else:
            self.canvas.coords(self.pen_body, 70, 300, 150, 315)
            self.canvas.coords(self.pen_tip, 150, 300, 172, 307, 150, 315)
            self.canvas.coords(self.pen_cap, 55, 298, 70, 317)

        if defect_reason and defect_reason != "None":
            self._set_text("alarm", defect_reason, "#fecaca")
        else:
            self._set_text("alarm", "No active defect", "#fecaca")

        if snap.product_id != self.last_logged_product and snap.product_id > 0:
            self.last_logged_product = snap.product_id
            self._log(f"Product {snap.product_id} entered the assembly cell.")
        if defect_reason != self.last_logged_defect and defect_reason != "None":
            self.last_logged_defect = defect_reason
            self._log(f"Quality message: {defect_reason}")

        self.after(250, self._refresh_ui)


def main() -> None:
    line = PenProductionLine()
    app = PenHMI(line)
    app.mainloop()


if __name__ == "__main__":
    main()
