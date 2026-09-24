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
alone and what driving them here would do. ``_swept_registers`` holds the
generated map to the register counts this sweep is sized for, so a regenerated
map that gains or loses rows fails instead of silently changing the sweep.
"""

from __future__ import annotations

import cocotb

from .smc_cla_regmap import cla_registers
from .smc_csr_seq_utils import SmcCsrSeq
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

# Register counts the generated map is expected to carry for this block. A
# regenerated map that loses rows would otherwise shrink the sweep silently.
_EXPECTED_WRITABLE = 78
_EXPECTED_HW_STATUS = 35


def _swept_registers() -> tuple[RdlReg, ...]:
    regs = tuple(cla_registers().values())
    writable = tuple(reg for reg in regs if reg.rw_mask)
    hw_status = tuple(reg for reg in regs if not reg.rw_mask)
    assert len(writable) == _EXPECTED_WRITABLE, (
        f"{_BLOCK} carries {len(writable)} registers with a software-writable "
        f"field in the generated map, not the {_EXPECTED_WRITABLE} this sweep "
        f"is sized for"
    )
    assert len(hw_status) == _EXPECTED_HW_STATUS, (
        f"{_BLOCK} carries {len(hw_status)} registers with no software-writable "
        f"field, not the {_EXPECTED_HW_STATUS} left to the reset sweep"
    )
    stale = sorted(set(_EXCLUDED) - {reg.path for reg in writable})
    assert not stale, "named registers the generated map no longer has: " + ", ".join(stale)
    return tuple(reg for reg in writable if reg.path not in _EXCLUDED)


SWEPT = _swept_registers()
# Registers whose write sweep touches bits outside the low half, so the
# high-half access carries a non-zero pattern of its own.
SWEPT_WIDE = tuple(reg for reg in SWEPT if reg.rw_mask >> 32)


class smc_dfd_cla_mmr_sweep_test_seq(SmcCsrSeq):
    """Drive every software-owned CLA MMR field half at a time and restore it."""

    def __init__(self, name: str = "smc_dfd_cla_mmr_sweep_test_seq") -> None:
        super().__init__(name)
        self.registers_swept = 0
        self.write_groups = 0
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

        got_rw = value & reg.rw_mask
        want_rw = model & reg.rw_mask
        assert got_rw == want_rw, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: software-writable bits read "
            f"0x{got_rw:x}, the register contract says 0x{want_rw:x}"
        )

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
            "CHK-CLA-MMR-WRITE-SWEEP: %d CLA MMR registers each read their generated "
            "RDL reset, took the ones pattern their software-access type allows "
            "through two half-register writes whose byte lanes over the other half "
            "were deasserted, read back exactly after each half (%d of them with a "
            "pattern above bit 31), and read back their RDL reset after the two "
            "restore writes; %d value compares, %d half-register writes",
            self.registers_swept,
            len(SWEPT_WIDE),
            self.value_checks,
            self.write_groups,
        )
