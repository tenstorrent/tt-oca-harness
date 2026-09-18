# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ocah_uart_vip: OCAH-stable cocotb components for asynchronous serial (UART) links.

One versioned Python API for driving, sampling, and judging UART traffic in
OCAH cocotb tests. The primary use is a firmware-visible console (8-N-1,
configurable baud rate); the line engines model 5..9 data bits, none, even,
or odd parity, and 1, 1.5, or 2 stop bits.

The backend is native to this package: ``OcahUartMasterDriver`` drives
frames onto a line and ``OcahUartLineMonitor`` reconstructs frames from one.
No external UART library is required; ``OcahUartImportError`` is exported but
never raised.

Primary exports
---------------
OcahUartConsole       Active console host: send strings, read lines, expect patterns.
OcahUartMonitor       Passive TX+RX tap with byte and frame callbacks.
OcahUartChecker       Frame-level checker emitting ``CHK-UART-*`` evidence.
OcahUartMasterDriver  Active line driver with fault injection (console TX engine).
OcahUartLineMonitor   Passive frame sampler with classification (console RX engine).
OcahUartFrame         The frame record both engines keep.
OcahUartParity        Parity rule of a frame format.

Quick-start
-----------
::

    from ocah_uart_vip import OcahUartChecker, OcahUartConsole

    @cocotb.test()
    async def test_uart_console(dut):
        console = OcahUartConsole(dut.uart_rx, dut.uart_tx, name="console", baud=115200)
        console.init_signals()
        await console.send_string("hello\\n")
        line = await console.read_line(timeout_us=500)
        checker = OcahUartChecker(required_ids=("CHK-UART-DATA",))
        checker.check_data(b"hello\\n", console.rx_frames(), label="dut_tx")
        checker.finalize()

See ``examples/example_loopback.py`` for a complete example.
"""

from .ocah_uart_checker import OcahUartChecker
from .ocah_uart_console import OcahUartConsole, OcahUartError, OcahUartImportError
from .ocah_uart_master_driver import OcahUartMasterDriver
from .ocah_uart_monitor import OcahUartLineMonitor, OcahUartMonitor
from .ocah_uart_types import (
    DEFAULT_BAUD,
    DEFAULT_TIMEOUT_US,
    OcahUartFrame,
    OcahUartParity,
    bit_period_ns,
    frame_periods,
    parity_bit,
)

__all__ = [
    # Active host
    "OcahUartConsole",
    # Passive monitor
    "OcahUartMonitor",
    # Checker
    "OcahUartChecker",
    # Native line engines
    "OcahUartMasterDriver",
    "OcahUartLineMonitor",
    # Types and constants
    "DEFAULT_BAUD",
    "DEFAULT_TIMEOUT_US",
    "OcahUartFrame",
    "OcahUartParity",
    "bit_period_ns",
    "frame_periods",
    "parity_bit",
    # Error types
    "OcahUartError",
    "OcahUartImportError",
]

__version__ = "0.2.0"
