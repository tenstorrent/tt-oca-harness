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
from .smc_csr_seq_utils import SmcCsrSeq

EFUSE_STATUS = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR"
)
EFUSE_PROGRAM_CTRL = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR"
)
EFUSE_MAP_0 = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")

OTP_WORD0_MARKER = 0xA5A55A5A
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

        otp0 = int(dut.tb_efuse_otp_word0.value)
        cocotb.log.info("OTP word0 after sense = 0x%08x", otp0)
        assert otp0 == OTP_WORD0_MARKER, (
            f"OTP word0 mismatch: got 0x{otp0:08x}, expected 0x{OTP_WORD0_MARKER:08x}"
        )

        map0 = await self.csr_read("EFUSE_MAP_0", EFUSE_MAP_0)
        cocotb.log.info("EFUSE_MAP_0 = 0x%08x", map0)
        assert map0 == OTP_WORD0_MARKER, (
            f"shadow/map word0 mismatch: got 0x{map0:08x}, expected 0x{OTP_WORD0_MARKER:08x}"
        )

        # efuse_bank_model keeps a single OTP array (no separate "programmed"
        # store). After sense, programmed_word0 mirrors the preload marker.
        prog0 = int(dut.tb_efuse_programmed_word0.value)
        assert prog0 == OTP_WORD0_MARKER, (
            f"programmed_word0 expected preload marker 0x{OTP_WORD0_MARKER:08x}, "
            f"got 0x{prog0:08x}"
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

        status = await self.csr_read("EFUSE_STATUS", EFUSE_STATUS)
        cocotb.log.info("EFUSE_STATUS=0x%08x", status)
        assert status & 1, "EFUSE_STATUS.efuse_sense_done not set"
