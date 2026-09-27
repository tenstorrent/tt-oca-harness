# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP<->SMC bidirectional handshake under the OSS SMU wrapper.

Two firmwares run against each other:

  * SEP: hw/sys/sep/dv/fw/tests/sep_smu_bidirect -- programs the SMU xbar SEP
    aperture, opens its outbound/inbound filter windows, read/write-checks SMC
    scratch8..11 across the crossbar, then trades four patterns with the SMC.
  * SMC: hw/sys/smu/dv/fw/tests/smu_sep_bidirect_arm -- the counterpart half,
    which also records how far it got in SMC scratch0.

Both directions have to work for the SEP to reach its pass loop: SEP->SMC is
proven by the scratch read/write checks and by the SMC observing SEP_READY and
SEP_ACK, SMC->SEP by the SEP observing the two reply patterns in its own cold
scratch. A one-way failure parks the SEP in its fail loop instead.

The SMC records how far it got in SMC scratch0, visible here as
smc_scratch_0_o. Once the SEP has parked in its pass loop that marker must
read the SMC firmware's DONE phase within a bounded number of cycles: the
SEP's verdict alone says the SEP saw both replies, the marker says the SMC
side also ran its half to completion. On a failure the marker answers "which
side stopped", which a PC profile of the SEP alone cannot.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq

# Phase words the SMC counterpart (hw/sys/smu/dv/fw/tests/smu_sep_bidirect_arm,
# SMC_PHASE_*) writes to SMC scratch0.
SMC_PHASES = {
    0x5C000001: "SMC entered, waiting for SEP_READY",
    0x5C000002: "SMC saw SEP_READY, replied SMC_TO_SEP",
    0x5C000003: "SMC saw SEP_ACK, replied SMC_DONE",
    0x5C000004: "SMC completed the handshake",
    0x5CBAD001: "SMC timed out waiting for SEP_READY",
    0x5CBAD002: "SMC timed out waiting for SEP_ACK",
}
SMC_PHASE_DONE = 0x5C000004
#: clk_smu_i cycles allowed between the SEP parking in its pass loop and the SMC
#: writing SMC_PHASE_DONE; the SMC issues that store right after the SMC_DONE
#: reply the SEP was waiting on.
SMC_PHASE_DONE_BOUND_CYCLES = 20_000


class SmuSepBidirectSeq(SepTerminalLoopSeq):
    NAME = "sep_bidirect"
    PASS_SYM = "smu_bidirect_pass_loop"
    FAIL_SYMS = {"bidirect": "smu_bidirect_fail_loop"}
    SYM_DEFAULT = "sep_smu_bidirect.tcm.sym"
    #: Emitted by the base class once the SEP verdict holds.
    EVIDENCE = ("SEP_REAL_FW_BIDIRECT_OK",)
    #: Emitted only after smc_scratch_0_o has read SMC_PHASE_DONE.
    HANDSHAKE_EVIDENCE = "SEP_SMC_HANDSHAKE_OK"

    @staticmethod
    def _phase_text(raw: int) -> str:
        return f"0x{raw:08x} ({SMC_PHASES.get(raw, 'unknown')})"

    def _smc_phase(self) -> str:
        raw = self.test.read_int(cocotb.top.smc_scratch_0_o, "smc_scratch_0_o", allow_xz=True)
        return self._phase_text(raw)

    async def _wait_smc_phase_done(self) -> int:
        """Cycles until smc_scratch_0_o reads SMC_PHASE_DONE; an X sample or expiry fails."""
        last = None
        for cycle in range(1, SMC_PHASE_DONE_BOUND_CYCLES + 1):
            await RisingEdge(self.dut.clk_smu_i)
            last = self.test.read_int(self.dut.smc_scratch_0_o, "smc_scratch_0_o", allow_xz=False)
            if last == SMC_PHASE_DONE:
                return cycle
        raise AssertionError(
            f"{self.NAME}: SMC phase did not reach {self._phase_text(SMC_PHASE_DONE)} within "
            f"{SMC_PHASE_DONE_BOUND_CYCLES} cycles of the SEP pass loop; last "
            f"{self._phase_text(last)}; {self._route_state()}"
        )

    def _route_state(self) -> str:
        """SEP aperture as the crossbar sees it.

        SMC->SEP writes land at 0x1080_2000, which only falls inside the SEP
        aperture once the SEP firmware has widened SEP_REGION_SIZE to
        0x2000_0000. At the 0x0100_0000 reset value the address misses every
        rule and the crossbar sends it to ext_out instead of the SEP, so the
        reply is silently delivered to the wrong target.
        """
        base = self.test.read_int(
            cocotb.top.sep_xbar_global_base_o, "sep_xbar_global_base_o", allow_xz=True
        )
        size = self.test.read_int(
            cocotb.top.sep_xbar_region_size_o, "sep_xbar_region_size_o", allow_xz=True
        )
        covered = base <= 0x1080_2000 < base + size
        arrived = self.test.read_int(
            cocotb.top.sep_xbar_in_aw_count_o, "sep_xbar_in_aw_count_o", allow_xz=True
        )
        return (
            f"SEP aperture=[0x{base:x} +0x{size:x}] covers 0x10802000: {covered}; "
            f"xbar->SEP inbound AW count={arrived} "
            f"addr=0x{self.test.read_int(cocotb.top.sep_xbar_in_aw_addr_o, 'a', allow_xz=True):x} "
            f"awuser=0x{self.test.read_int(cocotb.top.sep_xbar_in_aw_user_o, 'u', allow_xz=True):03x} "
            "(SEP inbound filter matches src_id=0x3 out of awuser)"
        )

    async def run(self) -> None:
        try:
            await super().run()
        except AssertionError as exc:
            # Attribute the stall to a side before re-raising.
            raise AssertionError(
                f"{exc}; SMC phase = {self._smc_phase()}; {self._route_state()}"
            ) from exc
        done_after = await self._wait_smc_phase_done()
        self.log.info(
            "CHK-SEP-SMC-HANDSHAKE: PASS (SEP parked in its pass loop; smc_scratch_0_o "
            "read %s %d cycle(s) later; %s)",
            self._phase_text(SMC_PHASE_DONE),
            done_after,
            self._route_state(),
        )
        self._log_evidence(self.HANDSHAKE_EVIDENCE)
