# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""STRAPS_LO/HI track captured_straps_i. SEP=0, no Force."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import reset_unit_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

STRAPS_LO_ADDR = smc_addr("SMC_TOP_SMC_RESET_UNIT_STRAPS_LO_BASE_ADDR")
STRAPS_HI_ADDR = smc_addr("SMC_TOP_SMC_RESET_UNIT_STRAPS_HI_BASE_ADDR")
if STRAPS_HI_ADDR != STRAPS_LO_ADDR + 4:
    raise RuntimeError(
        f"STRAPS_HI 0x{STRAPS_HI_ADDR:08x} is not STRAPS_LO+4 (0x{STRAPS_LO_ADDR + 4:08x})"
    )
STRAPS_HI_MASK = reset_unit_u32("RESET_UNIT__STRAPS_HI__STRAPS_bm")
# Both halves non-zero so HI cannot vacuously pass as stuck-0.
STRAP_PATTERN = 0x05A5_A5A5_A5A5_5A5A
STRAP_LO = STRAP_PATTERN & 0xFFFF_FFFF
STRAP_HI = (STRAP_PATTERN >> 32) & STRAPS_HI_MASK


class smu_smc_gpio_strap_sanity_test_seq:
    """Reset-unit STRAPS_* track captured_straps_i."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd_straps(self, jtag) -> tuple[int, int, int]:
        """Read STRAPS_LO/HI from the 64b lane at STRAPS_LO (HI is +4)."""
        st, rdata = await jtag2axi_single_read(
            jtag,
            STRAPS_LO_ADDR,
            size=SMC_DBG_AXSIZE_8B,
            require_complete=True,
        )
        require_jtag_tdo_resolved("STRAPS 64b RD")
        val = int(rdata)
        lo = val & 0xFFFF_FFFF
        hi = (val >> 32) & STRAPS_HI_MASK
        return st, lo, hi

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        if not hasattr(dut, "captured_straps_i"):
            raise AssertionError("captured_straps_i missing on OSS tb_top")

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        self.s1_ok = True
        sb.expect_eq("CHK-STRAP-GATE-OPEN", gate, 0)

        dut.captured_straps_i.value = 0
        await ClockCycles(dut.clk_smu_i, 8)
        st0, lo0, hi0 = await self._rd_straps(jtag)
        if st0 != J2A_STATUS_SUCCESS:
            raise AssertionError(f"idle STRAPS status={st0}")
        if lo0 != 0 or hi0 != 0:
            raise AssertionError(f"idle STRAPS lo=0x{lo0:08x} hi=0x{hi0:08x}")
        self.s2_ok = True
        sb.expect_eq("CHK-STRAP-IDLE-LO", lo0, 0)
        sb.expect_eq("CHK-STRAP-IDLE-HI", hi0, 0)

        dut.captured_straps_i.value = STRAP_PATTERN
        await ClockCycles(dut.clk_smu_i, 16)
        st2, lo1, hi1 = await self._rd_straps(jtag)
        if st2 != J2A_STATUS_SUCCESS:
            raise AssertionError(f"pattern STRAPS status={st2}")
        if lo1 != STRAP_LO:
            raise AssertionError(f"STRAPS_LO=0x{lo1:08x} want 0x{STRAP_LO:08x}")
        if hi1 != STRAP_HI:
            raise AssertionError(f"STRAPS_HI=0x{hi1:08x} want 0x{STRAP_HI:08x}")
        self.s3_ok = True
        self._log(f"SMC_STRAP_OK lo=0x{lo1:08x} hi=0x{hi1:08x}")
        sb.expect_eq(
            "CHK-SMC-STRAP pattern LO/HI",
            (lo1, hi1),
            (STRAP_LO, STRAP_HI),
            evidence="SMC_STRAP_OK",
        )

        dut.captured_straps_i.value = 0
        await ClockCycles(dut.clk_smu_i, 16)
        st4, lo2, hi2 = await self._rd_straps(jtag)
        if st4 != J2A_STATUS_SUCCESS:
            raise AssertionError(f"clear STRAPS status={st4}")
        if lo2 != 0 or hi2 != 0:
            raise AssertionError(f"cleared STRAPS lo=0x{lo2:08x} hi=0x{hi2:08x}")
        self.s4_ok = True
        sb.expect_eq("CHK-STRAP-CLEAR", (lo2, hi2), (0, 0))
