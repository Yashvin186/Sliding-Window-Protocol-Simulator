# Sliding Window Protocol Simulator

An interactive, accurate academic desktop simulator for Data Link Layer Sliding Window Protocols in Computer Networks, built with Python 3, Tkinter, and Matplotlib.

---

## Project Overview

This simulator demonstrates, compares, and evaluates the performance of three fundamental sliding window protocols:
1. **One-Bit Sliding Window (Stop-and-Wait ARQ)**: Alternating sequence bit (0/1), sends one frame at a time and waits for an ACK before advancing. Detects duplicates when ACKs are lost.
2. **Go-Back-N (GBN) ARQ**: Pipelined sender window (N), receiver accepts only in-order frames and discards out-of-order packets. Employs cumulative ACKs and a single timer for the oldest unacknowledged frame. On timeout, retransmits all outstanding frames in the window.
3. **Selective Repeat (SR) ARQ**: Sender and receiver both maintain independent windows (N). Receiver buffers out-of-order frames within the window and issues individual ACKs. Sender maintains individual timers per frame and retransmits only timed-out frames.

Includes an **All Protocols (Comparison Mode)** that runs all three protocols under identical network conditions and random seeds, presenting a side-by-side metric table and Matplotlib bar charts comparing Retransmissions, Throughput, and Efficiency.

---

## Project Structure

```text
.
|-- main.py              # Application entry point, Tkinter GUI, and control handlers
|-- protocols.py         # Protocol state machines (One-Bit, Go-Back-N, Selective Repeat)
|-- simulator.py         # Discrete-event engine (timing, loss, timers, statistics)
|-- visualization.py     # Sender-Receiver canvas timeline and Matplotlib comparison charts
|-- requirements.txt     # Python dependencies (matplotlib)
`-- README.md            # Documentation and demonstration guide
```

---

## Prerequisites and Setup (Virtual Environment)

All operations run strictly inside a local virtual environment (`venv`) within this directory without affecting system packages.

### 1. Create and Activate Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt):**
```cmd
python -m venv venv
.\venv\Scripts\activate.bat
```

**On Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

Install the only external dependency (`matplotlib`):
```bash
pip install -r requirements.txt
```

---

## Running the Application

To launch the simulator:

```powershell
python main.py
```

---

## User Interface and Controls

1. **Protocol Selection**:
   - Choose between *One-Bit Sliding Window*, *Go-Back-N*, *Selective Repeat*, or *All Protocols (Comparison Mode)*.
2. **Parameters**:
   - **Window Size (N)**: Size of the sliding window (default: `4`, min: `1`). Automatically locked to `1` for One-Bit.
   - **Number of Frames**: Total frames to transmit (default: `10`).
   - **Transmission Delay (ms)**: One-way delay from Sender to Receiver (default: `100 ms`).
   - **ACK Delay (ms)**: One-way delay for ACKs returning from Receiver to Sender (default: `50 ms`).
   - **Packet Loss (%)**: Frame drop probability (0-100%, default: `10%`).
   - **ACK Loss (%)**: ACK drop probability (0-100%, default: `5%`).
   - **Timeout (ms)**: Retransmission timer duration (default: `300 ms`, > RTT = 150 ms).
   - **Random Seed**: Integer seed (default: `42`) ensuring deterministic, reproducible loss patterns.
   - **Playback Speed**: Choose between `0.25x (Very Slow)`, `0.5x (Slow)`, `1x (Normal)`, `2x (Fast)`, `5x (Very Fast)`, or `Instant`.
3. **Controls**:
   - **START SIMULATION**: Validates parameters and begins execution.
   - **PAUSE / RESUME**: Pauses execution mid-transmission for classroom explanation.
   - **RESET**: Clears canvas, statistics, and event log.
4. **Visual Color Indicators**:
   - **Green**: Successfully transmitted / delivered frame.
   - **Red**: Lost frame (`X (LOST)`) or lost ACK (`X (ACK LOST)`).
   - **Orange**: Retransmitted frame or timeout marker.
   - **Blue**: ACK transmission and receipt.
   - **Purple**: Out-of-order frame safely buffered (Selective Repeat).
   - **Dark Orange / Red**: Out-of-order frame discarded (Go-Back-N).

---

## Performance Statistics and Formulas

The application computes actual metrics directly from simulation events:
- **Total Frames Transmitted**: Every frame transmission attempt (original + retransmissions).
- **Number of Retransmissions**: Additional transmission attempts after initial attempt.
- **Packets Lost**: Frame transmission attempts dropped by the channel.
- **ACKs Received**: ACKs successfully received by the sender.
- **Total Transmission Time**: Elapsed time from first transmission to final acknowledgment.
- **Throughput (frames/sec)**:
  $$\text{Throughput} = \frac{\text{Delivered Frames}}{\text{Total Simulation Time (seconds)}}$$
- **Efficiency (%)**:
  $$\text{Efficiency} = \left(\frac{\text{Useful Data Transmission Time}}{\text{Total Simulation Time}}\right) \times 100$$
  *Useful Data Transmission Time* $= \text{Delivered Frames} \times \text{Transmission Delay}$.
  *(Clearly labeled as a simplified educational metric).*

---

## Instructor Demonstration Walkthrough

When presenting this project to your professor or lab examiner, follow this 4-step demonstration sequence:

### Step 1: Demonstrate Stop-and-Wait (One-Bit Sliding Window)
1. Select **One-Bit Sliding Window**.
2. Note that Window Size is fixed at 1 and sequence numbers alternate 0 and 1.
3. Click **START SIMULATION**.
4. Point out that the sender waits for ACK 0 before transmitting Frame 1.
5. Set **ACK Loss = 30%** and run again: show that when ACK is lost, the sender times out and retransmits Frame 0. The receiver detects the duplicate sequence number, discards duplicate data, and resends the ACK so the sender can advance.

### Step 2: Demonstrate Go-Back-N Discard and Window Retransmission
1. Select **Go-Back-N** with Window Size = 4, Frames = 10, Packet Loss = 15%.
2. Click **START SIMULATION**.
3. Point out how the sender transmits frames pipelined up to window size 4.
4. When a frame (e.g. Frame 2) is lost:
   - Notice the receiver receives subsequent Frame 3, but **discards** it because it is out of order (GBN does not buffer out-of-order frames).
   - When the single timer for the base expires, the sender goes back and retransmits **all** unacknowledged frames (both Frame 2 and Frame 3).

### Step 3: Demonstrate Selective Repeat Buffering and Selective Retransmission
1. Select **Selective Repeat** with Window Size = 4, Frames = 10, Packet Loss = 15%.
2. Click **START SIMULATION**.
3. When a frame (e.g. Frame 2) is lost:
   - Notice the receiver **buffers** Frame 3 (highlighted in purple) instead of discarding it.
   - Receiver sends individual ACK for Frame 3.
   - On timeout of Frame 2, sender retransmits **ONLY Frame 2** (Frame 3 is NOT retransmitted).
   - Once Frame 2 arrives, the receiver delivers both Frame 2 and buffered Frame 3, sliding its window forward.

### Step 4: Demonstrate All Protocols (Comparison Mode)
1. Select **All Protocols (Comparison Mode)**.
2. Click **START SIMULATION**.
3. Explain the comparison table and Matplotlib bar charts:
   - **Retransmissions**: Show that Selective Repeat has fewer retransmissions than Go-Back-N under loss because it does not retransmit already buffered frames.
   - **Throughput and Efficiency**: Show that pipelined protocols (GBN and SR) achieve much higher throughput than Stop-and-Wait because they keep the channel full during round-trip delay.
   - Highlight that performance trade-offs depend on channel round-trip time, window size, and loss probabilities.
