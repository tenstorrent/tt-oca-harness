# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""In TEST_DEV a demotion forces its debug group open over the disable vector, until cold reset.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc ("Per-LC-state feature control profile",
"In-Field Debug Demotion", "Programming and Locking", "Reset Behavior"),
hw/sys/sep/regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl (DEMOTE_1, DEMOTE_2).

The eFuse shadow image named by ``+sep_shadow_reg_preload`` holds TEST_DEV with SIP_DIS bits 2, 3
and 25 set and SYS_DIS clear. The demote registers are written over the SEP debug module's
system bus, reached through the DTP primary TAP and the SEP STAP.

S1, setup: the image is the leaf's own and ``sep_fuse_sense_done_o`` rises within its bound.
S2, baseline: ``lcc_feat_ctrl_o`` reads the SIP_DIS-restricted word; both demote lanes are recorded.
S3, setup: the SEP STAP is selected and the debug module comes out of reset.
S4, DEMOTE_1.demote: lane 1 moves off its recorded code, lane 2 holds.
S5, sample: bits 2 and 3 read 1, bit 25 stays 0.
S6, DEMOTE_1.lock: DEMOTE_1 reads back with demote and lock both set and the word is unchanged.
S7, DEMOTE_2.demote: lane 2 moves off its recorded code, lane 1 holds its post-lock code.
S8, sample: bit 25 reads 1, the word is all ones.
S9, chiplet cold reset: both lanes return to their recorded codes and the word to the baseline.
The absolute lane codes are measured and logged only.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMCONTROL_ADDR,
    DMCONTROL_DMACTIVE,
    DMI_OP_NOP,
    DMI_OP_READ,
    DMI_OP_WRITE,
    DMI_STATUS_OK,
    DMSTATUS_ADDR,
    DMSTATUS_VERSION_SPEC_0_13,
    SEP_TAP_IR_DMI,
    network_ir_scan,
    pack_dmi,
    unpack_dmi,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    _SEP_LIFECYCLE_CTRL_H,
    COLD_RESET_BOUND,
    COLD_RESET_HOLD,
    DEMOTE_1_ADDR,
    DEMOTE_2_ADDR,
    DEMOTE_BM,
    DMI_RETRIES,
    DMI_STATUS_BUSY,
    SBA_POLLS,
    SBCS_ADDR,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    smu_dtp_sep_dm_sba_test_seq,
)
from seq_lib.smu_jtag_helpers import DTP_IR_TAP_3DCR, make_smu_jtag_tap
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_ALL_ENABLED,
    LANE_ENABLED,
    ExportSpec,
    smu_lc_export_seq,
)

#: hw/sys/sep/regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl, DEMOTE.lock [1:1], woset.
DEMOTE_LOCK_BM = c_header_u32(_SEP_LIFECYCLE_CTRL_H, "SEP_LIFECYCLE_CTRL__DEMOTE__LOCK_bm")
#: Same RDL: demote [0:0] and lock [1:1] are readable write-one-to-set fields, so DEMOTE_1 reads
#: back with both set after the demote and lock writes.
DEMOTE_1_LOCKED = DEMOTE_BM | DEMOTE_LOCK_BM

IMAGE = "sep_efuse_shadow_lc_test_dev_dis_fuse_dbg.preload"

#: hw/sys/sep/doc/lifecycle_controller.adoc, "Disable vector bit table": SIP_DIS bit 2 restricts
#: SEP_FUSE_DBG, bit 3 SMC_FUSE_DBG and bit 25 the reserved DBG_2 bit; the image sets exactly these.
SIP_DIS_VECTOR = (1 << 2) | (1 << 3) | (1 << 25)
#: Same chapter: DBG_1 is feature-control bits [23:0] and DBG_2 is [47:24].
DBG_1_MASK = (1 << 24) - 1
DBG_2_MASK = ((1 << 48) - 1) & ~DBG_1_MASK
#: TEST_DEV with DEMOTE 0 / 0 and SYS_DIS 0: ~(SIP_DIS | SYS_DIS) in every group
#: (lifecycle_controller.adoc, "Per-LC-state feature control profile").
FEAT_CTRL_BASELINE = FEAT_CTRL_ALL_ENABLED & ~SIP_DIS_VECTOR
#: Same table, DEMOTE 1 / 0: DBG_1 is forced open (T), DBG_2 keeps the DIS restriction.
FEAT_CTRL_DEMOTE_1 = FEAT_CTRL_BASELINE | DBG_1_MASK
#: Same table, DEMOTE 1 / 1: DBG_1 and DBG_2 are both forced open.
FEAT_CTRL_DEMOTE_1_2 = FEAT_CTRL_DEMOTE_1 | DBG_2_MASK

LANE_BOUND_CYCLES = 4000
RESET_CLEAR_BOUND_CYCLES = COLD_RESET_BOUND
TAP_RESET_TCKS = 16
IDLE_TCKS = 8
ROW_MARKS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")

#: Bounded waits of the leaf, one record each; the sense-done wait runs at boot and after the reset.
WAIT_LABELS = (
    "sense_done",
    "sba_demote_1",
    "lane_1_demote",
    "sba_lock_1",
    "sba_read_demote_1",
    "sba_demote_2",
    "lane_2_demote",
    "reset_assert",
    "sense_done",
    "dmi_retries",
)


class smu_lc_demote_test_dev_test_seq(smu_dtp_sep_dm_sba_test_seq):
    """DEMOTE_1 and DEMOTE_2 over the SEP system bus in TEST_DEV, then a cold reset."""

    def __init__(self, test) -> None:
        super().__init__(test)
        spec = ExportSpec(
            state="TEST_DEV",
            tag="TEST-DEV",
            image=IMAGE,
            feat_ctrl=FEAT_CTRL_BASELINE,
            lane=LANE_ENABLED,
        )
        self.export = smu_lc_export_seq(test, spec)
        self.sb = test.env.scoreboard
        self.step_ts: dict[str, float] = {}
        self.dmi_retries_max = 0
        self.dmi_last = "no access"
        self.sba_label = "sba_write"

    def _rd(self, name: str) -> int:
        return self.export._rd(name)

    def _lanes(self) -> tuple[int, int]:
        return self._rd("lcc_demote_state_1_o"), self._rd("lcc_demote_state_2_o")

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    async def _dmi(self, jtag, addr: int, data: int, op: int) -> int:
        await self._dmi_scan(jtag, pack_dmi(addr, data, op=op))
        for retry in range(DMI_RETRIES):
            captured = await self._dmi_scan(jtag, pack_dmi(addr, 0, op=DMI_OP_NOP))
            _, value, status = unpack_dmi(captured)
            self.dmi_retries_max = max(self.dmi_retries_max, retry)
            self.dmi_last = f"op={op} addr=0x{addr:02x} status={status}"
            if status == DMI_STATUS_OK:
                return value
            if status != DMI_STATUS_BUSY:
                raise AssertionError(f"DMI {self.dmi_last}")
        raise AssertionError(f"DMI still busy after {DMI_RETRIES} retries, last {self.dmi_last}")

    async def _sba_wait(self, jtag, what: str) -> None:
        for poll in range(1, SBA_POLLS + 1):
            sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            last = f"{what} sbcs=0x{sbcs:08x}"
            if sbcs & SBCS_SBBUSY:
                continue
            sberror = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
            if sberror or (sbcs & SBCS_SBBUSYERROR):
                raise AssertionError(f"system-bus {last} sberror={sberror}")
            self.export._record(self.sba_label, SBA_POLLS, poll, "polls", last)
            return
        self.export._record(
            self.sba_label, SBA_POLLS, SBA_POLLS, "polls", f"{what} sbbusy set", expired=True
        )

    async def _demote_write(self, jtag, label: str, addr: int, value: int) -> None:
        self.sba_label = label
        await self._sba_write(jtag, addr, value)

    async def _lane_leaves(self, label: str, which: int, baseline: int) -> tuple[int, int]:
        clk = self.dut.clk_smu_i
        lanes = self._lanes()
        for cycle in range(1, LANE_BOUND_CYCLES + 1):
            last = f"lane1=0b{lanes[0]:02b} lane2=0b{lanes[1]:02b}"
            if lanes[which] != baseline:
                self.export._record(label, LANE_BOUND_CYCLES, cycle - 1, "cycles", last)
                return lanes
            await RisingEdge(clk)
            lanes = self._lanes()
        last = f"lane1=0b{lanes[0]:02b} lane2=0b{lanes[1]:02b}"
        self.export._record(
            label, LANE_BOUND_CYCLES, LANE_BOUND_CYCLES, "cycles", last, expired=True
        )
        return lanes

    async def _feat(self) -> int:
        await RisingEdge(self.dut.clk_smu_i)
        return self._rd("lcc_feat_ctrl_o")

    async def _bring_up(self) -> tuple[OcahJtagMasterSequence, int]:
        raw = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        jtag = OcahJtagMasterSequence(raw)
        self.jtag = jtag
        await jtag.reset_to_tlr()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(IDLE_TCKS):
            await jtag.step_tms(0)
        await self._select_sep_stap(jtag)
        ir_value, ir_width = network_ir_scan(DTP_IR_TAP_3DCR, SEP_TAP_IR_DMI)
        await jtag.shift_ir(ir_value, width=ir_width, back_to_rti=True)
        await self._dmi(jtag, DMCONTROL_ADDR, DMCONTROL_DMACTIVE, DMI_OP_WRITE)
        dmstatus = await self._dmi(jtag, DMSTATUS_ADDR, 0, DMI_OP_READ)
        return jtag, dmstatus & 0xF

    async def _cold_reset(self) -> None:
        dut = self.dut
        record = self.export._record
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        last = "no sample"
        for cycle in range(1, RESET_CLEAR_BOUND_CYCLES + 1):
            await RisingEdge(dut.clk_ref_i)
            done = self._rd("sep_fuse_sense_done_o")
            rst_n = self._rd("obs_sep_rst_n_o")
            last = f"sep_fuse_sense_done_o={done} obs_sep_rst_n_o={rst_n}"
            if done == 0 and rst_n == 0:
                record("reset_assert", RESET_CLEAR_BOUND_CYCLES, cycle, "clk_ref_i cycles", last)
                break
        else:
            record(
                "reset_assert",
                RESET_CLEAR_BOUND_CYCLES,
                RESET_CLEAR_BOUND_CYCLES,
                "clk_ref_i cycles",
                last,
                expired=True,
            )
        await ClockCycles(dut.clk_ref_i, COLD_RESET_HOLD)
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.test.jtag_tap_reset(TAP_RESET_TCKS)

    async def run(self) -> None:
        export = self.export
        check = export._check

        await self._mark(
            "S1", "SETUP: TEST_DEV image with SIP_DIS bits 2, 3, 25, wait for sense done"
        )
        await export._setup()

        await self._mark("S2", "BASELINE: sample lcc_feat_ctrl_o and both demote lanes")
        baseline = await self._feat()
        code_1, code_2 = self._lanes()
        self._log(
            f"OBSERVATION baseline demote codes lane1=0b{code_1:02b} lane2=0b{code_2:02b} "
            "(measured and logged only)"
        )

        await self._mark("S3", "SETUP: SEP STAP select and debug module out of reset")
        jtag, dm_version = await self._bring_up()
        self._log(f"OBSERVATION dmstatus.version={dm_version}")

        await self._mark("S4", "write DEMOTE_1.demote over the SEP system bus")
        await self._demote_write(jtag, "sba_demote_1", DEMOTE_1_ADDR, DEMOTE_BM)
        lane_1, lane_2 = await self._lane_leaves("lane_1_demote", 0, code_1)
        check(
            "CHK-LC-DEMOTE-REACH-1-TEST-DEV",
            f"DEMOTE_1.demote written, lane1=0b{lane_1:02b} baseline=0b{code_1:02b} "
            f"lane2=0b{lane_2:02b} baseline=0b{code_2:02b} "
            f"dmstatus.version={dm_version} (absolute codes measured and logged only)",
            (lane_1 != code_1, lane_2 == code_2, dm_version),
            (True, True, DMSTATUS_VERSION_SPEC_0_13),
        )

        await self._mark("S5", "sample lcc_feat_ctrl_o after DEMOTE_1.demote")
        demoted_1 = await self._feat()
        check(
            "CHK-LC-DEMOTE-FORCES-DBG1-TEST-DEV",
            f"baseline=0x{baseline:016x} after DEMOTE_1.demote=0x{demoted_1:016x} "
            f"want=(0x{FEAT_CTRL_BASELINE:016x}, 0x{FEAT_CTRL_DEMOTE_1:016x})",
            (baseline, demoted_1),
            (FEAT_CTRL_BASELINE, FEAT_CTRL_DEMOTE_1),
        )

        await self._mark("S6", "write DEMOTE_1.lock over the SEP system bus")
        await self._demote_write(jtag, "sba_lock_1", DEMOTE_1_ADDR, DEMOTE_LOCK_BM)
        self.sba_label = "sba_read_demote_1"
        demote_1 = await self._sba_read64(jtag, DEMOTE_1_ADDR)
        locked = await self._feat()
        locked_1, _ = self._lanes()
        self._log(f"OBSERVATION post-lock lane1=0b{locked_1:02b} (measured and logged only)")
        check(
            "CHK-LC-DEMOTE-LOCK-PERSIST-TEST-DEV",
            f"after DEMOTE_1.lock DEMOTE_1=0x{demote_1:x} want=0x{DEMOTE_1_LOCKED:x}, "
            f"lcc_feat_ctrl_o=0x{locked:016x} want=0x{FEAT_CTRL_DEMOTE_1:016x}",
            (demote_1, locked),
            (DEMOTE_1_LOCKED, FEAT_CTRL_DEMOTE_1),
        )

        await self._mark("S7", "write DEMOTE_2.demote over the SEP system bus")
        await self._demote_write(jtag, "sba_demote_2", DEMOTE_2_ADDR, DEMOTE_BM)
        lane_1, lane_2 = await self._lane_leaves("lane_2_demote", 1, code_2)
        check(
            "CHK-LC-DEMOTE-REACH-2-TEST-DEV",
            f"DEMOTE_2.demote written, lane2=0b{lane_2:02b} baseline=0b{code_2:02b} "
            f"lane1=0b{lane_1:02b} post-lock=0b{locked_1:02b} (absolute codes measured and "
            "logged only)",
            (lane_2 != code_2, lane_1 == locked_1),
            (True, True),
        )

        await self._mark("S8", "sample lcc_feat_ctrl_o after DEMOTE_2.demote")
        demoted_2 = await self._feat()
        check(
            "CHK-LC-DEMOTE-FORCES-DBG2-TEST-DEV",
            f"after DEMOTE_2.demote lcc_feat_ctrl_o=0x{demoted_2:016x} "
            f"want=0x{FEAT_CTRL_DEMOTE_1_2:016x}",
            demoted_2,
            FEAT_CTRL_DEMOTE_1_2,
        )

        await self._mark("S9", "chiplet cold reset with the image unchanged, wait for sense done")
        pre_1, pre_2 = self._lanes()
        await self._cold_reset()
        await export._setup()
        cleared = await self._feat()
        done = self._rd("sep_fuse_sense_done_o")
        after_1, after_2 = self._lanes()
        check(
            "CHK-LC-DEMOTE-COLDCLEAR-CODES-TEST-DEV",
            f"after cold reset lane1=0b{after_1:02b} baseline=0b{code_1:02b} "
            f"lane2=0b{after_2:02b} baseline=0b{code_2:02b}; before reset "
            f"lane1=0b{pre_1:02b} lane2=0b{pre_2:02b}",
            (after_1, after_2, pre_1 != code_1, pre_2 != code_2),
            (code_1, code_2, True, True),
        )
        check(
            "CHK-LC-DEMOTE-COLDCLEAR-FEATCTRL-TEST-DEV",
            f"after cold reset lcc_feat_ctrl_o=0x{cleared:016x} sense_done={done} "
            f"want=0x{FEAT_CTRL_BASELINE:016x} before reset=0x{demoted_2:016x}",
            (cleared, done, demoted_2),
            (FEAT_CTRL_BASELINE, 1, FEAT_CTRL_DEMOTE_1_2),
        )

        await self._finish()

    async def _finish(self) -> None:
        """Report every bounded wait, then stamp the ordered step fence."""
        export = self.export
        clk = self.dut.clk_smu_i
        await self._mark("S10", "TIMEOUT: bounded waits and last state")
        await RisingEdge(clk)
        export._record("dmi_retries", DMI_RETRIES, self.dmi_retries_max, "retries", self.dmi_last)
        for rec in export.records:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(1 for rec in export.records if rec["expired"])
        self._log(f"CHK-TIMEOUT-PATHS: records={len(export.records)} expired={expired}")
        sb = self.sb
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait labels named by the steps",
            sorted(rec["label"] for rec in export.records),
            sorted(WAIT_LABELS),
            evidence="CHK-TIMEOUT-PATHS",
        )
        sb.expect_eq(
            "every record has a finite bound and a last-state diagnostic",
            all(0 < rec["bound"] < 10**9 and rec["last"] for rec in export.records),
            True,
            evidence="CHK-TIMEOUT-PATHS",
        )

        await ClockCycles(clk, 2)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*ROW_MARKS, "PASS"]
        stamps = [self.step_ts[k] for k in order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        text = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        self._log(f"CHK-NONVAC: ordered fence {'<'.join(order)} {text}")
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            all(d > 0 for d in deltas),
            True,
            evidence="CHK-NONVAC",
        )
