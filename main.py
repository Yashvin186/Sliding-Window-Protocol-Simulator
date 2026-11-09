"""
main.py
-------
Application entry point and Tkinter Desktop UI for the Sliding Window Protocol Simulator.

Supports:
- One-Bit Sliding Window (Stop-and-Wait ARQ)
- Go-Back-N ARQ
- Selective Repeat ARQ
- All Protocols (Comparison Mode with Table and Matplotlib Bar Charts)

Key UI features:
- Input configuration with robust validation
- Live Sender-Receiver diagram on Tkinter Canvas
- Live window status indicators (Sender window, Receiver window, Active frame, Timeouts)
- Live performance statistics panel
- Millisecond-accurate event log
- Non-blocking animation loop with Start, Pause, Resume, Reset, and Speed controls
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional

# Ensure package modules can be imported
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from protocols import ProtocolType
from simulator import SimulationConfig, SimulationEvent, SimulationStats, Simulator
from visualization import ComparisonVisualizer, SenderReceiverCanvas


class SlidingWindowApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Sliding Window Protocol Simulator - Computer Networks")
        self.geometry("1180x820")
        self.minsize(980, 700)

        # Style configuration
        self._configure_styles()

        # Simulation state
        self.current_simulator: Optional[Simulator] = None
        self.events_to_replay: List[SimulationEvent] = []
        self.replay_idx: int = 0
        self.is_paused: bool = False
        self.is_running: bool = False
        self.after_id: Optional[str] = None
        self.speed_multiplier: float = 1.0

        # Construct UI
        self._create_layout()

        # Initial state setup
        self._on_protocol_change()

    def _configure_styles(self) -> None:
        self.style = ttk.Style(self)
        # Use 'clam' or default platform theme
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.configure(".", font=("Segoe UI", 9))
        self.style.configure("TLabel", foreground="#1e293b")
        self.style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), foreground="#0f172a")
        self.style.configure("Status.TLabel", font=("Segoe UI", 9, "bold"), foreground="#2563eb")
        self.style.configure("Value.TLabel", font=("Segoe UI", 9, "bold"), foreground="#0284c7")

        # Buttons
        self.style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), background="#0284c7", foreground="#ffffff")
        self.style.map("Accent.TButton", background=[("active", "#0369a1")])

    def _create_layout(self) -> None:
        # Top title banner
        banner = tk.Frame(self, bg="#1e293b", height=50)
        banner.pack(side=tk.TOP, fill=tk.X)
        title_lbl = tk.Label(
            banner,
            text="SLIDING WINDOW PROTOCOL SIMULATOR",
            font=("Segoe UI", 13, "bold"),
            bg="#1e293b",
            fg="#f8fafc"
        )
        title_lbl.pack(side=tk.LEFT, padx=16, pady=8)

        subtitle_lbl = tk.Label(
            banner,
            text="Stop-and-Wait | Go-Back-N | Selective Repeat",
            font=("Segoe UI", 9),
            bg="#1e293b",
            fg="#94a3b8"
        )
        subtitle_lbl.pack(side=tk.RIGHT, padx=16, pady=10)

        # Main horizontal paned or side-by-side frame
        main_content = ttk.Frame(self)
        main_content.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # LEFT COLUMN: Configuration and Statistics
        left_panel = ttk.Frame(main_content, width=320)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        self._create_config_section(left_panel)
        self._create_stats_section(left_panel)

        # RIGHT COLUMN: Visualization & Comparison & Event Log
        right_panel = ttk.Frame(main_content)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._create_main_viz_section(right_panel)

    def _create_config_section(self, parent: ttk.Frame) -> None:
        cfg_frame = ttk.LabelFrame(parent, text="Simulation Configuration", padding=10)
        cfg_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))

        # Protocol selection
        ttk.Label(cfg_frame, text="Protocol:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=3)
        self.protocol_var = tk.StringVar(value=ProtocolType.GO_BACK_N.value)
        self.protocol_combo = ttk.Combobox(
            cfg_frame,
            textvariable=self.protocol_var,
            values=[
                ProtocolType.ONE_BIT.value,
                ProtocolType.GO_BACK_N.value,
                ProtocolType.SELECTIVE_REPEAT.value,
                ProtocolType.COMPARISON.value
            ],
            state="readonly",
            width=28
        )
        self.protocol_combo.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 6))
        self.protocol_combo.bind("<<ComboboxSelected>>", lambda e: self._on_protocol_change())

        # Inputs grid
        row = 2

        # Window Size
        ttk.Label(cfg_frame, text="Window Size (N):").grid(row=row, column=0, sticky="w", pady=2)
        self.win_size_var = tk.StringVar(value="4")
        self.win_size_entry = ttk.Entry(cfg_frame, textvariable=self.win_size_var, width=10)
        self.win_size_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # Number of Frames
        ttk.Label(cfg_frame, text="Number of Frames:").grid(row=row, column=0, sticky="w", pady=2)
        self.num_frames_var = tk.StringVar(value="10")
        self.num_frames_entry = ttk.Entry(cfg_frame, textvariable=self.num_frames_var, width=10)
        self.num_frames_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # Transmission Delay (ms)
        ttk.Label(cfg_frame, text="Tx Delay (ms):").grid(row=row, column=0, sticky="w", pady=2)
        self.tx_delay_var = tk.StringVar(value="100")
        self.tx_delay_entry = ttk.Entry(cfg_frame, textvariable=self.tx_delay_var, width=10)
        self.tx_delay_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # ACK Delay (ms)
        ttk.Label(cfg_frame, text="ACK Delay (ms):").grid(row=row, column=0, sticky="w", pady=2)
        self.ack_delay_var = tk.StringVar(value="50")
        self.ack_delay_entry = ttk.Entry(cfg_frame, textvariable=self.ack_delay_var, width=10)
        self.ack_delay_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # Packet Loss (%)
        ttk.Label(cfg_frame, text="Packet Loss (%):").grid(row=row, column=0, sticky="w", pady=2)
        self.pkt_loss_var = tk.StringVar(value="10")
        self.pkt_loss_entry = ttk.Entry(cfg_frame, textvariable=self.pkt_loss_var, width=10)
        self.pkt_loss_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # ACK Loss (%)
        ttk.Label(cfg_frame, text="ACK Loss (%):").grid(row=row, column=0, sticky="w", pady=2)
        self.ack_loss_var = tk.StringVar(value="5")
        self.ack_loss_entry = ttk.Entry(cfg_frame, textvariable=self.ack_loss_var, width=10)
        self.ack_loss_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # Timeout (ms)
        ttk.Label(cfg_frame, text="Timeout (ms):").grid(row=row, column=0, sticky="w", pady=2)
        self.timeout_var = tk.StringVar(value="300")
        self.timeout_entry = ttk.Entry(cfg_frame, textvariable=self.timeout_var, width=10)
        self.timeout_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # Random Seed (Reproducibility)
        ttk.Label(cfg_frame, text="Random Seed:").grid(row=row, column=0, sticky="w", pady=2)
        self.seed_var = tk.StringVar(value="42")
        self.seed_entry = ttk.Entry(cfg_frame, textvariable=self.seed_var, width=10)
        self.seed_entry.grid(row=row, column=1, sticky="e", pady=2)
        row += 1

        # Animation Speed
        ttk.Label(cfg_frame, text="Playback Speed:").grid(row=row, column=0, sticky="w", pady=(6, 2))
        self.speed_var = tk.StringVar(value="1x (Normal)")
        self.speed_combo = ttk.Combobox(
            cfg_frame,
            textvariable=self.speed_var,
            values=["0.5x (Slow)", "1x (Normal)", "2x (Fast)", "5x (Very Fast)", "Instant"],
            state="readonly",
            width=12
        )
        self.speed_combo.grid(row=row, column=1, sticky="e", pady=(6, 2))
        self.speed_combo.bind("<<ComboboxSelected>>", lambda e: self._on_speed_change())
        row += 1

        # Buttons
        btn_frame = ttk.Frame(cfg_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, sticky="we", pady=(10, 0))

        self.btn_start = tk.Button(
            btn_frame,
            text="START SIMULATION",
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=6,
            pady=4,
            command=self.start_simulation
        )
        self.btn_start.pack(fill=tk.X, pady=2)

        ctrl_row = ttk.Frame(btn_frame)
        ctrl_row.pack(fill=tk.X, pady=2)

        self.btn_pause = ttk.Button(ctrl_row, text="PAUSE", command=self.toggle_pause, state=tk.DISABLED)
        self.btn_pause.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        self.btn_reset = ttk.Button(ctrl_row, text="RESET", command=self.reset_simulation)
        self.btn_reset.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))

    def _create_stats_section(self, parent: ttk.Frame) -> None:
        stats_frame = ttk.LabelFrame(parent, text="Live Performance Statistics", padding=10)
        stats_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.stat_labels: dict[str, ttk.Label] = {}
        metrics = [
            ("Total Transmissions", "0"),
            ("Retransmissions", "0"),
            ("Packets Lost", "0"),
            ("ACKs Received", "0"),
            ("Timeouts", "0"),
            ("Delivered Frames", "0"),
            ("Pending / Failed", "0"),
            ("Total Time (ms)", "0"),
            ("Throughput (fps)", "0.00"),
            ("Efficiency (%)", "0.00%")
        ]

        for idx, (label_text, default_val) in enumerate(metrics):
            ttk.Label(stats_frame, text=f"{label_text}:", font=("Segoe UI", 8)).grid(row=idx, column=0, sticky="w", pady=1)
            val_lbl = ttk.Label(stats_frame, text=default_val, font=("Segoe UI", 8, "bold"), foreground="#0369a1")
            val_lbl.grid(row=idx, column=1, sticky="e", pady=1)
            self.stat_labels[label_text] = val_lbl

        stats_frame.columnconfigure(0, weight=1)
        stats_frame.columnconfigure(1, weight=1)

        # Efficiency note
        eff_note = ttk.Label(
            stats_frame,
            text="* Efficiency: (Delivered x TxDelay / Total Time) x 100\n  Simplified educational metric.",
            font=("Segoe UI", 7, "italic"),
            foreground="#64748b"
        )
        eff_note.grid(row=len(metrics), column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _create_main_viz_section(self, parent: ttk.Frame) -> None:
        # Notebook with 2 Tabs:
        # Tab 1: Protocol Simulation Visualization
        # Tab 2: Comparison Mode (Charts & Table)
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # --- TAB 1: Main Simulation ---
        self.tab_sim = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_sim, text="Interactive Simulation")

        # Top Live Status Indicator Bar
        status_bar = ttk.Frame(self.tab_sim, padding=(6, 4))
        status_bar.pack(side=tk.TOP, fill=tk.X)

        self.lbl_curr_frame = ttk.Label(status_bar, text="Frame: --", font=("Segoe UI", 9, "bold"), foreground="#1e293b")
        self.lbl_curr_frame.pack(side=tk.LEFT, padx=8)

        self.lbl_sender_win = ttk.Label(status_bar, text="Sender Win: []", font=("Segoe UI", 9), foreground="#0369a1")
        self.lbl_sender_win.pack(side=tk.LEFT, padx=8)

        self.lbl_rcvr_win = ttk.Label(status_bar, text="Receiver Win: []", font=("Segoe UI", 9), foreground="#059669")
        self.lbl_rcvr_win.pack(side=tk.LEFT, padx=8)

        self.lbl_delivered = ttk.Label(status_bar, text="Delivered: 0", font=("Segoe UI", 9), foreground="#16a34a")
        self.lbl_delivered.pack(side=tk.LEFT, padx=8)

        self.lbl_retx = ttk.Label(status_bar, text="Retx: 0", font=("Segoe UI", 9), foreground="#d97706")
        self.lbl_retx.pack(side=tk.LEFT, padx=8)

        # Vertical PanedWindow providing a draggable divider slider between Canvas and Event Log
        self.sim_paned = ttk.PanedWindow(self.tab_sim, orient=tk.VERTICAL)
        self.sim_paned.pack(fill=tk.BOTH, expand=True)

        # Canvas for Sender-Receiver arrows (Top Pane)
        self.viz_canvas = SenderReceiverCanvas(self.sim_paned)
        self.sim_paned.add(self.viz_canvas, weight=4)

        # Bottom Event Log (Bottom Pane) with vertical & horizontal scrollbars and size slider
        log_frame = ttk.LabelFrame(self.sim_paned, text="Simulation Event Log", padding=4)
        self.sim_paned.add(log_frame, weight=1)

        # Log Toolbar with Height Slider & Controls
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 3))

        ttk.Label(log_toolbar, text="Log Height Slider:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 6))

        self.log_height_slider = ttk.Scale(
            log_toolbar,
            from_=4,
            to=25,
            value=7,
            orient=tk.HORIZONTAL,
            length=140,
            command=self._on_log_height_slide
        )
        self.log_height_slider.pack(side=tk.LEFT, padx=(0, 8))

        self.lbl_log_lines = ttk.Label(log_toolbar, text="7 lines", font=("Segoe UI", 8, "bold"), foreground="#0369a1")
        self.lbl_log_lines.pack(side=tk.LEFT, padx=(0, 12))

        btn_clear_log = ttk.Button(log_toolbar, text="Clear Log", command=self._clear_event_log)
        btn_clear_log.pack(side=tk.RIGHT, padx=4)

        # Log Text Area with Vertical & Horizontal Scrollbar Sliders
        log_container = ttk.Frame(log_frame)
        log_container.pack(fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(log_container, orient=tk.VERTICAL)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        h_scroll = ttk.Scrollbar(log_container, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.log_text = tk.Text(
            log_container,
            height=7,
            font=("Consolas", 9),
            bg="#f8fafc",
            fg="#1e293b",
            wrap=tk.NONE,
            xscrollcommand=h_scroll.set,
            yscrollcommand=v_scroll.set
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scroll.config(command=self.log_text.yview)
        h_scroll.config(command=self.log_text.xview)

        # --- TAB 2: Comparison Mode ---
        self.tab_comparison = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_comparison, text="Protocol Comparison Mode")

        self.comp_visualizer = ComparisonVisualizer(self.tab_comparison)
        self.comp_visualizer.pack(fill=tk.BOTH, expand=True)

    def _on_protocol_change(self) -> None:
        sel = self.protocol_var.get()
        if sel == ProtocolType.ONE_BIT.value:
            self.win_size_var.set("1")
            self.win_size_entry.configure(state="disabled")
        else:
            self.win_size_entry.configure(state="normal")
            if self.win_size_var.get() == "1" and sel != ProtocolType.ONE_BIT.value:
                self.win_size_var.set("4")

        # Automatically select comparison tab when comparison protocol is chosen
        if sel == ProtocolType.COMPARISON.value:
            self.notebook.select(self.tab_comparison)
        else:
            self.notebook.select(self.tab_sim)

    def _on_speed_change(self) -> None:
        sel = self.speed_var.get()
        if "0.5x" in sel:
            self.speed_multiplier = 0.5
        elif "1x" in sel:
            self.speed_multiplier = 1.0
        elif "2x" in sel:
            self.speed_multiplier = 2.0
        elif "5x" in sel:
            self.speed_multiplier = 5.0
        elif "Instant" in sel:
            self.speed_multiplier = 9999.0

    def _on_log_height_slide(self, val: str) -> None:
        """Dynamically adjusts the text log height when user drags the slider."""
        lines = int(float(val))
        self.log_text.configure(height=lines)
        self.lbl_log_lines.configure(text=f"{lines} lines")

    def _clear_event_log(self) -> None:
        """Clears the event log text area."""
        self.log_text.delete("1.0", tk.END)

    def _validate_inputs(self) -> Optional[SimulationConfig]:
        """Validates configuration parameters according to section 2 rules."""
        try:
            proto_str = self.protocol_var.get()
            proto = ProtocolType(proto_str)

            w_size = int(self.win_size_var.get().strip())
            if w_size < 1:
                messagebox.showerror("Validation Error", "Window size must be at least 1.")
                return None

            n_frames = int(self.num_frames_var.get().strip())
            if n_frames <= 0:
                messagebox.showerror("Validation Error", "Number of frames must be greater than 0.")
                return None

            tx_d = float(self.tx_delay_var.get().strip())
            if tx_d <= 0:
                messagebox.showerror("Validation Error", "Transmission delay must be positive.")
                return None

            ack_d = float(self.ack_delay_var.get().strip())
            if ack_d <= 0:
                messagebox.showerror("Validation Error", "ACK delay must be positive.")
                return None

            p_loss = float(self.pkt_loss_var.get().strip())
            if not (0.0 <= p_loss <= 100.0):
                messagebox.showerror("Validation Error", "Packet loss must be between 0 and 100%.")
                return None

            a_loss = float(self.ack_loss_var.get().strip())
            if not (0.0 <= a_loss <= 100.0):
                messagebox.showerror("Validation Error", "ACK loss must be between 0 and 100%.")
                return None

            t_out = float(self.timeout_var.get().strip())
            if t_out <= 0:
                messagebox.showerror("Validation Error", "Timeout must be positive.")
                return None

            seed_str = self.seed_var.get().strip()
            seed = int(seed_str) if seed_str else None

            return SimulationConfig(
                protocol=proto,
                window_size=w_size,
                num_frames=n_frames,
                tx_delay=tx_d,
                ack_delay=ack_d,
                packet_loss_pct=p_loss,
                ack_loss_pct=a_loss,
                timeout_ms=t_out,
                seed=seed
            )
        except ValueError as err:
            messagebox.showerror("Input Error", f"Invalid input format: {err}")
            return None

    def start_simulation(self) -> None:
        """Starts a fresh simulation or runs comparison mode."""
        self.reset_simulation()

        config = self._validate_inputs()
        if not config:
            return

        if config.protocol == ProtocolType.COMPARISON:
            self._run_comparison_mode(config)
            return

        # Single Protocol Simulation Mode
        self.current_simulator = Simulator(config)
        self.current_simulator.run()
        self.events_to_replay = self.current_simulator.events
        self.replay_idx = 0

        self.is_running = True
        self.is_paused = False
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_pause.configure(state=tk.NORMAL, text="PAUSE")

        # If instant mode, replay all events immediately
        if self.speed_multiplier >= 1000.0:
            for ev in self.events_to_replay:
                self._apply_event_to_ui(ev)
            self._finalize_simulation(self.current_simulator.stats)
        else:
            self._schedule_next_event()

    def _schedule_next_event(self) -> None:
        if not self.is_running or self.is_paused:
            return

        if self.replay_idx >= len(self.events_to_replay):
            if self.current_simulator:
                self._finalize_simulation(self.current_simulator.stats)
            return

        ev = self.events_to_replay[self.replay_idx]
        self._apply_event_to_ui(ev)
        self.replay_idx += 1

        # Calculate delay to next event
        if self.replay_idx < len(self.events_to_replay):
            next_ev = self.events_to_replay[self.replay_idx]
            sim_delta_ms = max(5.0, next_ev.time_ms - ev.time_ms)
            gui_delay_ms = int(sim_delta_ms / self.speed_multiplier)
            # Bound GUI delay between 15ms and 800ms for smooth visibility
            gui_delay_ms = max(15, min(gui_delay_ms, 800))
        else:
            gui_delay_ms = 20

        self.after_id = self.after(gui_delay_ms, self._schedule_next_event)

    def _apply_event_to_ui(self, ev: SimulationEvent) -> None:
        # 1. Update Canvas
        self.viz_canvas.add_event(ev)

        # 2. Append to Event Log
        self.log_text.insert(tk.END, ev.description + "\n")
        self.log_text.see(tk.END)

        # 3. Update Status Indicators
        f_text = f"Frame {ev.frame_id}" if ev.frame_id >= 0 else "--"
        if ev.is_retransmit:
            f_text += " [Retx]"
        self.lbl_curr_frame.configure(text=f"Frame: {f_text}")

        s_start, s_end = ev.sender_window
        sender_frames = list(range(s_start, s_end + 1)) if s_start <= s_end else []
        self.lbl_sender_win.configure(text=f"Sender Win: {sender_frames}")

        r_start, r_end = ev.receiver_window
        rcvr_frames = list(range(r_start, r_end + 1)) if r_start <= r_end else []
        self.lbl_rcvr_win.configure(text=f"Receiver Win: {rcvr_frames}")

        self.lbl_delivered.configure(text=f"Delivered: {ev.delivered_count}")

        # Update stats live
        if self.current_simulator:
            st = self.current_simulator.stats
            self.lbl_retx.configure(text=f"Retx: {st.num_retransmissions}")
            self._update_stats_display(st)

    def _update_stats_display(self, st: SimulationStats) -> None:
        self.stat_labels["Total Transmissions"].configure(text=str(st.total_frames_transmitted))
        self.stat_labels["Retransmissions"].configure(text=str(st.num_retransmissions))
        self.stat_labels["Packets Lost"].configure(text=str(st.packets_lost))
        self.stat_labels["ACKs Received"].configure(text=str(st.acks_received))
        self.stat_labels["Timeouts"].configure(text=str(st.timeouts))
        self.stat_labels["Delivered Frames"].configure(text=str(st.delivered_frames))
        self.stat_labels["Pending / Failed"].configure(text=str(st.pending_or_failed_frames))
        self.stat_labels["Total Time (ms)"].configure(text=f"{int(st.total_time_ms)}")
        self.stat_labels["Throughput (fps)"].configure(text=f"{st.throughput_fps:.2f}")
        self.stat_labels["Efficiency (%)"].configure(text=f"{st.efficiency_pct:.1f}%")

    def _finalize_simulation(self, st: SimulationStats) -> None:
        self.is_running = False
        self.btn_start.configure(state=tk.NORMAL)
        self.btn_pause.configure(state=tk.DISABLED, text="PAUSE")
        self._update_stats_display(st)

        # Completion summary in log
        status_msg = "Completed successfully." if not st.aborted else f"Aborted: {st.abort_reason}"
        self.log_text.insert(tk.END, f"\n=== SIMULATION SUMMARY ===\nStatus: {status_msg}\n")
        self.log_text.insert(
            tk.END,
            f"Delivered: {st.delivered_frames} | Retransmissions: {st.num_retransmissions} | "
            f"Throughput: {st.throughput_fps:.2f} fps | Efficiency: {st.efficiency_pct:.1f}%\n"
        )
        self.log_text.see(tk.END)

    def toggle_pause(self) -> None:
        if not self.is_running:
            return
        if self.is_paused:
            self.is_paused = False
            self.btn_pause.configure(text="PAUSE")
            self._schedule_next_event()
        else:
            self.is_paused = True
            self.btn_pause.configure(text="RESUME")
            if self.after_id:
                self.after_cancel(self.after_id)
                self.after_id = None

    def reset_simulation(self) -> None:
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None

        self.is_running = False
        self.is_paused = False
        self.replay_idx = 0
        self.events_to_replay = []
        self.current_simulator = None

        self.btn_start.configure(state=tk.NORMAL)
        self.btn_pause.configure(state=tk.DISABLED, text="PAUSE")

        # Reset UI elements
        self.viz_canvas.reset()
        self.log_text.delete("1.0", tk.END)
        self.lbl_curr_frame.configure(text="Frame: --")
        self.lbl_sender_win.configure(text="Sender Win: []")
        self.lbl_rcvr_win.configure(text="Receiver Win: []")
        self.lbl_delivered.configure(text="Delivered: 0")
        self.lbl_retx.configure(text="Retx: 0")

        empty_stats = SimulationStats()
        self._update_stats_display(empty_stats)

    def _run_comparison_mode(self, base_config: SimulationConfig) -> None:
        """
        Executes all three protocols under identical network conditions and random seed,
        then displays comparison table and Matplotlib charts.
        """
        self.notebook.select(self.tab_comparison)

        # 1. One-Bit Sliding Window
        c1 = SimulationConfig(
            protocol=ProtocolType.ONE_BIT,
            window_size=1,
            num_frames=base_config.num_frames,
            tx_delay=base_config.tx_delay,
            ack_delay=base_config.ack_delay,
            packet_loss_pct=base_config.packet_loss_pct,
            ack_loss_pct=base_config.ack_loss_pct,
            timeout_ms=base_config.timeout_ms,
            seed=base_config.seed
        )
        sim1 = Simulator(c1)
        s1 = sim1.run()

        # 2. Go-Back-N
        c2 = SimulationConfig(
            protocol=ProtocolType.GO_BACK_N,
            window_size=base_config.window_size,
            num_frames=base_config.num_frames,
            tx_delay=base_config.tx_delay,
            ack_delay=base_config.ack_delay,
            packet_loss_pct=base_config.packet_loss_pct,
            ack_loss_pct=base_config.ack_loss_pct,
            timeout_ms=base_config.timeout_ms,
            seed=base_config.seed
        )
        sim2 = Simulator(c2)
        s2 = sim2.run()

        # 3. Selective Repeat
        c3 = SimulationConfig(
            protocol=ProtocolType.SELECTIVE_REPEAT,
            window_size=base_config.window_size,
            num_frames=base_config.num_frames,
            tx_delay=base_config.tx_delay,
            ack_delay=base_config.ack_delay,
            packet_loss_pct=base_config.packet_loss_pct,
            ack_loss_pct=base_config.ack_loss_pct,
            timeout_ms=base_config.timeout_ms,
            seed=base_config.seed
        )
        sim3 = Simulator(c3)
        s3 = sim3.run()

        # Display in comparison tab
        self.comp_visualizer.display_results(s1, s2, s3)


def main():
    app = SlidingWindowApp()
    app.mainloop()


if __name__ == "__main__":
    main()

