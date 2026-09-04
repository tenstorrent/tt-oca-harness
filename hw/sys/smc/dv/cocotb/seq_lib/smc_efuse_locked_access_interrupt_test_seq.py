# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked eFuse shadow access raises `tb_efuse_locked_access_irq`.

DECLARED PRECONDITION -- the read-lock is supplied by the bench, not the DUT.
`CHIPLET_ID` is read-locked before this sequence does anything because word 0 of
`hw/sys/smc/dv/assets/smc_efuse_default.hex` has `CHIPLET_ID_READ_LOCK` set, and
the adopter-supplied simulation stand-in for the OTP macro,
`hw/ip/efuse/dv/models/efuse_bank_model.sv`, `$readmemh`s that asset into the
bank at time 0 under `+smc_efuse_hex` (named on this testcase's `[[tests]]`
entry in `hw/sys/smc/dv/testlists/vplan_triplets.toml`). The read-lock leg
therefore proves that the DUT ENFORCES a lock it found already set; it does not
prove a lock can be established through the fuse-programming path. The
write-lock leg does establish its own lock, through the real `LOCKS` CSR write
path.

Everything asserted below -- lock enforcement, the blocked-read data, the
non-disclosure property and the interrupt itself -- is produced by RTL under
`hw/ip/efuse/rtl/` and `hw/sys/smc/rtl/`. The model contributes the fuse
CONTENT only, and every expectation that depends on that content is derived from
the asset at run time rather than hand-transcribed.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_addr, smc_efuse_map_u32
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import efuse_map_read_locked, efuse_preload_word_at

LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
CHIPLET_ID = smc_addr("SMC_TOP_SMC_EFUSE_MAP_CHIPLET_ID_BASE_ADDR")
WRITE_LOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__CHIPLET_ID_WRITE_LOCK_bm")
READ_LOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__CHIPLET_ID_READ_LOCK_bm")

# Exact expectation for the LOCKS shadow word, derived from the preload asset
# plus the generated map at run time. It travels the real path -- sense FSM ->
# shadow registers -> access control -> SEP_IN AXI -- so it is a transport proof
# of the register the whole scenario depends on, and it moves with the asset
# instead of rotting into a hand-copied literal.
LOCKS_PRELOAD = efuse_preload_word_at(LOCKS)
#: Host-side truth about whether the asset read-locks CHIPLET_ID.
CHIPLET_ID_READ_LOCKED = efuse_map_read_locked("SMC_EFUSE_MAP__LOCKS__CHIPLET_ID_READ_LOCK_bm")
#: Fuse content behind CHIPLET_ID, i.e. the word a leaking gate would disclose.
CHIPLET_ID_CONTENT = efuse_preload_word_at(CHIPLET_ID)

# Data a blocked shadow-register read returns. TRANSCRIBED FROM THE
# IMPLEMENTATION, and recorded as such: `hw/ip/efuse/doc/architecture.adoc:297-
# 299` fixes `0xbadcab1e` for the JTAG lifecycle-demux error slave, which is a
# different mechanism, and no section of that document states what a read-LOCKED
# shadow register returns. The matching RTL literals are
# `hw/ip/efuse/rtl/efuse_shadow_reg_access_control.sv:151,159`. This compare
# therefore pins the sentinel the design emits and CANNOT catch the design
# emitting a different one; it is a DV-derived expectation, not a SPEC-derived
# one. The SPEC-derived half of the read-lock claim is the non-disclosure assert
# in `body` -- architecture.adoc:196-199 defines `lock[0] = 1` as read-locked, so
# whatever the gate returns it must not be the CHIPLET_ID content -- and that
# half holds whatever sentinel the design chooses.
READ_LOCKED_VALUE = 0xBADCAB1E
_UNLOCKED_PAT = 0xCAFE0001
_DRAIN = 8


class smc_efuse_locked_access_interrupt_test_seq(SmcCsrSeq):
    """CHIPLET_ID lock IRQ via lifted peripheral_interrupts[28]."""

    def __init__(self, name: str = "smc_efuse_locked_access_interrupt_test_seq") -> None:
        super().__init__(name)
        #: Measured rising edges per leg, published for the testcase module.
        self.unlock_edges = -1
        self.wr_edges = -1
        self.rd_edges = -1
        #: Datum the read-locked read actually returned.
        self.rd_data = -1

    def _irq(self):
        pin = getattr(cocotb.top, "tb_efuse_locked_access_irq", None)
        if pin is None:
            raise AssertionError("tb_efuse_locked_access_irq missing on OSS tb_top")
        return pin

    async def _count_edges_during(self, label: str, coro) -> int:
        """Rising edges on the IRQ during ``coro``, with a set-and-cleared gate.

        The line is required to be 0 when the window opens and 0 again after the
        drain. Counting edges alone proves the interrupt SET; without the two
        level samples an interrupt that latched high and never released would be
        indistinguishable from one that pulsed ([LIVENESS-COMPLETENESS]).
        """
        edges = 0
        pin = self._irq()

        before = int(pin.value)
        assert before == 0, (
            f"{label}: tb_efuse_locked_access_irq is already 1 before the "
            f"window opened, so any edge counted inside it would be an artefact "
            f"of a line that never released"
        )

        async def _watch() -> None:
            nonlocal edges
            while True:
                await RisingEdge(pin)
                edges += 1

        task = cocotb.start_soon(_watch())
        try:
            await coro
            await ClockCycles(cocotb.top.clk_periph_i, _DRAIN)
        finally:
            task.kill()

        after = int(pin.value)
        assert after == 0, (
            f"{label}: tb_efuse_locked_access_irq is still 1 {_DRAIN} periph "
            f"clocks after the access completed; the locked-access interrupt is "
            f"specified as a pulse for the access phase, not a latched status"
        )
        return edges

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        # Host-side precondition of the non-disclosure check below: if the fuse
        # content behind CHIPLET_ID happened to equal the blocked-read sentinel,
        # "the gate did not return the content" would be unfalsifiable.
        assert CHIPLET_ID_CONTENT != READ_LOCKED_VALUE, (
            f"the preload asset puts 0x{CHIPLET_ID_CONTENT:08x} behind "
            f"CHIPLET_ID, which is the blocked-read sentinel; the "
            f"non-disclosure assert would then be vacuous"
        )
        assert CHIPLET_ID_READ_LOCKED, (
            "the preload asset does not read-lock CHIPLET_ID, so the read-lock "
            "leg of this scenario has no precondition to enforce"
        )

        # Exact compare against the asset-derived word, booked by the scoreboard.
        locks = await self.csr_read("LOCKS_PRE", LOCKS, expected=LOCKS_PRELOAD)
        assert (locks & WRITE_LOCK) == 0, f"CHIPLET_ID write-lock already set: LOCKS=0x{locks:08x}"
        assert (locks & READ_LOCK) != 0, (
            f"asset read-locks CHIPLET_ID but the DUT does not report it: LOCKS=0x{locks:08x}"
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-PRE: LOCKS=0x%08x (asset word 0x%08x) wr=%d rd=%d",
            locks,
            LOCKS_PRELOAD,
            1 if locks & WRITE_LOCK else 0,
            1 if locks & READ_LOCK else 0,
        )

        async def _unlocked_write() -> None:
            await self.csr_write("CHIPLET_ID_UNLOCK_WR", CHIPLET_ID, _UNLOCKED_PAT)

        self.unlock_edges = await self._count_edges_during("UNLOCK", _unlocked_write())
        assert self.unlock_edges == 0, (
            f"unlocked CHIPLET_ID write pulsed IRQ {self.unlock_edges} time(s)"
        )
        cocotb.log.info("CHK-EFUSE-LOCK-IRQ-UNLOCK: unlocked write edges=%d", self.unlock_edges)

        await self.csr_write("LOCKS_WOSSET_WR", LOCKS, locks | WRITE_LOCK)
        locks2 = await self.csr_read("LOCKS_WR", LOCKS)
        assert (locks2 & WRITE_LOCK) != 0, (
            f"CHIPLET_ID write-lock did not stick: LOCKS=0x{locks2:08x}"
        )

        async def _locked_write() -> None:
            await self.csr_write("CHIPLET_ID_LOCK_WR", CHIPLET_ID, _UNLOCKED_PAT ^ 0xA5A55A5A)

        self.wr_edges = await self._count_edges_during("WRLOCK", _locked_write())
        # Exactly one pulse. `efuse_shadow_reg_access_control.sv:146-161` raises
        # the line combinationally for the single APB access phase, so `>= 1`
        # would also pass a chattering or free-running interrupt, which is the
        # failure a locked-access interrupt most needs to exclude.
        assert self.wr_edges == 1, (
            f"write-locked CHIPLET_ID write produced {self.wr_edges} IRQ edges, "
            f"expected exactly 1 (one pulse per locked APB access phase)"
        )
        cocotb.log.info("CHK-EFUSE-LOCK-IRQ-WR: write-locked write edges=%d", self.wr_edges)

        async def _locked_read() -> None:
            # `expected=` hands the compare to the scoreboard, which raises on
            # mismatch. The value is returned so the evidence token and the
            # non-disclosure assert below both work on the OBSERVED datum.
            self.rd_data = await self.csr_read(
                "CHIPLET_ID_LOCK_RD", CHIPLET_ID, expected=READ_LOCKED_VALUE
            )

        self.rd_edges = await self._count_edges_during("RDLOCK", _locked_read())
        assert self.rd_edges == 1, (
            f"read-locked CHIPLET_ID read produced {self.rd_edges} IRQ edges, expected exactly 1"
        )
        # SPEC-derived half of the read-lock claim (architecture.adoc:196-199,
        # `lock[0] = 1` is read-locked): whatever sentinel the gate substitutes,
        # it must not disclose the field. Independent of READ_LOCKED_VALUE, so a
        # design that changed its sentinel still fails here if it leaks.
        assert self.rd_data != CHIPLET_ID_CONTENT, (
            f"read-locked CHIPLET_ID read returned the fuse content "
            f"0x{self.rd_data:08x}: the read lock did not substitute anything"
        )
        assert self.rd_data != _UNLOCKED_PAT, (
            f"read-locked CHIPLET_ID read returned the pattern this sequence "
            f"wrote (0x{self.rd_data:08x}): the read lock is not gating the "
            f"shadow register"
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-IRQ-RD: read-locked read edges=%d data=0x%08x "
            "(fuse content 0x%08x and the written pattern 0x%08x were both "
            "withheld)",
            self.rd_edges,
            self.rd_data,
            CHIPLET_ID_CONTENT,
            _UNLOCKED_PAT,
        )
