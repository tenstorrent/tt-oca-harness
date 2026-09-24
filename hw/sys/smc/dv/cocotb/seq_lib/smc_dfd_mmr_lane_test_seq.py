# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write the DST and DST-sink MMRs one byte at a time, and touch their unmapped offsets.

Every address, field position, width, reset value and software-access type
comes from the generated register map through :mod:`seq_lib.smc_rdl_regmap`.
The vendored RTL is not a source for any value this sequence programs or
compares against.

The DFD MMR leaves on this branch write whole registers. Two parts of the
write and read decode of the DST and DST-sink blocks are never exercised:

* **Byte writes.** A one-byte store covers only part of a register's 4-byte
  lane. Every register of the two blocks except the sink's RAM data port takes
  one: the low byte is written with its complement. What a register may do is
  either ignore the write or take the byte in its software-writable bits; what
  it must not do is change any other byte. The readback is held to exactly
  those outcomes, and the register is then written back whole.
* **Unmapped offsets.** The RDL leaves holes inside each block's register
  range. One offset in each block's hole is read and written: the access has
  to complete, a read of an unmapped offset has to return 0 in every bit, as
  any bit no field occupies does, and the registers on either side of the hole
  have to hold their values across the write. The DST offset chosen is the
  offset of the sink's RAM data port in its own block, so a read there has to
  be decoded as an ordinary register read rather than a RAM read.
"""

from __future__ import annotations

from functools import lru_cache

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_registers_under

_CLA_ADDRMAP = "smc_cla"
_BLOCKS = ("dst", "dst_sink")
# Registers of the two blocks the byte sweep writes: all of them but the sink's
# RAM data port, whose read has a side effect on the RAM read side. A
# regenerated map that gains or loses one fails rather than silently changing
# the sweep.
_EXPECTED_SWEPT = 18
_NOT_SWEPT = ("Trdstramdata",)
# Unmapped offsets, relative to each block's first register: inside the hole
# between the DST's last low register and its trace configuration register,
# and inside the hole between the sink's implementation and window registers.
# The DST one is the sink's RAM data port offset.
_UNMAPPED = {"dst": 0x40, "dst_sink": 0x8}
_BYTE_MASK = 0xFF


def _writable_mask(reg: RdlReg) -> int:
    mask = 0
    for field in reg.fields:
        if field.access == "read-write":
            mask |= field.mask
    return mask


def _block_of(reg: RdlReg) -> str:
    return reg.path.split("/")[1].split("[", 1)[0]


@lru_cache(maxsize=1)
def _block_registers() -> dict[str, tuple[RdlReg, ...]]:
    found: dict[str, dict[str, RdlReg]] = {b: {} for b in _BLOCKS}
    for reg in rdl_registers_under(_CLA_ADDRMAP):
        block = _block_of(reg)
        if block in found:
            found[block].setdefault(reg.path.rsplit("/", 1)[1], reg)
    return {b: tuple(sorted(r.values(), key=lambda x: x.addr)) for b, r in found.items()}


@lru_cache(maxsize=1)
def _swept() -> tuple[RdlReg, ...]:
    regs = tuple(
        r
        for b in _BLOCKS
        for r in _block_registers()[b]
        if r.path.rsplit("/", 1)[1] not in _NOT_SWEPT
    )
    assert len(regs) == _EXPECTED_SWEPT, (
        f"the generated map carries {len(regs)} registers to sweep across {list(_BLOCKS)}, "
        f"not the {_EXPECTED_SWEPT} this sweep is sized for"
    )
    return regs


class smc_dfd_mmr_lane_test_seq(SmcCsrSeq):
    """Byte-write every DST and sink MMR, and touch each block's unmapped offset."""

    def __init__(self, name: str = "smc_dfd_mmr_lane_test_seq") -> None:
        super().__init__(name)
        self.byte_written = 0
        self.byte_dropped = 0
        self.byte_taken = 0
        self.unmapped: dict[str, tuple[int, int, int]] = {}
        self.value_checks = 0

    @staticmethod
    def _word_mask(reg: RdlReg) -> int:
        return (1 << (reg.width_bytes * 8)) - 1

    async def _read(self, reg: RdlReg, label: str) -> int:
        word = await self.csr_read(f"{reg.path}:{label}", reg.addr, length=reg.width_bytes)
        return word & self._word_mask(reg)

    async def _access(self, op: SmcSysAxiOp, name: str, addr: int, data: int = 0) -> SmcSysAxiItem:
        """One 4-byte access that may complete with an error response."""
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item

    async def _byte_write(self, reg: RdlReg) -> None:
        before = await self._read(reg, "before")
        low = (before & _BYTE_MASK) ^ _BYTE_MASK
        await self.csr_write(f"{reg.path}:byte", reg.addr, low, length=1)
        self.byte_written += 1
        after = await self._read(reg, "after")
        writable_low = _writable_mask(reg) & _BYTE_MASK
        assert (after ^ before) & ~_BYTE_MASK == 0 and (after & writable_low) in (
            before & writable_low,
            low & writable_low,
        ), (
            f"{reg.path} @ 0x{reg.addr:08x}: a one-byte write of 0x{low:02x} to its low byte "
            f"changed it from 0x{before:x} to 0x{after:x}: either a byte the store did not "
            f"cover moved, or the written bits took neither their old nor their new value"
        )
        if (after & writable_low) == (before & writable_low):
            self.byte_dropped += 1
        else:
            self.byte_taken += 1
        self.value_checks += 1
        await self.csr_write(f"{reg.path}:restore", reg.addr, before, length=reg.width_bytes)
        restored = await self._read(reg, "restore_rb")
        mask = _writable_mask(reg)
        assert restored & mask == before & mask, (
            f"{reg.path} @ 0x{reg.addr:08x}: written back whole to 0x{before:x}, its "
            f"software-writable bits read 0x{restored & mask:x}"
        )
        self.value_checks += 1

    async def _unmapped(self, block: str) -> None:
        regs = _block_registers()[block]
        base = regs[0].addr
        addr = base + _UNMAPPED[block]
        assert all(r.addr != addr for r in regs), (
            f"offset 0x{_UNMAPPED[block]:x} of {block} is a declared register in the "
            f"generated map, not a hole"
        )
        below = max((r for r in regs if r.addr < addr), key=lambda r: r.addr)
        above = min((r for r in regs if r.addr > addr), key=lambda r: r.addr)
        held = {r.path: await self._read(r, "hole_before") for r in (below, above)}
        rd = await self._access(SmcSysAxiOp.READ, f"{block}_hole", addr)
        if rd.resp_code == 0:
            assert rd.rdata == 0, (
                f"{block} unmapped offset 0x{_UNMAPPED[block]:x} (0x{addr:08x}) read back "
                f"0x{rd.rdata:x}; no field occupies it, so every bit has to read 0"
            )
        wr = await self._access(SmcSysAxiOp.WRITE, f"{block}_hole", addr, 0xFFFFFFFF)
        for reg in (below, above):
            now = await self._read(reg, "hole_after")
            assert now == held[reg.path], (
                f"{reg.path} @ 0x{reg.addr:08x} read 0x{held[reg.path]:x} before and 0x{now:x} "
                f"after an all-ones write to the {block} unmapped offset 0x{addr:08x}"
            )
        self.unmapped[block] = (addr, rd.resp_code, wr.resp_code)
        self.value_checks += 3

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        regs = _swept()
        for reg in regs:
            await self._byte_write(reg)
        assert self.byte_written == len(regs), (
            f"the byte sweep wrote {self.byte_written} of the {len(regs)} writable registers"
        )
        cocotb.log.info(
            "CHK-DFD-MMR-BYTE: every one of the %d DST and DST-sink registers other than the "
            "sink's RAM data port took a one-byte write of its low byte's complement and "
            "changed no other byte (%d ignored the write, %d took it in their writable bits), "
            "then was written back whole and read back",
            len(regs),
            self.byte_dropped,
            self.byte_taken,
        )

        for block in _BLOCKS:
            await self._unmapped(block)
        cocotb.log.info(
            "CHK-DFD-MMR-UNMAPPED: an unmapped offset of each block was read and written "
            "(%s, as address and read/write response codes); every access completed, a read "
            "that completed without error returned 0, and the registers on either side of "
            "each hole held their values across an all-ones write",
            {b: f"0x{a:08x} rd={r} wr={w}" for b, (a, r, w) in self.unmapped.items()},
        )
