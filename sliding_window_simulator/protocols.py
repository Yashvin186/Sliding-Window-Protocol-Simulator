"""
protocols.py
------------
Defines the core logic and state representations for:
1. One-Bit Sliding Window (Stop-and-Wait ARQ)
2. Go-Back-N ARQ
3. Selective Repeat ARQ

Each protocol implements its own state machine:
- Window bounds and sequence numbers
- Acceptance / discard / buffering logic at receiver
- Cumulative vs Individual ACK handling
- Single timer vs Individual timers
- Retransmission logic on timeout
"""

from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class ProtocolType(str, Enum):
    ONE_BIT = "One-Bit Sliding Window"
    GO_BACK_N = "Go-Back-N"
    SELECTIVE_REPEAT = "Selective Repeat"
    COMPARISON = "All Protocols (Comparison Mode)"


class BaseProtocol:
    """Base class for sliding window protocol state management."""

    def __init__(self, num_frames: int, window_size: int):
        self.num_frames = num_frames
        self.window_size = window_size
        self.delivered_frames: List[int] = []
        self.sender_base: int = 0
        self.next_frame_to_send: int = 0

    def can_send(self) -> bool:
        """Returns True if sender window allows transmitting a new frame."""
        raise NotImplementedError

    def get_sender_window(self) -> Tuple[int, int]:
        """Returns (start_idx, end_idx) of sender window."""
        raise NotImplementedError

    def get_receiver_window(self) -> Tuple[int, int]:
        """Returns (start_idx, end_idx) of receiver window."""
        raise NotImplementedError

    def is_complete(self) -> bool:
        """Returns True if all frames have been successfully delivered and acked."""
        return len(self.delivered_frames) == self.num_frames and self.sender_base >= self.num_frames


class OneBitSlidingWindow(BaseProtocol):
    """
    One-Bit Sliding Window (Stop-and-Wait ARQ)
    -------------------------------------------
    - Window size is 1 frame.
    - Alternating sequence numbers: 0 and 1.
    - Sender transmits 1 frame and waits for ACK before sending next.
    - Receiver expects alternating 0 and 1. Duplicate frames are discarded
      (not delivered twice), but ACK is resent.
    - A single timer runs for the frame in-flight.
    """

    def __init__(self, num_frames: int, window_size: int = 1):
        super().__init__(num_frames, window_size=1)
        self.sender_seq: int = 0            # Alternates 0 and 1
        self.receiver_expected_seq: int = 0 # Alternates 0 and 1
        self.waiting_for_ack: bool = False
        self.current_frame_id: int = 0

    def can_send(self) -> bool:
        return (not self.waiting_for_ack) and (self.next_frame_to_send < self.num_frames)

    def on_frame_sent(self, frame_id: int) -> int:
        """Sender transmits frame_id with current 1-bit sequence number."""
        self.waiting_for_ack = True
        self.current_frame_id = frame_id
        if frame_id == self.next_frame_to_send:
            self.next_frame_to_send += 1
        return self.sender_seq

    def on_frame_received(self, frame_id: int, seq_num: int) -> Tuple[bool, bool, int]:
        """
        Receiver processes frame.
        Returns: (accepted, is_duplicate, ack_seq)
        - accepted: True if new frame delivered to application.
        - is_duplicate: True if frame already delivered earlier.
        - ack_seq: Sequence number of the ACK sent back.
        """
        if seq_num == self.receiver_expected_seq:
            # Expected sequence number: accept and deliver frame
            if frame_id not in self.delivered_frames:
                self.delivered_frames.append(frame_id)
            # Toggle expected sequence number for next frame
            self.receiver_expected_seq = 1 - self.receiver_expected_seq
            return True, False, seq_num
        else:
            # Duplicate frame received (previous ACK was likely lost)
            # Do NOT deliver twice, but resend ACK with received seq
            return False, True, seq_num

    def on_ack_received(self, ack_seq: int) -> bool:
        """
        Sender receives ACK.
        Returns True if ACK is valid and advances sender state.
        """
        if self.waiting_for_ack and ack_seq == self.sender_seq:
            self.waiting_for_ack = False
            self.sender_seq = 1 - self.sender_seq
            self.sender_base = self.current_frame_id + 1
            return True
        return False

    def on_timeout(self) -> int:
        """
        Timeout occurs for the unacknowledged frame.
        Returns frame_id to retransmit.
        """
        return self.current_frame_id

    def get_sender_window(self) -> Tuple[int, int]:
        start = self.sender_base
        end = min(self.sender_base, self.num_frames - 1)
        return start, end

    def get_receiver_window(self) -> Tuple[int, int]:
        # Receiver expects the next frame to be delivered
        expected_frame = len(self.delivered_frames)
        return expected_frame, expected_frame


class GoBackN(BaseProtocol):
    """
    Go-Back-N ARQ
    -------------
    - Sender can transmit up to N frames (window size) without waiting for ACKs.
    - Receiver accepts ONLY the next expected in-order frame. Out-of-order frames
      are discarded.
    - Cumulative ACKs: ACK k acknowledges all frames <= k.
    - Single timer maintained for the oldest unacknowledged frame (sender_base).
    - On timeout, sender retransmits ALL outstanding unacknowledged frames in
      [sender_base, next_frame_to_send - 1].
    """

    def __init__(self, num_frames: int, window_size: int = 4):
        super().__init__(num_frames, window_size)
        self.receiver_expected: int = 0  # Next in-order frame expected

    def can_send(self) -> bool:
        return (self.next_frame_to_send < self.sender_base + self.window_size) and \
               (self.next_frame_to_send < self.num_frames)

    def on_frame_sent(self, frame_id: int) -> None:
        if frame_id == self.next_frame_to_send:
            self.next_frame_to_send += 1

    def on_frame_received(self, frame_id: int) -> Tuple[bool, bool, Optional[int]]:
        """
        Receiver processes frame.
        Returns: (accepted, is_out_of_order, cumulative_ack_id)
        """
        if frame_id == self.receiver_expected:
            # In-order frame received: deliver it
            self.delivered_frames.append(frame_id)
            ack_to_send = self.receiver_expected
            self.receiver_expected += 1
            return True, False, ack_to_send
        else:
            # Out-of-order frame: discard!
            # Optionally resend cumulative ACK for the last in-order frame
            last_acked = self.receiver_expected - 1 if self.receiver_expected > 0 else None
            return False, True, last_acked

    def on_ack_received(self, cumulative_ack: int) -> List[int]:
        """
        Sender receives cumulative ACK for frames up to cumulative_ack.
        Returns list of newly acknowledged frame IDs.
        """
        newly_acked = []
        if cumulative_ack >= self.sender_base:
            for fid in range(self.sender_base, cumulative_ack + 1):
                newly_acked.append(fid)
            self.sender_base = cumulative_ack + 1
        return newly_acked

    def get_retransmission_frames(self) -> List[int]:
        """
        On timeout, Go-Back-N retransmits all outstanding unacknowledged frames
        from sender_base up to next_frame_to_send - 1.
        """
        return list(range(self.sender_base, self.next_frame_to_send))

    def get_sender_window(self) -> Tuple[int, int]:
        start = self.sender_base
        end = min(self.sender_base + self.window_size - 1, self.num_frames - 1)
        return start, end

    def get_receiver_window(self) -> Tuple[int, int]:
        # GBN receiver window is size 1: only expects receiver_expected
        exp = min(self.receiver_expected, self.num_frames - 1)
        return exp, exp


class SelectiveRepeat(BaseProtocol):
    """
    Selective Repeat ARQ
    --------------------
    - Sender can transmit up to N frames (window size).
    - Receiver accepts and buffers correctly received out-of-order frames within
      its window [receiver_base, receiver_base + window_size - 1].
    - Receiver sends individual ACKs for each frame received.
    - If a duplicate frame is received (already acknowledged/delivered in previous window),
      receiver resends ACK so the sender can advance.
    - Sender maintains individual timers for each outstanding frame.
    - On timeout of frame k, sender retransmits ONLY frame k.
    - Sender window advances when consecutive frames starting from sender_base are ACKed.
    - Receiver window advances and delivers consecutive buffered frames.
    """

    def __init__(self, num_frames: int, window_size: int = 4):
        super().__init__(num_frames, window_size)
        self.receiver_base: int = 0
        self.receiver_buffer: Dict[int, bool] = {}     # frame_id -> received
        self.sender_acked: Dict[int, bool] = {}         # frame_id -> acked

    def can_send(self) -> bool:
        return (self.next_frame_to_send < self.sender_base + self.window_size) and \
               (self.next_frame_to_send < self.num_frames)

    def on_frame_sent(self, frame_id: int) -> None:
        if frame_id == self.next_frame_to_send:
            self.next_frame_to_send += 1

    def on_frame_received(self, frame_id: int) -> Tuple[bool, bool, bool, int, List[int]]:
        """
        Receiver processes frame_id.
        Returns:
            accepted: True if placed into buffer or delivered
            buffered: True if held in buffer (out-of-order)
            is_duplicate: True if duplicate frame
            ack_to_send: frame_id to acknowledge
            newly_delivered: list of frame IDs delivered to upper layer
        """
        newly_delivered: List[int] = []

        # Case 1: Frame falls within receiver window
        if self.receiver_base <= frame_id < self.receiver_base + self.window_size:
            is_dup = (frame_id in self.receiver_buffer)
            self.receiver_buffer[frame_id] = True

            # If frame is at receiver_base, advance window and deliver contiguous frames
            if frame_id == self.receiver_base:
                while self.receiver_base in self.receiver_buffer:
                    if self.receiver_base not in self.delivered_frames:
                        self.delivered_frames.append(self.receiver_base)
                        newly_delivered.append(self.receiver_base)
                    self.receiver_base += 1
                return True, False, is_dup, frame_id, newly_delivered
            else:
                # Buffered out of order
                return True, True, is_dup, frame_id, newly_delivered

        # Case 2: Duplicate frame that fell in previous window
        # (Must re-ACK so sender can clear its timer and slide its window)
        elif max(0, self.receiver_base - self.window_size) <= frame_id < self.receiver_base:
            return False, False, True, frame_id, newly_delivered

        # Case 3: Out of receiver window bounds
        else:
            return False, False, False, frame_id, newly_delivered

    def on_ack_received(self, ack_id: int) -> bool:
        """
        Sender receives individual ACK for ack_id.
        Returns True if this was an outstanding frame.
        """
        if self.sender_base <= ack_id < self.sender_base + self.window_size:
            self.sender_acked[ack_id] = True
            # Slide sender_base if consecutive frames are acked
            while self.sender_acked.get(self.sender_base, False):
                self.sender_base += 1
            return True
        return False

    def is_frame_acked(self, frame_id: int) -> bool:
        return self.sender_acked.get(frame_id, False)

    def get_sender_window(self) -> Tuple[int, int]:
        start = self.sender_base
        end = min(self.sender_base + self.window_size - 1, self.num_frames - 1)
        return start, end

    def get_receiver_window(self) -> Tuple[int, int]:
        start = self.receiver_base
        end = min(self.receiver_base + self.window_size - 1, self.num_frames - 1)
        return start, end

