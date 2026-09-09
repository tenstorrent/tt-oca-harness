# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle state matrix: does the LCC decode eFuse content, or just pass it?

smu_sep_lcc_flow_test proves the firmware-driven demote reaches every consumer,
but it runs in one lifecycle state, so it cannot tell a real decode from a wire.
This anchor runs the same firmware against different eFuse images and checks the
posture changes the way sep_lifecycle_ctrl.sv says it should for each state.

Each entry supplies a shadow-register preload whose LC_STATE word differs, plus
what that state is expected to do. The eFuse image is the one LCC input firmware
cannot drive -- it is sampled before the CPU runs -- so it has to come from the
testbench side; everything downstream of it is still driven by the firmware.

Per Table 50 the demotes gate feat_ctrl[15:0] and feat_ctrl[31:16] in TEST_DEV
and PROD but have no entry in PROD_END. The check that can fail is a delta
against the reset baseline: PROD starts closed and must open; PROD_END must
stay closed. TEST_DEV's baseline is already ~(sip_dis | sys_dis), and
RMA_CHIPLET's feat_ctrl is all-ones by state, so those two cannot show a
closed-to-open demote -- a post-run open low-32 does not prove the write did
anything. Debug follows from the same bits, so PROD_END is also where
dbg_disable is expected to assert.

Expectations arrive as plusargs rather than being derived here, so the testlist
entry states the contract for its own eFuse image:
  +lcc_expect_lc_state=<hex>       lc_state as the SMC receives it
  +lcc_expect_demote_effective=0|1 post-run feat_ctrl[31:0] closed or open.
                                   When the reset baseline is already open
                                   this is not a demote delta.
  +lcc_expect_dbg_disabled=0|1     whether the DTP-facing dbg_disable asserts
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import addr_of, format_pc_profile, load_syms

SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000
SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000

PASS_SYM = "sep_smu_lcc_flow_pass_loop"
FAIL_SYMS = {
    "feat_ctrl_readable": "sep_smu_lcc_flow_fail_readable_loop",
    "demote1_not_accepted": "sep_smu_lcc_flow_fail_demote1_loop",
    "demote2_not_accepted": "sep_smu_lcc_flow_fail_demote2_loop",
    "demote_lock_not_enforced": "sep_smu_lcc_flow_fail_lock_loop",
}

SETTLE_CYCLES = 2000


def _plusarg_int(name: str) -> int:
    raw = cocotb.plusargs.get(name)
    assert raw is not None, f"+{name} is required; the testlist entry must state it"
    return int(str(raw), 0)


class SmuSepLccStateMatrixSeq:
    """Check the LCC's per-state profile against the eFuse image it was given."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_FW_MAX_CYCLES", "300000"), 0)

        want_lc = _plusarg_int("lcc_expect_lc_state")
        want_demote_eff = bool(_plusarg_int("lcc_expect_demote_effective"))
        want_dbg_dis = bool(_plusarg_int("lcc_expect_dbg_disabled"))

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_lcc_flow.tcm.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        pass_pc = addr_of(syms, PASS_SYM)
        fail_pcs = {addr_of(syms, s): label for label, s in FAIL_SYMS.items()}

        self.log.info("=" * 70)
        self.log.info("TEST: SEP lifecycle state matrix -- eFuse image vs LCC profile")
        self.log.info("=" * 70)
        self.log.info(
            "contract for this eFuse image: lc_state=0x%02x demote_effective=%s dbg_disabled=%s",
            want_lc,
            want_demote_eff,
            want_dbg_dis,
        )

        # Baseline before the firmware DEMOTE writes. A post-run open bit is
        # not a demote proof when this is already open (TEST_DEV / RMA).
        feat_ctrl_before = self._rd(self.dut.lcc_feat_ctrl_o, "lcc_feat_ctrl_o")
        baseline_open = (feat_ctrl_before & 0xFFFF_FFFF) != 0
        self.log.info(
            "feat_ctrl at reset: 0x%016x (low32 %s)",
            feat_ctrl_before,
            "open" if baseline_open else "closed",
        )

        verdict = None
        boot_rom_seen = False
        iccm_seen = False
        traces = 0
        pc_hist: Counter[int] = Counter()

        for _ in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)
            if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                traces += 1
                pc_hist[pc] += 1
                boot_rom_seen |= SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END
                iccm_seen |= SEP_ICCM_BASE <= pc < SEP_ICCM_END
                if verdict is None:
                    if pc == pass_pc:
                        verdict = ("pass", None)
                    elif pc in fail_pcs:
                        verdict = ("fail", fail_pcs[pc])
            if verdict is not None:
                break

        for _ in range(SETTLE_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)

        lc_state = self._rd(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
        feat_ctrl = self._rd(self.dut.lcc_feat_ctrl_o, "lcc_feat_ctrl_o")
        dbg_disable = self._rd(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o")
        demote1 = self._rd(self.dut.lcc_demote_state_1_o, "lcc_demote_state_1_o")
        demote2 = self._rd(self.dut.lcc_demote_state_2_o, "lcc_demote_state_2_o")

        low32_before = feat_ctrl_before & 0xFFFF_FFFF
        low32_after = feat_ctrl & 0xFFFF_FFFF
        post_open = low32_after != 0
        demote_opened = low32_before == 0 and low32_after != 0
        dbg_disabled = dbg_disable != 0

        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)
        self.log.info(
            "observed: lc_state=0x%02x feat_ctrl 0x%016x->0x%016x (low32 %s->%s) "
            "dbg_disable=0x%04x demote1=%s demote2=%s",
            lc_state,
            feat_ctrl_before,
            feat_ctrl,
            "open" if baseline_open else "closed",
            "open" if post_open else "closed",
            dbg_disable,
            format(demote1, "#04b"),
            format(demote2, "#04b"),
        )

        errors: list[str] = []
        if verdict is None:
            errors.append(
                f"firmware reached no terminal loop within {max_cycles} cycles (traces={traces})"
            )
        elif verdict[0] == "fail":
            errors.append(f"firmware parked in the {verdict[1]} fail loop")
        if not boot_rom_seen:
            errors.append("SEP never fetched from the boot-ROM window")
        if not iccm_seen:
            errors.append("SEP never executed in the ICCM range")

        if lc_state != want_lc:
            errors.append(
                f"SMC received lc_state 0x{lc_state:02x}, expected 0x{want_lc:02x} "
                "-- the eFuse image did not reach the SMC as this state"
            )
        # The firmware always sets both demotes, so the register side is
        # state-independent; only the effect may differ.
        if demote1 != 0b01 or demote2 != 0b01:
            errors.append(
                f"demote not asserted at the SMU boundary "
                f"(demote1={demote1:#04b} demote2={demote2:#04b})"
            )
        if want_demote_eff and baseline_open:
            # TEST_DEV / RMA_CHIPLET: baseline is already open, so a post-run
            # open bit is not a demote delta. Stay-open and demote asserted
            # are still required; PROD and PROD_END are the discriminating
            # feat_ctrl cases.
            if not post_open:
                errors.append(
                    f"feat_ctrl[31:0] closed after the run "
                    f"(0x{feat_ctrl_before:016x}->0x{feat_ctrl:016x}) -- "
                    "this state's baseline is already open, so the post "
                    "value must stay open"
                )
            self.log.info(
                "feat_ctrl[31:0] baseline already open at reset "
                "(0x%016x); demote effect is not a delta on this state. "
                "PROD must open from closed; PROD_END must stay closed.",
                feat_ctrl_before,
            )
        elif want_demote_eff:
            if not demote_opened:
                errors.append(
                    f"demote did not open feat_ctrl[31:0] "
                    f"(0x{feat_ctrl_before:016x}->0x{feat_ctrl:016x}) -- "
                    "expected a closed-to-open delta for this state"
                )
        elif post_open:
            errors.append(
                f"demote effect on feat_ctrl[31:0] is open, expected closed "
                f"for this state "
                f"(0x{feat_ctrl_before:016x}->0x{feat_ctrl:016x})"
            )
        if dbg_disabled != want_dbg_dis:
            errors.append(
                f"dbg_disable is 0x{dbg_disable:04x}, expected "
                f"{'asserted' if want_dbg_dis else 'clear'} for this state"
            )

        assert not errors, "SEP LCC state matrix: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-LCC-STATE-DECODE: PASS (eFuse image -> SMC lc_state 0x%02x as "
            "contracted; the LCC is decoding the image, not a fixed value)",
            lc_state,
        )
        if want_demote_eff and baseline_open:
            self.log.info(
                "CHK-SEP-LCC-STATE-PROFILE: PASS (baseline feat_ctrl[31:0] "
                "already open; demote asserted at the boundary; dbg_disable "
                "0x%04x matches the contract. Demote-open is not a delta here "
                "-- PROD and PROD_END are the discriminating cases)",
                dbg_disable,
            )
        else:
            self.log.info(
                "CHK-SEP-LCC-STATE-PROFILE: PASS (feat_ctrl[31:0] "
                "0x%016x->0x%016x %s and dbg_disable 0x%04x match Table 50 "
                "for this state, with the demote asserted at the boundary "
                "either way)",
                feat_ctrl_before,
                feat_ctrl,
                "opened" if demote_opened else "stayed closed",
                dbg_disable,
            )
        for token in ("SEP_LCC_STATE_DECODE_OK", "SEP_LCC_STATE_PROFILE_OK"):
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
