# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
ocah_i3c_vip — OCAH-stable I3C bus BFM wrappers for cocotb testbenches.

This package provides a single, versioned Python API surface for driving and
monitoring I3C bus traffic in OCAH cocotb tests.  Internally it delegates to
``cocotbext_i3c`` (Antmicro, Apache-2.0); callers never import that package
directly and never see its types.

All public methods accept and return plain Python ints or bytes objects.
No ``cocotbext_i3c`` types leak out.

Primary exports
---------------
OcahI3cBus       — controller-mode I3C bus driver (SDR private read/write +
                   CCC subset: RSTDAA, ENTDAA, SETDASA, GETSTATUS, GETPID).
OcahI3cTarget    — target-mode I3C device model with static address and IBI.
OcahI3cMonitor   — passive bus monitor with per-transfer callback.

Quick-start
-----------
::

    from ocah_i3c_vip import OcahI3cBus

    @cocotb.test()
    async def test_i3c_priv_write(dut):
        clk = Clock(dut.clk_i, 10, units="ns")
        cocotb.start_soon(clk.start())

        bus = OcahI3cBus(
            sda_i=dut.i3c_sda_i,
            sda_o=dut.i3c_sda_o,
            scl_i=dut.i3c_scl_i,
            scl_o=dut.i3c_scl_o,
            name="i3c_host",
        )
        bus.init_signals()
        await bus.wait_for_reset(dut.rst_ni)

        await bus.priv_write(addr=0x08, data=bytes([0xDE, 0xAD]))
        rx = await bus.priv_read(addr=0x08, length=2)
        assert rx == bytes([0xDE, 0xAD])

See ``examples/example_priv_rw.py`` for an annotated snippet.

Upstream dependency
-------------------
``cocotbext-i3c`` version **1.1.0** (pinned).  The checked-in copy lives at:

    vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/

If the package is not importable the wrapper raises ``OcahI3cImportError`` at
construction time with instructions for adding it to the Python path.
"""

from .ocah_i3c_bus import OcahI3cBus, OcahI3cBusError, OcahI3cImportError
from .ocah_i3c_target import OcahI3cTarget, OcahI3cTargetError
from .ocah_i3c_monitor import OcahI3cMonitor
from .ocah_i3c_split_port import (
    I3C_IMPORT_DIAGNOSTIC,
    OcahI3cSplitPortController,
    OcahI3cSplitPortError,
    OcahI3cSplitPortTarget,
    ensure_cocotbext_i3c,
)

__all__ = [
    # Active drivers
    "OcahI3cBus",
    "OcahI3cTarget",
    # Passive monitor
    "OcahI3cMonitor",
    # Split-port open-drain adapters (SMC-style ext_low TBs)
    "OcahI3cSplitPortTarget",
    "OcahI3cSplitPortController",
    "OcahI3cSplitPortError",
    "ensure_cocotbext_i3c",
    "I3C_IMPORT_DIAGNOSTIC",
    # Error types
    "OcahI3cBusError",
    "OcahI3cTargetError",
    "OcahI3cImportError",
]

__version__ = "0.1.0"
# Pinned upstream version this wrapper was validated against.
_COCOTBEXT_I3C_VERSION = "1.1.0"
