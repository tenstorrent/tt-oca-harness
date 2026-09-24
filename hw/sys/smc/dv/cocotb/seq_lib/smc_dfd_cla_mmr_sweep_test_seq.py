# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RDL-contract write sweep of the CLA MMR block over SEP_IN AXI.

The CLA sub-block of the SMC_CLA aperture carries 113 registers. Every address,
reset value, field position, software-access type and volatility below comes
from the generated register map through :mod:`seq_lib.smc_cla_regmap`, which
reads the PeakRDL IP-XACT export of ``smc_cla.rdl`` and cross-checks each
address against the matching ``smc_reg.py`` symbol. Nothing here is a
hand-transcribed address, mask or reset word, and the vendored RTL is not a
source for any of them.

``smc_remap_cla_test`` reads the aperture at reset. This sequence drives the
write side of the same contract:

* read at reset -- bits no field of the register occupies must read 0, and
  every field whose RDL reset survives until software writes it must carry it;
* write the low half, then the high half, each as its own narrower access, so
  the byte lanes over the other half are deasserted. Each readback also proves
  the untouched half kept its value, which is what distinguishes a per-half
  write enable from a whole-register one;
* restore the RDL reset a half at a time and read the register back.

Registers with no software-writable field are hardware-driven status
(``CDbgEapStatus``, the 32 signal-snapshot registers, the free-running
timestamp and its capture). Their read value is not pinned by the RDL once time
has advanced, so they carry no write expectation and are left to the reset
sweep in ``smc_remap_cla_test``.

``_EXCLUDED`` names the software-writable registers this sequence still leaves
alone and what driving them here would do. The register lists and their sizes
are derived from the generated map on every run, so a regenerated map changes
the sweep with it; the counts are logged with the checker.

``_LEGAL_VALUE_PINNED`` names fields the generated map declares plain
read-write that the vendored MMR specification (``cla_mmrs.yml``) gives a single
legal value, and that the design holds at it: the counters' ``Rsvd`` bit 63,
which the specification lists with ``LEGAL_VALUE: '0'`` under a WARL register.
The map drops that constraint, so its contract says the bit reads back what was
written; the design reads 0. The leaf holds those bits to the legal value
instead of the map's contract, and fails if one reads back the written value
or if the map stops declaring it read-write, so the entry is revisited either
way.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_cla_regmap import cla_field, cla_register, cla_registers
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import pack_fields
from .smc_rdl_regmap import RdlReg

_BLOCK = "smc_cla/cla"

# Registers of the block with at least one software-writable field that this
# sequence does not drive, and why.
_EXCLUDED: dict[str, str] = {
    f"{_BLOCK}/CDbgClaCtrlStatus": (
        "ClaLock is `If this bit is set, then CLA is locked and the enable_cla "
        "is latched forever`, which no later write can undo, and EnableEap arms "
        "the action bus of all 16 EAPs at once; driven by "
        "smc_dfd_cla_node_eap_sweep_test with ClaLock held at 0"
    ),
}

# Fields the generated map declares plain read-write whose single legal value
# the vendored MMR specification states, with that value. See the module text.
_LEGAL_VALUE_PINNED: dict[str, dict[str, int]] = {
    f"{_BLOCK}/CDbgClaCounter{n}Cfg": {"Rsvd": 0} for n in range(4)
}


def _pinned(reg: RdlReg) -> tuple[int, int]:
    """Mask and value of the legal-value-pinned bits of one register."""
    mask = value = 0
    for field in reg.fields:
        legal = _LEGAL_VALUE_PINNED.get(reg.path, {}).get(field.name)
        if legal is not None:
            mask |= field.mask
            value |= (legal << field.offset) & field.mask
    return mask, value


def _swept_registers() -> tuple[tuple[RdlReg, ...], int]:
    regs = tuple(cla_registers().values())
    writable = tuple(reg for reg in regs if reg.rw_mask)
    stale = sorted(set(_EXCLUDED) - {reg.path for reg in writable})
    assert not stale, "named registers the generated map no longer has: " + ", ".join(stale)
    by_path = {reg.path: reg for reg in regs}
    for path, fields in _LEGAL_VALUE_PINNED.items():
        reg = by_path.get(path)
        assert reg is not None, f"{path} is pinned but the generated map no longer has it"
        for name in fields:
            field = next((f for f in reg.fields if f.name == name), None)
            assert field is not None and field.plain_rw, (
                f"{path}.{name} is pinned to its specified legal value because the generated "
                f"map declares it plain read-write; the map no longer does, so the entry in "
                f"_LEGAL_VALUE_PINNED has to be revisited"
            )
    return tuple(reg for reg in writable if reg.path not in _EXCLUDED), len(regs) - len(writable)


SWEPT, HW_STATUS_COUNT = _swept_registers()

# A value for CDbgClaTimestamp with both fields non-zero and far from wrapping,
# and a value for the register's upper half written on its own.
_TIMESTAMP_VALUE = 0x0000_0100_0000_0100
_TIMESTAMP_UPPER_HALF = 0x2
# An offset inside the block's register hole between CDbgClaTimestampOffset and
# CDbgSignalMask0Hi, relative to the block's first register.
_HOLE_OFFSET = 0x310
_SETTLE_CYCLES = 64
# Registers whose write sweep touches bits outside the low half, so the
# high-half access carries a non-zero pattern of its own.
SWEPT_WIDE = tuple(reg for reg in SWEPT if reg.rw_mask >> 32)


class smc_dfd_cla_mmr_sweep_test_seq(SmcCsrSeq):
    """Drive every software-owned CLA MMR field half at a time and restore it."""

    def __init__(self, name: str = "smc_dfd_cla_mmr_sweep_test_seq") -> None:
        super().__init__(name)
        self.registers_swept = 0
        self.write_groups = 0
        self.pinned_checks = 0
        self.timestamp_running = (0, 0)
        self.timestamp_written = (0, 0)
        self.hole = (0, 0, 0)
        self.value_checks = 0

    @staticmethod
    def _word_mask(reg: RdlReg) -> int:
        return (1 << (reg.width_bytes * 8)) - 1

    async def _read_check(self, reg: RdlReg, label: str, model: int) -> int:
        value = await self.csr_read(f"{reg.path}:{label}", reg.addr, length=reg.width_bytes)
        value &= self._word_mask(reg)

        unimplemented = value & ~reg.declared_mask & self._word_mask(reg)
        assert unimplemented == 0, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: read "
            f"0x{value:016x}, which drives 0x{unimplemented:x} in bits no field of "
            f"the register occupies (declared 0x{reg.declared_mask:x})"
        )

        pin_mask, pin_value = _pinned(reg)
        rw = reg.rw_mask & ~pin_mask
        got_rw = value & rw
        want_rw = model & rw
        assert got_rw == want_rw, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: software-writable bits read "
            f"0x{got_rw:x}, the register contract says 0x{want_rw:x}"
        )
        if pin_mask:
            assert value & pin_mask == pin_value, (
                f"{reg.path} @ 0x{reg.addr:08x} [{label}]: bits 0x{pin_mask:x}, which the "
                f"generated map declares read-write and the MMR specification pins to "
                f"0x{pin_value:x}, read 0x{value & pin_mask:x}. If the design now takes the "
                f"write, drop the entry from _LEGAL_VALUE_PINNED"
            )
            self.pinned_checks += 1

        pinned_ro = reg.static_mask & ~reg.rw_mask
        assert value & pinned_ro == reg.reset_word & pinned_ro, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: bits software cannot write read "
            f"0x{value & pinned_ro:x}, their RDL reset is 0x{reg.reset_word & pinned_ro:x}"
        )
        self.value_checks += 1
        return value

    async def _granule_cycle(self, reg: RdlReg) -> None:
        """Half-register writes with the other half's byte lanes deasserted."""
        half = reg.width_bytes // 2
        granules = ((0, half), (half, half))
        model = reg.reset_word
        await self._read_check(reg, "reset", model)

        for pattern, tag in ((reg.rw_mask, "ones"), (reg.reset_word, "restore")):
            for offset, width in granules:
                gmask = ((1 << (width * 8)) - 1) << (offset * 8)
                touched = reg.rw_mask & gmask
                await self.csr_write(
                    f"{reg.path}:{tag}@{offset}",
                    reg.addr + offset,
                    (pattern & gmask) >> (offset * 8),
                    length=width,
                )
                model = (model & ~touched) | (pattern & touched)
                self.write_groups += 1
                await self._read_check(reg, f"{tag}@{offset}", model)

    async def _timestamp(self) -> None:
        """Write and read CDbgClaTimestamp, which hardware also writes, with the CLA enabled.

        The generated map declares both timestamp fields ``sw = rw; hw = rw``: software
        writes them and hardware advances them. With the CLA enabled (its event-action
        pairs left disabled), the register is read twice, then written whole and read
        back, then written through its upper half alone and read back. Hardware may
        only move the value forward from what software wrote, so every readback has to
        be at or above the value written, and the upper half has to read the value its
        own write gave it.
        """
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        ts = cla_register("CDbgClaTimestamp")
        word = pack_fields(
            ctrl,
            {"EnableCla": 1, "ClaChainLoopDelay": (ctrl.reset_word & chain.mask) >> chain.offset},
        )
        await self.csr_write(f"{ctrl.path}:ts_enable", ctrl.addr, word, length=ctrl.width_bytes)
        first = await self.csr_read(f"{ts.path}:ts_first", ts.addr, length=ts.width_bytes)
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        second = await self.csr_read(f"{ts.path}:ts_second", ts.addr, length=ts.width_bytes)
        self.timestamp_running = (first, second)
        await self.csr_write(
            f"{ts.path}:ts_write", ts.addr, _TIMESTAMP_VALUE, length=ts.width_bytes
        )
        back = await self.csr_read(f"{ts.path}:ts_back", ts.addr, length=ts.width_bytes)
        assert back >= _TIMESTAMP_VALUE, (
            f"{ts.path} @ 0x{ts.addr:08x}: written 0x{_TIMESTAMP_VALUE:016x}, reads 0x{back:016x}, "
            f"below the written value; hardware may only advance it"
        )
        half = ts.width_bytes // 2
        await self.csr_write(
            f"{ts.path}:ts_upper", ts.addr + half, _TIMESTAMP_UPPER_HALF, length=half
        )
        upper = await self.csr_read(f"{ts.path}:ts_upper_rb", ts.addr, length=ts.width_bytes)
        assert upper >> (half * 8) == _TIMESTAMP_UPPER_HALF, (
            f"{ts.path} @ 0x{ts.addr:08x}: its upper half was written 0x{_TIMESTAMP_UPPER_HALF:x} "
            f"on its own, and the register reads 0x{upper:016x}"
        )
        self.timestamp_written = (back, upper)
        await self.csr_write(f"{ts.path}:ts_restore", ts.addr, ts.reset_word, length=ts.width_bytes)
        await self.csr_write(
            f"{ctrl.path}:ts_restore", ctrl.addr, ctrl.reset_word, length=ctrl.width_bytes
        )
        self.value_checks += 2

    async def _hole(self) -> None:
        """Read and write one offset of the block's register hole."""
        regs = sorted(cla_registers().values(), key=lambda r: r.addr)
        base = regs[0].addr & ~0xFFF
        addr = base + _HOLE_OFFSET
        assert all(r.addr != addr for r in regs), f"0x{addr:08x} is a declared CLA register"
        below = max((r for r in regs if r.addr < addr), key=lambda r: r.addr)
        above = min((r for r in regs if r.addr > addr), key=lambda r: r.addr)
        held = {}
        for reg in (below, above):
            held[reg.path] = await self.csr_read(
                f"{reg.path}:hole_before", reg.addr, length=reg.width_bytes
            )
        items = []
        for op, data in ((SmcSysAxiOp.READ, 0), (SmcSysAxiOp.WRITE, (1 << 64) - 1)):
            item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_cla_hole")
            item.op = op
            item.addr = addr
            item.length = 8
            item.wdata = data
            item.allow_error = True
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
            items.append(item)
        if items[0].resp_code == 0:
            assert items[0].rdata == 0, (
                f"the CLA hole at 0x{addr:08x} read 0x{items[0].rdata:x}; no field occupies it"
            )
        for reg in (below, above):
            now = await self.csr_read(f"{reg.path}:hole_after", reg.addr, length=reg.width_bytes)
            assert now == held[reg.path], (
                f"{reg.path} read 0x{held[reg.path]:x} before and 0x{now:x} after an all-ones "
                f"write to the CLA hole at 0x{addr:08x}"
            )
        self.hole = (addr, items[0].resp_code, items[1].resp_code)
        self.value_checks += 3

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        for reg in SWEPT:
            await self._granule_cycle(reg)
            self.registers_swept += 1

        assert self.registers_swept == len(SWEPT), (
            f"the sweep drove {self.registers_swept} CLA MMR registers, the list "
            f"built from the generated map has {len(SWEPT)}"
        )
        assert len(SWEPT_WIDE) >= 40, (
            f"only {len(SWEPT_WIDE)} of the swept registers have a software-writable "
            f"bit above bit 31, so the high-half write of the rest carries no pattern "
            f"and the per-half proof would rest on too few registers"
        )
        cocotb.log.info(
            "CHK-CLA-MMR-WRITE-SWEEP: %d CLA MMR registers (every register of the block "
            "with a software-writable field in the generated map, less %d excluded; %d "
            "more have none and are left to the reset sweep) each read their generated "
            "RDL reset, took the ones pattern their software-access type allows "
            "through two half-register writes whose byte lanes over the other half "
            "were deasserted, read back exactly after each half (%d of them with a "
            "pattern above bit 31), and read back their RDL reset after the two "
            "restore writes; %d value compares, %d half-register writes. %d reads held "
            "the fields in _LEGAL_VALUE_PINNED at their specified legal value",
            self.registers_swept,
            len(_EXCLUDED),
            HW_STATUS_COUNT,
            len(SWEPT_WIDE),
            self.value_checks,
            self.write_groups,
            self.pinned_checks,
        )

        await self._timestamp()
        cocotb.log.info(
            "CHK-CLA-TIMESTAMP: with the CLA enabled, CDbgClaTimestamp read 0x%016x then 0x%016x "
            "%d cycles later; written 0x%016x it read back 0x%016x, and its upper half written "
            "0x%x on its own read back in a register value of 0x%016x",
            *self.timestamp_running,
            _SETTLE_CYCLES,
            _TIMESTAMP_VALUE,
            self.timestamp_written[0],
            _TIMESTAMP_UPPER_HALF,
            self.timestamp_written[1],
        )
        await self._hole()
        cocotb.log.info(
            "CHK-CLA-MMR-HOLE: the CLA hole at 0x%08x took a read (response %d) and an all-ones "
            "write (response %d); a read that completed OKAY returned 0 and the registers on "
            "either side held their values",
            *self.hole,
        )
