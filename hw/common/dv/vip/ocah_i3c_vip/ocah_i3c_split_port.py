# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Split-port open-drain I3C adapters for OCAH cocotb TBs.

Some OCAH testbenches (notably SMC OSS) expose I3C pads as:

* ``sda_i`` / ``scl_i`` — resolved bus levels (cocotb reads)
* ``sda_o`` / ``scl_o`` (often named ``*_ext_low``) — TB drive inputs where
  ``1`` pulls the line low and ``0`` releases it

``cocotbext-i3c`` uses the opposite drive polarity on ``sda_o`` / ``scl_o``
(``1`` = release). These helpers invert polarity via property setters and
implement per-bus wired-AND so controller + target can share one split-port
bus.

Also centralizes the cocotb 2.0 import shims and PYTHONPATH bootstrap for the
vendored ``cocotbext-i3c`` package.

Public API
----------
ensure_cocotbext_i3c() -> (available, diagnostic)
OcahI3cSplitPortTarget(sda_i, sda_o, scl_i, scl_o, *, address, name)
OcahI3cSplitPortController(sda_i, sda_o, scl_i, scl_o, *, speed, name)
"""

from __future__ import annotations

import logging
import os
import sys

__all__ = [
    "ensure_cocotbext_i3c",
    "I3C_IMPORT_DIAGNOSTIC",
    "OcahI3cSplitPortTarget",
    "OcahI3cSplitPortController",
    "OcahI3cSplitPortError",
]


class OcahI3cSplitPortError(RuntimeError):
    """Raised when split-port I3C VIP wiring or usage is invalid."""


def ensure_cocotbext_i3c() -> tuple[bool, str]:
    """Locate vendored cocotbext-i3c and apply cocotb 2.0 import shims.

    Returns ``(available, diagnostic)``. ``available`` is True only when
    ``cocotbext_i3c.i3c_target.I3CTarget`` imports cleanly.
    """
    if "cocotbext_i3c.i3c_target" in sys.modules:
        return True, "already-imported"

    roots = []
    och = os.environ.get("OCH_ROOT", "")
    if och:
        roots.append(os.path.join(och, "deps", "i3c-core", "third_party", "cocotbext-i3c", "src"))
    # Fallbacks used by various checkout layouts.
    here = os.path.abspath(__file__)
    # .../hw/common/dv/vip/ocah_i3c_vip/ocah_i3c_split_port.py -> repo root ~6 up
    repo = here
    for _ in range(10):
        repo = os.path.dirname(repo)
        if os.path.isdir(os.path.join(repo, "deps")):
            roots.append(
                os.path.join(repo, "deps", "i3c-core", "third_party", "cocotbext-i3c", "src")
            )
            break

    for candidate in roots:
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)

    # cocotb 2.0 removed ModifiableObject and private time helpers that the
    # vendored cocotbext-i3c still imports. Alias them for import compatibility.
    try:
        import cocotb.handle as _cocotb_handle

        if not hasattr(_cocotb_handle, "ModifiableObject"):
            _compat = (
                getattr(_cocotb_handle, "LogicObject", None)
                or getattr(_cocotb_handle, "NonConstantObject", None)
                or getattr(_cocotb_handle, "SimHandleBase", object)
            )
            _cocotb_handle.ModifiableObject = _compat

        import cocotb.utils as _cocotb_utils

        if not hasattr(_cocotb_utils, "_get_simulator_precision"):
            import cocotb.simulator as _cocotb_sim

            def _get_simulator_precision() -> int:
                return _cocotb_sim.get_precision()

            _cocotb_utils._get_simulator_precision = _get_simulator_precision
        if not hasattr(_cocotb_utils, "_get_log_time_scale"):
            _log_time_scale = {
                "fs": -15,
                "ps": -12,
                "ns": -9,
                "us": -6,
                "ms": -3,
                "sec": 0,
                "s": 0,
            }

            def _get_log_time_scale(units: str) -> int:
                return _log_time_scale[units.lower()]

            _cocotb_utils._get_log_time_scale = _get_log_time_scale
    except Exception:  # noqa: BLE001 - best-effort compat shim
        pass

    try:
        from cocotbext_i3c.i3c_target import I3CTarget  # noqa: F401

        return True, "ok"
    except SyntaxError as exc:
        return False, (
            f"cocotbext-i3c requires Python 3.10+ (match statement); "
            f"current Python {sys.version_info.major}.{sys.version_info.minor}: {exc}"
        )
    except ImportError as exc:
        return False, f"ImportError: {exc}"


_HAS_I3C, _I3C_IMPORT_DIAG = ensure_cocotbext_i3c()
I3C_IMPORT_DIAGNOSTIC = _I3C_IMPORT_DIAG

# Per-bus wired-AND vote sets keyed by id(drive_handle).
_SDA_LOW_DRIVERS: dict[int, set[int]] = {}
_SCL_LOW_DRIVERS: dict[int, set[int]] = {}


def _release_ext_low_idle(entity) -> None:
    sda_o = getattr(entity, "sda_o", None)
    scl_o = getattr(entity, "scl_o", None)
    if sda_o is not None:
        sda_o.setimmediatevalue(0)
        drivers = _SDA_LOW_DRIVERS.get(id(sda_o))
        if drivers is not None:
            drivers.discard(id(entity))
    if scl_o is not None:
        scl_o.setimmediatevalue(0)
        drivers = _SCL_LOW_DRIVERS.get(id(scl_o))
        if drivers is not None:
            drivers.discard(id(entity))


class _OcahI3cSplitPortMixin:
    """Polarity + per-bus wired-AND override for I3CTarget / I3cController."""

    @property
    def sda(self):  # type: ignore[override]
        return self.sda_i.value

    @sda.setter
    def sda(self, value) -> None:  # type: ignore[override]
        sda_o = self.sda_o
        if sda_o is None:
            return
        bus_key = id(sda_o)
        drivers = _SDA_LOW_DRIVERS.setdefault(bus_key, set())
        if bool(value):
            drivers.discard(id(self))
        else:
            drivers.add(id(self))
        sda_o.value = 1 if drivers else 0

    @property
    def scl(self):  # type: ignore[override]
        return self.scl_i.value

    @scl.setter
    def scl(self, value) -> None:  # type: ignore[override]
        scl_o = self.scl_o
        if scl_o is None:
            return
        bus_key = id(scl_o)
        drivers = _SCL_LOW_DRIVERS.setdefault(bus_key, set())
        if bool(value):
            drivers.discard(id(self))
        else:
            drivers.add(id(self))
        scl_o.value = 1 if drivers else 0


if _HAS_I3C:
    from cocotbext_i3c.i3c_controller import I3cController as _I3cController
    from cocotbext_i3c.i3c_target import I3CTarget as _I3CTarget

    class OcahI3cSplitPortTarget(_OcahI3cSplitPortMixin, _I3CTarget):
        """I3C target for split-port open-drain TBs."""

        def __init__(
            self,
            sda_i,
            sda_o,
            scl_i,
            scl_o,
            *,
            address: int = 0x50,
            name: str = "OcahI3cSplitPortTarget",
        ) -> None:
            super().__init__(
                sda_i=sda_i,
                sda_o=sda_o,
                scl_i=scl_i,
                scl_o=scl_o,
                address=address,
            )
            _release_ext_low_idle(self)
            self.log = logging.getLogger(name)
            self.log.info("%s bound: address=0x%02X", name, address)

    class OcahI3cSplitPortController(_OcahI3cSplitPortMixin, _I3cController):
        """I3C controller for split-port open-drain TBs."""

        def __init__(
            self,
            sda_i,
            sda_o,
            scl_i,
            scl_o,
            *,
            speed: float = 4e6,
            name: str = "OcahI3cSplitPortController",
        ) -> None:
            super().__init__(
                sda_i=sda_i,
                sda_o=sda_o,
                scl_i=scl_i,
                scl_o=scl_o,
                speed=speed,
                silent=True,
            )
            _release_ext_low_idle(self)
            self.log = logging.getLogger(name)
            self.log.info("%s bound: speed=%.0f Hz", name, speed)

else:  # pragma: no cover

    class OcahI3cSplitPortTarget:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise OcahI3cSplitPortError(
                "OcahI3cSplitPortTarget unavailable: " + _I3C_IMPORT_DIAG
            )

    class OcahI3cSplitPortController:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise OcahI3cSplitPortError(
                "OcahI3cSplitPortController unavailable: " + _I3C_IMPORT_DIAG
            )
