# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
ocah_uart_vip — OCAH-stable cocotb wrappers for UART console traffic.

This package provides a single, versioned Python API surface for driving and
monitoring UART serial traffic in OCAH cocotb tests.  The primary use-case is
the SMC firmware-visible console (8N1, configurable baud rate).

Internally the active driver delegates to ``cocotbext-uart`` when it is
available in the environment.  When it is not installed the module raises
``OcahUartImportError`` at construction time with a clear install message,
mirroring the ``ocah_axi_vip`` migration-plan pattern.

Primary exports
---------------
OcahUartConsole   — Active UART console host: send strings, expect patterns.
OcahUartMonitor   — Passive byte-level RX/TX monitor with callbacks.

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
from .ocah_uart_monitor import OcahUartMonitor

__all__ = [
    # Active host
    "OcahUartConsole",
    # Passive monitor
    "OcahUartMonitor",
    # Error types
    "OcahUartError",
    "OcahUartImportError",
]

__version__ = "0.1.0"
