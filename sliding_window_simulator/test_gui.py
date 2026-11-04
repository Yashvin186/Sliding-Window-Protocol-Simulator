"""
test_gui.py
-----------
Comprehensive GUI and Integration tests for SlidingWindowApp.
Verifies:
- UI initialization and styling
- Form validation (invalid window size, negative delays, etc.)
- Running One-Bit, GBN, and Selective Repeat through UI actions
- Comparison mode table and chart rendering
- Pause / Resume / Reset state toggling
"""

import os
import sys
import unittest
from unittest.mock import patch

pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sliding_window_simulator")
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from main import SlidingWindowApp
from protocols import ProtocolType


class TestSlidingWindowGUI(unittest.TestCase):

    def setUp(self):
        self.app = SlidingWindowApp()
        self.app.withdraw()  # Hide window during automated test

    def tearDown(self):
        self.app.destroy()

    def test_initial_state(self):
        """Test initial UI controls and default values."""
        self.assertEqual(self.app.protocol_var.get(), ProtocolType.GO_BACK_N.value)
        self.assertEqual(self.app.win_size_var.get(), "4")
        self.assertEqual(self.app.num_frames_var.get(), "10")
        self.assertEqual(self.app.tx_delay_var.get(), "100")
        self.assertEqual(self.app.ack_delay_var.get(), "50")
        self.assertEqual(self.app.pkt_loss_var.get(), "10")
        self.assertEqual(self.app.ack_loss_var.get(), "5")
        self.assertEqual(self.app.timeout_var.get(), "300")

    def test_validation_errors(self):
        """Test input validation rejects invalid values."""
        # 1. Window size < 1
        self.app.win_size_var.set("0")
        with patch("tkinter.messagebox.showerror") as mock_err:
            config = self.app._validate_inputs()
            self.assertIsNone(config)
            mock_err.assert_called_once()

        # 2. Number of frames <= 0
        self.app.win_size_var.set("4")
        self.app.num_frames_var.set("0")
        with patch("tkinter.messagebox.showerror") as mock_err:
            config = self.app._validate_inputs()
            self.assertIsNone(config)

        # 3. Packet loss > 100%
        self.app.num_frames_var.set("10")
        self.app.pkt_loss_var.set("150")
        with patch("tkinter.messagebox.showerror") as mock_err:
            config = self.app._validate_inputs()
            self.assertIsNone(config)

    def test_run_simulation_instant(self):
        """Test running a full simulation in Instant mode."""
        self.app.speed_var.set("Instant")
        self.app._on_speed_change()
        self.app.num_frames_var.set("5")
        self.app.pkt_loss_var.set("0")
        self.app.ack_loss_var.set("0")

        self.app.start_simulation()
        self.app.update()

        # Check delivered count and summary
        st = self.app.current_simulator.stats
        self.assertEqual(st.delivered_frames, 5)
        self.assertEqual(st.num_retransmissions, 0)
        self.assertFalse(self.app.is_running)

    def test_comparison_mode(self):
        """Test All Protocols Comparison Mode."""
        self.app.protocol_var.set(ProtocolType.COMPARISON.value)
        self.app._on_protocol_change()
        self.app.num_frames_var.set("6")
        self.app.pkt_loss_var.set("10")
        self.app.ack_loss_var.set("5")
        self.app.seed_var.set("42")

        self.app.start_simulation()
        self.app.update()

        # Check comparison table has rows
        items = self.app.comp_visualizer.tree.get_children()
        self.assertGreaterEqual(len(items), 7)

    def test_pause_and_reset(self):
        """Test pause and reset state transitions."""
        self.app.speed_var.set("1x (Normal)")
        self.app._on_speed_change()
        self.app.num_frames_var.set("10")
        self.app.start_simulation()

        self.assertTrue(self.app.is_running)
        self.app.toggle_pause()
        self.assertTrue(self.app.is_paused)

        self.app.reset_simulation()
        self.assertFalse(self.app.is_running)
        self.assertFalse(self.app.is_paused)


if __name__ == "__main__":
    unittest.main()

