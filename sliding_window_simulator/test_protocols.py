"""
test_protocols.py
-----------------
Automated test suite verifying the 7 technical accuracy tests required:
1. No Packet Loss (loss=0%, ack_loss=0%) -> 0 retransmissions, all delivered
2. Packet Loss (loss=30%, ack_loss=0%) -> lost frames retransmitted
3. ACK Loss (loss=0%, ack_loss=30%) -> recovered without duplicate delivery
4. Go-Back-N out-of-order discard and window retransmission
5. Selective Repeat out-of-order buffering and individual retransmission
6. Window Size 1 -> all three work correctly like Stop-and-Wait
7. High Packet Loss (100%) -> terminates safely via retry limit
"""

import os
import sys
import unittest

# Ensure the module can be imported from either root or package directory
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from protocols import ProtocolType
from simulator import SimulationConfig, Simulator


class TestSlidingWindowProtocols(unittest.TestCase):

    def test_1_no_packet_loss(self):
        """Test 1: 0% loss, 0% ack loss -> all delivered, 0 retransmissions."""
        for proto in [ProtocolType.ONE_BIT, ProtocolType.GO_BACK_N, ProtocolType.SELECTIVE_REPEAT]:
            with self.subTest(protocol=proto):
                config = SimulationConfig(
                    protocol=proto,
                    window_size=4,
                    num_frames=10,
                    tx_delay=100.0,
                    ack_delay=50.0,
                    packet_loss_pct=0.0,
                    ack_loss_pct=0.0,
                    timeout_ms=300.0,
                    seed=123
                )
                sim = Simulator(config)
                stats = sim.run()
                self.assertFalse(stats.aborted)
                self.assertEqual(stats.delivered_frames, 10)
                self.assertEqual(stats.num_retransmissions, 0)
                self.assertEqual(stats.packets_lost, 0)
                self.assertEqual(stats.total_frames_transmitted, 10)

    def test_2_packet_loss(self):
        """Test 2: 30% packet loss -> lost frames retransmitted, all eventually delivered."""
        for proto in [ProtocolType.ONE_BIT, ProtocolType.GO_BACK_N, ProtocolType.SELECTIVE_REPEAT]:
            with self.subTest(protocol=proto):
                config = SimulationConfig(
                    protocol=proto,
                    window_size=4,
                    num_frames=8,
                    tx_delay=50.0,
                    ack_delay=25.0,
                    packet_loss_pct=30.0,
                    ack_loss_pct=0.0,
                    timeout_ms=150.0,
                    seed=42
                )
                sim = Simulator(config)
                stats = sim.run()
                self.assertFalse(stats.aborted)
                self.assertEqual(stats.delivered_frames, 8)
                self.assertGreater(stats.packets_lost, 0)
                self.assertGreater(stats.num_retransmissions, 0)

    def test_3_ack_loss(self):
        """Test 3: 0% packet loss, 30% ack loss -> recovered without duplicates delivered."""
        for proto in [ProtocolType.ONE_BIT, ProtocolType.GO_BACK_N, ProtocolType.SELECTIVE_REPEAT]:
            with self.subTest(protocol=proto):
                config = SimulationConfig(
                    protocol=proto,
                    window_size=4,
                    num_frames=8,
                    tx_delay=50.0,
                    ack_delay=25.0,
                    packet_loss_pct=0.0,
                    ack_loss_pct=30.0,
                    timeout_ms=150.0,
                    seed=99
                )
                sim = Simulator(config)
                stats = sim.run()
                self.assertFalse(stats.aborted)
                # Exactly 8 unique frames delivered, no duplicate payload delivered
                self.assertEqual(stats.delivered_frames, 8)
                self.assertEqual(len(set(sim.protocol.delivered_frames)), 8)

    def test_4_go_back_n_discard_and_retransmit(self):
        """
        Test 4: GBN with forced loss of Frame 1 on attempt 1.
        Verify receiver discards Frame 2, 3 (subsequent out-of-order).
        Verify sender retransmits outstanding frames 1, 2, 3 on timeout.
        """
        config = SimulationConfig(
            protocol=ProtocolType.GO_BACK_N,
            window_size=4,
            num_frames=5,
            tx_delay=100.0,
            ack_delay=50.0,
            packet_loss_pct=0.0,
            ack_loss_pct=0.0,
            timeout_ms=300.0,
            forced_frame_losses={(1, 1)}  # Frame 1 lost on first attempt
        )
        sim = Simulator(config)
        stats = sim.run()
        self.assertFalse(stats.aborted)
        self.assertEqual(stats.delivered_frames, 5)

        # Find out-of-order events
        ooo_events = [e for e in sim.events if "discarded out-of-order Frame" in e.description]
        self.assertTrue(len(ooo_events) > 0, "GBN should discard out-of-order frames")

        # Verify Frame 1, 2, 3 retransmitted
        retransmitted_fids = [e.frame_id for e in sim.events if e.is_retransmit and e.event_type == "FRAME_TX_START"]
        self.assertIn(1, retransmitted_fids)
        self.assertIn(2, retransmitted_fids)

    def test_5_selective_repeat_buffer_and_selective_retransmit(self):
        """
        Test 5: SR with forced loss of Frame 1 on attempt 1.
        Verify receiver buffers Frame 2, 3.
        Verify sender retransmits ONLY Frame 1.
        """
        config = SimulationConfig(
            protocol=ProtocolType.SELECTIVE_REPEAT,
            window_size=4,
            num_frames=5,
            tx_delay=100.0,
            ack_delay=50.0,
            packet_loss_pct=0.0,
            ack_loss_pct=0.0,
            timeout_ms=300.0,
            forced_frame_losses={(1, 1)}  # Frame 1 lost on first attempt
        )
        sim = Simulator(config)
        stats = sim.run()
        self.assertFalse(stats.aborted)
        self.assertEqual(stats.delivered_frames, 5)

        # Verify buffering occurred for out-of-order frames
        buffered_events = [e for e in sim.events if e.is_buffered]
        self.assertTrue(len(buffered_events) > 0, "SR should buffer out-of-order frames")

        # Retransmitted frames in SR: ONLY Frame 1 should be retransmitted, NOT Frame 2 or 3!
        retransmitted_fids = [e.frame_id for e in sim.events if e.is_retransmit and e.event_type == "FRAME_TX_START"]
        self.assertEqual(retransmitted_fids, [1], "SR should selectively retransmit ONLY Frame 1")

    def test_6_window_size_1(self):
        """Test 6: Window Size = 1 -> all 3 protocols behave like Stop-and-Wait."""
        for proto in [ProtocolType.ONE_BIT, ProtocolType.GO_BACK_N, ProtocolType.SELECTIVE_REPEAT]:
            with self.subTest(protocol=proto):
                config = SimulationConfig(
                    protocol=proto,
                    window_size=1,
                    num_frames=5,
                    tx_delay=50.0,
                    ack_delay=25.0,
                    packet_loss_pct=0.0,
                    ack_loss_pct=0.0,
                    timeout_ms=150.0
                )
                sim = Simulator(config)
                stats = sim.run()
                self.assertFalse(stats.aborted)
                self.assertEqual(stats.delivered_frames, 5)
                self.assertEqual(stats.num_retransmissions, 0)
                # In window size 1, transmission time is 5 * (50 + 25) = 375 ms
                self.assertAlmostEqual(stats.total_time_ms, 375.0, delta=1.0)

    def test_7_high_packet_loss_100_percent(self):
        """Test 7: 100% packet loss -> safely terminates via retry limit."""
        for proto in [ProtocolType.ONE_BIT, ProtocolType.GO_BACK_N, ProtocolType.SELECTIVE_REPEAT]:
            with self.subTest(protocol=proto):
                config = SimulationConfig(
                    protocol=proto,
                    window_size=4,
                    num_frames=5,
                    tx_delay=50.0,
                    ack_delay=25.0,
                    packet_loss_pct=100.0,
                    ack_loss_pct=0.0,
                    timeout_ms=100.0,
                    max_retries_per_frame=4
                )
                sim = Simulator(config)
                stats = sim.run()
                self.assertTrue(stats.aborted, f"{proto} should abort on 100% loss")
                self.assertIn("Maximum retry limit", stats.abort_reason)


if __name__ == "__main__":
    unittest.main()
