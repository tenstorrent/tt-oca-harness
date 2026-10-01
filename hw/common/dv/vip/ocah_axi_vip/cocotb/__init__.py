# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
ocah_axi_vip — OCAH-stable wrappers for AXI4 and AXI4-Lite.

This package provides a single, versioned Python API surface for driving and
responding to AXI4 and AXI4-Lite traffic in OCAH cocotb tests.  All classes
accept and return plain Python ints; no internal VIP types leak out.

The VIP is implemented per side with side-token naming
(``ocah_axi[_lite]_master_*`` / ``ocah_axi[_lite]_slave_*``); tests consume
each side through its ``*Sequence`` class (the mandated test-facing surface),
usually obtained from the side's ``*Agent`` bundle. Wire-level bus
observation (monitor, checker, reference model, scoreboard, watchers) is
side-neutral shared collateral and carries no side token.

Primary exports
---------------
OcahAxiMasterAgent / OcahAxiMasterSequence         — AXI4 full-bus master (burst-capable, ID-tagged).
OcahAxiLiteMasterAgent / OcahAxiLiteMasterSequence — AXI4-Lite master (single-beat, no IDs).
OcahAxiSlaveAgent / OcahAxiSlaveSequence           — AXI4 memory-backed responder.
OcahAxiLiteSlaveAgent / OcahAxiLiteSlaveSequence   — AXI4-Lite memory-backed responder.
OcahAxiMonitor / OcahAxiLiteMonitor  — Passive transaction monitors with callbacks.
OcahAxiRefModel       — Shadow memory + expected-response reference model.
OcahAxiScoreboard     — Evidence-emitting scoreboard over monitor item streams.
OcahAxiProtocolWatcher / OcahAxiLiteProtocolWatcher — cycle-level rule watchers.
OcahAxiConfig         — Bus geometry; binds an interface scope at the real widths.

Quick-start
-----------
::

    from ocah_axi_vip import OcahAxiLiteMasterAgent

    @cocotb.test()
    async def test_register_access(dut):
        clk = Clock(dut.aclk, 10, units="ns")
        cocotb.start_soon(clk.start())

        master = OcahAxiLiteMasterAgent(dut.axil_if, name="cfg_host").sequence
        master.init_signals()
        await master.wait_for_reset()

        await master.write(0x0000_0000, 0x1)
        val = await master.read(0x0000_0000)
        assert val == 0x1

See ``examples/example_register_access.py`` for a more complete example.
"""

from typing import Any

from .ocah_axi_checker import OcahAxiChecker, OcahAxiCheckerError
from .ocah_axi_item import (
    OcahAxiItem,
    OcahAxiLiteReadItem,
    OcahAxiLiteWriteItem,
    OcahAxiReadItem,
    OcahAxiReadPairResult,
    OcahAxiReadResult,
    OcahAxiWriteItem,
    OcahAxiWritePairResult,
    OcahAxiWriteResult,
)
from .ocah_axi_ref_model import (
    OcahAxiPrediction,
    OcahAxiRefModel,
    OcahAxiRegionExpectation,
)
from .ocah_axi_scoreboard import OcahAxiScoreboard
from .ocah_axi_types import (
    DEFAULT_TIMEOUT_NS,
    PROT_INSTRUCTION,
    PROT_NONSECURE,
    PROT_PRIVILEGED,
    RESP_DECERR,
    RESP_EXOKAY,
    RESP_OKAY,
    RESP_SLVERR,
    RESP_TIMEOUT,
    OcahAxiProtocol,
    default_timeout_ns,
    resp_name,
    worst_resp,
)


class OcahAxiVipBackendError(ImportError):
    """Raised at construction of a class whose optional backend is not importable."""


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
    from .ocah_axi_config import OcahAxiBus, OcahAxiConfig
    from .ocah_axi_lite_master_agent import OcahAxiLiteMasterAgent
    from .ocah_axi_lite_master_config import OcahAxiLiteMasterConfig
    from .ocah_axi_lite_master_driver import OcahAxiLiteMasterDriver
    from .ocah_axi_lite_master_sequence import OcahAxiLiteMasterError, OcahAxiLiteMasterSequence
    from .ocah_axi_lite_slave_agent import OcahAxiLiteSlaveAgent
    from .ocah_axi_lite_slave_config import OcahAxiLiteSlaveConfig
    from .ocah_axi_lite_slave_driver import OcahAxiLiteSlaveDriver
    from .ocah_axi_lite_slave_sequence import OcahAxiLiteSlaveSequence
    from .ocah_axi_master_agent import OcahAxiMasterAgent
    from .ocah_axi_master_config import OcahAxiMasterConfig
    from .ocah_axi_master_driver import (
        OcahAxiIdCapture,
        OcahAxiMasterDriver,
        apply_profile,
        clear_profile,
    )
    from .ocah_axi_master_sequence import OcahAxiMasterError, OcahAxiMasterSequence
    from .ocah_axi_slave_agent import OcahAxiSlaveAgent
    from .ocah_axi_slave_config import OcahAxiSlaveConfig
    from .ocah_axi_slave_driver import OcahAxiSlaveDriver
    from .ocah_axi_slave_sequence import OcahAxiSlaveSequence
except ModuleNotFoundError as exc:
    if "cocotbext" not in str(exc):
        raise
    OcahAxiConfig = _unavailable_class("OcahAxiConfig", "cocotbext-axi")
    OcahAxiBus = Any  # type: ignore[misc,assignment]
    OcahAxiMasterAgent = _unavailable_class("OcahAxiMasterAgent", "cocotbext-axi")
    OcahAxiMasterConfig = _unavailable_class("OcahAxiMasterConfig", "cocotbext-axi")
    OcahAxiMasterDriver = _unavailable_class("OcahAxiMasterDriver", "cocotbext-axi")
    OcahAxiIdCapture = _unavailable_class("OcahAxiIdCapture", "cocotbext-axi")

    def apply_profile(driver, profile) -> None:
        raise OcahAxiVipBackendError(
            "apply_profile requires backend `cocotbext-axi`, which is not importable."
        )

    def clear_profile(driver) -> None:
        raise OcahAxiVipBackendError(
            "clear_profile requires backend `cocotbext-axi`, which is not importable."
        )

    OcahAxiMasterSequence = _unavailable_class("OcahAxiMasterSequence", "cocotbext-axi")
    OcahAxiMasterError = OcahAxiVipBackendError
    OcahAxiLiteMasterAgent = _unavailable_class("OcahAxiLiteMasterAgent", "cocotbext-axi")
    OcahAxiLiteMasterConfig = _unavailable_class("OcahAxiLiteMasterConfig", "cocotbext-axi")
    OcahAxiLiteMasterDriver = _unavailable_class("OcahAxiLiteMasterDriver", "cocotbext-axi")
    OcahAxiLiteMasterSequence = _unavailable_class("OcahAxiLiteMasterSequence", "cocotbext-axi")
    OcahAxiLiteMasterError = OcahAxiVipBackendError
    OcahAxiSlaveAgent = _unavailable_class("OcahAxiSlaveAgent", "cocotbext-axi")
    OcahAxiSlaveConfig = _unavailable_class("OcahAxiSlaveConfig", "cocotbext-axi")
    OcahAxiSlaveDriver = _unavailable_class("OcahAxiSlaveDriver", "cocotbext-axi")
    OcahAxiSlaveSequence = _unavailable_class("OcahAxiSlaveSequence", "cocotbext-axi")
    OcahAxiLiteSlaveAgent = _unavailable_class("OcahAxiLiteSlaveAgent", "cocotbext-axi")
    OcahAxiLiteSlaveConfig = _unavailable_class("OcahAxiLiteSlaveConfig", "cocotbext-axi")
    OcahAxiLiteSlaveDriver = _unavailable_class("OcahAxiLiteSlaveDriver", "cocotbext-axi")
    OcahAxiLiteSlaveSequence = _unavailable_class("OcahAxiLiteSlaveSequence", "cocotbext-axi")

try:
    from .ocah_axi_monitor import OcahAxiLiteMonitor, OcahAxiMonitor
except ModuleNotFoundError as exc:
    if "cocotb" not in str(exc):
        raise
    OcahAxiMonitor = _unavailable_class("OcahAxiMonitor", "cocotb")
    OcahAxiLiteMonitor = _unavailable_class("OcahAxiLiteMonitor", "cocotb")

try:
    from .ocah_axi_protocol_watcher import (
        OcahAxiLiteProtocolWatcher,
        OcahAxiProtocolWatcher,
        OcahAxiWatchFinding,
    )
except ModuleNotFoundError as exc:
    if "cocotb" not in str(exc):
        raise
    OcahAxiProtocolWatcher = _unavailable_class("OcahAxiProtocolWatcher", "cocotb")
    OcahAxiLiteProtocolWatcher = _unavailable_class("OcahAxiLiteProtocolWatcher", "cocotb")
    OcahAxiWatchFinding = None

from .ocah_axi_master_config import AxiTimingProfile

__all__ = [
    # Per-channel timing control (AW/W ordering, response backpressure)
    "AxiTimingProfile",
    "apply_profile",
    "clear_profile",
    # Master side (AXI4 and AXI4-Lite)
    "OcahAxiMasterAgent",
    "OcahAxiMasterConfig",
    "OcahAxiMasterDriver",
    "OcahAxiMasterSequence",
    "OcahAxiIdCapture",
    "OcahAxiLiteMasterAgent",
    "OcahAxiLiteMasterConfig",
    "OcahAxiLiteMasterDriver",
    "OcahAxiLiteMasterSequence",
    # Slave side (AXI4 and AXI4-Lite)
    "OcahAxiSlaveAgent",
    "OcahAxiSlaveConfig",
    "OcahAxiSlaveDriver",
    "OcahAxiSlaveSequence",
    "OcahAxiLiteSlaveAgent",
    "OcahAxiLiteSlaveConfig",
    "OcahAxiLiteSlaveDriver",
    "OcahAxiLiteSlaveSequence",
    # Passive monitors
    "OcahAxiBus",
    "OcahAxiConfig",
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
    # Reference model, scoreboard, and protocol watchers
    "OcahAxiRefModel",
    "OcahAxiRegionExpectation",
    "OcahAxiPrediction",
    "OcahAxiScoreboard",
    "OcahAxiProtocolWatcher",
    "OcahAxiLiteProtocolWatcher",
    "OcahAxiWatchFinding",
    # Error types
    "OcahAxiMasterError",
    "OcahAxiLiteMasterError",
    "OcahAxiVipBackendError",
    "OcahAxiReadResult",
    "OcahAxiWriteResult",
    "OcahAxiReadPairResult",
    "OcahAxiWritePairResult",
    # AXI response code constants
    "OcahAxiProtocol",
    "RESP_OKAY",
    "RESP_EXOKAY",
    "RESP_SLVERR",
    "RESP_DECERR",
    "RESP_TIMEOUT",
    "DEFAULT_TIMEOUT_NS",
    "default_timeout_ns",
    "resp_name",
    "worst_resp",
    # AxPROT bit values
    "PROT_PRIVILEGED",
    "PROT_NONSECURE",
    "PROT_INSTRUCTION",
]

__version__ = "0.2.0"
