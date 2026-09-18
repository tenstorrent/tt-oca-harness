# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked eFuse shadow access raises `tb_efuse_locked_access_irq`.

DECLARED PRECONDITION -- the read-lock is supplied by the bench, not the DUT.
`JTAG_PUBLIC_IDENTITY` is read-locked before this sequence does anything because
word 0 of `hw/sys/smc/dv/assets/smc_efuse_default.hex` has
`JTAG_PUBLIC_IDENTITY_READ_LOCK` set (bit 1 of LOCKS, value 0x2), and the
adopter-supplied simulation stand-in for the OTP macro,
`hw/ip/efuse/dv/models/efuse_bank_model.sv`, `$readmemh`s that asset into the
bank at time 0 under `+smc_efuse_hex` (named on this testcase's `[[tests]]`
entry in `hw/sys/smc/dv/testlists/depth.toml`). The read-lock leg
therefore proves that the DUT ENFORCES a lock it found already set; it does not
prove a lock can be established through the fuse-programming path. The
write-lock leg does establish its own lock, through the real `LOCKS` CSR write
path.

Everything asserted below -- lock enforcement, the non-disclosure property and
the interrupt itself -- is produced by the design under test. The model
contributes the fuse CONTENT only, and every expectation that depends on that
content is derived from the asset at run time rather than hand-transcribed.

The read-locked read is not value-compared. `hw/ip/efuse/doc/architecture.adoc`
specifies `0xbadcab1e` only for the JTAG lifecycle-demux error slave and does
not state what a read-locked shadow register returns over the CSR path, so that
leg claims the interrupt pulse and non-disclosure (the `lock` field table:
`lock[0] = 1` is read-locked) and nothing about the substituted word.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_addr, smc_efuse_map_u32
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import efuse_map_read_locked, efuse_preload_word_at

LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
JTAG_PUBLIC_IDENTITY = smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR")
WRITE_LOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__JTAG_PUBLIC_IDENTITY_WRITE_LOCK_bm")
READ_LOCK = smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__JTAG_PUBLIC_IDENTITY_READ_LOCK_bm")

# Exact expectation for the LOCKS shadow word, derived from the preload asset
# plus the generated map at run time so it follows a regenerated asset. It
# travels the real path -- sense FSM -> shadow registers -> access control ->
# SEP_IN AXI -- so it is a transport proof of the register the whole scenario
# depends on.
LOCKS_PRELOAD = efuse_preload_word_at(LOCKS)
#: Host-side truth about whether the asset read-locks JTAG_PUBLIC_IDENTITY.
JTAG_PUBLIC_IDENTITY_READ_LOCKED = efuse_map_read_locked(
    "SMC_EFUSE_MAP__LOCKS__JTAG_PUBLIC_IDENTITY_READ_LOCK_bm"
)
#: Fuse content behind JTAG_PUBLIC_IDENTITY word 0, i.e. the word a leaking gate would disclose.
JTAG_PUBLIC_IDENTITY_CONTENT = efuse_preload_word_at(JTAG_PUBLIC_IDENTITY)

# Exact expectation for LOCKS after this sequence sets the JTAG_PUBLIC_IDENTITY
# write lock: the asset word plus the one bit it writes, both from generated symbols.
LOCKS_AFTER_WRITE_LOCK = LOCKS_PRELOAD | WRITE_LOCK
_UNLOCKED_PAT = 0xCAFE0001
_DRAIN = 8


class smc_efuse_locked_access_interrupt_test_seq(SmcCsrSeq):
    """JTAG_PUBLIC_IDENTITY lock IRQ via lifted peripheral_interrupts[27]."""

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

        assert JTAG_PUBLIC_IDENTITY_READ_LOCKED, (
            "the preload asset does not read-lock JTAG_PUBLIC_IDENTITY, so the "
            "read-lock leg of this scenario has no precondition to enforce"
        )

        # Exact compare against the asset-derived word, booked by the scoreboard.
        locks = await self.csr_read("LOCKS_PRE", LOCKS, expected=LOCKS_PRELOAD)
        assert (locks & WRITE_LOCK) == 0, (
            f"JTAG_PUBLIC_IDENTITY write-lock already set: LOCKS=0x{locks:08x}"
        )
        assert (locks & READ_LOCK) != 0, (
            f"asset read-locks JTAG_PUBLIC_IDENTITY but the DUT does not report it: "
            f"LOCKS=0x{locks:08x}"
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-PRE: LOCKS=0x%08x (asset word 0x%08x) wr=%d rd=%d",
            locks,
            LOCKS_PRELOAD,
            1 if locks & WRITE_LOCK else 0,
            1 if locks & READ_LOCK else 0,
        )

        async def _unlocked_write() -> None:
            await self.csr_write(
                "JTAG_PUBLIC_IDENTITY_UNLOCK_WR", JTAG_PUBLIC_IDENTITY, _UNLOCKED_PAT
            )

        self.unlock_edges = await self._count_edges_during("UNLOCK", _unlocked_write())
        assert self.unlock_edges == 0, (
            f"unlocked JTAG_PUBLIC_IDENTITY write pulsed IRQ {self.unlock_edges} time(s)"
        )
        cocotb.log.info("CHK-EFUSE-LOCK-IRQ-UNLOCK: unlocked write edges=%d", self.unlock_edges)

        await self.csr_write("LOCKS_WOSSET_WR", LOCKS, LOCKS_AFTER_WRITE_LOCK)
        # Exact compare booked by the scoreboard: the asset word plus the lock
        # bit this sequence just set, stated before the access.
        locks2 = await self.csr_read("LOCKS_WR", LOCKS, expected=LOCKS_AFTER_WRITE_LOCK)
        assert (locks2 & WRITE_LOCK) != 0, (
            f"JTAG_PUBLIC_IDENTITY write-lock did not stick: LOCKS=0x{locks2:08x}"
        )

        async def _locked_write() -> None:
            await self.csr_write(
                "JTAG_PUBLIC_IDENTITY_LOCK_WR", JTAG_PUBLIC_IDENTITY, _UNLOCKED_PAT ^ 0xA5A55A5A
            )

        self.wr_edges = await self._count_edges_during("WRLOCK", _locked_write())
        # Exactly one rising edge per locked access: with the 0-before / 0-after
        # gate in `_count_edges_during` this is the per-access pulse, and `>= 1`
        # would also pass a chattering or free-running interrupt, which is the
        # failure a locked-access interrupt most needs to exclude.
        assert self.wr_edges == 1, (
            f"write-locked JTAG_PUBLIC_IDENTITY write produced {self.wr_edges} IRQ edges, "
            f"expected exactly 1 (one pulse per locked APB access phase)"
        )
        cocotb.log.info("CHK-EFUSE-LOCK-IRQ-WR: write-locked write edges=%d", self.wr_edges)

        async def _locked_read() -> None:
            # No exact expectation: the architecture document does not state
            # the word a read-locked shadow register returns (see the module
            # docstring). The OBSERVED datum feeds the non-disclosure asserts
            # and the evidence token below.
            self.rd_data = await self.csr_read("JTAG_PUBLIC_IDENTITY_LOCK_RD", JTAG_PUBLIC_IDENTITY)

        self.rd_edges = await self._count_edges_during("RDLOCK", _locked_read())
        assert self.rd_edges == 1, (
            f"read-locked JTAG_PUBLIC_IDENTITY read produced {self.rd_edges} IRQ edges, "
            f"expected exactly 1"
        )
        # SPEC-derived read-lock claim (architecture.adoc `lock` field table,
        # `lock[0] = 1` is read-locked): whatever word the gate substitutes, it
        # must not disclose the field, so a design that leaks fails here
        # regardless of the substituted value.
        assert self.rd_data != JTAG_PUBLIC_IDENTITY_CONTENT, (
            f"read-locked JTAG_PUBLIC_IDENTITY read returned the fuse content "
            f"0x{self.rd_data:08x}: the read lock did not substitute anything"
        )
        assert self.rd_data != _UNLOCKED_PAT, (
            f"read-locked JTAG_PUBLIC_IDENTITY read returned the pattern this sequence "
            f"wrote (0x{self.rd_data:08x}): the read lock is not gating the "
            f"shadow register"
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-IRQ-RD: read-locked read edges=%d data=0x%08x "
            "(fuse content 0x%08x and the written pattern 0x%08x were both "
            "withheld)",
            self.rd_edges,
            self.rd_data,
            JTAG_PUBLIC_IDENTITY_CONTENT,
            _UNLOCKED_PAT,
        )
