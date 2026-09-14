# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``OcahUartConsole`` usage examples.

Four snippets show the API patterns an OCAH test follows: a console
loopback judged by the checker, pattern matching with ``expect()``, a passive
tap beside the console, and a mid-test baud change. They are not stand-alone
tests: replace ``dut.uart_rx`` (the DUT's receive line, driven by the console)
and ``dut.uart_tx`` (the DUT's transmit line, sampled by the console) with the
handles of the bench, and start the DUT clock before calling them. The DUT is
assumed to echo what it receives.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

from ocah_uart_vip import OcahUartChecker, OcahUartConsole, OcahUartMonitor

BAUD = 115200


@cocotb.test()
async def example_uart_loopback(dut):
    """Send ASCII lines, read the echo, and judge the exchange with the checker."""
    cocotb.start_soon(Clock(dut.clk, 10, "ns").start())
    console = OcahUartConsole(
        dut.uart_rx, dut.uart_tx, dut.clk, name="console", baud=BAUD, timeout_us=2_000
    )
    console.init_signals()
    await Timer(200, "ns")

    sent = b"ping\nline0\nline1\n"
    await console.send_bytes(sent)
    lines = [await console.read_line(timeout_us=5_000) for _ in range(3)]
    assert lines == ["ping", "line0", "line1"], lines

    checker = OcahUartChecker(
        name="example_uart", required_ids=("CHK-UART-DATA", "CHK-UART-CLEAN", "CHK-UART-BAUD")
    )
    checker.check_line(sent, console.rx_frames(), baud=BAUD, label="dut_tx")
    checker.check_statistics(
        console.get_statistics(),
        {"bytes_sent": len(sent), "bytes_received": len(sent), "lines_received": 3},
        label="console",
    )
    checker.finalize()


@cocotb.test()
async def example_uart_expect(dut):
    """Wait for a firmware banner, then query a version string."""
    cocotb.start_soon(Clock(dut.clk, 10, "ns").start())
    console = OcahUartConsole(dut.uart_rx, dut.uart_tx, dut.clk, name="boot", baud=BAUD)
    console.init_signals()

    banner = await console.expect(r"(?i)ready", timeout_us=50_000)
    cocotb.log.info("banner: %r", banner)
    await console.send_string("version\n")
    version = await console.expect(r"v\d+\.\d+", timeout_us=5_000)
    cocotb.log.info("version: %r", version)


@cocotb.test()
async def example_uart_monitor(dut):
    """Observe both lines with a passive tap while the console runs traffic."""
    cocotb.start_soon(Clock(dut.clk, 10, "ns").start())
    console = OcahUartConsole(dut.uart_rx, dut.uart_tx, dut.clk, name="console", baud=BAUD)
    console.init_signals()
    monitor = OcahUartMonitor(dut.uart_rx, dut.uart_tx, dut.clk, name="tap", baud=BAUD)
    observed_tx: list[int] = []
    monitor.add_tx_callback(observed_tx.append)
    await monitor.start()

    text = b"hello\n"
    await console.send_bytes(text)
    await console.read_line(timeout_us=5_000)
    await console.flush()
    await monitor.stop()

    checker = OcahUartChecker(name="example_tap", required_ids=("CHK-UART-DATA",))
    checker.check_data(text, monitor.get_tx_frames(), label="tap_tx")
    checker.check_data(text, monitor.get_rx_frames(), label="tap_rx")
    checker.expect_equal("CHK-UART-TAP-CALLBACK", observed_tx, list(text))
    checker.finalize()


@cocotb.test()
async def example_uart_baud_change(dut):
    """Change the baud rate mid-test; the DUT must switch at the same time."""
    cocotb.start_soon(Clock(dut.clk, 10, "ns").start())
    console = OcahUartConsole(dut.uart_rx, dut.uart_tx, dut.clk, name="baud", baud=9600)
    console.init_signals()
    await Timer(100, "ns")

    await console.send_string("slow\n")
    assert await console.read_line(timeout_us=10_000) == "slow"
    await console.flush()
    await console.set_baud(BAUD)
    await console.send_string("fast\n")
    assert await console.read_line(timeout_us=2_000) == "fast"
