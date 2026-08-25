# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
ocah_uart_vip — OCAH-stable cocotb wrappers for UART console traffic.

This package provides a single, versioned Python API surface for driving and
monitoring UART serial traffic in OCAH cocotb tests.  The primary use-case is
the SMC firmware-visible console (8N1, configurable baud rate).

The backend is native to this package: ``OcahUartMasterDriver`` drives
8-N-1 frames onto a line and ``OcahUartLineMonitor`` reassembles bytes from
one.  No external UART library is required; ``OcahUartImportError`` is
retained only for backward compatibility with callers that catch it.

Primary exports
---------------
OcahUartConsole       — Active UART console host: send strings, expect patterns.
OcahUartMonitor       — Passive byte-level RX/TX monitor with callbacks.
OcahUartMasterDriver  — Active host-side 8-N-1 line driver (console TX engine).
OcahUartLineMonitor   — Passive wire-level 8-N-1 byte sampler (console RX engine).

Quick-start
-----------
::

    from ocah_uart_vip import OcahUartConsole

    @cocotb.test()
    async def test_uart_loopback(dut):
        clk = Clock(dut.clk, 10, units="ns")
        cocotb.start_soon(clk.start())

        console = OcahUartConsole(
            dut.uart_txd,
            dut.uart_rxd,
            dut.clk,
            name="smc_uart",
        )
        console.init_signals()
        await console.set_baud(115200)
        await console.send_string("hello\\n")
        line = await console.read_line(timeout_us=500)
        assert "hello" in line

See ``examples/example_loopback.py`` for a more complete example.
"""

from .ocah_uart_console import OcahUartConsole, OcahUartError, OcahUartImportError
from .ocah_uart_master_driver import OcahUartMasterDriver
from .ocah_uart_monitor import OcahUartLineMonitor, OcahUartMonitor

__all__ = [
    # Active host
    "OcahUartConsole",
    # Passive monitor
    "OcahUartMonitor",
    # Native line engines
    "OcahUartMasterDriver",
    "OcahUartLineMonitor",
    # Error types
    "OcahUartError",
    "OcahUartImportError",
]

__version__ = "0.1.0"
