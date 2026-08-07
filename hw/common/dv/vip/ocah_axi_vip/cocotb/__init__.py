# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
ocah_axi_vip — OCAH-stable wrappers for AXI4 and AXI4-Lite.

This package provides a single, versioned Python API surface for driving and
responding to AXI4 and AXI4-Lite traffic in OCAH cocotb tests.  All classes
accept and return plain Python ints; no internal VIP types leak out.

APB lives in its own package (``ocah_apb_vip``) because it is a distinct
protocol (one package per protocol); it also targets ``cocotbext-axi``, which
provides ``ApbMaster``/``ApbBus``.

Primary exports
---------------
OcahAxiMaster         — AXI4 full-bus master (burst-capable, ID-tagged).
OcahAxiLiteMaster     — AXI4-Lite master (single-beat, no IDs).
OcahAxiSlave          — AXI4 memory-backed slave/responder.
OcahAxiRam            — Alias for OcahAxiSlave.
OcahAxiLiteSlave      — AXI4-Lite memory-backed slave/responder.
OcahAxiLiteRam        — Alias for OcahAxiLiteSlave.
OcahAxiMonitor      — Passive AXI4 transaction monitor with callbacks.
OcahAxiLiteMonitor  — Passive AXI4-Lite transaction monitor with callbacks.

Quick-start
-----------
::

    from ocah_axi_vip import OcahAxiLiteMaster

    @cocotb.test()
    async def test_register_access(dut):
        clk = Clock(dut.aclk, 10, units="ns")
        cocotb.start_soon(clk.start())

        master = OcahAxiLiteMaster(dut.axil_if, name="cfg_host")
        master.init_signals()
        await master.wait_for_reset()

        await master.write(0x0000_0000, 0x1)
        val = await master.read(0x0000_0000)
        assert val == 0x1

See ``examples/example_register_access.py`` for a more complete example.
"""

from .ocah_axi_checker import OcahAxiChecker, OcahAxiCheckerError
from .ocah_axi_item import (
    OcahAxiItem,
    OcahAxiLiteReadItem,
    OcahAxiLiteWriteItem,
    OcahAxiReadItem,
    OcahAxiWriteItem,
)
from .ocah_axi_lite_slave import OcahAxiLiteRam, OcahAxiLiteSlave, OcahFaultAxiLiteRam
from .ocah_axi_slave import OcahAxiRam, OcahAxiSlave, OcahAxiSlaveImportError, OcahFaultAxiRam
from .results import (
    RESP_DECERR,
    RESP_EXOKAY,
    RESP_OKAY,
    RESP_SLVERR,
    RESP_TIMEOUT,
    OcahAxiReadResult,
    OcahAxiWriteResult,
)


class OcahAxiVipBackendError(ImportError):
    """Raised when an optional legacy-backed monitor cannot import its backend."""


def _unavailable_class(class_name: str, backend: str):
    class _Unavailable:
        def __init__(self, *args, **kwargs) -> None:
            raise OcahAxiVipBackendError(
                f"{class_name} requires backend `{backend}`, which is not importable."
            )

    _Unavailable.__name__ = class_name
    _Unavailable.__qualname__ = class_name
    return _Unavailable


try:
    from .ocah_axi_master import OcahAxiMaster, OcahAxiMasterError
    from .ocah_axi_lite_master import OcahAxiLiteMaster, OcahAxiLiteMasterError
except ModuleNotFoundError as exc:
    if "cocotbext" not in str(exc):
        raise
    OcahAxiMaster = _unavailable_class("OcahAxiMaster", "cocotbext-axi")
    OcahAxiMasterError = OcahAxiVipBackendError
    OcahAxiLiteMaster = _unavailable_class("OcahAxiLiteMaster", "cocotbext-axi")
    OcahAxiLiteMasterError = OcahAxiVipBackendError

try:
    from .ocah_axi_monitor import OcahAxiLiteMonitor, OcahAxiMonitor
except ModuleNotFoundError as exc:
    if "cocotb" not in str(exc):
        raise
    OcahAxiMonitor = _unavailable_class("OcahAxiMonitor", "cocotb")
    OcahAxiLiteMonitor = _unavailable_class("OcahAxiLiteMonitor", "cocotb")

__all__ = [
    # Master drivers
    "OcahAxiMaster",
    "OcahAxiLiteMaster",
    # Slave/responders
    "OcahAxiSlave",
    "OcahAxiRam",
    "OcahFaultAxiRam",
    "OcahAxiLiteSlave",
    "OcahAxiLiteRam",
    "OcahFaultAxiLiteRam",
    # Passive monitors
    "OcahAxiMonitor",
    "OcahAxiLiteMonitor",
    # Items and checkers
    "OcahAxiItem",
    "OcahAxiWriteItem",
    "OcahAxiReadItem",
    "OcahAxiLiteWriteItem",
    "OcahAxiLiteReadItem",
    "OcahAxiChecker",
    "OcahAxiCheckerError",
    # Error types
    "OcahAxiMasterError",
    "OcahAxiLiteMasterError",
    "OcahAxiSlaveImportError",
    "OcahAxiVipBackendError",
    "OcahAxiReadResult",
    "OcahAxiWriteResult",
    # AXI response code constants
    "RESP_OKAY",
    "RESP_EXOKAY",
    "RESP_SLVERR",
    "RESP_DECERR",
    "RESP_TIMEOUT",
]

__version__ = "0.1.0"
