# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""COLD vs COLD_WARM scratch across tb_sep_wdt_reset_n. No Force."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
COLD_PAT = 0xDEADBEEF
WARM_PAT = 0xCAFEB0BA
# WDT reset into the COLD_WARM domain is async; 16 SMC clocks cover the
# wrapper sync into rst_wdt. Proof is the post-pulse CSR handshake, not this
# pulse width alone.
_WDT_PULSE = 16
_CSR_BOUND = 64

# ---------------------------------------------------------------------------
# RESET_UNIT SS_* / ISOLATE_REQ sweep.
#
# All of these are `sw = rw; hw = r` with reset 0x0 in
# hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl -- plain software-owned
# storage whose only consumer is a TOP-LEVEL OUTPUT, so no write feeds back into
# the DUT and resets the bench:
#   * `ss_reset_ctrl_o [31:0]` (smc.sv:191) reaches tb_top as
#     `ss_reset_ctrl [31:0]` (tb_top.sv:1184,1279) and only
#     `ss_reset_ctrl[0].warm_reset_n` is tapped out (tb_top.sv:1400).
#   * `isolate_req_o [31:0]` (smc.sv:187) goes straight to the observation port
#     `tb_isolate_req_o` (tb_top.sv:144,1276).
# Neither loops back into the DUT, so driving them perturbs nothing.
#
_SS_SWEEP_REGS = (
    "SS_CONFIG",
    "SS_COLD_RESET_N",
    "SS_CONFIG_HOLD",
    "SS_SRAM_HOLD",
    "SS_CRITICAL_HOLD",
    "SS_DEBUG_HOLD",
    "SS_FORCE_TO_REF_CLK",
)
# The inclusion criterion is "`sw = rw`, reset 0x0, reversible, and no path back
# into the bench". The `external` keyword only says where a register lives:
# `SS_CONFIG` @0x20 and `SS_COLD_RESET_N` @0x40 are `external`
# (reset_unit.rdl:227,230) and meet the criterion. Each register outside the
# tuple above fails it for a reason of its own:
#
#   * `SS_WARM_RESET_N` @0x44 -- `sw = rw; hw = r` like the swept seven, but its
#     reset is 0xFFFFFFFF (reset_unit.rdl:44-50), so the sweep's `expected=0`
#     reset leg does not apply, and `ss_reset_ctrl[0].warm_reset_n` is tapped
#     into the bench at `tb_top.sv:1400`, so driving it perturbs the run.
#   * `SS_RESET_COMPLETE` @0x60 -- `sw = r; hw = w` (reset_unit.rdl:97-104):
#     software cannot write it, so a write/readback expectation does not exist.
#   * `SYNC_REG` @0xA8 -- `sw = rw; hw = r`, but a single bit `sync[0:0]`
#     (reset_unit.rdl:106-112). A 1-bit register cannot carry the alternating
#     `_SS_PATTERN`, so it would need its own expectation rather than the
#     sweep's.
#   * `SS_CONFIG_LOCK` @0x24 and `SS_COLD_RESET_LOCK` @0x70 -- `onwrite = woset`,
#     irreversible until a cold reset, and the latter removes SS_COLD_RESET_N's
#     writability, so the sweep's restore leg cannot apply;
#     `smc_reset_unit_lock_test_seq` covers them.
#   * `ISOLATE_REQ_VIS` @0xC0 -- `sw = r; hw = w` pin visibility
#     (reset_unit.rdl:146-152).
#   * `ISOLATE_REQ_SMC_REG` @0xB8 -- hardware-set, software-cleared, and one bit
#     wide. `smc_cool_reset_wrap.sv:267-278` sets it to 1 when
#     `cfg_flr_pf_active` asserts and clears it to 0 on ANY software write with
#     a non-zero bit enable, regardless of the data; `:99` returns
#     `{31'b0, isolate_req_smc_reg}`. A write/readback probe therefore reads
#     0x0 by specification. Proving the set half needs an FLR event, which is
#     out of this testcase's scope.
#   * `ISOLATE_REQ_PINEN_REG` @0xB4 and `ISOLATE_REQ_SMCEN_REG` @0xBC -- plain
#     `sw = rw` storage, but both OR into the pin this testcase observes:
#     `smc_cool_reset_wrap.sv:294` computes `isolate_req_o[i] =
#     isolate_req_reg[i] | (isolate_req_pinen_reg[i] & isolate_req_pin) |
#     (isolate_req_smcen_reg[i] & isolate_req_smc_reg)`. Leaving them at reset
#     keeps the `tb_isolate_req_o` observation below attributable to
#     `ISOLATE_REQ_REG` alone.
#
# `ISOLATE_REQ_REG` @0xB0 keeps its own dedicated check below because its value
# is observable on a DUT output pin, a property independent of all of the above.
# Alternating bits so a stuck-at-0 or stuck-at-1 register cannot read it back.
_SS_PATTERN = 0x5A5A_A5A5
# ISOLATE_REQ_REG gets a stronger check than write/readback: its value is
# observable on a DUT output pin, so the CSR-to-pin path is checked too. A
# single bit is driven, and one that is not bit 0, so a tie-off or an
# off-by-one on the bus would not satisfy it.
ISOLATE_REQ_BIT = 5


class smc_reset_unit_sanity_test_seq(SmcCsrSeq):
    """COLD persists across SEP WDT reset; COLD_WARM does not."""

    def __init__(self, name: str = "smc_reset_unit_sanity_test_seq") -> None:
        super().__init__(name)
        # Names of the registers the SS_* sweep actually drove, published for
        # the testcase module's zero-activity guard.
        self.ss_regs_swept: list[str] = []

    async def _ss_sweep(self, dut) -> None:
        """Write/readback/restore the software-owned RESET_UNIT SS_* registers.

        Run AFTER the SEP WDT pulse: the pulse clears the COLD_WARM
        domain, so values written before it would not survive to be read back.
        """
        for reg in _SS_SWEEP_REGS:
            addr = smc_addr(f"SMC_TOP_SMC_RESET_UNIT_{reg}_BASE_ADDR")
            await self.csr_read(f"{reg}_RESET", addr, expected=0)
            await self.csr_write(f"{reg}_WR", addr, _SS_PATTERN)
            await self.csr_read(f"{reg}_RB", addr, expected=_SS_PATTERN)
            await self.csr_write(f"{reg}_RESTORE", addr, 0)
            await self.csr_read(f"{reg}_RESTORE_RB", addr, expected=0)
            self.ss_regs_swept.append(reg)

        # ISOLATE_REQ_REG: CSR value must also appear on the DUT output pin.
        iso = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
        assert hasattr(dut, "tb_isolate_req_o"), (
            "tb_isolate_req_o missing from the TB top: the CSR-to-pin half of "
            "the ISOLATE_REQ_REG check has no observation port"
        )
        pin_idle = int(dut.tb_isolate_req_o.value)
        assert pin_idle == 0, (
            f"isolate_req_o is already 0x{pin_idle:x} before ISOLATE_REQ_REG "
            f"was written; the pin check below could not be attributed to the "
            f"CSR write"
        )
        await self.csr_read("ISOLATE_REQ_REG_RESET", iso, expected=0)
        await self.csr_write("ISOLATE_REQ_REG_WR", iso, 1 << ISOLATE_REQ_BIT)
        await self.csr_read("ISOLATE_REQ_REG_RB", iso, expected=1 << ISOLATE_REQ_BIT)
        await RisingEdge(dut.clk_smc_i)
        pin_set = int(dut.tb_isolate_req_o.value)
        assert pin_set == (1 << ISOLATE_REQ_BIT), (
            f"ISOLATE_REQ_REG read back 0x{1 << ISOLATE_REQ_BIT:x} but the DUT "
            f"output isolate_req_o is 0x{pin_set:x}; the CSR stores the value "
            f"without driving the pin it is specified to drive"
        )
        await self.csr_write("ISOLATE_REQ_REG_RESTORE", iso, 0)
        await self.csr_read("ISOLATE_REQ_REG_RESTORE_RB", iso, expected=0)
        await RisingEdge(dut.clk_smc_i)
        pin_clr = int(dut.tb_isolate_req_o.value)
        assert pin_clr == 0, (
            f"isolate_req_o stayed 0x{pin_clr:x} after ISOLATE_REQ_REG was restored to 0"
        )
        cocotb.log.info(
            "CHK-RESET-UNIT-SS-SWEEP: %d software-owned SS_*/ISOLATE_REQ "
            "registers took 0x%08x on a reset-read / write / readback / restore "
            "cycle; ISOLATE_REQ_REG additionally drove isolate_req_o 0x%x -> "
            "0x%x -> 0x%x, so the CSR-to-pin path is checked and not just the "
            "storage. Every RESET_UNIT register outside this set is named in "
            "the module header with the criterion that excludes it",
            len(_SS_SWEEP_REGS),
            _SS_PATTERN,
            pin_idle,
            pin_set,
            pin_clr,
        )

    async def _await_warm_cleared(self, dut, label: str) -> int:
        last = None
        for _ in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_WARM", SCRATCH_COLD_WARM_0)
            if last == 0:
                return last
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(f"{label}: COLD_WARM last=0x{last:x} want=0 after {_CSR_BOUND} polls")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert int(dut.tb_sep_wdt_reset_n.value) == 1, "SEP WDT reset must idle high"

        await self.csr_write("SCRATCH_COLD_0", SCRATCH_COLD_0, COLD_PAT)
        await self.csr_write("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, WARM_PAT)
        got_c = await self.csr_read("SCRATCH_COLD_0_PRE", SCRATCH_COLD_0, expected=COLD_PAT)
        got_w = await self.csr_read(
            "SCRATCH_COLD_WARM_0_PRE", SCRATCH_COLD_WARM_0, expected=WARM_PAT
        )
        cocotb.log.info(
            "CHK-RESET-UNIT-PRE: COLD=0x%x COLD_WARM=0x%x before SEP WDT pulse",
            got_c,
            got_w,
        )

        dut.tb_sep_wdt_reset_n.value = 0
        for _ in range(_WDT_PULSE):
            await RisingEdge(dut.clk_smc_i)
        dut.tb_sep_wdt_reset_n.value = 1

        got_w = await self._await_warm_cleared(dut, "POST")
        got_c = await self.csr_read("SCRATCH_COLD_0_POST", SCRATCH_COLD_0, expected=COLD_PAT)
        cocotb.log.info(
            "CHK-RESET-UNIT-WDT: COLD stayed 0x%x COLD_WARM cleared to 0x%x",
            got_c,
            got_w,
        )
        await self._ss_sweep(dut)
        # The two per-leg tokens above carry the evidence; the fail-capable legs
        # are `csr_read(expected=...)`, `_await_warm_cleared`'s expiry, and
        # `_ss_sweep`'s CSR-to-pin check on `tb_isolate_req_o`
        # ([NO-ALWAYS-PASS-CHECKER]).
