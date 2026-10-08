# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""NDMRESET_PROCESS bits at and above the cluster count: stored, not driven.

Contract SMC_RESET_052, anchor smc_ndm_process_extra_bits_test.
Allocated scenario: RST-NDM.S4.
Spec sources: ndm_reset.rdl NDMRESET_PROCESS, smc-programming.adoc External CPU Cluster NDM Reset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

NDM_PROCESS = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR")
NDM_CLUSTERS = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR")
NDM_CLUSTER_COUNT = 4
_COUNT_MASK = 0xFF
_WINDOW_CYCLES = 64
_STEPS = ("S1", "S2")
_CHECKERS = ("CHK-NDM-PROCESS-ABOVE-COUNT",)


class smc_ndm_process_extra_bits_test_seq(SmcCsrSeq):
    """Write PROCESS bits above the count and watch process_o stay 0."""

    def __init__(self, name: str = "smc_ndm_process_extra_bits_test_seq") -> None:
        super().__init__(name)
        self.process_readback: int | None = None
        self.samples_taken: int = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _sample_process(self, label: str) -> int:
        sig = cocotb.top.tb_ndmreset_process
        assert sig.value.is_resolvable, f"{label}: tb_ndmreset_process is X/Z ({sig.value})"
        return int(sig.value)

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        nclu = await self.csr_read("NDM_CLUSTER_COUNT", NDM_CLUSTERS, expected=NDM_CLUSTER_COUNT)
        count = nclu & _COUNT_MASK
        mask_above = (0xFFFFFFFF << count) & 0xFFFFFFFF
        idle = self._sample_process("IDLE")
        assert idle == 0, f"tb_ndmreset_process idles 0x{idle:x}, want 0x0"
        self._mark_step("S1")

        await self.csr_write("NDM_PROCESS_ABOVE", NDM_PROCESS, mask_above)
        readback = await self.csr_read("NDM_PROCESS_ABOVE", NDM_PROCESS, expected=mask_above)
        assert readback == mask_above, (
            f"NDMRESET_PROCESS read 0x{readback:x}, want 0x{mask_above:x}"
        )
        for i in range(_WINDOW_CYCLES):
            await RisingEdge(dut.clk_smc_i)
            got = self._sample_process(f"WINDOW[{i}]")
            assert got == 0, (
                f"tb_ndmreset_process=0x{got:x} at clk_smc_i sample {i}/{_WINDOW_CYCLES} "
                f"with NDMRESET_PROCESS=0x{readback:x}, count={count}"
            )
            self.samples_taken += 1
        self.process_readback = readback
        self._mark_step("S2")
        self._log_chk(
            "CHK-NDM-PROCESS-ABOVE-COUNT",
            f"NDMRESET_CLUSTER_COUNT={count}; wrote 0x{mask_above:X} to NDMRESET_PROCESS, "
            f"read back 0x{readback:X} (bits at and above the count are stored); "
            f"tb_ndmreset_process==0x0 at all {self.samples_taken} clk_smc_i samples "
            f"(they drive no output)",
        )

        await self.csr_restore("NDM_PROCESS", NDM_PROCESS, 0)
        after = self._sample_process("RESTORE")
        assert after == 0, f"tb_ndmreset_process=0x{after:x} after restore, want 0x0"

        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        assert self._chk_marks[0][1] >= stamp_of["S2"], "checker line printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<PASS; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
