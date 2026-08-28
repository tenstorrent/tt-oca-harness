# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-5 / P2-6: OTP burn + shadow verify through smc_ip_integration efuse_bank_model.

DEFENDS:
  * Real fuse-sense completes without +skip_fuse_sense (tb_fuse_sense_done).
  * Sensed shadow / OTP word0 matches +smc_efuse_hex preload marker.
  * First PROGRAM with +smc_efuse_prog_fail_count=1 fails without sticky-OR.
  * Second PROGRAM sticky-OR burn updates tb_efuse_programmed_word0.

DOES NOT DEFEND:
  * Samsung macro analog timing / voltage.
  * Full OCCP ROM secure-boot stack (see smc_occp_sanity_secure_error_test).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_addr
from .smc_efuse_vip_utils import efuse_preload_word_at
from .smc_csr_seq_utils import SmcCsrSeq

EFUSE_STATUS = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR"
)
EFUSE_PROGRAM_CTRL = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR"
)
EFUSE_MAP_0 = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")

# Word 0 of the eFuse bank model after sense, i.e. word 0 of the preload asset
# the model $readmemh's at time 0. Derived from the asset at run time via the
# same helper the sibling efuse sequences use, rather than a transcribed
# literal, which cannot detect the asset and the model disagreeing
# ([INDEPENDENT-EXPECTED-MODEL]).
OTP_WORD0_MARKER = efuse_preload_word_at(
    smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
)
_PROG_DATA = 1 << 16
_PROG_GO = 1 << 17
_PROG_READBACK = 1 << 18
_PROG_ENABLE = 1 << 27


class smc_efuse_otp_burn_shadow_test_seq(SmcCsrSeq):
    """Sense + shadow golden + burn-fail then burn-success."""

    async def _wait_program_done(self, clk, label: str) -> int:
        for _ in range(10_000):
            await RisingEdge(clk)
            st = await self.csr_read(label, EFUSE_PROGRAM_CTRL)
            if (st >> 25) & 1:  # program_done
                return st
        raise AssertionError(f"{label}: program_done never set")

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        for _ in range(200_000):
            await RisingEdge(clk)
            if int(dut.tb_fuse_sense_done.value):
                break
        else:
            raise AssertionError("tb_fuse_sense_done never asserted (sense hung)")

        await ClockCycles(clk, 20)

        # MODEL-BACKED, DECLARED. `tb_efuse_otp_word0` taps the adopter-supplied
        # `efuse_bank_model` (hw/ip/efuse/dv/models/efuse_bank_model.sv,
        # instantiated at hw/top/smc_ip_integration.sv:102-115), whose set-once
        # behaviour is `onwrite = woset` in the DV RDL. SPEC declares it a
        # stand-in for the foundry OTP macro
        # (hw/ip/efuse/doc/architecture.adoc:163-170). Every assert on
        # `tb_efuse_*_word0` below therefore shows that the controller's command
        # reached the bank model -- it is NOT evidence that a fuse burns in
        # silicon ([BEHAVIORAL-STUB-DECLARED]).
        #
        # The DUT-path asserts in this sequence are the two that go through the
        # register interface: `EFUSE_MAP_0` (the shadow/map load) and
        # `EFUSE_STATUS.efuse_sense_done`.
        otp0 = int(dut.tb_efuse_otp_word0.value)
        cocotb.log.info("OTP word0 after sense = 0x%08x (model-backed)", otp0)
        assert otp0 == OTP_WORD0_MARKER, (
            f"OTP word0 mismatch: got 0x{otp0:08x}, expected 0x{OTP_WORD0_MARKER:08x}"
        )

        map0 = await self.csr_read("EFUSE_MAP_0", EFUSE_MAP_0)
        cocotb.log.info("EFUSE_MAP_0 = 0x%08x", map0)
        assert map0 == OTP_WORD0_MARKER, (
            f"shadow/map word0 mismatch: got 0x{map0:08x}, expected 0x{OTP_WORD0_MARKER:08x}"
        )

        # `tb_efuse_programmed_word0` and `tb_efuse_otp_word0` ARE THE SAME NET:
        # `tb_top.sv:1358` is `assign tb_efuse_programmed_word0 =
        # tb_efuse_otp_word0;`. Asserting both against the same expectation
        # compared one value twice and read as two independent observations
        # ([NO-ALWAYS-PASS-CHECKER]). The duplicate assert is removed; the
        # equality of the two TB outputs is stated once, as a fact about the
        # testbench rather than a property of the DUT.
        prog0 = int(dut.tb_efuse_programmed_word0.value)
        assert prog0 == otp0, (
            f"tb_efuse_programmed_word0 (0x{prog0:08x}) and tb_efuse_otp_word0 "
            f"(0x{otp0:08x}) differ, but tb_top.sv:1358 aliases them -- the "
            f"testbench no longer matches this sequence's assumption"
        )

        # First PROGRAM (bit2 is clear in A5A55A5A): fail-inject must not sticky-OR.
        # Prefer a clear bit so PROGRAM_READBACK can observe a real miss when the
        # bank model zeroes the write data under +smc_efuse_prog_fail_count.
        _FAIL_BIT = 2
        await self.csr_write(
            "EFUSE_PROGRAM_CTRL_FAIL",
            EFUSE_PROGRAM_CTRL,
            _FAIL_BIT | _PROG_DATA | _PROG_GO | _PROG_READBACK | _PROG_ENABLE,
        )
        st_fail = await self._wait_program_done(clk, "PROGRAM_FAIL")
        prog_fail = int(dut.tb_efuse_programmed_word0.value)
        cocotb.log.info(
            "after injected fail: PROGRAM_CTRL=0x%08x programmed=0x%08x status=%d",
            st_fail,
            prog_fail,
            (st_fail >> 26) & 1,
        )
        assert prog_fail == OTP_WORD0_MARKER, (
            "program-fail inject must not sticky-OR OTP bits"
        )
        assert (st_fail >> 26) & 1, "program_status expected 1 on injected fail"

        # Second PROGRAM (bit0 is clear in A5A55A5A): success sticky-OR.
        await self.csr_write(
            "EFUSE_PROGRAM_CTRL_OK",
            EFUSE_PROGRAM_CTRL,
            0 | _PROG_DATA | _PROG_GO | _PROG_READBACK | _PROG_ENABLE,
        )
        st_ok = await self._wait_program_done(clk, "PROGRAM_OK")
        prog_ok = int(dut.tb_efuse_programmed_word0.value)
        cocotb.log.info(
            "after burn success: PROGRAM_CTRL=0x%08x programmed=0x%08x",
            st_ok,
            prog_ok,
        )
        assert (prog_ok & 1) == 1, "sticky-OR burn did not set bit0"
        assert prog_ok == (OTP_WORD0_MARKER | 1), (
            f"sticky-OR burn unexpected: got 0x{prog_ok:08x}"
        )
        # POSITIVE CONTROL for the `program_status == 1` assert on the injected
        # failure above. Without it, a PROGRAM_CTRL whose status bit were stuck
        # high would satisfy the fail leg just as well
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). The clean program's status word
        # was already being read into `st_ok` and logged, and then discarded;
        # it is now compared.
        assert ((st_ok >> 26) & 1) == 0, (
            f"program_status is set after a program that was NOT fail-injected "
            f"(PROGRAM_CTRL=0x{st_ok:08x}); the status bit does not "
            f"discriminate, so the injected-failure assert above proves nothing"
        )

        status = await self.csr_read("EFUSE_STATUS", EFUSE_STATUS)
        cocotb.log.info("EFUSE_STATUS=0x%08x", status)
        assert status & 1, "EFUSE_STATUS.efuse_sense_done not set"
