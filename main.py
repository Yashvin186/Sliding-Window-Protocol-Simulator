"""
Launcher for Sliding Window Protocol Simulator.
Allows running `python main.py` directly from the project root.
"""

import os
import sys

pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sliding_window_simulator")
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

import importlib.util
spec = importlib.util.spec_from_file_location("sim_main", os.path.join(pkg_dir, "main.py"))
sim_main = importlib.util.module_from_spec(spec)
sys.modules["sim_main"] = sim_main
spec.loader.exec_module(sim_main)

if __name__ == "__main__":
    sim_main.main()
