# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PERIPH-EXT: the SMC peripheral crossbar's 0xC040_0000 window, over J2A.

The window splits in two at the crossbar: the eFuse bank-control shim takes
the first EFUSE_SHIM_SIZE bytes and leaves smu_wrapper on its own AXI-Lite
port, and everything above it is the macro AXI-Lite window that
smc_ip_integration decodes.

S1: EFUSE_SHIM_CTRL.EFUSE_BANK_INIT_TIME reads its reset value, takes a new
    value, and takes the reset value back -- the shim port carries both a
    request and a response.
S2: the straps block inside the macro window answers, and an offset above it
    that no sub-window claims decode-errors. The pair is what separates "the
    macro window is decoded" from "nothing is behind it".
S3: the SMC aperture decides whether any of that is reachable at all. Shrink
    BASE_CONFIG.REGION_SIZE below the window and the same read leaves the
    chiplet through the output fabric instead; set it to zero and no address
    is local any more. S3 is last because it takes the fabric away.

32-bit CSRs at addr[2]=1 use the upper 64b J2A lane (wstrb=0xF0), matching
``wdt_unlock``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

# hw/sys/smc/rtl/crossbars/smc_periph_axi_lite_xbar.sv: rule idx 6 places
# efuse.efuse_shim at 0xC040_0000 and rule idx 11 puts external.external
# directly above it, up to 0xC080_0000.
EFUSE_SHIM_BASE = 0xC040_0000
# hw/ip/efuse/dv/models/regs/gen/c/efuse_shim_ctrl_addr.h: the block's only
# register sits at offset 0.
EFUSE_BANK_INIT_TIME = EFUSE_SHIM_BASE + 0x0
# hw/ip/efuse/dv/models/regs/gen/c/efuse_shim_ctrl.h:
# EFUSE_SHIM_CTRL__EFUSE_BANK_INIT_TIME__INIT_TIME_reset.
EFUSE_BANK_INIT_TIME_RESET = 0x20
# A value the reset cannot be mistaken for, inside the 32-bit field.
EFUSE_BANK_INIT_TIME_PROBE = 0x0000_0155

# hw/top/smc_ip_integration.sv: ExtStrapsBase 'h5800 inside the macro window,
# straps_reg_pkg::STRAPS_REG_SIZE = 'h8 -> STRAPS_LO then STRAPS_HI.
EXT_STRAPS_LO = 0xC040_5800
EXT_STRAPS_HI = 0xC040_5804
# Above every sub-window smc_ip_integration decodes, so its ExtUnmapped leg
# terminates the access in an error slave.
EXT_UNMAPPED = 0xC040_6000

REGION_SIZE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
# hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl: REGION_SIZE.size
# defaults to 16 MB and must be a non-zero power of two; zero "leaves no
# reachable local aperture".
REGION_SIZE_RESET = 0x0100_0000
# Still a power of two, and small enough that LOCAL_BASE + size lands below
# the 0xC040_0000 peripheral window.
REGION_SIZE_SHRUNK = 0x0040_0000
# Cycles allowed for an outbound-boundary counter to move after a J2A op.
EGRESS_POLL_CYCLES = 2000


class smu_periph_ext_window_test_seq:
    """eFuse bank-control shim CSR and the macro AXI-Lite window decode."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    @staticmethod
    def _lane(addr: int, data: int = 0) -> tuple[int, int]:
        """Map a 32b CSR onto the 64b J2A data/wstrb lane (see wdt_unlock)."""
        word = int(data) & 0xFFFF_FFFF
        if addr & 0x4:
            return word << 32, 0xF0
        return word, 0x0F

    async def _j2a_rd32(self, jtag, addr: int, label: str) -> tuple[int, int]:
        st, rdata = await jtag2axi_single_read(
            jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"J2A RD {label}")
        raw = int(rdata)
        word = (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF
        return st, word

    async def _j2a_wr32(self, jtag, addr: int, data: int, label: str) -> int:
        packed, wstrb = self._lane(addr, data)
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            packed,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"J2A WR {label}")
        return st

    async def _bring_up_tap(self):
        dut = self.dut
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
        return jtag

    async def _step_efuse_shim(self, jtag, sb) -> None:
        """S1: the eFuse bank-control shim CSR reads, writes and restores."""
        st_rst, at_reset = await self._j2a_rd32(jtag, EFUSE_BANK_INIT_TIME, "INIT_TIME reset")
        sb.expect_eq("CHK-PERIPH-EXT-SHIM-RD status", st_rst, J2A_STATUS_SUCCESS)
        sb.expect_eq(
            "CHK-PERIPH-EXT-SHIM-RESET INIT_TIME at reset",
            at_reset,
            EFUSE_BANK_INIT_TIME_RESET,
            evidence="CHK-PERIPH-EXT-SHIM",
        )

        st_wr = await self._j2a_wr32(
            jtag, EFUSE_BANK_INIT_TIME, EFUSE_BANK_INIT_TIME_PROBE, "INIT_TIME probe"
        )
        sb.expect_eq("CHK-PERIPH-EXT-SHIM-WR status", st_wr, J2A_STATUS_SUCCESS)
        st_rb, readback = await self._j2a_rd32(jtag, EFUSE_BANK_INIT_TIME, "INIT_TIME readback")
        sb.expect_eq("CHK-PERIPH-EXT-SHIM-RB status", st_rb, J2A_STATUS_SUCCESS)
        sb.expect_eq(
            "CHK-PERIPH-EXT-SHIM-RW INIT_TIME takes the written value",
            readback,
            EFUSE_BANK_INIT_TIME_PROBE,
        )

        st_res = await self._j2a_wr32(
            jtag, EFUSE_BANK_INIT_TIME, EFUSE_BANK_INIT_TIME_RESET, "INIT_TIME restore"
        )
        sb.expect_eq("CHK-PERIPH-EXT-SHIM-RESTORE status", st_res, J2A_STATUS_SUCCESS)
        _, restored = await self._j2a_rd32(jtag, EFUSE_BANK_INIT_TIME, "INIT_TIME restored")
        sb.expect_eq(
            "CHK-PERIPH-EXT-SHIM-RESTORE INIT_TIME back to reset",
            restored,
            EFUSE_BANK_INIT_TIME_RESET,
        )
        self._log(
            f"CHK-PERIPH-EXT-SHIM: INIT_TIME reset=0x{at_reset:08x} "
            f"probe=0x{readback:08x} restored=0x{restored:08x}"
        )
        self.s1_ok = True

    async def _step_macro_window(self, jtag, sb) -> None:
        """S2: the macro AXI-Lite window answers on straps and denies above it."""
        st_lo, data_lo = await self._j2a_rd32(jtag, EXT_STRAPS_LO, "STRAPS_LO")
        st_hi, data_hi = await self._j2a_rd32(jtag, EXT_STRAPS_HI, "STRAPS_HI")
        sb.expect_eq("CHK-PERIPH-EXT-STRAPS-LO decoded", st_lo, J2A_STATUS_SUCCESS)
        sb.expect_eq(
            "CHK-PERIPH-EXT-STRAPS-HI decoded",
            st_hi,
            J2A_STATUS_SUCCESS,
            evidence="CHK-PERIPH-EXT-STRAPS",
        )

        st_un, data_un = await self._j2a_rd32(jtag, EXT_UNMAPPED, "unmapped macro offset")
        sb.expect_eq(
            "CHK-PERIPH-EXT-UNMAPPED decode-errors",
            st_un,
            J2A_STATUS_DECERR,
            evidence="CHK-PERIPH-EXT-UNMAPPED",
        )
        self._log(
            f"CHK-PERIPH-EXT-WINDOW: straps_lo=0x{data_lo:08x} straps_hi=0x{data_hi:08x} "
            f"unmapped_status={st_un} unmapped_data=0x{data_un:08x}"
        )
        self.s2_ok = True

    def _egress_reads(self) -> int:
        return self._sample_int("smu_axi_out_read_count_o")

    async def _await_egress_read(self, baseline: int, label: str) -> int:
        """Bounded poll for the outbound read counter to move past ``baseline``."""
        last = baseline
        for _ in range(EGRESS_POLL_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            last = self._egress_reads()
            if last > baseline:
                return last
        raise AssertionError(
            f"TIMEOUT {label}: smu_axi_out_read_count_o stayed at {last} "
            f"(baseline {baseline}) for {EGRESS_POLL_CYCLES} clk_smu cycles"
        )

    async def _step_aperture(self, jtag, sb) -> None:
        """S3: REGION_SIZE decides whether the window stays inside the chiplet."""
        st_sz, size_at_reset = await self._j2a_rd32(jtag, REGION_SIZE_ADDR, "REGION_SIZE reset")
        sb.expect_eq("CHK-PERIPH-EXT-APERTURE-RD status", st_sz, J2A_STATUS_SUCCESS)
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE REGION_SIZE at reset",
            size_at_reset,
            REGION_SIZE_RESET,
        )
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE REGION_SIZE broadcast matches the CSR",
            self._sample_int("smc_region_size_o"),
            REGION_SIZE_RESET,
        )

        # Inside the aperture the shim read is answered on-chiplet, so the
        # outbound boundary sees nothing. This is the control for the two
        # legs below.
        inside_base = self._egress_reads()
        _, inside_word = await self._j2a_rd32(jtag, EFUSE_BANK_INIT_TIME, "INIT_TIME inside")
        await ClockCycles(self.dut.clk_smu_i, 64)
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE-INSIDE nothing left the chiplet",
            self._egress_reads(),
            inside_base,
        )
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE-INSIDE shim answered",
            inside_word,
            EFUSE_BANK_INIT_TIME_RESET,
        )

        # Shrink below 0xC040_0000: the same address is no longer local.
        st_wr = await self._j2a_wr32(
            jtag, REGION_SIZE_ADDR, REGION_SIZE_SHRUNK, "REGION_SIZE shrink"
        )
        sb.expect_eq("CHK-PERIPH-EXT-APERTURE-SHRINK status", st_wr, J2A_STATUS_SUCCESS)
        _, size_shrunk = await self._j2a_rd32(jtag, REGION_SIZE_ADDR, "REGION_SIZE shrunk")
        sb.expect_eq("CHK-PERIPH-EXT-APERTURE-SHRINK readback", size_shrunk, REGION_SIZE_SHRUNK)
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE-SHRINK broadcast",
            self._sample_int("smc_region_size_o"),
            REGION_SIZE_SHRUNK,
        )

        outside_base = self._egress_reads()
        _, outside_word = await self._j2a_rd32(jtag, EFUSE_BANK_INIT_TIME, "INIT_TIME outside")
        outside_count = await self._await_egress_read(outside_base, "s3_shrunk_egress")
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE-SHRINK the shim read left the chiplet",
            outside_count,
            outside_base + 1,
            evidence="CHK-PERIPH-EXT-APERTURE",
        )

        # Zero: the RDL says this leaves no reachable local aperture, so even
        # a core SMC CSR is routed out. Nothing after this can reach the
        # local fabric, so it is the last stimulus.
        st_zero = await self._j2a_wr32(jtag, REGION_SIZE_ADDR, 0, "REGION_SIZE zero")
        sb.expect_eq("CHK-PERIPH-EXT-APERTURE-ZERO status", st_zero, J2A_STATUS_SUCCESS)
        await ClockCycles(self.dut.clk_smu_i, 64)
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE-ZERO broadcast",
            self._sample_int("smc_region_size_o"),
            0,
        )

        zero_base = self._egress_reads()
        _, version_word = await self._j2a_rd32(jtag, SMC_CHIP_CONFIG_VERSION_LO, "VERSION_LO zero")
        zero_count = await self._await_egress_read(zero_base, "s3_zero_egress")
        sb.expect_eq(
            "CHK-PERIPH-EXT-APERTURE-ZERO a core CSR read left the chiplet",
            zero_count,
            zero_base + 1,
            evidence="CHK-PERIPH-EXT-APERTURE-ZERO",
        )
        self._log(
            f"CHK-PERIPH-EXT-APERTURE: reset=0x{size_at_reset:08x} inside=0x{inside_word:08x} "
            f"shrunk=0x{size_shrunk:08x} outside=0x{outside_word:08x} "
            f"zero_version_read=0x{version_word:08x}"
        )
        self.s3_ok = True

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(self.dut.clk_smu_i, 16)

        jtag = await self._bring_up_tap()
        await self._step_efuse_shim(jtag, sb)
        await self._step_macro_window(jtag, sb)
        await self._step_aperture(jtag, sb)
