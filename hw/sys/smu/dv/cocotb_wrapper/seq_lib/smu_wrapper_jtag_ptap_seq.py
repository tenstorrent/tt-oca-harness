# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary TAP reachable on the production wrapper, with the SEP running.

This test drives JTAG on the wrapper rather than only pulsing it into reset;
the DTP/SEP probe anchors need a TAP that answers.

What it proves, in order:

  S1  IDCODE matches the RTL default and TDO is resolved, so the TAP is
      answering rather than reading back as an unresolved 0.
  S2  BYPASS is a one-bit register -- over an 8-bit scan TDO comes back as the
      pattern shifted up one bit (capture-0, then TDI delayed). IDCODE alone
      can be satisfied by a stuck chain; the delay cannot.
  S3  Both hold at a second TCK period, so the result is not tied to one
      clock ratio against clk_smu.
  S4  The SEP is still executing afterwards, which is the part specific to this
      profile: TAP access must not disturb a running SEP.
  S5  The IC_RESET override bits are clear. Every wrapper test rests on this --
      an asserted override holds SMC cold/fuse reset and the SEP never fetches,
      which is exactly the failure the base test's TAP reset walk exists to
      prevent.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.wrapper_jtag import (
    PTAP_DEFAULT_IDCODE,
    PTAP_IR_WIDTH,
    make_wrapper_ptap,
    ptap_ir_opcode,
    require_tdo_resolved,
)

BYPASS_PATTERN = 0xA5
BYPASS_WIDTH = 8
TCK_PERIODS_NS = (100, 200)


class SmuWrapperJtagPtapSeq:
    """IDCODE + BYPASS on the wrapper PTAP, without disturbing the SEP."""

    #: Evidence tokens logged once every check above the verdict has held.
    EVIDENCE = (
        "SMU_WRAPPER_PTAP_OK",
        "SMU_WRAPPER_PTAP_SEP_UNDISTURBED_OK",
        "SMU_WRAPPER_IC_RESET_CLEAR_OK",
    )

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        test.declare_evidence(*self.EVIDENCE)

    async def _idcode(self, jtag) -> int:
        got = await jtag.read_idcode()
        require_tdo_resolved("IDCODE")
        assert got == PTAP_DEFAULT_IDCODE, (
            f"IDCODE want 0x{PTAP_DEFAULT_IDCODE:08x} got 0x{got:08x}"
        )
        return got

    async def _bypass(self, jtag) -> None:
        await jtag.shift_ir(ptap_ir_opcode("BYPASS_3F"), width=PTAP_IR_WIDTH, back_to_rti=False)
        captured = int(await jtag.shift_dr(BYPASS_PATTERN, BYPASS_WIDTH, back_to_rti=True))
        require_tdo_resolved("BYPASS")
        mask = (1 << BYPASS_WIDTH) - 1
        # The shift register captures 0 and then returns TDI one bit later, so
        # over an 8-bit scan TDO is the pattern shifted up by one, matching the
        # bare `--dut smu_block` PTAP checker.
        want = (BYPASS_PATTERN << 1) & mask
        assert (captured & mask) == want, (
            f"BYPASS tdi=0x{BYPASS_PATTERN:02x} tdo=0x{captured & mask:02x} "
            f"want 0x{want:02x} (capture-0 then TDI delayed one bit)"
        )

    async def run(self) -> None:
        self.log.info("=" * 70)
        self.log.info("TEST: primary TAP on the production wrapper, SEP running")
        self.log.info("=" * 70)

        inst_before = self.test.read_int(
            self.dut.sep_inst_count_o, "sep_inst_count_o", allow_xz=True
        )

        for period in TCK_PERIODS_NS:
            jtag = make_wrapper_ptap(period)
            await jtag.reset_tap()
            idcode = await self._idcode(jtag)
            await self._bypass(jtag)
            self.log.info(
                "TCK %d ns: IDCODE=0x%08x, BYPASS one-bit delay confirmed",
                period,
                idcode,
            )

        # The SEP must still be retiring after the TAP work. A wrapper anchor
        # that silently halted the SEP would still pass every JTAG check above.
        await ClockCycles(self.dut.clk_smu_i, 2000)
        inst_after = self.test.read_int(
            self.dut.sep_inst_count_o, "sep_inst_count_o", allow_xz=True
        )

        smc_ovrd = self.test.read_int(
            self.dut.ic_reset_smc_ovrd_o, "ic_reset_smc_ovrd_o", allow_xz=True
        )
        sep_ovrd = self.test.read_int(
            self.dut.ic_reset_sep_ovrd_any_o, "ic_reset_sep_ovrd_any_o", allow_xz=True
        )

        errors: list[str] = []
        if smc_ovrd != 0:
            errors.append(
                f"SMC IC_RESET override bits set (0x{smc_ovrd:017x}) -- the TAP "
                "reset walk did not clear the TDR, so cold/fuse reset is being held"
            )
        if sep_ovrd != 0:
            errors.append(
                "SEP IC_RESET override asserted -- the TAP reset walk did not clear the TDR"
            )
        if inst_after <= inst_before:
            errors.append(
                f"SEP stopped retiring across the TAP accesses ({inst_before} -> {inst_after})"
            )
        assert not errors, "wrapper PTAP: " + "; ".join(errors)

        self.log.info(
            "CHK-WRAPPER-PTAP-IDCODE: PASS (IDCODE 0x%08x at %s ns TCK, TDO resolved)",
            PTAP_DEFAULT_IDCODE,
            "/".join(str(p) for p in TCK_PERIODS_NS),
        )
        self.log.info(
            "CHK-WRAPPER-PTAP-BYPASS: PASS (one-bit register at each period; a "
            "stuck chain cannot produce the TDI delay)"
        )
        self.log.info(
            "CHK-WRAPPER-PTAP-SEP-LIVE: PASS (SEP retired %d -> %d across the TAP accesses)",
            inst_before,
            inst_after,
        )
        self.log.info(
            "CHK-WRAPPER-IC-RESET-CLEAR: PASS (SMC override bits 0x%x, SEP override "
            "0 -- the base test TAP reset walk really does clear the TDR)",
            smc_ovrd,
        )
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
