"""
simulator.py
------------
Discrete-Event Simulation (DES) Engine for Sliding Window Protocols.

Handles:
- Event scheduling with priority queue
- Frame and ACK transmission delay
- Deterministic and random packet loss and ACK loss
- Retransmission timers (single timer for GBN/One-Bit, individual for SR)
- Retransmission counters and safe termination (retry limit)
- Accurate performance statistics calculation
"""

import copy
from dataclasses import dataclass, field
import heapq
import random
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from protocols import BaseProtocol, GoBackN, OneBitSlidingWindow, ProtocolType, SelectiveRepeat


@dataclass
class SimulationConfig:
    protocol: ProtocolType
    window_size: int = 4
    num_frames: int = 10
    tx_delay: float = 100.0        # ms
    ack_delay: float = 50.0        # ms
    packet_loss_pct: float = 10.0  # 0 to 100
    ack_loss_pct: float = 5.0      # 0 to 100
    timeout_ms: float = 300.0      # ms
    seed: Optional[int] = None
    max_retries_per_frame: int = 10
    max_simulation_time_ms: float = 100000.0  # Safe upper ceiling

    # Custom hooks for testing / forced loss
    forced_frame_losses: Optional[Set[Tuple[int, int]]] = None  # (frame_id, attempt_idx)
    forced_ack_losses: Optional[Set[Tuple[int, int]]] = None    # (ack_id, attempt_idx)


@dataclass
class SimulationStats:
    total_frames_transmitted: int = 0
    num_retransmissions: int = 0
    packets_lost: int = 0
    acks_received: int = 0
    acks_lost: int = 0
    timeouts: int = 0
    delivered_frames: int = 0
    pending_or_failed_frames: int = 0
    total_time_ms: float = 0.0
    throughput_fps: float = 0.0
    efficiency_pct: float = 0.0
    aborted: bool = False
    abort_reason: str = ""

    def calculate(self, num_frames: int, tx_delay: float) -> None:
        """Compute final throughput and educational efficiency."""
        self.pending_or_failed_frames = max(0, num_frames - self.delivered_frames)
        total_sec = self.total_time_ms / 1000.0
        if total_sec > 0:
            self.throughput_fps = round(self.delivered_frames / total_sec, 2)
        else:
            self.throughput_fps = 0.0

        if self.total_time_ms > 0:
            # Useful data transmission time = successfully delivered unique frames * tx_delay
            useful_time = self.delivered_frames * tx_delay
            self.efficiency_pct = round((useful_time / self.total_time_ms) * 100.0, 2)
        else:
            self.efficiency_pct = 0.0


@dataclass
class SimulationEvent:
    time_ms: float
    event_type: str
    frame_id: int
    attempt_idx: int = 0
    seq_num: Optional[int] = None
    ack_id: Optional[int] = None
    is_retransmit: bool = False
    description: str = ""
    sender_window: Tuple[int, int] = (0, 0)
    receiver_window: Tuple[int, int] = (0, 0)
    delivered_count: int = 0
    # Visual cues: 'green', 'red', 'orange', 'blue', 'grey'
    visual_color: str = "grey"
    # Direction: 's2r' (sender to receiver), 'r2s' (receiver to sender), 'sender', 'receiver'
    direction: str = "sender"
    is_delivered: bool = False
    is_duplicate: bool = False
    is_buffered: bool = False
    # Pairing and live animation snapshot fields
    packet_uid: str = ""
    sender_base: int = 0
    sender_next: int = 0
    sender_acked: List[int] = field(default_factory=list)
    receiver_delivered: List[int] = field(default_factory=list)
    receiver_buffered: List[int] = field(default_factory=list)
    stats_snapshot: Optional[SimulationStats] = None


class Simulator:
    """Discrete Event Simulator for sliding window network protocols."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.rng = random.Random(config.seed if config.seed is not None else random.randint(1, 1000000))

        # Protocol instance
        if config.protocol == ProtocolType.ONE_BIT:
            self.protocol: BaseProtocol = OneBitSlidingWindow(config.num_frames, window_size=1)
        elif config.protocol == ProtocolType.GO_BACK_N:
            self.protocol = GoBackN(config.num_frames, config.window_size)
        elif config.protocol == ProtocolType.SELECTIVE_REPEAT:
            self.protocol = SelectiveRepeat(config.num_frames, config.window_size)
        else:
            raise ValueError(f"Unknown protocol: {config.protocol}")

        self.stats = SimulationStats()
        self.events: List[SimulationEvent] = []

        # Internal tracking
        self.current_time_ms: float = 0.0
        self.frame_attempts: Dict[int, int] = {i: 0 for i in range(config.num_frames)}
        self.ack_attempts: Dict[int, int] = {}
        self.frame_retries: Dict[int, int] = {i: 0 for i in range(config.num_frames)}

        # Active timers: frame_id -> expiration_time_ms (or 'gbn' -> expiration_time_ms)
        self.active_timers: Dict[Any, float] = {}
        self.timer_counter: int = 0

        # Event queue: min-heap of (time_ms, counter, event_type, data)
        self.queue: List[Tuple[float, int, str, Dict[str, Any]]] = []
        self._seq_counter: int = 0

    def _push_event(self, time_ms: float, event_type: str, data: Dict[str, Any]) -> None:
        self._seq_counter += 1
        heapq.heappush(self.queue, (time_ms, self._seq_counter, event_type, data))

    def _record_event(self, **kwargs) -> None:
        """Creates a SimulationEvent with live state and stats snapshots."""
        snap = copy.copy(self.stats)
        snap.delivered_frames = len(self.protocol.delivered_frames)
        snap.total_time_ms = self.current_time_ms
        snap.calculate(self.config.num_frames, self.config.tx_delay)

        ev = SimulationEvent(
            time_ms=self.current_time_ms,
            sender_window=self.protocol.get_sender_window(),
            receiver_window=self.protocol.get_receiver_window(),
            delivered_count=len(self.protocol.delivered_frames),
            sender_base=self.protocol.sender_base,
            sender_next=self.protocol.next_frame_to_send,
            sender_acked=self.protocol.get_acked_frames(),
            receiver_delivered=list(self.protocol.delivered_frames),
            receiver_buffered=self.protocol.get_buffered_frames(),
            stats_snapshot=snap,
            **kwargs
        )
        self.events.append(ev)

    def _should_drop_frame(self, frame_id: int, attempt: int) -> bool:
        if self.config.forced_frame_losses is not None:
            return (frame_id, attempt) in self.config.forced_frame_losses
        if self.config.packet_loss_pct <= 0.0:
            return False
        if self.config.packet_loss_pct >= 100.0:
            return True
        return (self.rng.random() * 100.0) < self.config.packet_loss_pct

    def _should_drop_ack(self, ack_id: int, attempt: int) -> bool:
        if self.config.forced_ack_losses is not None:
            return (ack_id, attempt) in self.config.forced_ack_losses
        if self.config.ack_loss_pct <= 0.0:
            return False
        if self.config.ack_loss_pct >= 100.0:
            return True
        return (self.rng.random() * 100.0) < self.config.ack_loss_pct

    def _start_timer(self, key: Any, expire_at: float) -> None:
        self.active_timers[key] = expire_at
        self._push_event(expire_at, "TIMEOUT_CHECK", {"timer_key": key, "expected_expire": expire_at})

    def _stop_timer(self, key: Any) -> None:
        if key in self.active_timers:
            del self.active_timers[key]

    def _schedule_transmissions(self) -> None:
        """Checks if protocol sender can send new frames and schedules them."""
        while self.protocol.can_send():
            fid = self.protocol.next_frame_to_send
            self._send_frame(fid, is_retransmit=False)

    def _send_frame(self, frame_id: int, is_retransmit: bool) -> None:
        self.stats.total_frames_transmitted += 1
        self.frame_attempts[frame_id] += 1
        attempt = self.frame_attempts[frame_id]

        if is_retransmit:
            self.stats.num_retransmissions += 1
            self.frame_retries[frame_id] += 1

        # Protocol notification of frame sent
        seq = frame_id
        if isinstance(self.protocol, OneBitSlidingWindow):
            seq = self.protocol.on_frame_sent(frame_id)
        elif isinstance(self.protocol, (GoBackN, SelectiveRepeat)):
            self.protocol.on_frame_sent(frame_id)

        # Timers
        if isinstance(self.protocol, OneBitSlidingWindow):
            self._start_timer("stop_and_wait", self.current_time_ms + self.config.timeout_ms)
        elif isinstance(self.protocol, GoBackN):
            # GBN maintains a single timer for the base frame
            if "gbn_base" not in self.active_timers:
                self._start_timer("gbn_base", self.current_time_ms + self.config.timeout_ms)
        elif isinstance(self.protocol, SelectiveRepeat):
            # SR maintains individual timer for this frame
            self._start_timer(frame_id, self.current_time_ms + self.config.timeout_ms)

        color = "orange" if is_retransmit else "green"
        prefix = "Retransmitted" if is_retransmit else "transmitted"
        desc = f"[{int(self.current_time_ms)} ms] Sender {prefix} Frame {frame_id}."
        if isinstance(self.protocol, OneBitSlidingWindow):
            desc = f"[{int(self.current_time_ms)} ms] Sender {prefix} Frame {frame_id} (Seq {seq})."

        packet_uid = f"FRM_{frame_id}_{attempt}"
        self._record_event(
            event_type="FRAME_TX_START",
            frame_id=frame_id,
            attempt_idx=attempt,
            seq_num=seq,
            is_retransmit=is_retransmit,
            description=desc,
            visual_color=color,
            direction="s2r",
            packet_uid=packet_uid
        )

        # Check packet loss
        lost = self._should_drop_frame(frame_id, attempt)
        arrival_time = self.current_time_ms + self.config.tx_delay
        self._push_event(arrival_time, "FRAME_ARRIVE", {
            "frame_id": frame_id,
            "seq_num": seq,
            "attempt": attempt,
            "is_lost": lost,
            "is_retransmit": is_retransmit,
            "packet_uid": packet_uid
        })

    def run(self) -> SimulationStats:
        """Executes the discrete event simulation until completion or abort."""
        # Initial transmissions
        self._schedule_transmissions()

        while self.queue:
            time_ms, _, ev_type, data = heapq.heappop(self.queue)
            self.current_time_ms = time_ms

            # Safety check: simulation ceiling
            if self.current_time_ms > self.config.max_simulation_time_ms:
                self.stats.aborted = True
                self.stats.abort_reason = f"Exceeded maximum simulation time limit ({self.config.max_simulation_time_ms} ms)."
                self._record_event(
                    event_type="SIMULATION_ABORTED",
                    frame_id=-1,
                    description=f"[{int(self.current_time_ms)} ms] Simulation aborted: {self.stats.abort_reason}",
                    visual_color="red",
                    direction="sender"
                )
                break

            if ev_type == "FRAME_ARRIVE":
                self._handle_frame_arrive(data)

            elif ev_type == "ACK_ARRIVE":
                self._handle_ack_arrive(data)

            elif ev_type == "TIMEOUT_CHECK":
                self._handle_timeout_check(data)

            # Check if simulation is complete
            if self.protocol.is_complete():
                self._stop_timer("stop_and_wait")
                self._stop_timer("gbn_base")
                for fid in range(self.config.num_frames):
                    self._stop_timer(fid)

                self._record_event(
                    event_type="SIMULATION_COMPLETED",
                    frame_id=-1,
                    description=f"[{int(self.current_time_ms)} ms] All {self.config.num_frames} frames successfully delivered and acknowledged.",
                    visual_color="green",
                    direction="receiver"
                )
                break

        self.stats.delivered_frames = len(self.protocol.delivered_frames)
        self.stats.total_time_ms = self.current_time_ms
        self.stats.calculate(self.config.num_frames, self.config.tx_delay)
        return self.stats

    def _handle_frame_arrive(self, data: Dict[str, Any]) -> None:
        frame_id = data["frame_id"]
        seq_num = data["seq_num"]
        attempt = data["attempt"]
        is_lost = data["is_lost"]
        is_retransmit = data["is_retransmit"]
        packet_uid = data["packet_uid"]

        if is_lost:
            self.stats.packets_lost += 1
            desc = f"[{int(self.current_time_ms)} ms] Frame {frame_id} was lost in transit."
            self._record_event(
                event_type="FRAME_LOST",
                frame_id=frame_id,
                attempt_idx=attempt,
                seq_num=seq_num,
                is_retransmit=is_retransmit,
                description=desc,
                visual_color="red",
                direction="s2r",
                packet_uid=packet_uid
            )
            return

        # Frame arrived safely at receiver
        if isinstance(self.protocol, OneBitSlidingWindow):
            accepted, is_dup, ack_seq = self.protocol.on_frame_received(frame_id, seq_num)
            if accepted:
                desc = f"[{int(self.current_time_ms)} ms] Receiver received Frame {frame_id} (Seq {seq_num})."
            else:
                desc = f"[{int(self.current_time_ms)} ms] Receiver detected duplicate Frame {frame_id} (Seq {seq_num}). Discarded payload."

            self._record_event(
                event_type="FRAME_RECEIVED",
                frame_id=frame_id,
                attempt_idx=attempt,
                seq_num=seq_num,
                is_retransmit=is_retransmit,
                description=desc,
                visual_color="green",
                direction="receiver",
                is_delivered=accepted,
                is_duplicate=is_dup,
                packet_uid=packet_uid
            )
            # Send ACK
            self._send_ack(ack_id=ack_seq, frame_id=frame_id)

        elif isinstance(self.protocol, GoBackN):
            accepted, is_ooo, cumulative_ack = self.protocol.on_frame_received(frame_id)
            if accepted:
                desc = f"[{int(self.current_time_ms)} ms] Receiver received Frame {frame_id}."
            else:
                desc = f"[{int(self.current_time_ms)} ms] Receiver discarded out-of-order Frame {frame_id} (expected {self.protocol.receiver_expected})."

            self._record_event(
                event_type="FRAME_RECEIVED",
                frame_id=frame_id,
                attempt_idx=attempt,
                seq_num=frame_id,
                is_retransmit=is_retransmit,
                description=desc,
                visual_color="green" if accepted else "red",
                direction="receiver",
                is_delivered=accepted,
                is_duplicate=False,
                packet_uid=packet_uid
            )
            # Send cumulative ACK if applicable
            if cumulative_ack is not None:
                self._send_ack(ack_id=cumulative_ack, frame_id=frame_id)

        elif isinstance(self.protocol, SelectiveRepeat):
            accepted, is_buf, is_dup, ack_to_send, newly_deliv = self.protocol.on_frame_received(frame_id)
            if accepted and not is_buf:
                deliv_str = f" Delivered Frame(s) {newly_deliv}." if len(newly_deliv) > 1 else ""
                desc = f"[{int(self.current_time_ms)} ms] Receiver received Frame {frame_id}.{deliv_str}"
            elif is_buf:
                desc = f"[{int(self.current_time_ms)} ms] Receiver received and buffered out-of-order Frame {frame_id}."
            elif is_dup:
                desc = f"[{int(self.current_time_ms)} ms] Receiver received duplicate Frame {frame_id}. Resending ACK."
            else:
                desc = f"[{int(self.current_time_ms)} ms] Receiver ignored outside-window Frame {frame_id}."

            self._record_event(
                event_type="FRAME_RECEIVED",
                frame_id=frame_id,
                attempt_idx=attempt,
                seq_num=frame_id,
                is_retransmit=is_retransmit,
                description=desc,
                visual_color="green" if accepted or is_dup else "red",
                direction="receiver",
                is_delivered=accepted and not is_buf,
                is_duplicate=is_dup,
                is_buffered=is_buf,
                packet_uid=packet_uid
            )
            # Selective repeat acknowledges each received frame individually
            self._send_ack(ack_id=ack_to_send, frame_id=frame_id)

    def _send_ack(self, ack_id: int, frame_id: int) -> None:
        self.ack_attempts[ack_id] = self.ack_attempts.get(ack_id, 0) + 1
        attempt = self.ack_attempts[ack_id]
        ack_uid = f"ACK_{ack_id}_{attempt}"

        lost = self._should_drop_ack(ack_id, attempt)
        desc = f"[{int(self.current_time_ms)} ms] Receiver sent ACK {ack_id}."
        self._record_event(
            event_type="ACK_TX_START",
            frame_id=frame_id,
            attempt_idx=attempt,
            ack_id=ack_id,
            description=desc,
            visual_color="blue",
            direction="r2s",
            packet_uid=ack_uid
        )

        arrival_time = self.current_time_ms + self.config.ack_delay
        self._push_event(arrival_time, "ACK_ARRIVE", {
            "ack_id": ack_id,
            "frame_id": frame_id,
            "attempt": attempt,
            "is_lost": lost,
            "packet_uid": ack_uid
        })

    def _handle_ack_arrive(self, data: Dict[str, Any]) -> None:
        ack_id = data["ack_id"]
        frame_id = data["frame_id"]
        attempt = data["attempt"]
        is_lost = data["is_lost"]
        ack_uid = data["packet_uid"]

        if is_lost:
            self.stats.acks_lost += 1
            desc = f"[{int(self.current_time_ms)} ms] ACK {ack_id} was lost in transit."
            self._record_event(
                event_type="ACK_LOST",
                frame_id=frame_id,
                attempt_idx=attempt,
                ack_id=ack_id,
                description=desc,
                visual_color="red",
                direction="r2s",
                packet_uid=ack_uid
            )
            return

        # ACK safely received by sender
        self.stats.acks_received += 1
        desc = f"[{int(self.current_time_ms)} ms] Sender received ACK {ack_id}."

        if isinstance(self.protocol, OneBitSlidingWindow):
            valid = self.protocol.on_ack_received(ack_id)
            if valid:
                self._stop_timer("stop_and_wait")
            self._record_event(
                event_type="ACK_RECEIVED",
                frame_id=frame_id,
                attempt_idx=attempt,
                ack_id=ack_id,
                description=desc if valid else f"[{int(self.current_time_ms)} ms] Sender ignored late/duplicate ACK {ack_id}.",
                visual_color="blue",
                direction="sender",
                packet_uid=ack_uid
            )
            if valid:
                self._schedule_transmissions()

        elif isinstance(self.protocol, GoBackN):
            newly_acked = self.protocol.on_ack_received(ack_id)
            self._record_event(
                event_type="ACK_RECEIVED",
                frame_id=frame_id,
                attempt_idx=attempt,
                ack_id=ack_id,
                description=desc,
                visual_color="blue",
                direction="sender",
                packet_uid=ack_uid
            )

            if newly_acked:
                # Base has moved
                if self.protocol.sender_base == self.protocol.next_frame_to_send:
                    # All outstanding frames have been acknowledged
                    self._stop_timer("gbn_base")
                else:
                    # Restart timer for the new oldest unacknowledged frame
                    self._start_timer("gbn_base", self.current_time_ms + self.config.timeout_ms)
                # Check if window allows more frames to be transmitted
                self._schedule_transmissions()

        elif isinstance(self.protocol, SelectiveRepeat):
            valid = self.protocol.on_ack_received(ack_id)
            if valid:
                self._stop_timer(ack_id)
            self._record_event(
                event_type="ACK_RECEIVED",
                frame_id=frame_id,
                attempt_idx=attempt,
                ack_id=ack_id,
                description=desc if valid else f"[{int(self.current_time_ms)} ms] Sender received duplicate ACK {ack_id}.",
                visual_color="blue",
                direction="sender",
                packet_uid=ack_uid
            )
            if valid:
                self._schedule_transmissions()

    def _handle_timeout_check(self, data: Dict[str, Any]) -> None:
        timer_key = data["timer_key"]
        expected_expire = data["expected_expire"]

        # If timer was cancelled or superseded, ignore
        if self.active_timers.get(timer_key) != expected_expire:
            return

        self.stats.timeouts += 1

        if timer_key == "stop_and_wait":
            frame_id = self.protocol.current_frame_id
            if self.frame_retries[frame_id] >= self.config.max_retries_per_frame:
                self._abort_retry_limit(frame_id)
                return

            self._record_event(
                event_type="TIMEOUT",
                frame_id=frame_id,
                description=f"[{int(self.current_time_ms)} ms] Timeout occurred for Frame {frame_id}.",
                visual_color="orange",
                direction="sender"
            )
            # Retransmit frame
            self._send_frame(frame_id, is_retransmit=True)

        elif timer_key == "gbn_base":
            base_frame = self.protocol.sender_base
            if base_frame >= self.config.num_frames:
                return

            if self.frame_retries[base_frame] >= self.config.max_retries_per_frame:
                self._abort_retry_limit(base_frame)
                return

            self._record_event(
                event_type="TIMEOUT",
                frame_id=base_frame,
                description=f"[{int(self.current_time_ms)} ms] Timeout occurred for Frame {base_frame} (GBN base). Retransmitting outstanding window.",
                visual_color="orange",
                direction="sender"
            )

            # GBN retransmits ALL unacknowledged frames in current window
            to_retransmit = self.protocol.get_retransmission_frames()
            # Restart timer for the base frame
            self._start_timer("gbn_base", self.current_time_ms + self.config.timeout_ms)
            for fid in to_retransmit:
                self._send_frame(fid, is_retransmit=True)

        else:
            # Selective repeat: individual timer for frame_id
            frame_id = timer_key
            if isinstance(self.protocol, SelectiveRepeat) and not self.protocol.is_frame_acked(frame_id):
                if self.frame_retries[frame_id] >= self.config.max_retries_per_frame:
                    self._abort_retry_limit(frame_id)
                    return

                self._record_event(
                    event_type="TIMEOUT",
                    frame_id=frame_id,
                    description=f"[{int(self.current_time_ms)} ms] Timeout occurred for Frame {frame_id}. Retransmitting Frame {frame_id}.",
                    visual_color="orange",
                    direction="sender"
                )
                # SR retransmits ONLY the timed-out frame
                self._send_frame(frame_id, is_retransmit=True)

    def _abort_retry_limit(self, frame_id: int) -> None:
        self.stats.aborted = True
        self.stats.abort_reason = (
            f"Maximum retry limit ({self.config.max_retries_per_frame}) reached for Frame {frame_id}."
        )
        self._record_event(
            event_type="SIMULATION_ABORTED",
            frame_id=frame_id,
            description=f"[{int(self.current_time_ms)} ms] Simulation stopped: {self.stats.abort_reason}",
            visual_color="red",
            direction="sender"
        )
        self.queue.clear()

