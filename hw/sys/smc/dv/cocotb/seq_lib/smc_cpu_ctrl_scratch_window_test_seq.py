# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU-control scratch-window write/readback depth test."""

from __future__ import annotations

import cocotb

from .smc_addr_map import cpu_ctrl_u32, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Addresses come from the generated map, not from literals: a hardcoded base
# such as `0xC003_9080` has to be tracked by hand when the block moves. The
# indexed macro `SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(idx) = 0xC0039080 +
# idx * 0x8` (smc_addr.h:2325) is the authority for both base and stride
# ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
SCRATCH_WRITES = [
    (
        f"CPU_CTRL_SCRATCH_{_i}",
        smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", _i),
        0xC0A0_0000 | _i,
    )
    for _i in (0, 7, 15)
]

# DUMMY_ROM_0..3 are `sw = rw; hw = r` (cpu_ctrl.rdl) with NON-TRIVIAL 64-bit
# resets -- RISC-V instruction words, not zeroes. Those resets are the
# discriminating rows of this sweep: no unmapped window and no stuck register
# can fabricate 0x0145051300000517. Each is read at reset, written with a
# probe, read back, and restored to its exact generated reset value.
#
# Safe to clobber here: this testcase never boots a core (it issues CSR traffic
# only), and every row is restored before the sequence ends.
#
# Read by symbol from `hw/sys/smc/regs/gen/c/blocks/cpu_ctrl.h`, the same
# generated header the addresses come from, so the goldens cannot drift out of
# step with the RDL ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
DUMMY_ROM_COUNT = 4
DUMMY_ROM_RESETS = {
    _i: cpu_ctrl_u32(f"CPU_CTRL__DUMMY_ROM_{_i}__DUMMY_ROM_WORD_{_i}_reset")
    for _i in range(DUMMY_ROM_COUNT)
}
# DUMMY_ROM_NULL[4] @0x2A0 is plain padding scratch.
DUMMY_ROM_NULL_COUNT = 4
DUMMY_ROM_NULL_RESET = cpu_ctrl_u32("CPU_CTRL__DUMMY_ROM_NULL__DUMMY_ROM_NULL_reset")
# At least one row must be non-trivially non-zero, or the sweep degenerates into
# reading zeroes back off registers that a dead or unmapped window could also
# fabricate ([NO-ZERO-ACTIVITY-PASS]).
assert sum(1 for _v in DUMMY_ROM_RESETS.values() if _v) >= 3, (
    f"DUMMY_ROM resets are no longer discriminating: {DUMMY_ROM_RESETS}"
)
_ROM_PROBE = 0xA5A5_5A5A_C3C3_3C3C
# CORE_RESET_PULSE_COUNT is NOT swept: cpu_ctrl.rdl gives it
# `sw = ['r','rw']` / `hw = ['r','w']`, i.e. it carries hardware-driven fields
# (core_resets_done). A register the hardware drives cannot be held to its RDL
# reset, and masking it correctly would need field masks this testcase does not
# import.


class smc_cpu_ctrl_scratch_window_test_seq(SmcCsrSeq):
    """Exercise first/middle/last CPU scratch registers and restore them."""

    def __init__(self, name: str = "smc_cpu_ctrl_scratch_window_test_seq") -> None:
        super().__init__(name)
        #: (addr, pattern) pairs whose write/readback the scoreboard compared
        self.scratch_proven: list[tuple[int, int]] = []
        #: reset word read back from DUMMY_ROM_0 after the probe was restored
        self.rom0_restored: int | None = None

    async def body(self) -> None:
        saved = []
        for name, addr, pattern in SCRATCH_WRITES:
            old_value = await self.csr_read(f"{name}_SAVE", addr)
            saved.append((name, addr, old_value))
            # `csr_write_readback` sets `item.expected` on the readback, so the
            # compare is booked by the scoreboard; the pair is recorded here
            # only after that readback returned.
            await self.csr_write_readback(name, addr, pattern)
            self.scratch_proven.append((addr, pattern))

        for name, addr, value in reversed(saved):
            await self.csr_restore(name, addr, value)

        # Named token for the window this testcase is named for. Emitted only
        # after every write/readback and every restore-readback above returned,
        # each of which the scoreboard value-compared ([EVIDENCE-TOKEN-CONDITIONAL]).
        cocotb.log.info(
            "CHK-CPU-CTRL-SCRATCH: %d CPU_CTRL SCRATCH register(s) written and "
            "read back exactly (%s), then restored to the word each held before "
            "(%s); all %d compares booked by the scoreboard",
            len(self.scratch_proven),
            ", ".join(f"0x{a:08x}<-0x{p:08x}" for a, p in self.scratch_proven),
            ", ".join(f"0x{a:08x}=0x{v:08x}" for _n, a, v in saved),
            len(self.scratch_proven) * 2,
        )

        await self._dummy_rom_sweep()

        # `self.accesses` is bumped by this sequence's own csr_* calls, so
        # asserting it against a literal only restates the loop above and cannot
        # fail on anything the DUT did ([NO-ALWAYS-PASS-CHECKER]).
        # `assert_all_reachable` cross-checks the same count against the
        # scoreboard, so a mis-bound analysis path fails.
        expected = len(SCRATCH_WRITES) * 5 + len(DUMMY_ROM_RESETS) * 5 + DUMMY_ROM_NULL_COUNT
        self.assert_all_reachable(expected, "CPU_CTRL_SCRATCH_WINDOW")

    async def _dummy_rom_sweep(self) -> None:
        """Reset / write / readback / restore over DUMMY_ROM_0..3 + NULL[4]."""
        for idx, reset in DUMMY_ROM_RESETS.items():
            addr = smc_addr(f"SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_{idx}_BASE_ADDR")
            await self.csr_read(f"DUMMY_ROM_{idx}_RESET", addr, expected=reset, length=8)
            await self.csr_write(f"DUMMY_ROM_{idx}_WR", addr, _ROM_PROBE, length=8)
            await self.csr_read(f"DUMMY_ROM_{idx}_RB", addr, expected=_ROM_PROBE, length=8)
            await self.csr_write(f"DUMMY_ROM_{idx}_RESTORE", addr, reset, length=8)
            restored = await self.csr_read(
                f"DUMMY_ROM_{idx}_RESTORE_RB", addr, expected=reset, length=8
            )
            if idx == 0:
                self.rom0_restored = restored
        for idx in range(DUMMY_ROM_NULL_COUNT):
            addr = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", idx)
            await self.csr_read(
                f"DUMMY_ROM_NULL_{idx}_RESET",
                addr,
                expected=DUMMY_ROM_NULL_RESET,
                length=8,
            )
        cocotb.log.info(
            "CHK-CPU-CTRL-DUMMY-ROM: %d DUMMY_ROM registers read at their "
            "non-zero generated resets (0x%016x ...), took probe 0x%016x on a "
            "write/readback, and were restored exactly; %d DUMMY_ROM_NULL "
            "padding rows read at reset 0",
            len(DUMMY_ROM_RESETS),
            DUMMY_ROM_RESETS[0],
            _ROM_PROBE,
            DUMMY_ROM_NULL_COUNT,
        )
