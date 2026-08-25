# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
example_loopback.py — OcahUartConsole usage examples.

Demonstrates:
  1. Basic UART loopback (send a string, read it back).
  2. Pattern-matching with ``expect()``.
  3. Passive monitoring with ``OcahUartMonitor`` alongside a console driver.
  4. Baud-rate reconfiguration.

These snippets are NOT stand-alone tests; they show the API patterns a real
OCAH test would follow.  Replace ``dut.uart_txd`` / ``dut.uart_rxd`` with the
actual signal handles in your testbench.

Assumptions
-----------
- The DUT internally loops TXD back to RXD (loopback DUT or SMC console in
  echo mode).
- Clock is started externally before these functions are called.
- No external UART library is needed; the package's native line engines
  provide the backend.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

from ocah_uart_vip import OcahUartConsole, OcahUartMonitor


# ---------------------------------------------------------------------------
# Example 1 — Basic loopback: send a string and read it back line-by-line
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_uart_loopback(dut):
    """Send ASCII lines and verify the DUT echoes them back."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # Construct the console wrapper.  Both baud and log file can also be set
    # via plusargs: +uart_baud=115200 and +uart_log=/tmp/smc_uart.log
    console = OcahUartConsole(
        dut.uart_txd,       # TX signal handle  (DUT pin name may differ)
        dut.uart_rxd,       # RX signal handle
        dut.clk,
        name="smc_console",
        baud=115200,
        timeout_us=2_000,   # 2 ms per-byte timeout
    )

    # Init signals before the first clock edge to avoid X propagation.
    console.init_signals()

    # Allow the DUT time to come out of reset.
    await Timer(200, units="ns")

    # ---------- transmit a line ----------
    await console.send_string("ping\n")
    cocotb.log.info("Sent: 'ping\\n'")

    # ---------- receive the echoed line ----------
    line = await console.read_line(timeout_us=5_000)
    assert line == "ping", f"expected 'ping', got {line!r}"
    cocotb.log.info("Received echoed line: %r", line)

    # ---------- send a multi-line burst ----------
    for i in range(3):
        await console.send_string(f"line{i}\n")

    for i in range(3):
        line = await console.read_line(timeout_us=5_000)
        assert line == f"line{i}", f"line {i}: expected 'line{i}', got {line!r}"

    # ---------- statistics ----------
    stats = console.get_statistics()
    cocotb.log.info("Console stats: %s", stats)
    assert stats["bytes_sent"] > 0
    assert stats["lines_received"] == 4   # "ping" + 3 numbered lines

    cocotb.log.info("example_uart_loopback PASSED")


# ---------------------------------------------------------------------------
# Example 2 — Pattern matching with expect()
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_uart_expect(dut):
    """Boot SMC and wait for the firmware boot banner."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    console = OcahUartConsole(
        dut.uart_txd, dut.uart_rxd, dut.clk,
        name="smc_boot",
        baud=115200,
        timeout_us=10_000,  # firmware may take a few ms to print
    )
    console.init_signals()

    # Wait for the SMC firmware to print its boot banner.  The regex matches
    # any line containing "SMC" and "ready" (case-insensitive).
    banner = await console.expect(
        r"(?i)smc.*ready",
        timeout_us=50_000,   # 50 ms budget for firmware boot
    )
    cocotb.log.info("Boot banner received: %r", banner)

    # Now interact with the console.
    await console.send_string("version\n")
    version_line = await console.expect(r"v\d+\.\d+", timeout_us=5_000)
    cocotb.log.info("Firmware version: %r", version_line)

    cocotb.log.info("example_uart_expect PASSED")


# ---------------------------------------------------------------------------
# Example 3 — Passive monitor alongside a console driver
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_uart_monitor(dut):
    """Attach a passive monitor to observe both TX and RX bytes."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    console = OcahUartConsole(
        dut.uart_txd, dut.uart_rxd, dut.clk, name="console", baud=115200
    )
    console.init_signals()

    # Passive monitor taps the same lines without interfering.
    monitor = OcahUartMonitor(
        dut.uart_txd, dut.uart_rxd, dut.clk, name="uart_mon", baud=115200
    )

    # Accumulate observed bytes for post-test checking.
    observed_tx: list = []
    observed_rx: list = []

    monitor.add_tx_callback(lambda b: observed_tx.append(b))
    monitor.add_rx_callback(lambda b: observed_rx.append(b))
    await monitor.start()

    await Timer(100, units="ns")   # settle

    # Send a known string; DUT loops it back.
    test_str = "hello"
    await console.send_string(test_str + "\n")
    await console.read_line(timeout_us=5_000)

    await Timer(500, units="ns")   # allow monitor to drain
    await monitor.stop()

    # Verify the monitor captured what was sent.
    tx_bytes = monitor.get_tx_bytes()
    assert len(tx_bytes) == len(test_str) + 1, (
        f"expected {len(test_str) + 1} TX bytes, got {len(tx_bytes)}"
    )

    mon_stats = monitor.get_statistics()
    cocotb.log.info("Monitor stats: %s", mon_stats)
    assert mon_stats["tx_bytes_observed"] >= len(test_str)

    cocotb.log.info("example_uart_monitor PASSED")


# ---------------------------------------------------------------------------
# Example 4 — Baud-rate reconfiguration
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_uart_baud_change(dut):
    """Change baud rate mid-test."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    console = OcahUartConsole(
        dut.uart_txd, dut.uart_rxd, dut.clk, name="baud_test", baud=9600
    )
    console.init_signals()
    await Timer(100, units="ns")

    # Communicate at 9600 baud.
    await console.send_string("slow\n")
    line = await console.read_line(timeout_us=10_000)
    assert line == "slow"

    # Switch to 115200.  The DUT must switch simultaneously.
    await console.set_baud(115200)

    await console.send_string("fast\n")
    line = await console.read_line(timeout_us=2_000)
    assert line == "fast"

    cocotb.log.info("example_uart_baud_change PASSED")
