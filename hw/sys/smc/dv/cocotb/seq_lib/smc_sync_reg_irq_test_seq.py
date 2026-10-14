# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYNC_REG.sync drives sync_irq_o; only bit 0 is implemented.

Spec sources: reset_unit.rdl SYNC_REG, port_table.adoc SMC Port Declaration (sync_irq_o).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SYNC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SYNC_REG_BASE_ADDR")
# TB ceiling for the register-to-pin path in clk_smc_i edges; not a latency claim.
POLL_BOUND_SMC_CYCLES = 64
_HOLD_SAMPLES = 8
_STEPS = ("S1", "S2", "S3", "S4")
_CHECKERS = ("CHK-SYNC-RESET-0", "CHK-SYNC-DRIVES-IRQ", "CHK-SYNC-ONLY-BIT-0")


class smc_sync_reg_irq_test_seq(SmcCsrSeq):
    """Write SYNC_REG over SEP_IN and follow sync_irq_o on clk_smc_i."""

    def __init__(self, name: str = "smc_sync_reg_irq_test_seq") -> None:
        super().__init__(name)
        self.rise_samples: int | None = None
        self.fall_samples: int | None = None
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _sample_irq(label: str) -> int:
        sig = cocotb.top.tb_sync_irq
        assert sig.value.is_resolvable, f"{label}: tb_sync_irq is X/Z ({sig.value})"
        return int(sig.value)

    async def _poll_irq(self, want: int, label: str) -> int:
        last = self._sample_irq(f"{label} entry")
        for n in range(1, POLL_BOUND_SMC_CYCLES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._sample_irq(f"{label}[{n}]")
            if last == want:
                return n
        raise AssertionError(
            f"{label}: tb_sync_irq did not reach {want} within {POLL_BOUND_SMC_CYCLES} "
            f"clk_smc_i samples (last sample {last})"
        )

    async def _hold_irq_low(self, label: str) -> None:
        for n in range(1, _HOLD_SAMPLES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            got = self._sample_irq(f"{label}[{n}]")
            assert got == 0, f"{label}: tb_sync_irq={got} at clk_smc_i sample {n}/{_HOLD_SAMPLES}"

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        self._mark_step("S1")

        rst_rdata = await self.csr_read("SYNC_REG_RESET", SYNC_REG, expected=0)
        rst_irq = self._sample_irq("RESET")
        assert rst_rdata == 0 and rst_irq == 0, (
            f"after primary reset SYNC_REG=0x{rst_rdata:x} sync_irq_o={rst_irq}, want 0 and 0"
        )
        self._mark_step("S2")
        self._log_chk(
            "CHK-SYNC-RESET-0",
            f"SYNC_REG read 0x{rst_rdata:08X} and sync_irq_o={rst_irq} after primary reset",
        )

        await self.csr_write("SYNC_REG_SET", SYNC_REG, 0x1)
        cocotb.log.info("LIFECYCLE CHK-SYNC-DRIVES-IRQ set: SEP_IN write of 0x1 to SYNC_REG")
        set_rdata = await self.csr_read("SYNC_REG_SET", SYNC_REG, expected=0x1)
        rise = await self._poll_irq(1, "RISE")
        cocotb.log.info(
            f"LIFECYCLE CHK-SYNC-DRIVES-IRQ observed: sync_irq_o reads 1 after {rise} "
            f"clk_smc_i samples (bound {POLL_BOUND_SMC_CYCLES})"
        )
        await self.csr_write("SYNC_REG_CLR", SYNC_REG, 0x0)
        cocotb.log.info("LIFECYCLE CHK-SYNC-DRIVES-IRQ cleared: SEP_IN write of 0x0 to SYNC_REG")
        clr_rdata = await self.csr_read("SYNC_REG_CLR", SYNC_REG, expected=0x0)
        fall = await self._poll_irq(0, "FALL")
        cocotb.log.info(
            f"LIFECYCLE CHK-SYNC-DRIVES-IRQ checked_cleared: sync_irq_o reads 0 after {fall} "
            f"clk_smc_i samples and SYNC_REG reads 0x{clr_rdata:X}"
        )
        self.rise_samples = rise
        self.fall_samples = fall
        self._mark_step("S3")
        self._log_chk(
            "CHK-SYNC-DRIVES-IRQ",
            f"after SYNC_REG=0x1 (read 0x{set_rdata:X}) sync_irq_o rose to 1 after {rise} "
            f"clk_smc_i samples; after SYNC_REG=0x0 sync_irq_o fell to 0 after {fall} "
            f"clk_smc_i samples (bound {POLL_BOUND_SMC_CYCLES})",
        )

        await self.csr_write("SYNC_REG_UPPER", SYNC_REG, 0xFFFFFFFE)
        upper_rdata = await self.csr_read("SYNC_REG_UPPER", SYNC_REG, expected=0x00000000)
        await self._hold_irq_low("UPPER_HOLD")
        await self.csr_write("SYNC_REG_ALL", SYNC_REG, 0xFFFFFFFF)
        all_rdata = await self.csr_read("SYNC_REG_ALL", SYNC_REG, expected=0x00000001)
        await self._poll_irq(1, "ALL_RISE")
        irq_all = self._sample_irq("ALL_RISE sample")
        await self.csr_restore("SYNC_REG", SYNC_REG, 0)
        await self._poll_irq(0, "RESTORE_FALL")
        self._mark_step("S4")
        self._log_chk(
            "CHK-SYNC-ONLY-BIT-0",
            f"SYNC_REG read 0x{upper_rdata:08X} after 0xFFFFFFFE (sync_irq_o stayed 0 at "
            f"{_HOLD_SAMPLES} samples) and 0x{all_rdata:08X} after 0xFFFFFFFF "
            f"(sync_irq_o={irq_all}); only bit 0 is implemented",
        )

        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, ("S2", "S3", "S4")):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<PASS; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
