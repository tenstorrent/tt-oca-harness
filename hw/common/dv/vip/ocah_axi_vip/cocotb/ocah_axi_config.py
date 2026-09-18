# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bus geometry of one AXI4 or AXI4-Lite connection and the binding of an
interface scope at that geometry (side-neutral).

An ``ocah_axi_if`` instance carries the interface's default member widths so
the SV-UVM layer sees one ``virtual ocah_axi_if`` type; the geometry of the
bus behind it lives in the configuration, as in the SV twin
``uvm/ocah_axi_config.svh``, whose monitor masks sampled values down to the
real widths. The cocotb engines size their byte lanes from the signals they
are handed, so :meth:`OcahAxiConfig.bus` hands them a view of the scope in
which every geometry-bearing member reports the configured width: a read
returns the low bits, a write drives the low bits and holds the bits above
at zero. Members already at the configured width pass through unchanged, so
one call binds a flat port bundle or a real-geometry interface alike.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from cocotb.handle import Deposit, Force, Immediate
from cocotb.types import LogicArray
from cocotbext.axi import AxiBus, AxiLiteBus

from .ocah_axi_types import OcahAxiProtocol

__all__ = ["OcahAxiBus", "OcahAxiConfig"]

# The bus handle ``OcahAxiConfig.bus()`` returns and every agent, monitor, and
# watcher of this package accepts; consumers pass it through unchanged.
OcahAxiBus: TypeAlias = AxiBus | AxiLiteBus

_ADDR_MEMBERS = ("awaddr", "araddr")
_DATA_MEMBERS = ("wdata", "rdata")
_STRB_MEMBERS = ("wstrb",)
_ID_MEMBERS = ("awid", "bid", "arid", "rid")
_USER_MEMBERS = ("awuser", "wuser", "buser", "aruser", "ruser")
_MEMBER_VIEW_OWN = frozenset({"_handle", "_width", "_physical", "_mask"})
_SCOPE_VIEW_OWN = frozenset({"_scope", "_widths", "_prefix"})
# Every member an AXI4 / AXI4-Lite scope can carry. cocotb_bus locates signals by
# scanning dir() of the entity, and dir() of a cocotb handle lists what VPI
# iteration enumerates, which for an SV interface instance under VCS is none of
# its members. A by-name lookup resolves them on every simulator, so the view's
# dir() adds each of these it can resolve by name.
_BUS_MEMBERS = (
    "awid",
    "awaddr",
    "awlen",
    "awsize",
    "awburst",
    "awlock",
    "awcache",
    "awprot",
    "awqos",
    "awregion",
    "awuser",
    "awvalid",
    "awready",
    "wdata",
    "wstrb",
    "wlast",
    "wuser",
    "wvalid",
    "wready",
    "bid",
    "bresp",
    "buser",
    "bvalid",
    "bready",
    "arid",
    "araddr",
    "arlen",
    "arsize",
    "arburst",
    "arlock",
    "arcache",
    "arprot",
    "arqos",
    "arregion",
    "aruser",
    "arvalid",
    "arready",
    "rid",
    "rdata",
    "rresp",
    "rlast",
    "ruser",
    "rvalid",
    "rready",
)


@dataclass(frozen=True)
class OcahAxiConfig:
    """Geometry of one bus and the view that presents an interface scope at it.

    Carries the protocol and the address, data, ID, and user widths; the SV
    twin's component gating and expected-response tables have no cocotb
    counterpart here.
    """

    protocol: OcahAxiProtocol = OcahAxiProtocol.AXI4_LITE
    addr_width: int = 32
    data_width: int = 32
    id_width: int = 0
    user_width: int = 0

    def __post_init__(self) -> None:
        if self.addr_width < 1:
            raise ValueError(f"addr_width must be >= 1, got {self.addr_width}")
        if self.data_width < 8 or self.data_width & (self.data_width - 1):
            raise ValueError(f"data_width must be a power of two >= 8, got {self.data_width}")
        if self.id_width < 0 or self.user_width < 0:
            raise ValueError("id_width and user_width must be >= 0")
        if self.protocol is OcahAxiProtocol.AXI4_LITE and (self.id_width or self.user_width):
            raise ValueError("AXI4-Lite carries no ID or user signals; both widths must be 0")

    @property
    def strb_width(self) -> int:
        return self.data_width // 8

    def member_widths(self, prefix: str | None = None) -> dict[str, int]:
        """Configured width of every geometry-bearing member, keyed by signal name."""
        widths: dict[str, int] = {}
        widths.update({name: self.addr_width for name in _ADDR_MEMBERS})
        widths.update({name: self.data_width for name in _DATA_MEMBERS})
        widths.update({name: self.strb_width for name in _STRB_MEMBERS})
        if self.protocol is OcahAxiProtocol.AXI4:
            if self.id_width:
                widths.update({name: self.id_width for name in _ID_MEMBERS})
            if self.user_width:
                widths.update({name: self.user_width for name in _USER_MEMBERS})
        if prefix:
            return {f"{prefix}_{name}": width for name, width in widths.items()}
        return widths

    def bus(self, scope: Any, *, prefix: str | None = None) -> OcahAxiBus:
        """Bind ``scope`` at this geometry and return the package's bus handle.

        ``scope`` is an interface instance handle, or any hierarchy handle
        whose members are the AXI signals; ``prefix`` selects a flattened
        bundle (``<prefix>_awaddr`` ...) the way ``from_prefix`` does. Every
        agent, monitor, and watcher of this package accepts the returned bus.
        """
        view = _ScopeView(scope, self.member_widths(prefix), prefix)
        bus_type = AxiLiteBus if self.protocol is OcahAxiProtocol.AXI4_LITE else AxiBus
        if prefix:
            return bus_type.from_prefix(view, prefix)
        return bus_type.from_entity(view)


def _width_of(handle: Any) -> int:
    try:
        return len(handle)
    except TypeError:
        return 1


class _MemberView:
    """A signal handle confined to its low ``width`` bits; the bits above read and write as 0."""

    def __init__(self, handle: Any, width: int) -> None:
        physical = _width_of(handle)
        if width > physical:
            raise ValueError(
                f"{handle._path}: configured width {width} exceeds the member width {physical}"
            )
        self._handle = handle
        self._width = width
        self._physical = physical
        self._mask = (1 << width) - 1

    def __len__(self) -> int:
        return self._width

    @property
    def value(self) -> LogicArray:
        return LogicArray(str(self._handle.value)[-self._width :])

    @value.setter
    def value(self, value: Any) -> None:
        self._handle.set(self._widen(value))

    def set(self, value: Any) -> None:
        self._handle.set(self._widen(value))

    def setimmediatevalue(self, value: Any) -> None:
        self._handle.set(Immediate(self._widen(value)))

    def _widen(self, value: Any) -> Any:
        """The value at the member's physical width; the action wrapper, if any, is kept."""
        for action in (Deposit, Force, Immediate):
            if isinstance(value, action):
                return action(self._widen(value.value))
        if isinstance(value, LogicArray):
            bits = str(value)[-self._width :].rjust(self._width, "0")
            return LogicArray("0" * (self._physical - self._width) + bits)
        return int(value) & self._mask

    def __getattr__(self, name: str) -> Any:
        if name in _MEMBER_VIEW_OWN:
            raise AttributeError(name)
        return getattr(self._handle, name)


class _ScopeView:
    """A hierarchy handle whose listed members are presented through ``_MemberView``."""

    def __init__(self, scope: Any, widths: Mapping[str, int], prefix: str | None = None) -> None:
        self._scope = scope
        self._widths = dict(widths)
        self._prefix = prefix

    def __getattr__(self, name: str) -> Any:
        if name in _SCOPE_VIEW_OWN:
            raise AttributeError(name)
        handle = getattr(self._scope, name)
        width = self._widths.get(name)
        if width is None or width == _width_of(handle):
            return handle
        return _MemberView(handle, width)

    def __dir__(self) -> list[str]:
        names = set(dir(self._scope))
        for member in _BUS_MEMBERS:
            name = f"{self._prefix}_{member}" if self._prefix else member
            if name not in names and hasattr(self._scope, name):
                names.add(name)
        return sorted(names)
