# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
ocah_apb_vip — OCAH-stable APB VIP.

This package provides a single, versioned Python API surface for driving APB
peripheral-register traffic in OCAH cocotb tests.  All addresses, data values,
and byte-enable masks are plain Python ints; no internal VIP types leak out.

Backend note
------------
``cocotbext-axi`` provides a full APB suite (``ApbMaster``, ``ApbBus``,
``ApbSlave``, ``ApbRam``), so APB follows the same cocotbext-backend pattern as
``ocah_jtag_vip`` and ``ocah_axi_vip``.  It lives in its own package only
because it is a distinct protocol — one package per protocol.  The public API
mirrors ``OcahAxiLiteMasterAgent`` so tests can switch between APB and AXI4-Lite
register interfaces without restructuring driver code.

Quick-start
-----------
::

    from ocah_apb_vip import OcahApbMaster

    master = OcahApbMaster(dut.apb_if, dut.pclk, name="cfg_host")
    master.init_signals()
    await master.wait_for_reset()

    await master.write(0x0000_0000, 0x1)
    val = await master.read(0x0000_0000)
"""

from .ocah_apb_checker import OcahApbChecker, OcahApbCheckerError
from .ocah_apb_item import OcahApbItem
from .ocah_apb_master import (
    RESP_OKAY,
    RESP_SLVERR,
    OcahApbMaster,
    OcahApbMasterError,
    OcahApbReadResult,
    OcahApbWriteResult,
)
from .ocah_apb_monitor import OcahApbMonitor
from .ocah_apb_slave import OcahApbRam, OcahApbSlave

__all__ = [
    "OcahApbMaster",
    "OcahApbSlave",
    "OcahApbRam",
    "OcahApbMonitor",
    "OcahApbChecker",
    "OcahApbCheckerError",
    "OcahApbItem",
    "OcahApbMasterError",
    "OcahApbReadResult",
    "OcahApbWriteResult",
    "RESP_OKAY",
    "RESP_SLVERR",
]

__version__ = "0.1.0"
