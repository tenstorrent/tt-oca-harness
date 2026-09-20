# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
ocah_jtag_vip — OCAH-stable JTAG TAP driver and monitor for IEEE 1149.1.

This package provides a single, versioned Python API surface for driving and
monitoring standard JTAG (IEEE 1149.1) TAPs in OCAH cocotb tests.  It covers
the PTAP, STAP, and CPU TAP scenarios encountered in SMC and SEP debug flows.

Internally the driver uses ``cocotbext-jtag`` bus/device primitives plus OCAH
raw TAP stepping helpers. Tests import from this package only; no backend types
leak out. Without ``cocotbext-jtag`` the package imports: the checker,
the reference model, the state helpers, the device maps, and the reactive
device engine work, and constructing a master-side class or a slave monitor
raises ``OcahJtagVipBackendError`` naming the missing backend.

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
This package covers *IEEE 1149.1 only*.  IJTAG (IEEE 1687) instruments and
boundary-scan (EXTEST/SAMPLE) are out of scope.
"""

from .ocah_jtag_checker import OcahJtagChecker, OcahJtagCheckerError
from .ocah_jtag_device import OcahJtagDevice, OcahJtagRegister
from .ocah_jtag_item import OcahJtagScanItem, OcahJtagStateItem
from .ocah_jtag_master_config import OcahJtagMasterConfig
from .ocah_jtag_ref_model import TLR_TMS_ONES, OcahJtagTapRefModel
from .ocah_jtag_slave_config import OcahJtagSlaveConfig
from .ocah_jtag_slave_driver import (
    OcahJtagSlaveDriver,
    OcahJtagSlaveEngine,
    OcahJtagSlaveUpdate,
)
from .ocah_jtag_slave_sequence import OcahJtagSlaveSequence
from .ocah_jtag_state import OcahJtagState, jtag_tms_path, next_jtag_state


class OcahJtagVipBackendError(ImportError):
    """Raised at construction of a class whose backend is not importable."""


def _unavailable_class(class_name: str, backend: str):
    class _Unavailable:
        def __init__(self, *args, **kwargs) -> None:
            raise OcahJtagVipBackendError(
                f"{class_name} requires backend `{backend}`, which is not importable."
            )

    _Unavailable.__name__ = class_name
    _Unavailable.__qualname__ = class_name
    return _Unavailable


# The master side binds the wire through the backend's bus primitives; the
# slave monitor reuses the master monitor. Everything above imports without
# the backend.
try:
    from .ocah_jtag_master_agent import OcahJtagMasterAgent
    from .ocah_jtag_master_driver import OcahJtagMasterDriver, OcahJtagMasterDriverError
    from .ocah_jtag_master_monitor import OcahJtagMasterMonitor
    from .ocah_jtag_master_sequence import OcahJtagMasterSequence
    from .ocah_jtag_slave_agent import OcahJtagSlaveAgent
    from .ocah_jtag_slave_monitor import OcahJtagSlaveMonitor
except ModuleNotFoundError as exc:
    if "cocotbext" not in str(exc):
        raise
    OcahJtagMasterAgent = _unavailable_class("OcahJtagMasterAgent", "cocotbext-jtag")  # type: ignore[misc]
    OcahJtagMasterDriver = _unavailable_class("OcahJtagMasterDriver", "cocotbext-jtag")  # type: ignore[misc]
    OcahJtagMasterDriverError = OcahJtagVipBackendError  # type: ignore[misc,assignment]
    OcahJtagMasterMonitor = _unavailable_class("OcahJtagMasterMonitor", "cocotbext-jtag")  # type: ignore[misc]
    OcahJtagMasterSequence = _unavailable_class("OcahJtagMasterSequence", "cocotbext-jtag")  # type: ignore[misc]
    OcahJtagSlaveAgent = _unavailable_class("OcahJtagSlaveAgent", "cocotbext-jtag")  # type: ignore[misc]
    OcahJtagSlaveMonitor = _unavailable_class("OcahJtagSlaveMonitor", "cocotbext-jtag")  # type: ignore[misc]

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
    "OcahJtagVipBackendError",
    "TLR_TMS_ONES",
    "next_jtag_state",
    "jtag_tms_path",
    "IDCODE_OPCODE",
]

__version__ = "0.3.0"
