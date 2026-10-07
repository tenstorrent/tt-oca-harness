# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PERIPH-EXT: the SMC adopter external window, over J2A.

``hw/sys/smc/doc/memmap.adoc`` ("AXI-Lite External Window") places the window
at SMC BASE + 0x040_0000, splits it into a mandatory region at the window base
and a supplementary region at +0x4000, and passes whatever no block claims
through to the adopter external port. The register map generated from
``smc.rdl`` (``hw/sys/smc/regs/gen/c/smc_addr.h``) places EFUSE_SHIM_CTRL at
the mandatory-region base, the straps pair in the mandatory region, and
records how far the allocated blocks reach.

S1: EFUSE_SHIM_CTRL.EFUSE_BANK_INIT_TIME reads its RDL reset value, takes a
    new value, and takes the reset value back -- the shim port carries both a
    request and a response.
S2: the straps pair answers, and the first word past it, which no block claims,
    returns DECERR. The pair is what separates "the window is
    decoded" from "nothing is behind it": a default slave returning zeros
    would answer the straps read too.
S3: the SMC aperture decides whether any of that is reachable at all. Shrink
    BASE_CONFIG.REGION_SIZE so LOCAL_BASE + size ends at the window and the
    same read leaves the chiplet through the output fabric instead. S3 is last
    because it takes the window away. REGION_SIZE zero is not driven:
    fabric.adoc forbids it, and the crossbar's address decoder assumes every
    rule spans at least one byte.

32-bit CSRs at addr[2]=1 use the upper 64b J2A lane (wstrb=0xF0), matching
``wdt_unlock``.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    c_header_u32,
    smc_addr,
)
from seq_lib.smu_boundary_regs import smc_base_config_u32
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

_REPO_ROOT = Path(__file__).resolve().parents[6]
_EFUSE_SHIM_CTRL_C = _REPO_ROOT / "hw" / "ip" / "efuse" / "dv" / "models" / "regs" / "gen" / "c"

# hw/sys/smc/doc/memmap.adoc, "AXI-Lite External Window": the window, its
# mandatory region at the base and its supplementary region above it.
EXTERNAL_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR")
EXT_MANDATORY_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_BASE_ADDR")
EXT_SUPPLEMENTARY_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_BASE_ADDR")

EFUSE_SHIM_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_BASE_ADDR")
# The shim behind the eFuse bank-control port follows efuse_shim_ctrl.rdl; the
# SMC map fixes only where the block sits.
EFUSE_BANK_INIT_TIME = EFUSE_SHIM_BASE + c_header_u32(
    _EFUSE_SHIM_CTRL_C / "efuse_shim_ctrl_addr.h",
    "EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME_BASE_ADDR",
)
EFUSE_BANK_INIT_TIME_RESET = c_header_u32(
    _EFUSE_SHIM_CTRL_C / "efuse_shim_ctrl.h",
    "EFUSE_SHIM_CTRL__EFUSE_BANK_INIT_TIME__INIT_TIME_reset",
)
# A value the reset cannot be mistaken for, inside the 32-bit field.
EFUSE_BANK_INIT_TIME_PROBE = 0x0000_0155

# The boot ROM reads the strap registers the SMC map places in the
# mandatory region.
EXT_STRAPS_LO = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR")
EXT_STRAPS_HI = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_HI_BASE_ADDR")
# The first word past the straps pair: inside the mandatory region, below the
# supplementary region, and claimed by no block. memmap.adoc passes what no block
# claims through to the adopter external port, and hw/sys/smu/doc/port_table.adoc ties that port's
# response to DECERR when nothing is attached.
EXT_UNMAPPED = EXT_STRAPS_HI + 4

REGION_SIZE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
LOCAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
# smc_base_config.rdl: REGION_SIZE.size is a non-zero power of two that
# LOCAL_BASE is aligned to. This size ends the local aperture exactly at the
# window, so the shim is the first address outside it.
REGION_SIZE_SHRUNK = EXTERNAL_BASE - LOCAL_BASE_RESET
# Cycles allowed for an outbound-boundary counter to move after a J2A op.
EGRESS_POLL_CYCLES = 2000


def _require_window_map() -> None:
    """Refuse to run if the sources above disagree about the window."""
    facts = (
        (EXT_MANDATORY_BASE == EXTERNAL_BASE, "mandatory region is not at the window base"),
        (
            EXT_SUPPLEMENTARY_BASE == EXTERNAL_BASE + 0x4000,
            "supplementary region is not at +0x4000",
        ),
        (
            EXT_MANDATORY_BASE <= EFUSE_SHIM_BASE < EXT_SUPPLEMENTARY_BASE,
            "eFuse shim is outside the mandatory region",
        ),
        (
            EXT_MANDATORY_BASE <= EXT_STRAPS_LO and EXT_STRAPS_HI + 4 <= EXT_SUPPLEMENTARY_BASE,
            "straps pair is outside the mandatory region",
        ),
        (
            EXT_UNMAPPED < EXT_SUPPLEMENTARY_BASE,
            "unallocated probe is outside the mandatory region",
        ),
        (
            (REGION_SIZE_SHRUNK & (REGION_SIZE_SHRUNK - 1)) == 0
            and LOCAL_BASE_RESET % REGION_SIZE_SHRUNK == 0,
            "shrunk REGION_SIZE is not a power of two LOCAL_BASE is aligned to",
        ),
        (
            0 < REGION_SIZE_SHRUNK < REGION_SIZE_RESET,
            "shrunk REGION_SIZE does not shrink the reset",
        ),
    )
    bad = [msg for ok, msg in facts if not ok]
    if bad:
        raise RuntimeError("adopter external window map: " + "; ".join(bad))


_require_window_map()


class smu_periph_ext_window_test_seq:
    """eFuse bank-control shim CSR and the adopter external window."""

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
        """S2: the window answers on the straps pair and DECERRs above every allocation."""
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

        # LOCAL_BASE + REGION_SIZE_SHRUNK ends at the window: the shim is no
        # longer local.
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

        self._log(
            f"CHK-PERIPH-EXT-APERTURE: reset=0x{size_at_reset:08x} inside=0x{inside_word:08x} "
            f"shrunk=0x{size_shrunk:08x} outside=0x{outside_word:08x}"
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
