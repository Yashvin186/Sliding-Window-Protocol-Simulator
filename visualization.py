"""
visualization.py
----------------
Visualization components for the Sliding Window Protocol Simulator:
1. SenderReceiverCanvas: Tkinter Canvas displaying the Sender-Receiver column diagram
   with animated/static color-coded arrows and live status labels.
2. ComparisonVisualizer: Matplotlib embedded bar charts comparing Retransmissions,
   Throughput, and Efficiency across protocols.
"""

import os
import tempfile

# Ensure Matplotlib uses a writable temp cache directory
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl_cache"))

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

from simulator import SimulationEvent, SimulationStats


class SenderReceiverCanvas(ttk.Frame):
    """
    Tkinter Canvas implementing the two-column Sender-Receiver diagram.
    Displays frame arrows (Green, Red, Orange, Blue, Grey) and status indicators.
    """

    # Visual configuration
    COLOR_SUCCESS = "#2ecc71"      # Green: Successfully transmitted frame
    COLOR_LOST = "#e74c3c"         # Red: Lost frame / ACK
    COLOR_RETRANSMIT = "#e67e22"   # Orange: Retransmitted frame
    COLOR_ACK = "#2980b9"          # Blue: ACK transmission
    COLOR_WAITING = "#95a5a6"      # Grey: Waiting or pending frame
    COLOR_BUFFERED = "#8e44ad"     # Purple: Buffered in Selective Repeat
    COLOR_DISCARDED = "#d35400"    # Brown/Dark Orange: GBN out-of-order discard

    def __init__(self, parent: Any, **kwargs):
        super().__init__(parent, **kwargs)

        # Layout: Canvas + Vertical Scrollbar
        self.canvas = tk.Canvas(self, bg="#ffffff", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.row_y: int = 50
        self.row_height: int = 34
        self.margin_x: int = 40
        self.sender_x: int = 140
        self.receiver_x: int = 520
        self.current_in_flight_id: Optional[int] = None

        self._draw_headers()

    def _on_canvas_configure(self, event):
        # Dynamically adjust sender/receiver columns based on width
        width = event.width
        if width > 400:
            self.sender_x = int(width * 0.22)
            self.receiver_x = int(width * 0.78)
            self._redraw_headers()

    def reset(self) -> None:
        """Clears all drawn transmission arrows and resets the timeline."""
        self.canvas.delete("all")
        self.row_y = 50
        self.current_in_flight_id = None
        self._draw_headers()
        self.canvas.configure(scrollregion=(0, 0, self.winfo_width(), self.row_y + 100))
        self.canvas.yview_moveto(0.0)

    def _draw_headers(self) -> None:
        """Draws column titles and guide lines for SENDER and RECEIVER."""
        # Top background bar
        self.canvas.create_rectangle(0, 0, 2000, 42, fill="#f4f6f9", outline="#e2e8f0", tags="header")

        # Sender Column Header
        self.canvas.create_text(
            self.sender_x, 15,
            text="SENDER",
            font=("Segoe UI", 11, "bold"),
            fill="#1e293b",
            tags="header"
        )
        self.canvas.create_text(
            self.sender_x, 30,
            text="(Orange = Retransmission / Retx)",
            font=("Segoe UI", 7),
            fill="#d97706",
            tags="header"
        )

        # Receiver Column Header
        self.canvas.create_text(
            self.receiver_x, 15,
            text="RECEIVER",
            font=("Segoe UI", 11, "bold"),
            fill="#1e293b",
            tags="header"
        )
        self.canvas.create_text(
            self.receiver_x, 30,
            text="(Green = Received | Blue = ACK)",
            font=("Segoe UI", 7),
            fill="#2563eb",
            tags="header"
        )

        # Vertical guide rails
        self.canvas.create_line(self.sender_x, 42, self.sender_x, 10000, fill="#f1f5f9", dash=(4, 4), tags="guides")
        self.canvas.create_line(self.receiver_x, 42, self.receiver_x, 10000, fill="#f1f5f9", dash=(4, 4), tags="guides")

    def _redraw_headers(self) -> None:
        self.canvas.delete("header")
        self.canvas.delete("guides")
        self._draw_headers()

    def add_event(self, event: SimulationEvent) -> None:
        """Renders an arrow/indicator corresponding to a simulation event."""
        y = self.row_y
        self.row_y += self.row_height

        # Auto-expand scroll region
        canvas_height = max(self.row_y + 100, 600)
        self.canvas.configure(scrollregion=(0, 0, self.winfo_width(), canvas_height))

        # Auto scroll to latest event
        self.canvas.yview_moveto(1.0)

        # Timestamp badge on far left
        time_badge = f"{int(event.time_ms)}ms"
        self.canvas.create_text(
            35, y,
            text=time_badge,
            font=("Segoe UI", 8),
            fill="#64748b",
            anchor="e"
        )

        if event.event_type == "FRAME_TX_START":
            # Sender starts transmitting frame
            if event.is_retransmit:
                label = f"Frame {event.frame_id} (Retx)"
                box_w = 56
                color = self.COLOR_RETRANSMIT
            else:
                label = f"Frame {event.frame_id}"
                box_w = 46
                color = self.COLOR_SUCCESS

            # Sender node tag
            self.canvas.create_rectangle(
                self.sender_x - box_w, y - 11, self.sender_x + box_w, y + 11,
                fill="#ffffff", outline=color, width=1.5
            )
            self.canvas.create_text(
                self.sender_x, y,
                text=label,
                font=("Segoe UI", 8, "bold" if event.is_retransmit else "normal"),
                fill=color
            )

        elif event.event_type == "FRAME_LOST":
            # Red arrow stopping mid-way with 'X (LOST)'
            mid_x = (self.sender_x + self.receiver_x) // 2
            self.canvas.create_line(
                self.sender_x + 48, y, mid_x, y,
                fill=self.COLOR_LOST, width=2, arrow=tk.LAST, arrowshape=(8, 10, 3)
            )
            # Red X marker
            self.canvas.create_text(
                mid_x + 35, y,
                text="X (LOST)",
                font=("Segoe UI", 9, "bold"),
                fill=self.COLOR_LOST
            )

        elif event.event_type == "FRAME_RECEIVED":
            color = self.COLOR_SUCCESS
            status_text = f"Frame {event.frame_id}"
            if event.is_duplicate:
                color = self.COLOR_DISCARDED
                status_text = f"Frame {event.frame_id} (Dup)"
            elif event.is_buffered:
                color = self.COLOR_BUFFERED
                status_text = f"Frame {event.frame_id} (Buffered)"
            elif not event.is_delivered:
                color = self.COLOR_DISCARDED
                status_text = f"Frame {event.frame_id} (Discard)"

            # Full arrow from Sender to Receiver
            self.canvas.create_line(
                self.sender_x + 48, y, self.receiver_x - 52, y,
                fill=color, width=2, arrow=tk.LAST, arrowshape=(8, 10, 3)
            )

            # Receiver node tag
            self.canvas.create_rectangle(
                self.receiver_x - 52, y - 11, self.receiver_x + 58, y + 11,
                fill="#ffffff", outline=color, width=1.5
            )
            self.canvas.create_text(
                self.receiver_x + 3, y,
                text=status_text,
                font=("Segoe UI", 8, "bold" if event.is_buffered else "normal"),
                fill=color
            )

        elif event.event_type == "ACK_TX_START":
            # Receiver sending ACK back to Sender
            ack_label = f"ACK {event.ack_id}"
            self.canvas.create_rectangle(
                self.receiver_x - 42, y - 11, self.receiver_x + 42, y + 11,
                fill="#ebf5fb", outline=self.COLOR_ACK, width=1.5
            )
            self.canvas.create_text(
                self.receiver_x, y,
                text=ack_label,
                font=("Segoe UI", 8, "bold"),
                fill=self.COLOR_ACK
            )

        elif event.event_type == "ACK_LOST":
            # Dashed arrow from receiver stopping midway with 'X (ACK LOST)'
            mid_x = (self.sender_x + self.receiver_x) // 2
            self.canvas.create_line(
                self.receiver_x - 42, y, mid_x, y,
                fill=self.COLOR_LOST, width=2, dash=(4, 3), arrow=tk.LAST, arrowshape=(8, 10, 3)
            )
            self.canvas.create_text(
                mid_x - 45, y,
                text="X (ACK LOST)",
                font=("Segoe UI", 9, "bold"),
                fill=self.COLOR_LOST
            )

        elif event.event_type == "ACK_RECEIVED":
            # Full blue dashed arrow from Receiver to Sender
            self.canvas.create_line(
                self.receiver_x - 42, y, self.sender_x + 42, y,
                fill=self.COLOR_ACK, width=2, dash=(4, 3), arrow=tk.LAST, arrowshape=(8, 10, 3)
            )
            self.canvas.create_rectangle(
                self.sender_x - 42, y - 11, self.sender_x + 42, y + 11,
                fill="#ebf5fb", outline=self.COLOR_ACK, width=1.5
            )
            self.canvas.create_text(
                self.sender_x, y,
                text=f"ACK {event.ack_id} OK",
                font=("Segoe UI", 8, "bold"),
                fill=self.COLOR_ACK
            )

        elif event.event_type == "TIMEOUT":
            # Timeout marker at Sender
            self.canvas.create_rectangle(
                self.sender_x - 55, y - 11, self.sender_x + 55, y + 11,
                fill="#fef9e7", outline=self.COLOR_RETRANSMIT, width=1.5
            )
            self.canvas.create_text(
                self.sender_x, y,
                text=f"Timeout F{event.frame_id}",
                font=("Segoe UI", 8, "bold"),
                fill=self.COLOR_RETRANSMIT
            )

        elif event.event_type in ("SIMULATION_COMPLETED", "SIMULATION_ABORTED"):
            # End banner
            is_comp = (event.event_type == "SIMULATION_COMPLETED")
            banner_color = self.COLOR_SUCCESS if is_comp else self.COLOR_LOST
            text = "SIMULATION COMPLETED" if is_comp else "SIMULATION STOPPED"
            self.canvas.create_rectangle(
                self.sender_x - 60, y - 13, self.receiver_x + 60, y + 13,
                fill="#f8fafc", outline=banner_color, width=2
            )
            self.canvas.create_text(
                (self.sender_x + self.receiver_x) // 2, y,
                text=text,
                font=("Segoe UI", 9, "bold"),
                fill=banner_color
            )


class ComparisonVisualizer(ttk.Frame):
    """
    Renders the performance comparison table and Matplotlib bar charts
    comparing Retransmissions, Throughput, and Efficiency.
    """

    def __init__(self, parent: Any, **kwargs):
        super().__init__(parent, **kwargs)

        self.table_frame = ttk.LabelFrame(self, text="Performance Comparison Summary", padding=8)
        self.table_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.tree = ttk.Treeview(
            self.table_frame,
            columns=("metric", "one_bit", "gbn", "sr"),
            show="headings",
            height=8
        )
        self.tree.heading("metric", text="Metric")
        self.tree.heading("one_bit", text="One-Bit SW (Stop-and-Wait)")
        self.tree.heading("gbn", text="Go-Back-N")
        self.tree.heading("sr", text="Selective Repeat")

        self.tree.column("metric", width=220, anchor="w")
        self.tree.column("one_bit", width=160, anchor="center")
        self.tree.column("gbn", width=160, anchor="center")
        self.tree.column("sr", width=160, anchor="center")
        self.tree.pack(fill=tk.X, expand=True)

        # Matplotlib Chart Frame
        self.chart_frame = ttk.Frame(self)
        self.chart_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.figure = None
        self.canvas_widget = None

        # Educational takeaway note
        self.note_label = ttk.Label(
            self,
            text="* Note: Performance depends on window size, round-trip time, and network loss conditions.\n"
                 "  Go-Back-N provides higher throughput with simple buffering, while Selective Repeat avoids unnecessary retransmissions.",
            font=("Segoe UI", 9, "italic"),
            foreground="#475569",
            justify=tk.LEFT
        )
        self.note_label.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=5)

    def display_results(
        self,
        stats_one_bit: SimulationStats,
        stats_gbn: SimulationStats,
        stats_sr: SimulationStats
    ) -> None:
        """Populates the comparison table and renders the 3 Matplotlib bar charts."""
        # Clear existing rows
        for item in self.tree.get_children():
            self.tree.delete(item)

        rows = [
            ("Total Transmissions", stats_one_bit.total_frames_transmitted, stats_gbn.total_frames_transmitted, stats_sr.total_frames_transmitted),
            ("Retransmissions", stats_one_bit.num_retransmissions, stats_gbn.num_retransmissions, stats_sr.num_retransmissions),
            ("Packets Lost", stats_one_bit.packets_lost, stats_gbn.packets_lost, stats_sr.packets_lost),
            ("ACKs Received", stats_one_bit.acks_received, stats_gbn.acks_received, stats_sr.acks_received),
            ("Timeouts", stats_one_bit.timeouts, stats_gbn.timeouts, stats_sr.timeouts),
            ("Total Time (ms)", f"{int(stats_one_bit.total_time_ms)}", f"{int(stats_gbn.total_time_ms)}", f"{int(stats_sr.total_time_ms)}"),
            ("Throughput (frames/sec)", f"{stats_one_bit.throughput_fps:.2f}", f"{stats_gbn.throughput_fps:.2f}", f"{stats_sr.throughput_fps:.2f}"),
            ("Efficiency (%)", f"{stats_one_bit.efficiency_pct:.1f}%", f"{stats_gbn.efficiency_pct:.1f}%", f"{stats_sr.efficiency_pct:.1f}%")
        ]

        for row in rows:
            self.tree.insert("", tk.END, values=row)

        # Render Matplotlib Bar Charts
        self._plot_charts(stats_one_bit, stats_gbn, stats_sr)

    def _plot_charts(
        self,
        s1: SimulationStats,
        s2: SimulationStats,
        s3: SimulationStats
    ) -> None:
        if self.canvas_widget:
            self.canvas_widget.get_tk_widget().destroy()

        protocols = ["One-Bit SW", "Go-Back-N", "Selective Repeat"]
        colors = ["#3498db", "#e67e22", "#2ecc71"]

        # Create 1 row x 3 columns of subplots
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(10, 3.2), dpi=100)
        fig.patch.set_facecolor("#f8fafc")

        # 1. Retransmissions
        retx_vals = [s1.num_retransmissions, s2.num_retransmissions, s3.num_retransmissions]
        bars1 = ax1.bar(protocols, retx_vals, color=colors, width=0.55)
        ax1.set_title("Retransmissions (Lower is Better)", fontsize=10, fontweight="bold", pad=8)
        ax1.set_ylabel("Count", fontsize=9)
        ax1.grid(axis="y", linestyle="--", alpha=0.5)
        ax1.tick_params(axis="x", labelsize=8)
        for bar in bars1:
            h = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., h + 0.1, f"{int(h)}", ha="center", va="bottom", fontsize=8)

        # 2. Throughput
        tp_vals = [s1.throughput_fps, s2.throughput_fps, s3.throughput_fps]
        bars2 = ax2.bar(protocols, tp_vals, color=colors, width=0.55)
        ax2.set_title("Throughput (Higher is Better)", fontsize=10, fontweight="bold", pad=8)
        ax2.set_ylabel("Frames / Sec", fontsize=9)
        ax2.grid(axis="y", linestyle="--", alpha=0.5)
        ax2.tick_params(axis="x", labelsize=8)
        for bar in bars2:
            h = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., h + 0.05, f"{h:.1f}", ha="center", va="bottom", fontsize=8)

        # 3. Efficiency
        eff_vals = [s1.efficiency_pct, s2.efficiency_pct, s3.efficiency_pct]
        bars3 = ax3.bar(protocols, eff_vals, color=colors, width=0.55)
        ax3.set_title("Efficiency % (Higher is Better)", fontsize=10, fontweight="bold", pad=8)
        ax3.set_ylabel("Percentage (%)", fontsize=9)
        ax3.grid(axis="y", linestyle="--", alpha=0.5)
        ax3.set_ylim(0, max(max(eff_vals) * 1.25, 20))
        ax3.tick_params(axis="x", labelsize=8)
        for bar in bars3:
            h = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width()/2., h + 1.0, f"{h:.1f}%", ha="center", va="bottom", fontsize=8)

        fig.tight_layout()

        self.canvas_widget = FigureCanvasTkAgg(fig, master=self.chart_frame)
        self.canvas_widget.draw()
        self.canvas_widget.get_tk_widget().pack(fill=tk.BOTH, expand=True)
