# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
ocah_jtag_vip — OCAH-stable JTAG TAP driver and monitor for IEEE 1149.1.

This package provides a single, versioned Python API surface for driving and
monitoring standard JTAG (IEEE 1149.1) TAPs in OCAH cocotb tests.  It covers
the PTAP, STAP, and CPU TAP scenarios encountered in SMC and SEP debug flows.

Internally the driver uses ``cocotbext-jtag`` bus/device primitives plus OCAH
raw TAP stepping helpers. Tests import from this package only; no backend types
leak out.

Primary exports
---------------
OcahJtagMasterDriver        — Active TAP driver with named high-level methods.
OcahJtagMasterMonitor    — Passive monitor that captures IR/DR transitions and fires
                     user callbacks with plain-int transaction records.
OcahJtagTapRefModel — Pure-Python IEEE 1149.1 TAP reference model used by
                     `OcahJtagChecker` for named TAP state/reset/BYPASS checks.

Standard IEEE 1149.1 instruction codes (re-exported for convenience)
---------------------------------------------------------------------
IDCODE_OPCODE      — 0x01  (standard IDCODE instruction)
BYPASS_OPCODE      — all-ones for the configured IR width

Quick-start
-----------
::

    from ocah_jtag_vip import OcahJtagMasterDriver

    @cocotb.test()
    async def test_idcode(dut):
        tap = OcahJtagMasterDriver(dut.jtag_ptap_if, name="ptap")
        tap.init_signals()
        await tap.reset_tap()
        idcode = await tap.read_idcode()
        assert idcode != 0xFFFF_FFFF, f"IDCODE read back unexpected value"

See ``examples/example_idcode.py`` for a complete runnable snippet.

Scope
-----
This package covers *IEEE 1149.1 only*.  IJTAG (IEEE 1687) instruments stay in
``bfm/ijtag_vip/``.  Boundary-scan (EXTEST/SAMPLE) is out of scope.
"""

from .ocah_jtag_master_agent import OcahJtagMasterAgent
from .ocah_jtag_checker import OcahJtagChecker, OcahJtagCheckerError
from .ocah_jtag_master_config import OcahJtagMasterConfig
from .ocah_jtag_device import OcahJtagDevice, OcahJtagRegister
from .ocah_jtag_master_driver import OcahJtagMasterDriver, OcahJtagMasterDriverError
from .ocah_jtag_item import OcahJtagScanItem, OcahJtagStateItem
from .ocah_jtag_master_monitor import OcahJtagMasterMonitor
from .ocah_jtag_ref_model import TLR_TMS_ONES, OcahJtagTapRefModel
from .ocah_jtag_master_sequence import OcahJtagMasterSequence
from .ocah_jtag_slave_agent import OcahJtagSlaveAgent
from .ocah_jtag_slave_config import OcahJtagSlaveConfig
from .ocah_jtag_slave_driver import (
    OcahJtagSlaveDriver,
    OcahJtagSlaveEngine,
    OcahJtagSlaveUpdate,
)
from .ocah_jtag_slave_monitor import OcahJtagSlaveMonitor
from .ocah_jtag_slave_sequence import OcahJtagSlaveSequence
from .ocah_jtag_state import OcahJtagState, jtag_tms_path, next_jtag_state

# Standard IDCODE instruction — IEEE 1149.1 §12.1.1 mandates opcode 0x01.
IDCODE_OPCODE: int = 0x01

__all__ = [
    "OcahJtagMasterAgent",
    "OcahJtagMasterConfig",
    "OcahJtagMasterDriver",
    "OcahJtagMasterDriverError",
    "OcahJtagMasterMonitor",
    "OcahJtagChecker",
    "OcahJtagCheckerError",
    "OcahJtagDevice",
    "OcahJtagRegister",
    "OcahJtagScanItem",
    "OcahJtagMasterSequence",
    "OcahJtagSlaveAgent",
    "OcahJtagSlaveConfig",
    "OcahJtagSlaveDriver",
    "OcahJtagSlaveEngine",
    "OcahJtagSlaveMonitor",
    "OcahJtagSlaveSequence",
    "OcahJtagSlaveUpdate",
    "OcahJtagStateItem",
    "OcahJtagState",
    "OcahJtagTapRefModel",
    "TLR_TMS_ONES",
    "next_jtag_state",
    "jtag_tms_path",
    "IDCODE_OPCODE",
]

__version__ = "0.3.0"
