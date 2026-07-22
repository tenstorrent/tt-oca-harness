# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
ocah_i2c_vip — OCAH-stable cocotb wrappers for I2C master/device traffic.

This package provides a single, versioned Python API surface for driving and
monitoring I2C bus transactions in OCAH cocotb tests.  Primary use-cases are
SMC I2C top-level tests and EEPROM-style device emulation.

Internally the drivers delegate to ``cocotbext-i2c`` when that library is
available in the environment.  When it is not installed the classes raise
``OcahI2cImportError`` at construction time with a clear install message,
mirroring the ``ocah_axi_vip`` migration-plan pattern.

Primary exports
---------------
OcahI2cMaster   — Active I2C master: write, read, combined transactions.
OcahI2cDevice   — Passive I2C device emulator: register address-based callbacks.
OcahI2cMemory   — EEPROM-style memory device: preload, dump.
OcahI2cMonitor  — Passive bus monitor with per-transaction callbacks.
OcahI2cSplitPortMaster / Memory / Monitor — split-port ext_low TB adapters.

Quick-start
-----------
::

    from ocah_i2c_vip import OcahI2cMaster

    @cocotb.test()
    async def test_i2c_write_read(dut):
        clk = Clock(dut.clk, 10, units="ns")
        cocotb.start_soon(clk.start())

        master = OcahI2cMaster(dut.scl, dut.sda, dut.clk, name="i2c_master")
        master.init_signals()

        await master.write(0x50, b"\\x00\\x01\\x02")
        data = await master.read(0x50, length=3)
        assert data == b"\\x00\\x01\\x02"

See ``examples/example_i2c_eeprom.py`` for a more complete example.
"""

from .ocah_i2c_master import OcahI2cMaster, OcahI2cError, OcahI2cImportError
from .ocah_i2c_device import OcahI2cDevice
from .ocah_i2c_memory import OcahI2cMemory
from .ocah_i2c_monitor import OcahI2cMonitor
from .ocah_i2c_split_port import (
    OcahI2cSplitPortError,
    OcahI2cSplitPortMaster,
    OcahI2cSplitPortMemory,
    OcahI2cSplitPortMonitor,
)

__all__ = [
    # Active master
    "OcahI2cMaster",
    # Device emulators
    "OcahI2cDevice",
    "OcahI2cMemory",
    # Passive monitor
    "OcahI2cMonitor",
    # Split-port open-drain adapters (SMC-style ext_low TBs)
    "OcahI2cSplitPortMaster",
    "OcahI2cSplitPortMemory",
    "OcahI2cSplitPortMonitor",
    "OcahI2cSplitPortError",
    # Error types
    "OcahI2cError",
    "OcahI2cImportError",
]

__version__ = "0.1.0"
