"""
visualization.py
----------------
Visualization components for the Sliding Window Protocol Simulator:
1. SenderReceiverCanvas:
   - Top sticky animated Sliding Window bar showing all frames (0..N-1),
     with smooth sliding brackets for both Sender and Receiver windows.
   - Scrollable Space-Time Diagram showing Sender & Receiver timelines,
     diagonal downward frame/ACK arrows, lost-packet breaks, mini window
     snapshots beside each event, and smooth packet flight animation.
2. ComparisonVisualizer:
   - Matplotlib embedded bar charts comparing Retransmissions, Throughput,
     and Efficiency across protocols.
"""

import os
import tempfile

# Ensure Matplotlib uses a writable temp cache directory
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl_cache"))

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

from simulator import SimulationEvent, SimulationStats


class SenderReceiverCanvas(ttk.Frame):
    """
    Combined animated visualization:
    - Top sticky window strip showing all frames and sliding window transition.
    - Bottom scrollable space-time diagram with diagonal arrows and mini windows.
    """

    COLOR_SUCCESS = "#16a34a"      # Green: Delivered / ACKed
    COLOR_INFLIGHT = "#eab308"     # Yellow/Amber: In-flight waiting for ACK
    COLOR_LOST = "#dc2626"         # Red: Lost frame / ACK
    COLOR_RETRANSMIT = "#ea580c"   # Orange: Retransmitted frame / Timeout
    COLOR_ACK = "#2563eb"          # Blue: ACK transmission
    COLOR_WAITING = "#94a3b8"      # Grey: Pending frame
    COLOR_BUFFERED = "#9333ea"     # Purple: Buffered out-of-order (SR)
    COLOR_DISCARDED = "#b91c1c"    # Dark Red: Discarded out-of-order (GBN)
    COLOR_WIN_BG = "#fce7f3"       # Soft pink/highlight inside mini window

    def __init__(self, parent: Any, **kwargs):
        super().__init__(parent, **kwargs)

        # --- 1. TOP STICKY ANIMATED SLIDING WINDOW STRIP ---
        self.win_canvas = tk.Canvas(self, height=112, bg="#f8fafc", highlightthickness=1, highlightbackground="#cbd5e1")
        self.win_canvas.pack(side=tk.TOP, fill=tk.X)

        # --- 2. MAIN SCROLLABLE SPACE-TIME CANVAS ---
        timeline_container = ttk.Frame(self)
        timeline_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(timeline_container, bg="#ffffff", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(timeline_container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.win_canvas.bind("<Configure>", lambda e: self._redraw_window_strip())

        # Geometry defaults
        self.sender_x: int = 260
        self.receiver_x: int = 560
        self.next_sender_y: int = 68
        self.next_receiver_y: int = 68

        # Simulation state for visual tracking
        self.num_frames: int = 10
        self.window_size: int = 4
        self.sender_base: int = 0
        self.sender_next: int = 0
        self.receiver_base: int = 0
        self.receiver_end: int = 0

        self.acked_frames: set = set()
        self.inflight_frames: set = set()
        self.retx_frames: set = set()
        self.lost_frames: set = set()
        self.delivered_frames: set = set()
        self.buffered_frames: set = set()
        self.discarded_flash: Optional[int] = None

        # Smooth sliding bracket animation coordinates
        self.s_bracket_x1: float = 0.0
        self.s_bracket_x2: float = 0.0
        self.r_bracket_x1: float = 0.0
        self.r_bracket_x2: float = 0.0
        self._win_anim_after: Optional[str] = None

        # Active diagonal arrow flight tracking: packet_uid -> dict
        self.flights: Dict[str, Dict[str, Any]] = {}
        self._arrow_anim_after: Optional[str] = None
        self._arrow_anim_paused: bool = False
        self._pending_anim_state: Optional[Dict[str, Any]] = None

        self._draw_headers()
        self._redraw_window_strip()

    def _on_canvas_configure(self, event) -> None:
        width = event.width
        if width > 420 and not self.flights:
            self.sender_x = int(width * 0.34)
            self.receiver_x = int(width * 0.66)
            self._redraw_headers()

    def configure_simulation(self, num_frames: int, window_size: int) -> None:
        """Initializes the window strip for a fresh simulation."""
        self.num_frames = max(1, num_frames)
        self.window_size = max(1, window_size)
        self.reset()

    def reset(self) -> None:
        """Clears all drawings, active animations, and resets state."""
        if self._win_anim_after:
            self.after_cancel(self._win_anim_after)
            self._win_anim_after = None
        if self._arrow_anim_after:
            self.after_cancel(self._arrow_anim_after)
            self._arrow_anim_after = None

        self._arrow_anim_paused = False
        self._pending_anim_state = None
        self.flights.clear()

        self.canvas.delete("all")
        self.next_sender_y = 68
        self.next_receiver_y = 68

        self.sender_base = 0
        self.sender_next = 0
        self.receiver_base = 0
        self.receiver_end = 0

        self.acked_frames.clear()
        self.inflight_frames.clear()
        self.retx_frames.clear()
        self.lost_frames.clear()
        self.delivered_frames.clear()
        self.buffered_frames.clear()
        self.discarded_flash = None

        # Reset bracket positions to frame 0
        s_tx1, s_tx2 = self._get_window_pixel_bounds(0, min(self.window_size - 1, self.num_frames - 1))
        self.s_bracket_x1, self.s_bracket_x2 = s_tx1, s_tx2
        self.r_bracket_x1, self.r_bracket_x2 = s_tx1, self._get_window_pixel_bounds(0, 0)[1]

        self._draw_headers()
        self._redraw_window_strip()
        self.canvas.configure(scrollregion=(0, 0, max(700, self.winfo_width()), 500))
        self.canvas.yview_moveto(0.0)

    # ------------------------------------------------------------------
    # TOP STICKY ANIMATED SLIDING WINDOW STRIP
    # ------------------------------------------------------------------

    def _get_strip_layout(self) -> Tuple[int, int, int]:
        """Returns (start_x, box_w, gap) for frame cells in the sticky strip."""
        w = max(self.win_canvas.winfo_width(), 720)
        start_x = 92
        avail = w - start_x - 24
        max_boxes = min(self.num_frames, 30)
        step = max(20, min(42, avail // max(1, max_boxes)))
        gap = max(2, min(5, step // 8))
        box_w = step - gap
        return start_x, box_w, gap

    def _get_window_pixel_bounds(self, idx_start: int, idx_end: int) -> Tuple[float, float]:
        start_x, box_w, gap = self._get_strip_layout()
        idx_start = max(0, min(idx_start, self.num_frames - 1))
        idx_end = max(idx_start, min(idx_end, self.num_frames - 1))
        x1 = start_x + idx_start * (box_w + gap) - 3
        x2 = start_x + idx_end * (box_w + gap) + box_w + 3
        return float(x1), float(x2)

    def _animate_window_brackets(self, s_start: int, s_end: int, r_start: int, r_end: int, instant: bool = False) -> None:
        if self._win_anim_after:
            self.after_cancel(self._win_anim_after)
            self._win_anim_after = None

        target_sx1, target_sx2 = self._get_window_pixel_bounds(s_start, s_end)
        target_rx1, target_rx2 = self._get_window_pixel_bounds(r_start, r_end)

        if instant or self.num_frames > 30:
            self.s_bracket_x1, self.s_bracket_x2 = target_sx1, target_sx2
            self.r_bracket_x1, self.r_bracket_x2 = target_rx1, target_rx2
            self._redraw_window_strip()
            return

        # Smoothly interpolate bracket position over 8 steps
        steps = 8
        start_sx1, start_sx2 = self.s_bracket_x1, self.s_bracket_x2
        start_rx1, start_rx2 = self.r_bracket_x1, self.r_bracket_x2

        def _step(k: int) -> None:
            t = k / steps
            # Ease-out quad
            ease = 1.0 - (1.0 - t) * (1.0 - t)
            self.s_bracket_x1 = start_sx1 + (target_sx1 - start_sx1) * ease
            self.s_bracket_x2 = start_sx2 + (target_sx2 - start_sx2) * ease
            self.r_bracket_x1 = start_rx1 + (target_rx1 - start_rx1) * ease
            self.r_bracket_x2 = start_rx2 + (target_rx2 - start_rx2) * ease
            self._redraw_window_strip()
            if k < steps:
                self._win_anim_after = self.after(18, lambda: _step(k + 1))
            else:
                self._win_anim_after = None

        _step(1)

    def _redraw_window_strip(self) -> None:
        self.win_canvas.delete("all")
        start_x, box_w, gap = self._get_strip_layout()

        # Labels on left
        self.win_canvas.create_text(14, 24, text="SENDER:", font=("Segoe UI", 8, "bold"), fill="#0f172a", anchor="w")
        self.win_canvas.create_text(14, 62, text="RECEIVER:", font=("Segoe UI", 8, "bold"), fill="#0f172a", anchor="w")

        visible_count = min(self.num_frames, 30)
        for i in range(visible_count):
            bx = start_x + i * (box_w + gap)

            # --- Sender frame cell ---
            if i in self.acked_frames:
                s_fill, s_out, s_fg = "#dcfce7", self.COLOR_SUCCESS, "#166534"
            elif i in self.retx_frames:
                s_fill, s_out, s_fg = "#ffedd5", self.COLOR_RETRANSMIT, "#9a3412"
            elif i in self.lost_frames:
                s_fill, s_out, s_fg = "#fee2e2", self.COLOR_LOST, "#991b1b"
            elif i in self.inflight_frames:
                s_fill, s_out, s_fg = "#fef9c3", self.COLOR_INFLIGHT, "#854d0e"
            elif self.sender_base <= i < self.sender_base + self.window_size:
                s_fill, s_out, s_fg = "#e0f2fe", "#0284c7", "#075985"
            else:
                s_fill, s_out, s_fg = "#f1f5f9", "#cbd5e1", "#64748b"

            self.win_canvas.create_rectangle(bx, 11, bx + box_w, 37, fill=s_fill, outline=s_out, width=1.2)
            self.win_canvas.create_text(bx + box_w / 2, 24, text=str(i), font=("Segoe UI", 8, "bold"), fill=s_fg)

            # --- Receiver frame cell ---
            if i == self.discarded_flash:
                r_fill, r_out, r_fg = "#fee2e2", self.COLOR_DISCARDED, "#991b1b"
            elif i in self.delivered_frames:
                r_fill, r_out, r_fg = "#dcfce7", self.COLOR_SUCCESS, "#166534"
            elif i in self.buffered_frames:
                r_fill, r_out, r_fg = "#f3e8ff", self.COLOR_BUFFERED, "#6b21a8"
            elif self.receiver_base <= i <= self.receiver_end:
                r_fill, r_out, r_fg = "#ecfdf5", "#10b981", "#065f46"
            else:
                r_fill, r_out, r_fg = "#f1f5f9", "#cbd5e1", "#64748b"

            self.win_canvas.create_rectangle(bx, 49, bx + box_w, 75, fill=r_fill, outline=r_out, width=1.2)
            self.win_canvas.create_text(bx + box_w / 2, 62, text=str(i), font=("Segoe UI", 8, "bold"), fill=r_fg)

        if self.num_frames > 30:
            self.win_canvas.create_text(
                start_x + 30 * (box_w + gap) + 6, 43,
                text=f"(+{self.num_frames - 30} more)",
                font=("Segoe UI", 7), fill="#64748b", anchor="w"
            )

        # Sliding Window Brackets
        if self.sender_base < self.num_frames and self.sender_base < 30:
            self.win_canvas.create_rectangle(
                self.s_bracket_x1, 7, self.s_bracket_x2, 41,
                outline="#0284c7", width=2.4
            )
        if self.receiver_base < self.num_frames and self.receiver_base < 30:
            self.win_canvas.create_rectangle(
                self.r_bracket_x1, 45, self.r_bracket_x2, 79,
                outline="#16a34a", width=2.4
            )

        # Legend row at bottom of strip
        legend_items = [
            ("#dcfce7", "#16a34a", "ACKed / Delivered"),
            ("#fef9c3", "#eab308", "In-Flight"),
            ("#ffedd5", "#ea580c", "Retransmit (Retx)"),
            ("#fee2e2", "#dc2626", "Lost / Discarded"),
            ("#f3e8ff", "#9333ea", "SR Buffered"),
        ]
        lx = 16
        for bg_c, bd_c, text_c in legend_items:
            self.win_canvas.create_rectangle(lx, 90, lx + 12, 102, fill=bg_c, outline=bd_c, width=1.2)
            self.win_canvas.create_text(lx + 16, 96, text=text_c, font=("Segoe UI", 8), fill="#334155", anchor="w")
            lx += 132

    # ------------------------------------------------------------------
    # SPACE-TIME TIMELINE DIAGRAM (MATCHING TEXTBOOK REFERENCE)
    # ------------------------------------------------------------------

    def _draw_headers(self) -> None:
        """Draws Sender and Receiver header boxes and continuous vertical timeline axes."""
        # Header boxes (Sender & Receiver)
        self.canvas.create_rectangle(
            self.sender_x - 52, 10, self.sender_x + 52, 42,
            fill="#f0fdf4", outline="#16a34a", width=2, tags="header"
        )
        self.canvas.create_text(
            self.sender_x, 26, text="Sender", font=("Segoe UI", 11, "bold"), fill="#15803d", tags="header"
        )

        self.canvas.create_rectangle(
            self.receiver_x - 52, 10, self.receiver_x + 52, 42,
            fill="#f0fdf4", outline="#16a34a", width=2, tags="header"
        )
        self.canvas.create_text(
            self.receiver_x, 26, text="Receiver", font=("Segoe UI", 11, "bold"), fill="#15803d", tags="header"
        )

        # Vertical timeline axes extending downwards
        self.canvas.create_line(
            self.sender_x, 42, self.sender_x, 20000,
            fill="#1e293b", width=2, tags="guides"
        )
        self.canvas.create_line(
            self.receiver_x, 42, self.receiver_x, 20000,
            fill="#1e293b", width=2, tags="guides"
        )

    def _redraw_headers(self) -> None:
        self.canvas.delete("header")
        self.canvas.delete("guides")
        self._draw_headers()

    def _draw_mini_window(self, side: str, y: int, base: int, end_win: int, highlight_idx: Optional[int], pointer_label: str = "") -> None:
        """
        Draws the compact sliding window box row on the left of Sender or right of Receiver,
        matching the textbook sliding window diagram.
        """
        cell_w = 18
        cell_h = 18
        max_cells = min(self.num_frames, 7)

        # Determine slice of frames to display around `base`
        if self.num_frames <= max_cells:
            start_idx = 0
        else:
            start_idx = max(0, min(base - 1, self.num_frames - max_cells))
        indices = list(range(start_idx, start_idx + max_cells))

        total_w = len(indices) * cell_w
        if side == "sender":
            x0 = self.sender_x - 28 - total_w
        else:
            x0 = self.receiver_x + 28

        y0 = y - cell_h // 2

        # Draw each cell
        w_x1, w_x2 = None, None
        for offset, fid in enumerate(indices):
            cx1 = x0 + offset * cell_w
            cx2 = cx1 + cell_w

            in_win = (base <= fid <= end_win)
            if in_win:
                if w_x1 is None:
                    w_x1 = cx1
                w_x2 = cx2

            if fid == highlight_idx:
                fill_c = "#fde68a" if side == "sender" else "#bbf7d0"
            elif in_win:
                fill_c = self.COLOR_WIN_BG
            else:
                fill_c = "#ffffff"

            self.canvas.create_rectangle(cx1, y0, cx2, y0 + cell_h, fill=fill_c, outline="#334155", width=1)
            self.canvas.create_text(
                (cx1 + cx2) / 2, y0 + cell_h / 2,
                text=str(fid), font=("Segoe UI", 7, "bold"), fill="#1e293b"
            )

        # Draw thick grey/dark sliding window bracket around active window cells
        if w_x1 is not None and w_x2 is not None:
            self.canvas.create_rectangle(w_x1 - 1, y0 - 3, w_x2 + 1, y0 + cell_h + 3, outline="#475569", width=2.4)

        # Draw pointer indicator 'S' or 'R' below current cell
        if highlight_idx is not None and highlight_idx in indices:
            off = indices.index(highlight_idx)
            px = x0 + off * cell_w + cell_w / 2
            self.canvas.create_line(px, y0 + cell_h + 1, px, y0 + cell_h + 9, fill="#15803d", width=1.5)
            if pointer_label:
                self.canvas.create_text(
                    px, y0 + cell_h + 15, text=pointer_label,
                    font=("Segoe UI", 7, "bold"), fill="#15803d"
                )

    def _expand_scroll(self, y_max: int) -> None:
        h = max(y_max + 120, 500)
        self.canvas.configure(scrollregion=(0, 0, max(700, self.winfo_width()), h))
        self.canvas.yview_moveto(1.0)

    def _update_window_strip_from_event(self, event: SimulationEvent, instant: bool = False) -> None:
        self.sender_base = event.sender_base
        self.sender_next = event.sender_next
        self.acked_frames = set(event.sender_acked)
        self.delivered_frames = set(event.receiver_delivered)
        self.buffered_frames = set(event.receiver_buffered)

        r_start, r_end = event.receiver_window
        self.receiver_base = r_start
        self.receiver_end = r_end

        if event.event_type == "FRAME_TX_START":
            self.inflight_frames.add(event.frame_id)
            self.lost_frames.discard(event.frame_id)
            if event.is_retransmit:
                self.retx_frames.add(event.frame_id)
            else:
                self.retx_frames.discard(event.frame_id)
            self.discarded_flash = None

        elif event.event_type == "FRAME_LOST":
            self.inflight_frames.discard(event.frame_id)
            self.lost_frames.add(event.frame_id)

        elif event.event_type == "FRAME_RECEIVED":
            self.inflight_frames.discard(event.frame_id)
            if not event.is_delivered and not event.is_buffered and not event.is_duplicate:
                self.discarded_flash = event.frame_id
            else:
                self.discarded_flash = None

        elif event.event_type == "ACK_RECEIVED":
            for f in self.acked_frames:
                self.inflight_frames.discard(f)
                self.retx_frames.discard(f)
                self.lost_frames.discard(f)

        elif event.event_type == "TIMEOUT":
            self.retx_frames.add(event.frame_id)

        s_start, s_end = event.sender_window
        self._animate_window_brackets(s_start, s_end, r_start, r_end, instant=instant)

    # ------------------------------------------------------------------
    # ANIMATED EVENT PLAYBACK
    # ------------------------------------------------------------------

    def play_event(self, event: SimulationEvent, step_duration_ms: int, on_done: Optional[Callable[[], None]] = None) -> None:
        """
        Renders an event on the Space-Time Diagram and Window Strip.
        If step_duration_ms > 0, smoothly animates packet/arrow movement over step_duration_ms
        and invokes on_done() when complete.
        """
        instant = (step_duration_ms <= 0)
        self._update_window_strip_from_event(event, instant=instant)

        ev_type = event.event_type
        uid = event.packet_uid

        if ev_type == "FRAME_TX_START":
            y_start = self.next_sender_y
            self.next_sender_y += 42
            y_target = max(y_start + 52, self.next_receiver_y)

            # Time stamp label next to Sender line
            self.canvas.create_text(
                self.sender_x - 8, y_start,
                text=f"{int(event.time_ms)}ms",
                font=("Segoe UI", 7), fill="#64748b", anchor="e"
            )

            # Mini sender window graphic on the left
            s_start, s_end = event.sender_window
            self._draw_mini_window("sender", y_start, s_start, s_end, event.frame_id, pointer_label="S")

            color = self.COLOR_RETRANSMIT if event.is_retransmit else "#1e293b"
            label = f"Frame {event.frame_id} (Retx)" if event.is_retransmit else f"Frame {event.frame_id}"

            line_id = self.canvas.create_line(
                self.sender_x, y_start, self.sender_x, y_start,
                fill=color, width=2.0
            )
            dot_id = self.canvas.create_oval(
                self.sender_x - 4, y_start - 4, self.sender_x + 4, y_start + 4,
                fill=color, outline=""
            )
            self.flights[uid] = {
                "x1": self.sender_x, "y1": y_start,
                "x2": self.receiver_x, "y2": y_target,
                "color": color, "label": label,
                "line_id": line_id, "dot_id": dot_id,
                "progress": 0.0, "dashed": False
            }
            self._expand_scroll(y_target)
            self._animate_flight(uid, 0.0, 0.35, step_duration_ms, on_done)

        elif ev_type == "FRAME_RECEIVED":
            f = self.flights.get(uid)
            if not f:
                if on_done:
                    on_done()
                return

            y_start = f["y1"]
            y_end = max(y_start + 52, self.next_receiver_y)
            self.next_receiver_y = y_end + 36
            f["y2"] = y_end

            # Color based on outcome
            if event.is_buffered:
                color = self.COLOR_BUFFERED
                tag_note = " (Buffered)"
            elif not event.is_delivered and not event.is_duplicate:
                color = self.COLOR_DISCARDED
                tag_note = " (Discarded)"
            elif event.is_duplicate:
                color = self.COLOR_RETRANSMIT
                tag_note = " (Duplicate)"
            else:
                color = self.COLOR_SUCCESS if not event.is_retransmit else self.COLOR_RETRANSMIT
                tag_note = ""

            f["color"] = color
            self.canvas.itemconfig(f["line_id"], fill=color, arrow=tk.LAST, arrowshape=(8, 10, 3))
            self.canvas.itemconfig(f["dot_id"], fill=color)

            # Label above diagonal arrow
            mid_x = (self.sender_x + self.receiver_x) / 2
            mid_y = (y_start + y_end) / 2 - 12
            self.canvas.create_text(
                mid_x, mid_y,
                text=f["label"] + tag_note,
                font=("Segoe UI", 8, "bold"),
                fill=color
            )

            # Mini receiver window graphic on the right
            r_start, r_end = event.receiver_window
            self._draw_mini_window("receiver", y_end, r_start, r_end, event.frame_id, pointer_label="R")
            self._expand_scroll(y_end)

            def _finish_rx():
                self.canvas.delete(f["dot_id"])
                if on_done:
                    on_done()

            self._animate_flight(uid, f["progress"], 1.0, step_duration_ms, _finish_rx)

        elif ev_type == "FRAME_LOST":
            f = self.flights.get(uid)
            if not f:
                if on_done:
                    on_done()
                return

            y_start = f["y1"]
            y_end = f["y2"]
            f["color"] = self.COLOR_LOST
            self.canvas.itemconfig(f["line_id"], fill=self.COLOR_LOST)
            self.canvas.itemconfig(f["dot_id"], fill=self.COLOR_LOST)

            def _finish_lost():
                self.canvas.delete(f["dot_id"])
                # Draw angled break + Lost label just like textbook diagram
                bx = self.sender_x + (self.receiver_x - self.sender_x) * 0.56
                by = y_start + (y_end - y_start) * 0.56
                self.canvas.create_line(
                    bx, by, bx - 16, by + 10,
                    fill=self.COLOR_LOST, width=2, arrow=tk.LAST, arrowshape=(7, 9, 3)
                )
                self.canvas.create_text(
                    bx + 6, by + 14,
                    text=f"X ({f['label']} Lost)",
                    font=("Segoe UI", 8, "bold"),
                    fill=self.COLOR_LOST, anchor="w"
                )
                if on_done:
                    on_done()

            self._animate_flight(uid, f["progress"], 0.56, step_duration_ms, _finish_lost)

        elif ev_type == "ACK_TX_START":
            y_ack_start = max(self.next_receiver_y - 24, 68)
            self.next_receiver_y = max(self.next_receiver_y, y_ack_start + 30)
            y_ack_target = max(y_ack_start + 46, self.next_sender_y)

            line_id = self.canvas.create_line(
                self.receiver_x, y_ack_start, self.receiver_x, y_ack_start,
                fill=self.COLOR_ACK, width=1.8, dash=(5, 4)
            )
            dot_id = self.canvas.create_oval(
                self.receiver_x - 4, y_ack_start - 4, self.receiver_x + 4, y_ack_start + 4,
                fill=self.COLOR_ACK, outline=""
            )
            self.flights[uid] = {
                "x1": self.receiver_x, "y1": y_ack_start,
                "x2": self.sender_x, "y2": y_ack_target,
                "color": self.COLOR_ACK, "label": f"ACK {event.ack_id}",
                "line_id": line_id, "dot_id": dot_id,
                "progress": 0.0, "dashed": True
            }
            self._expand_scroll(y_ack_target)
            self._animate_flight(uid, 0.0, 0.35, step_duration_ms, on_done)

        elif ev_type == "ACK_RECEIVED":
            f = self.flights.get(uid)
            if not f:
                if on_done:
                    on_done()
                return

            y_start = f["y1"]
            y_end = max(y_start + 46, self.next_sender_y)
            self.next_sender_y = y_end + 36
            f["y2"] = y_end

            self.canvas.itemconfig(f["line_id"], arrow=tk.LAST, arrowshape=(8, 10, 3))

            mid_x = (self.sender_x + self.receiver_x) / 2
            mid_y = (y_start + y_end) / 2 - 11
            self.canvas.create_text(
                mid_x, mid_y,
                text=f["label"],
                font=("Segoe UI", 8, "bold"),
                fill=self.COLOR_ACK
            )

            # Mini sender window updated after ACK
            s_start, s_end = event.sender_window
            self._draw_mini_window("sender", y_end, s_start, s_end, event.sender_base if event.sender_base < self.num_frames else None, pointer_label="S")
            self._expand_scroll(y_end)

            def _finish_ack():
                self.canvas.delete(f["dot_id"])
                if on_done:
                    on_done()

            self._animate_flight(uid, f["progress"], 1.0, step_duration_ms, _finish_ack)

        elif ev_type == "ACK_LOST":
            f = self.flights.get(uid)
            if not f:
                if on_done:
                    on_done()
                return

            y_start = f["y1"]
            y_end = f["y2"]
            f["color"] = self.COLOR_LOST
            self.canvas.itemconfig(f["line_id"], fill=self.COLOR_LOST)
            self.canvas.itemconfig(f["dot_id"], fill=self.COLOR_LOST)

            def _finish_ack_lost():
                self.canvas.delete(f["dot_id"])
                bx = self.receiver_x + (self.sender_x - self.receiver_x) * 0.56
                by = y_start + (y_end - y_start) * 0.56
                self.canvas.create_text(
                    bx, by + 12,
                    text=f"X ({f['label']} Lost)",
                    font=("Segoe UI", 8, "bold"),
                    fill=self.COLOR_LOST
                )
                if on_done:
                    on_done()

            self._animate_flight(uid, f["progress"], 0.56, step_duration_ms, _finish_ack_lost)

        elif ev_type == "TIMEOUT":
            y_t = max(self.next_sender_y, self.next_receiver_y - 10)
            self.next_sender_y = y_t + 34
            self.canvas.create_rectangle(
                self.sender_x - 104, y_t - 10, self.sender_x - 8, y_t + 10,
                fill="#fff7ed", outline=self.COLOR_RETRANSMIT, width=1.5
            )
            self.canvas.create_text(
                self.sender_x - 56, y_t,
                text=f"Timeout F{event.frame_id}",
                font=("Segoe UI", 8, "bold"),
                fill=self.COLOR_RETRANSMIT
            )
            self._expand_scroll(y_t)
            if instant:
                if on_done:
                    on_done()
            else:
                self._arrow_anim_after = self.after(max(40, step_duration_ms // 2), lambda: on_done() if on_done else None)

        elif ev_type in ("SIMULATION_COMPLETED", "SIMULATION_ABORTED"):
            y_end = max(self.next_sender_y, self.next_receiver_y) + 20
            is_comp = (ev_type == "SIMULATION_COMPLETED")
            b_color = self.COLOR_SUCCESS if is_comp else self.COLOR_LOST
            b_text = "SIMULATION COMPLETED" if is_comp else "SIMULATION STOPPED"
            self.canvas.create_rectangle(
                self.sender_x - 30, y_end - 13, self.receiver_x + 30, y_end + 13,
                fill="#f8fafc", outline=b_color, width=2
            )
            self.canvas.create_text(
                (self.sender_x + self.receiver_x) / 2, y_end,
                text=b_text, font=("Segoe UI", 9, "bold"), fill=b_color
            )
            self._expand_scroll(y_end + 30)
            if on_done:
                on_done()
        else:
            if on_done:
                on_done()

    def _animate_flight(
        self,
        uid: str,
        start_p: float,
        end_p: float,
        duration_ms: int,
        on_done: Optional[Callable[[], None]]
    ) -> None:
        f = self.flights[uid]
        if duration_ms <= 0:
            cx = f["x1"] + (f["x2"] - f["x1"]) * end_p
            cy = f["y1"] + (f["y2"] - f["y1"]) * end_p
            self.canvas.coords(f["line_id"], f["x1"], f["y1"], cx, cy)
            f["progress"] = end_p
            if on_done:
                on_done()
            return

        sub_steps = 12
        tick_ms = max(16, duration_ms // sub_steps)
        state = {
            "uid": uid, "start_p": start_p, "end_p": end_p,
            "step": 1, "sub_steps": sub_steps, "tick_ms": tick_ms,
            "on_done": on_done
        }
        self._pending_anim_state = state
        self._run_anim_step()

    def _run_anim_step(self) -> None:
        if self._arrow_anim_paused or not self._pending_anim_state:
            return

        st = self._pending_anim_state
        f = self.flights.get(st["uid"])
        if not f:
            self._pending_anim_state = None
            if st["on_done"]:
                st["on_done"]()
            return

        k = st["step"]
        total = st["sub_steps"]
        p = st["start_p"] + (st["end_p"] - st["start_p"]) * (k / total)
        cx = f["x1"] + (f["x2"] - f["x1"]) * p
        cy = f["y1"] + (f["y2"] - f["y1"]) * p

        self.canvas.coords(f["line_id"], f["x1"], f["y1"], cx, cy)
        self.canvas.coords(f["dot_id"], cx - 4, cy - 4, cx + 4, cy + 4)
        f["progress"] = p

        if k < total:
            st["step"] += 1
            self._arrow_anim_after = self.after(st["tick_ms"], self._run_anim_step)
        else:
            self._arrow_anim_after = None
            self._pending_anim_state = None
            if st["on_done"]:
                st["on_done"]()

    def pause_animation(self) -> None:
        self._arrow_anim_paused = True
        if self._arrow_anim_after:
            self.after_cancel(self._arrow_anim_after)
            self._arrow_anim_after = None

    def resume_animation(self) -> None:
        if self._arrow_anim_paused:
            self._arrow_anim_paused = False
            if self._pending_anim_state:
                self._run_anim_step()


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
