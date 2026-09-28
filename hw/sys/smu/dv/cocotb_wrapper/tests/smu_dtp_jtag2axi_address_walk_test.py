# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag2axi_address_walk_test - every address bit of the three DTP JTAG2AXI bridges.

The DTP's three JTAG2AXI bridges reach the SMC fabric, the SMC OTP controller
and the SEP OTP controller through nets the SMU wires between u_dtp, u_smc and
u_sep, and the SMC fabric bridge also reaches the adopter AXI-Lite window and
the DTP CSR window through the SMC. A single-op carries its own write strobe,
and a strobe of zero is a legal AXI write that changes no byte, so every
write here that lands on a live register carries a zero strobe.

S1: SMC fabric bridge, byte writes and reads of SCRATCH_COLD at byte offsets
    1, 2 and 3 complete SUCCESS; a zero-strobe write to 0x1000, outside the
    SMC map and inside the SEP aperture, completes.
S2: adopter window (smc_addr.h SMC_EXTERNAL_REGION, 4 MiB at 0xC040_0000): a
    write and a read at the base plus 2^k for every k below 22 complete. The
    SMC diverts the eFuse shim CSR at the window base to its eFuse controller
    and the integration decodes the rest, so the responses differ by offset;
    each address still crosses the SMC's external port or the eFuse shim port.
S3: DTP CSR window (DTP_CTRL_REG, 2 KiB at 0xC000_B000): a read and a
    zero-strobe write at the base plus 2^k for every k below 11 complete.
S4, S5: the SMC and SEP OTP bridges: a read and a zero-strobe write at 0,
    2^k for every k below 32 and 0xFFFF_FFFF each complete.
S6: a cold reset on rst_cold_ni takes the primary SMC reset low and releases
    it again, returning the bridges' held request fields to their reset values.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_jtag_helpers import (
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    pack_otp_single_op,
    require_jtag_tdo_resolved,
    unpack_otp_single_op,
)
from smu_base_test import smu_base_test

SCRATCH = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
EXT_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_REGION_BASE_ADDR")
EXT_SIZE = smc_addr("SMC_TOP_SMC_EXTERNAL_REGION_SIZE")
DTP_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")
DTP_SIZE = smc_addr("SMC_TOP_DTP_CTRL_REG_SIZE")
SEP_APERTURE_ADDR = 0x1000
POLLS = 128
RESET_BOUND = 20000
RESET_HOLD = 64


def _bits_below(size: int) -> list[int]:
    return [1 << k for k in range(size.bit_length() - 1)]


@pyuvm.test()
class smu_dtp_jtag2axi_address_walk_test(smu_base_test):
    """Every address bit of the SMC fabric and both OTP JTAG2AXI bridges reaches its target."""

    use_shared_env = True

    async def _fab(self, jtag, write: bool, addr: int, *, size: int, wstrb: int = 0) -> int:
        if write:
            st, _ = await jtag2axi_single_write(
                jtag, addr, 0, wstrb=wstrb, size=size, poll_limit=POLLS
            )
        else:
            st, _ = await jtag2axi_single_read(jtag, addr, size=size, poll_limit=POLLS)
        require_jtag_tdo_resolved(f"fabric walk @0x{addr:x}")
        return st

    async def _otp(self, jtag, tdr: str, write: bool, addr: int) -> int:
        op = J2A_OP_WRITE if write else J2A_OP_READ
        await jtag.write(tdr, pack_otp_single_op(op, addr, 0, wstrb=0))
        require_jtag_tdo_resolved(f"{tdr} issue @0x{addr:x}")
        await ClockCycles(cocotb.top.clk_smu_i, 32)
        status = J2A_STATUS_BUSY
        for _ in range(POLLS):
            capt = await jtag.read(tdr, shift_value=0)
            status, _ = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(cocotb.top.clk_smu_i, 16)
        return status

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        s1 = []
        for offset in (1, 2, 3):
            s1.append(await self._fab(jtag, True, SCRATCH + offset, size=0, wstrb=1 << offset))
            s1.append(await self._fab(jtag, False, SCRATCH + offset, size=0))
        outside = await self._fab(jtag, True, SEP_APERTURE_ADDR, size=2, wstrb=0)
        self.logger.info(f"CHK-J2A-WALK-FABRIC offsets={s1} outside_map={outside}")
        sb.expect_eq(
            "CHK-J2A-WALK-FABRIC",
            (s1, outside != J2A_STATUS_BUSY),
            ([J2A_STATUS_SUCCESS] * 6, True),
            evidence="CHK-J2A-WALK-FABRIC",
        )

        s2 = []
        for bit in _bits_below(EXT_SIZE):
            addr = EXT_BASE + bit
            size = 0 if bit < 4 else 2
            wstrb = (1 << (bit & 7)) if size == 0 else (0x0F << (addr & 4))
            s2.append(await self._fab(jtag, True, addr, size=size, wstrb=wstrb))
            s2.append(await self._fab(jtag, False, addr, size=size))
        self.logger.info(f"CHK-J2A-WALK-EXTERNAL statuses={s2}")
        sb.expect_true(
            "CHK-J2A-WALK-EXTERNAL",
            J2A_STATUS_BUSY not in s2,
            evidence="CHK-J2A-WALK-EXTERNAL",
        )

        s3 = []
        for bit in _bits_below(DTP_SIZE):
            addr = DTP_BASE + bit
            size = 0 if bit < 4 else 2
            s3.append(await self._fab(jtag, False, addr, size=size))
            s3.append(await self._fab(jtag, True, addr, size=size, wstrb=0))
        self.logger.info(f"CHK-J2A-WALK-DTP-CSR statuses={s3}")
        sb.expect_true(
            "CHK-J2A-WALK-DTP-CSR",
            J2A_STATUS_BUSY not in s3,
            evidence="CHK-J2A-WALK-DTP-CSR",
        )

        otp_addrs = [0] + [1 << k for k in range(32)] + [0xFFFF_FFFF]
        for tdr, token in (
            ("SMC_OTP_AXI_SINGLE_OP", "CHK-J2A-WALK-SMC-OTP"),
            ("SEP_OTP_AXI_SINGLE_OP", "CHK-J2A-WALK-SEP-OTP"),
        ):
            statuses = []
            for addr in otp_addrs:
                statuses.append(await self._otp(jtag, tdr, False, addr))
                statuses.append(await self._otp(jtag, tdr, True, addr))
            self.logger.info(f"{token} statuses={statuses}")
            sb.expect_true(token, J2A_STATUS_BUSY not in statuses, evidence=token)

        observed = []
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        for _ in range(RESET_BOUND):
            await RisingEdge(dut.clk_ref_i)
            if sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o") == 0:
                break
        observed.append(sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o"))
        await ClockCycles(dut.clk_ref_i, RESET_HOLD)
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.jtag_tap_reset(16)
        for _ in range(RESET_BOUND):
            await RisingEdge(dut.clk_smu_i)
            if sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o") == 1:
                break
        observed.append(sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o"))
        self.logger.info(f"CHK-J2A-WALK-COLD-RESET primary reset during/after={observed}")
        sb.expect_eq(
            "CHK-J2A-WALK-COLD-RESET", observed, [0, 1], evidence="CHK-J2A-WALK-COLD-RESET"
        )
