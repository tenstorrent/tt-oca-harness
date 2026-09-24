# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write every read-only MMR of the DFD blocks and require the write to be ignored.

Every address, field position, reset value, software-access type and
volatility comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap`. The vendored RTL is not a source for any value
this sequence programs or compares against.

The two MMR write sweeps on this branch drive the registers that have a
software-writable field. The registers that have none -- the signal
snapshots, the timestamps, the counters' hardware-driven halves, the sink's
data port and write pointer -- are never written at all, so the write decode
of their addresses is never exercised and the ``sw = r`` half of their
contract is never tested.

This sequence writes all of them. What it holds the DUT to is the contract
itself: a register the RDL makes read-only must not take the value, and a bit
no field of a register occupies must read 0.

Some of these registers are hardware-driven and free-running, so "unchanged"
is not a claim that can be made about them. Rather than carry a hand-written
exclusion list that would rot, the sequence measures it: every register is
read twice before the write, and only the ones that returned the same value
both times are held to returning it again afterwards. The rest are still
written -- the decode is exercised either way -- and are held to the
undeclared-bits rule only.

The CLA is left disarmed throughout, and the sequence checks that before it
starts, so the hardware-driven registers are as quiescent as this bench can
make them.

One register does take the write: ``dst_sink/Trdstramwphigh``, which
``dfd_dst_sink.rdl`` declares ``sw = r; hw = w``. It is pinned in
``_KNOWN_WRITABLE`` with that reason rather than skipped, so the leaf fails if
the deviation is corrected and the entry has to be revisited, and fails just
as loudly if another register starts taking writes.
"""

from __future__ import annotations

from functools import lru_cache

import cocotb

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_registers_under

_CLA_ADDRMAP = "smc_cla"
_BLOCKS = ("cla", "dst", "dst_sink", "funnel")

# Registers with no software-writable field that the generated map is expected
# to carry across the four sub-blocks. A regenerated map that gains or loses
# one fails rather than silently changing the sweep.
_EXPECTED_READ_ONLY = 37

# Registers that must hold still for the unchanged leg to rest on enough of
# them. Below this the leaf would be an undeclared-bits check only.
_MIN_HELD = 20

# Registers the RDL declares read-only that the design nevertheless lets
# software write. The deviation is pinned rather than skipped, so a design or
# map change in either direction fails this leaf and the entry is revisited.
_KNOWN_WRITABLE: dict[str, str] = {
    "smc_cla/dst_sink/Trdstramwphigh": (
        "dfd_dst_sink.rdl declares the whole register `sw = r; hw = w`, but a "
        "software write of all ones lands and is read back"
    ),
}


def _sw_write_mask(reg: RdlReg) -> int:
    mask = 0
    for field in reg.fields:
        if field.access == "read-write":
            mask |= field.mask
    return mask


@lru_cache(maxsize=1)
def _read_only() -> tuple[RdlReg, ...]:
    """Every register of the four sub-blocks with no software-writable field."""
    found: dict[tuple[str, str], RdlReg] = {}
    for reg in rdl_registers_under(_CLA_ADDRMAP):
        block = reg.path.split("/")[1].split("[", 1)[0]
        if block not in _BLOCKS or _sw_write_mask(reg):
            continue
        found.setdefault((block, reg.path.rsplit("/", 1)[1]), reg)
    regs = tuple(sorted(found.values(), key=lambda r: r.addr))
    assert len(regs) == _EXPECTED_READ_ONLY, (
        f"the generated map carries {len(regs)} registers with no software-writable field "
        f"across {list(_BLOCKS)}, not the {_EXPECTED_READ_ONLY} this sweep is sized for"
    )
    return regs


class smc_dfd_ro_mmr_write_test_seq(SmcCsrSeq):
    """Write every read-only DFD MMR and hold the DUT to the read-only contract."""

    def __init__(self, name: str = "smc_dfd_ro_mmr_write_test_seq") -> None:
        super().__init__(name)
        self.registers_written = 0
        self.held = 0
        self.free_running = 0
        self.undeclared_checks = 0
        self.took_write: dict[str, tuple[int, int]] = {}
        self.value_checks = 0

    @staticmethod
    def _word_mask(reg: RdlReg) -> int:
        return (1 << (reg.width_bytes * 8)) - 1

    async def _read(self, reg: RdlReg, label: str) -> int:
        value = await self.csr_read(f"{reg.path}:{label}", reg.addr, length=reg.width_bytes)
        value &= self._word_mask(reg)
        undeclared = value & ~reg.declared_mask & self._word_mask(reg)
        assert undeclared == 0, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: reads 0x{value:x}, which drives "
            f"0x{undeclared:x} in bits no field of the register occupies (declared "
            f"0x{reg.declared_mask:x})"
        )
        self.undeclared_checks += 1
        self.value_checks += 1
        return value

    async def _cycle(self, reg: RdlReg) -> None:
        first = await self._read(reg, "settle")
        second = await self._read(reg, "before")
        await self.csr_write(
            f"{reg.path}:write", reg.addr, self._word_mask(reg), length=reg.width_bytes
        )
        self.registers_written += 1
        after = await self._read(reg, "after")
        if reg.path in _KNOWN_WRITABLE:
            assert after == self._word_mask(reg), (
                f"{reg.path} @ 0x{reg.addr:08x} is pinned as a known deviation -- "
                f"{_KNOWN_WRITABLE[reg.path]} -- but a write of "
                f"0x{self._word_mask(reg):x} left it reading 0x{after:x}. If the design or "
                f"the register map has been corrected, drop the entry from _KNOWN_WRITABLE"
            )
            self.took_write[reg.path] = (second, after)
            self.value_checks += 1
            return
        if first == second:
            assert after == second, (
                f"{reg.path} @ 0x{reg.addr:08x}: the RDL gives it no software-writable "
                f"field, and it read 0x{second:x} twice running, but after a software write "
                f"of 0x{self._word_mask(reg):x} it reads 0x{after:x}"
            )
            self.held += 1
            self.value_checks += 1
        else:
            self.free_running += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        ctrl = cla_register("CDbgClaCtrlStatus")
        armed = cla_field(ctrl, "EnableCla").mask | cla_field(ctrl, "EnableEap").mask
        state = await self.csr_read("CDbgClaCtrlStatus:idle", ctrl.addr, length=ctrl.width_bytes)
        assert state & armed == 0, (
            f"CDbgClaCtrlStatus @ 0x{ctrl.addr:08x} reads 0x{state:x} with "
            f"0x{state & armed:x} of its enable bits set before this sweep starts; the "
            f"hardware-driven registers below would then be moving for a reason this "
            f"sequence does not control"
        )
        self.value_checks += 1

        regs = _read_only()
        for reg in regs:
            await self._cycle(reg)

        assert self.registers_written == len(regs), (
            f"the sweep wrote {self.registers_written} of the {len(regs)} read-only "
            f"registers the generated map declares"
        )
        assert sorted(self.took_write) == sorted(_KNOWN_WRITABLE), (
            f"the registers that took a software write were {sorted(self.took_write)}; the "
            f"pinned deviation list is {sorted(_KNOWN_WRITABLE)}"
        )
        assert self.held >= _MIN_HELD, (
            f"only {self.held} of the {len(regs)} read-only registers read the same value "
            f"twice running and could be held to it across the write; {self.free_running} "
            f"were moving on their own, so the unchanged leg rests on too few registers"
        )
        cocotb.log.info(
            "CHK-DFD-RO-MMR-HELD: %d of the %d registers the RDL gives no software-writable "
            "field read the same value twice running with the CLA disarmed and returned it "
            "again after a software write of all ones, so the write reached the decode and "
            "the read-only contract held; the other %d were moving on their own and carry "
            "no unchanged claim. Pinned deviations that did take the write: %s",
            self.held,
            len(regs),
            self.free_running,
            {k: f"0x{b:x}" for k, (_a, b) in self.took_write.items()},
        )
        cocotb.log.info(
            "CHK-DFD-RO-MMR-UNDECLARED: %d reads over the %d written registers each drove 0 "
            "in every bit no field of the register occupies, before and after the write, so "
            "no write reached storage the register map does not declare",
            self.undeclared_checks,
            len(regs),
        )
