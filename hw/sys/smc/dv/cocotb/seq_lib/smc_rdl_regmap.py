# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register and field metadata read from the generated IP-XACT map.

``hw/sys/smc/regs/gen/ipxact/smc.xml`` is PeakRDL's IP-XACT export of the same
``smc.rdl`` sources the C, Python and SystemVerilog outputs are generated from.
It is the only generated artefact that carries the RDL *software access type*
of every field -- ``read-only`` / ``read-write`` / ``write-only``, the
``oneToSet`` / ``oneToClear`` write modifier, the read side effect and the
``volatile`` flag PeakRDL sets when hardware can change the field. The C block
headers and ``smc_reg.py`` carry addresses, bit positions and reset values but
no access type, so a test that wants an expectation derived from the register
contract rather than from an observed read has to read it here.

Both maps are used together, not one instead of the other: every address this
module hands out is compared against the matching ``*_REG_ADDR`` symbol in
``hw/sys/smc/regs/gen/py/smc_reg.py`` (the map the other SMC CSR sequences
address through) before a sequence sees it, so the two generated views of the
same RDL have to agree or the lookup raises.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache

from .smc_addr_map import _REPO

_IPXACT = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "ipxact" / "smc.xml"
_SMC_REG_PY = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "py"
_NS = {"i": "http://www.accellera.org/XMLSchema/IPXACT/1685-2014"}

# IP-XACT numbers are SystemVerilog-style literals ('h1000) or plain integers.
_VERILOG_HEX = re.compile(r"^'h([0-9A-Fa-f_]+)$")


def _num(text: str) -> int:
    text = text.strip()
    match = _VERILOG_HEX.match(text)
    return int(match.group(1).replace("_", ""), 16) if match else int(text, 0)


@dataclass(frozen=True)
class RdlField:
    """One RDL field of one register, as the generated IP-XACT declares it."""

    name: str
    offset: int
    width: int
    reset: int | None
    access: str
    volatile: bool
    modified_write: str | None
    read_action: str | None

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.offset

    @property
    def plain_rw(self) -> bool:
        """Software-writable with a readback the register contract pins exactly.

        ``read-write`` alone is not enough: ``volatile`` means hardware also
        drives the field (``hw = w`` / ``hw = rw``, a self-clearing
        ``singlepulse``, or a field with a software-access side effect), and a
        ``modifiedWriteValue`` / ``readAction`` means the written value is not
        what lands in the storage. For any of those the written value is not the
        value the next read must return, so a generic write/readback sweep has
        no expectation to compare against and must leave the field alone.
        """
        return (
            self.access == "read-write"
            and not self.volatile
            and self.modified_write is None
            and self.read_action is None
        )

    @property
    def static(self) -> bool:
        """Reset value survives until software writes the field."""
        return not self.volatile and self.reset is not None


@dataclass(frozen=True)
class RdlReg:
    """One register instance (one array element for a register array)."""

    path: str
    symbol: str
    addr: int
    width_bytes: int
    index: int | None
    fields: tuple[RdlField, ...]

    @property
    def base_path(self) -> str:
        """Path without the array index, i.e. the register the RDL declares."""
        return self.path.split("[", 1)[0]

    @property
    def declared_mask(self) -> int:
        """Bits some field occupies. Everything else is unimplemented."""
        mask = 0
        for field in self.fields:
            mask |= field.mask
        return mask

    @property
    def reset_word(self) -> int:
        word = 0
        for field in self.fields:
            if field.reset is not None:
                word |= (field.reset << field.offset) & field.mask
        return word

    @property
    def rw_mask(self) -> int:
        mask = 0
        for field in self.fields:
            if field.plain_rw:
                mask |= field.mask
        return mask

    @property
    def static_mask(self) -> int:
        mask = 0
        for field in self.fields:
            if field.static:
                mask |= field.mask
        return mask


def _field_of(node: ET.Element) -> RdlField:
    def text(tag: str) -> str | None:
        found = node.find(f"i:{tag}", _NS)
        return found.text if found is not None else None

    reset = node.find("i:resets/i:reset/i:value", _NS)
    return RdlField(
        name=text("name") or "",
        offset=int(text("bitOffset") or 0),
        width=int(text("bitWidth") or 0),
        reset=_num(reset.text) if reset is not None and reset.text else None,
        access=text("access") or "",
        volatile=(text("volatile") or "false").lower() == "true",
        modified_write=text("modifiedWriteValue"),
        read_action=text("readAction"),
    )


@lru_cache(maxsize=1)
def _smc_reg_module():
    if str(_SMC_REG_PY) not in sys.path:
        sys.path.insert(0, str(_SMC_REG_PY))
    import smc_reg

    return smc_reg


@lru_cache(maxsize=1)
def _registers() -> dict[str, RdlReg]:
    root = ET.parse(_IPXACT).getroot()
    block = root.find(".//i:addressBlock", _NS)
    if block is None:
        raise RuntimeError(f"no ipxact:addressBlock in {_IPXACT}")

    out: dict[str, RdlReg] = {}

    def walk(node: ET.Element, prefix: list[str], base: int) -> None:
        for sub in node.findall("i:registerFile", _NS):
            name = sub.find("i:name", _NS).text
            offset = _num(sub.find("i:addressOffset", _NS).text)
            walk(sub, prefix + [name], base + offset)
        for reg in node.findall("i:register", _NS):
            name = reg.find("i:name", _NS).text
            addr = base + _num(reg.find("i:addressOffset", _NS).text)
            width_bytes = _num(reg.find("i:size", _NS).text) // 8
            dim = reg.find("i:dim", _NS)
            fields = tuple(_field_of(f) for f in reg.findall("i:field", _NS))
            stem = "_".join(part.upper() for part in prefix + [name])
            path = "/".join(prefix + [name])
            if dim is None:
                out[path] = RdlReg(path, f"{stem}_REG_ADDR", addr, width_bytes, None, fields)
            else:
                for i in range(int(dim.text)):
                    out[f"{path}[{i}]"] = RdlReg(
                        f"{path}[{i}]",
                        f"{stem}_{i}__REG_ADDR",
                        addr + i * width_bytes,
                        width_bytes,
                        i,
                        fields,
                    )

    walk(block, [], _num(block.find("i:baseAddress", _NS).text))
    return out


def rdl_register(path: str) -> RdlReg:
    """Return one register's metadata, cross-checked against ``smc_reg.py``.

    ``path`` is the IP-XACT hierarchy with ``/`` between register-file names and
    an index in brackets for a register array, e.g. ``smc_cpu_ctrl/SCRATCH[3]``.
    """
    try:
        reg = _registers()[path]
    except KeyError as exc:
        raise KeyError(f"{path} is not a register in {_IPXACT}") from exc
    mapped = getattr(_smc_reg_module(), reg.symbol, None)
    assert mapped is not None, (
        f"{path}: the IP-XACT map places it at 0x{reg.addr:08x} but the generated "
        f"smc_reg.py declares no {reg.symbol}, so the two generated views of the "
        f"same RDL do not agree on this register"
    )
    assert mapped == reg.addr, (
        f"{path}: IP-XACT says 0x{reg.addr:08x}, smc_reg.{reg.symbol} says 0x{mapped:08x}"
    )
    return reg


def rdl_array(path: str) -> tuple[RdlReg, ...]:
    """Every element of a register array, in index order."""
    regs = [reg for key, reg in _registers().items() if key.startswith(f"{path}[")]
    assert regs, f"{path} is not a register array in {_IPXACT}"
    return tuple(rdl_register(f"{path}[{i}]") for i in range(len(regs)))


def rdl_registers_under(prefix: str) -> tuple[RdlReg, ...]:
    """Every register instance whose hierarchy starts at ``prefix``."""
    regs = tuple(
        reg for key, reg in _registers().items() if key == prefix or key.startswith(f"{prefix}/")
    )
    assert regs, f"{prefix} names no register in {_IPXACT}"
    return regs
