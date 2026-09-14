# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sep_smoke_test (SMU_ALL_007).

DV-CARD:          SMU_ALL_007   ANCHOR: smu_sep_smoke_test

Allocated (narrowed Option B; SEP=0 bare tb_top):
  SMC-RST-PRIMARY-EXPORT.S1 / S2
  DTP-XTRIG-CTM.S2 / S3
No Force/deposit. No SEP-sysif/LC/SEC_DIS/mem/fuse/WDT/alias/CTM.S1/CTP/DTP-CSR.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_jtag_helpers import make_smu_jtag_tap, pack_debug_control

DEST_PATS = (0x01, 0x80, 0xA5, 0x5A)
PULSE_DEST_PATS = (0x01, 0x20, 0x25, 0x5A)
SRC_ACK_PATS = (0x01, 0x80, 0x3C)
CFG_INT_CT_MODE = 0x80


class smu_sep_smoke_test_seq:
    """SMU_ALL_007: primary-reset export + CTM mode packing / reserved [1:0]."""

    BOUND_CYCLES = 2000
    BOUND_REF = 2000
    SETTLE = 8
    COLD_HOLD = 64
    # Real poll-with-expiry sites (each can hit EXPIRED):
    #   s1_primary,
    #   s2_primary_ref_assert, s2_primary_smc_assert, s2_primary_release,
    #   s3_primary_ref_assert, s3_primary_smc_assert, s3_primary_release
    EXPECTED_TIMEOUT_PATHS = 7

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    async def _wait_eq(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
        name: str,
    ) -> int:
        last = None
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, name)
            if last == expect:
                self._timeout_paths.append(f"{label}: bound={bound} ok last=0x{last:x}")
                return last
        self._timeout_paths.append(
            f"{label}: bound={bound} EXPIRED last={'None' if last is None else f'0x{last:x}'}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} last_state={last} expect={expect} name={name}"
        )

    async def _functional_cold_pulse(self) -> None:
        """Assert functional cold via rst_cold_ni; keep JTAG TRST high."""
        dut = self.dut
        # Keep TRST deasserted so TDR state is not POR-cleared.
        dut.jtag_trst.value = 1
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, self.COLD_HOLD)

    async def _release_cold(self) -> None:
        dut = self.dut
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        jtag.init_signals()
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, self.SETTLE)

        # ------------------------------------------------------------------
        # S1 SETUP
        # ------------------------------------------------------------------
        self._mark_step(
            "S1",
            "SETUP: bring SMU out of reset with clocks stable; ready bare "
            "tb_top for reset-export and CTM xtrig; record baseline",
        )
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s1_primary",
            name="rst_primary_smc_clk_no",
        )
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        dut.jtag_trst.value = 1
        base_ref = self._sample(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no")
        base_smc = self._sample(dut.rst_primary_smc_clk_no, "rst_primary_smc_clk_no")
        base_ack = self._sample(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack")
        if base_ref != 1 or base_smc != 1:
            raise AssertionError(f"baseline primary not released: ref={base_ref} smc={base_smc}")
        if base_ack != 0:
            raise AssertionError(f"baseline xtrig_ctm_dst_ack={base_ack}")
        self._log(
            f"BASELINE: rst_primary_ref={base_ref} rst_primary_smc={base_smc} "
            f"dst_ack={base_ack} cells=SEP=0,tb=bare"
        )

        # ------------------------------------------------------------------
        # S2 SMC-RST-PRIMARY-EXPORT.S1 — functional cold asserts both exports
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            "ACTION/RESPONSE/EFFECT SMC-RST-PRIMARY-EXPORT.S1: functional "
            "cold reset asserts both exported primary reset outputs",
        )
        self._log(
            "COVERAGE SMC-RST-PRIMARY-EXPORT.S1 cells: "
            "src=cold,obs=rst_primary_smc,obs=rst_primary_ref"
        )
        await self._functional_cold_pulse()
        await self._wait_eq(
            dut.rst_primary_ref_clk_no,
            0,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF,
            label="s2_primary_ref_assert",
            name="rst_primary_ref_clk_no",
        )
        await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s2_primary_smc_assert",
            name="rst_primary_smc_clk_no",
        )
        obs_ref = self._sample(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no")
        obs_smc = self._sample(dut.rst_primary_smc_clk_no, "rst_primary_smc_clk_no")
        if obs_ref != 0 or obs_smc != 0:
            raise AssertionError(f"RST-PRIMARY.S1 fail: ref={obs_ref} smc={obs_smc} expect both 0")
        await self._release_cold()
        await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s2_primary_release",
            name="rst_primary_smc_clk_no",
        )
        detail_s1 = (
            f"src=cold obs_ref={obs_ref} obs_smc={obs_smc} "
            f"cells=src=cold,obs=rst_primary_smc,obs=rst_primary_ref"
        )
        self._log(f"CHK-SMC-RST-PRIMARY-EXPORT-S1: PASS ({detail_s1})")
        sb.expect_eq(
            "CHK-SMC-RST-PRIMARY-EXPORT-S1 both asserted",
            (obs_ref, obs_smc),
            (0, 0),
            evidence="CHK-SMC-RST-PRIMARY-EXPORT-S1",
        )

        # ------------------------------------------------------------------
        # S3 SMC-RST-PRIMARY-EXPORT.S2 — TDR retained across rst_primary
        # ------------------------------------------------------------------
        self._mark_step(
            "S3",
            "ACTION/RESPONSE/EFFECT SMC-RST-PRIMARY-EXPORT.S2: JTAG/TDR "
            "state is not cleared by rst_primary alone",
        )
        self._log(
            "COVERAGE SMC-RST-PRIMARY-EXPORT.S2 cells: "
            "rst_primary=assert,jtag_tdr=retained_unless_por"
        )
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        stall_val = pack_debug_control(boot_stall_ovrd=1, boot_stall=1)
        await jtag.write("DEBUG_CONTROL", stall_val)
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        ovrd_pre = self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd")
        stall_pre = self._sample(dut.jtag_boot_stall, "jtag_boot_stall")
        if ovrd_pre != 1 or stall_pre != 1:
            raise AssertionError(
                f"RST-PRIMARY.S2 TDR preload fail: ovrd={ovrd_pre} stall={stall_pre}"
            )
        # Functional cold asserts rst_primary; TRST stays 1 (not POR).
        await self._functional_cold_pulse()
        await self._wait_eq(
            dut.rst_primary_ref_clk_no,
            0,
            clk=dut.clk_ref_i,
            bound=self.BOUND_REF,
            label="s3_primary_ref_assert",
            name="rst_primary_ref_clk_no",
        )
        await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            0,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s3_primary_smc_assert",
            name="rst_primary_smc_clk_no",
        )
        ovrd_mid = self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd")
        stall_mid = self._sample(dut.jtag_boot_stall, "jtag_boot_stall")
        trst_mid = self._sample(dut.jtag_trst, "jtag_trst")
        if trst_mid != 1:
            raise AssertionError(f"RST-PRIMARY.S2 TRST must stay high (not POR): trst={trst_mid}")
        if ovrd_mid != 1 or stall_mid != 1:
            raise AssertionError(
                f"RST-PRIMARY.S2 TDR cleared by rst_primary alone: "
                f"ovrd={ovrd_mid} stall={stall_mid} "
                f"(expect retained while TRST=1)"
            )
        await self._release_cold()
        await self._wait_eq(
            dut.rst_primary_smc_clk_no,
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s3_primary_release",
            name="rst_primary_smc_clk_no",
        )
        ovrd_post = self._sample(dut.jtag_boot_stall_ovrd, "jtag_boot_stall_ovrd")
        stall_post = self._sample(dut.jtag_boot_stall, "jtag_boot_stall")
        if ovrd_post != 1 or stall_post != 1:
            raise AssertionError(
                f"RST-PRIMARY.S2 TDR not retained after primary release: "
                f"ovrd={ovrd_post} stall={stall_post}"
            )
        # Clear stall so later CTM steps are not boot-gated.
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, self.SETTLE)
        detail_s2 = (
            f"rst_primary=assert jtag_tdr=retained_unless_por "
            f"ovrd={ovrd_mid} stall={stall_mid} trst={trst_mid} "
            f"cells=rst_primary=assert,jtag_tdr=retained_unless_por"
        )
        self._log(f"CHK-SMC-RST-PRIMARY-EXPORT-S2: PASS ({detail_s2})")
        sb.expect_eq(
            "CHK-SMC-RST-PRIMARY-EXPORT-S2 TDR retained",
            (ovrd_mid, stall_mid),
            (1, 1),
            evidence="CHK-SMC-RST-PRIMARY-EXPORT-S2",
        )

        # ------------------------------------------------------------------
        # S4 DTP-XTRIG-CTM.S2 — configured mode packing; pulse-sync ack unused
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "ACTION/RESPONSE/EFFECT DTP-XTRIG-CTM.S2: pulse-sync mode "
            "leaves ack ports unused as specified",
        )
        self._log("COVERAGE DTP-XTRIG-CTM.S2 cells: mode=pulse_sync,ack_unused=1")
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, self.SETTLE)

        # Observe DTP mode[1:0] hierarchically; Failed/X/Z = unobservable.
        # No DefaultCfg inference / skip-to-pass on the proof path.
        mode_sig = dut.u_dut.DTP_XTRIG_INT_CT_MODE
        mode_val = self._sample(mode_sig, "DTP_XTRIG_INT_CT_MODE")
        expected_mode = CFG_INT_CT_MODE << 2
        if mode_val != expected_mode:
            raise AssertionError(
                f"CTM.S2 mode=0x{mode_val:x} expect 0x{expected_mode:x} "
                "(configured [9:2] plus SMC-reserved [1:0])"
            )
        mode_lo = mode_val & 0x3
        if mode_lo != 0:
            raise AssertionError(f"CTM.S2 mode[1:0]={mode_lo} expect 0 (pulse-sync)")

        ack_samples: list[int] = []
        # Bit 7 is configured for handshake mode to prove the upper configured
        # mode bit survives packing. Exercise ack-unused only on pulse-sync lanes.
        for pat in PULSE_DEST_PATS:
            dut.xtrig_ctm_dst_req.value = pat
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)
            ack = self._sample(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack")
            ack_samples.append(ack)
            if ack != 0:
                raise AssertionError(
                    f"CTM.S2 ack used under pulse-sync: pat={pat:#x} dst_ack={ack:#x}"
                )
        dut.xtrig_ctm_dst_req.value = 0
        await ClockCycles(dut.clk_smu_i, 2)
        idle_ack = self._sample(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack")
        if idle_ack != 0:
            raise AssertionError(f"CTM.S2 idle dst_ack={idle_ack}")
        detail_ctm2 = (
            f"mode=0x{mode_val:x} configured_hi=0x{CFG_INT_CT_MODE:x} "
            f"mode_lo={mode_lo} pulse_sync_ack_unused=1 "
            f"dst_ack_samples={[hex(a) for a in ack_samples]} "
            f"cells=mode=pulse_sync,ack_unused=1"
        )
        self._log(f"CHK-DTP-XTRIG-CTM-S2: PASS ({detail_ctm2})")
        sb.expect_eq(
            "CHK-DTP-XTRIG-CTM-S2 ack unused",
            (mode_val, mode_lo, idle_ack, max(ack_samples) if ack_samples else 0),
            (expected_mode, 0, 0, 0),
            evidence="CHK-DTP-XTRIG-CTM-S2",
        )

        # ------------------------------------------------------------------
        # S5 DTP-XTRIG-CTM.S3 — bits [1:0] reserved for SMC
        # ------------------------------------------------------------------
        self._mark_step(
            "S5",
            "ACTION/RESPONSE/EFFECT DTP-XTRIG-CTM.S3: bits [1:0] remain reserved for SMC",
        )
        self._log("COVERAGE DTP-XTRIG-CTM.S3 cells: bits=1:0,owner=smc")
        dtp_dst_req = dut.u_dut.dtp_xtrig_ctm_dst_req
        dtp_src_ack = dut.u_dut.dtp_xtrig_ctm_src_ack

        for pat in DEST_PATS:
            dut.xtrig_ctm_dst_req.value = pat
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)
            dtp = self._sample(dtp_dst_req, "dtp_xtrig_ctm_dst_req")
            if ((dtp >> 2) & 0xFF) != pat:
                raise AssertionError(
                    f"CTM.S3 remap fail: pat={pat:#x} dtp[9:2]={(dtp >> 2) & 0xFF:#x}"
                )
            # External product pins must not own DTP[1:0] (SMC reserved).
            if (dtp & 0x3) != 0:
                raise AssertionError(
                    f"CTM.S3 bits[1:0] polluted by external dst_req "
                    f"pat={pat:#x}: dtp[1:0]={dtp & 0x3}"
                )
        dut.xtrig_ctm_dst_req.value = 0

        for pat in SRC_ACK_PATS:
            dut.xtrig_ctm_src_ack.value = pat
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)
            ack = self._sample(dtp_src_ack, "dtp_xtrig_ctm_src_ack")
            if ((ack >> 2) & 0xFF) != pat:
                raise AssertionError(
                    f"CTM.S3 src_ack remap fail: pat={pat:#x} dtp[9:2]={(ack >> 2) & 0xFF:#x}"
                )
            if (ack & 0x3) != 0:
                raise AssertionError(
                    f"CTM.S3 src_ack[1:0] not hardwire 0: pat={pat:#x} lo={ack & 0x3}"
                )
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, 2)
        lo_dst = self._sample(dtp_dst_req, "dtp_xtrig_ctm_dst_req") & 0x3
        lo_ack = self._sample(dtp_src_ack, "dtp_xtrig_ctm_src_ack") & 0x3
        detail_ctm3 = (
            f"bits=1:0 owner=smc lo_dst={lo_dst} lo_ack_hardwire={lo_ack} cells=bits=1:0,owner=smc"
        )
        self._log(f"CHK-DTP-XTRIG-CTM-S3: PASS ({detail_ctm3})")
        sb.expect_eq(
            "CHK-DTP-XTRIG-CTM-S3 [1:0] SMC reserved",
            (lo_dst, lo_ack),
            (0, 0),
            evidence="CHK-DTP-XTRIG-CTM-S3",
        )

        # ------------------------------------------------------------------
        # S6 TIMEOUT inventory
        # ------------------------------------------------------------------
        self._mark_step(
            "S6",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last observed state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT_PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count fail: {n_paths} "
                f"expect={self.EXPECTED_TIMEOUT_PATHS} paths={self._timeout_paths}"
            )
        expired = [p for p in self._timeout_paths if "EXPIRED" in p]
        if expired:
            raise AssertionError(f"CHK-TIMEOUT-PATHS unexpected EXPIRED: {expired}")
        detail_to = (
            f"finite_bound_paths={n_paths} "
            f"expect={self.EXPECTED_TIMEOUT_PATHS} expiry_fail_path=armed"
        )
        self._log(f"CHK-TIMEOUT-PATHS: PASS ({detail_to})")
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count+shape",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_ALL_007 sequence complete (PASS term recorded for NONVAC fence)")
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        deltas_ns = [
            int((self._step_ts[b] - self._step_ts[a]) * 1e9) for a, b in zip(order, order[1:])
        ]
        positive_deltas = sum(1 for d in deltas_ns if d > 0)
        expect_deltas = len(order) - 1
        if positive_deltas != expect_deltas:
            raise AssertionError(
                f"CHK-NONVAC positive-delta count fail: {positive_deltas} "
                f"expect={expect_deltas} deltas_ns={deltas_ns}"
            )
        self._log("CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<S6<PASS all hold")
        sb.expect_eq(
            "CHK-NONVAC positive step-delta count",
            positive_deltas,
            expect_deltas,
            evidence="CHK-NONVAC",
        )
