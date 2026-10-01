# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP BSR EXTEST/SAMPLE_PRELOAD instruction-gated .select.

S1: Idle RTI ``tb_bsr_select`` low, then IDCODE IR+DR with live TCK while BSR
    select-high TCK count stays 0 (instruction gate, not TCK fanout).
S2: EXTEST IR+DR: BSR select-high TCK count equals TAP DR-state width.
S3: SAMPLE_PRELOAD IR+DR after TLR: same BSR select bar. TDO bits are not compared.

``jtag_bsr_host_scan_ctrl_o.select`` is TAP-state AND instruction-gated and is
low in RTI, so samples must run *during* the scan, not after ``back_to_rti``.
Distinct from ``smu_dtp_bsr_extest_loopback_test`` (TDO loopback).
Not claimed: pad BSR I/O, DFD/iJTAG SIB open, TDO payload match.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_BSR_MODEL_LEN,
    DTP_DEFAULT_IDCODE,
    DTP_IR_EXTEST,
    DTP_IR_IDCODE,
    DTP_IR_SAMPLE_PRELOAD,
    DTP_IR_WIDTH,
    make_smu_jtag_tap,
)

IDCODE_DR_WIDTH = 32
MIN_UNSEL_TCK = DTP_IR_WIDTH + IDCODE_DR_WIDTH
# shift_dr(N, back_to_rti): Select-DR + Capture-DR + N Shift + Exit1-DR + Update-DR
EXPECTED_BSR_SEL_TCK = DTP_BSR_MODEL_LEN + 4


class smu_dtp_bsr_ijtag_scan_test_seq:
    """Prove BSR_ENABLE-qualified .select during EXTEST / SAMPLE_PRELOAD."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _count_select(self, acc: dict[str, int]) -> None:
        """Count TCK rises, and the BSR-selected subset, on TCK itself.

        Sampling jtag_tck on clk_ref_i aliases at the clock ratios in play:
        SmuEnvCfg.randomize_timing draws jtag_period_ns from (32, 40, 48)
        against the 10 ns reference clock, which leaves few ref samples inside
        a TCK high phase, so whole pulses can go uncounted. Waiting on the TCK
        edge is exact and independent of both periods.

        `.select` is driven off the TAP state machine, so it is sampled in the
        read-only region after the edge: the value that qualifies this TCK is
        the settled one, not whatever is mid-update at the edge itself.
        """
        while True:
            await RisingEdge(self.dut.jtag_tck)
            await ReadOnly()
            acc["tck_n"] += 1
            if self._sample_bit("tb_bsr_select"):
                acc["bsr_tcks"] += 1

    async def _scan_and_observe(
        self, jtag: OcahJtagMasterSequence, ir: int, dr_val: int, dr_width: int
    ) -> dict[str, int]:
        acc = {"tck_n": 0, "bsr_tcks": 0}
        mon = cocotb.start_soon(self._count_select(acc))
        await jtag.shift_ir(ir, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(dr_val, dr_width, back_to_rti=True)
        mon.cancel()
        return acc

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        raw = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        jtag = OcahJtagMasterSequence(raw)
        await jtag.reset_to_tlr()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await raw.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-DTP-BSR-IJTAG-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        idle_bsr = self._sample_bit("tb_bsr_select")
        if idle_bsr:
            raise AssertionError(f"idle RTI BSR select not gated bsr={idle_bsr}")
        sb.expect_eq("CHK-DTP-BSR-IDLE-SELECT", idle_bsr, 0)
        self._log(f"CHK-DTP-BSR-IDLE-SELECT bsr={idle_bsr}")

        unsel = await self._scan_and_observe(jtag, DTP_IR_IDCODE, 0, IDCODE_DR_WIDTH)
        if unsel["tck_n"] < MIN_UNSEL_TCK:
            raise AssertionError(
                f"IDCODE TCK count {unsel['tck_n']} < {MIN_UNSEL_TCK} "
                "(unselected BSR bar would be vacuous)"
            )
        if unsel["bsr_tcks"] != 0:
            raise AssertionError(
                f"IDCODE must not assert BSR select "
                f"bsr_tcks={unsel['bsr_tcks']} tck_n={unsel['tck_n']}"
            )
        self.s1_ok = True
        self._log(f"CHK-DTP-BSR-UNSEL-IDCODE tck_n={unsel['tck_n']} bsr_tcks={unsel['bsr_tcks']}")
        sb.expect_eq("CHK-DTP-BSR-UNSEL-IDCODE", unsel["bsr_tcks"], 0)

        extest = await self._scan_and_observe(jtag, DTP_IR_EXTEST, 0xA5, DTP_BSR_MODEL_LEN)
        if extest["bsr_tcks"] != EXPECTED_BSR_SEL_TCK:
            raise AssertionError(
                f"EXTEST bsr_tcks={extest['bsr_tcks']} want {EXPECTED_BSR_SEL_TCK} "
                f"(tck_n={extest['tck_n']} unsel_bsr={unsel['bsr_tcks']})"
            )
        if extest["tck_n"] <= extest["bsr_tcks"]:
            raise AssertionError(
                f"EXTEST TCK must also cover IR (select low): "
                f"tck_n={extest['tck_n']} bsr_tcks={extest['bsr_tcks']}"
            )
        self.s2_ok = True
        self._log(
            f"CHK-DTP-BSR-EXTEST-SELECT tck_n={extest['tck_n']} "
            f"bsr_tcks={extest['bsr_tcks']} want={EXPECTED_BSR_SEL_TCK}"
        )
        sb.expect_eq(
            "CHK-DTP-BSR-EXTEST-SELECT",
            extest["bsr_tcks"],
            EXPECTED_BSR_SEL_TCK,
            evidence="CHK-DTP-BSR-EXTEST-SELECT",
        )

        # TLR so SAMPLE_PRELOAD IR does not inherit EXTEST decode on Select-DR/IR.
        await jtag.reset_to_tlr()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)

        sample = await self._scan_and_observe(jtag, DTP_IR_SAMPLE_PRELOAD, 0x5A, DTP_BSR_MODEL_LEN)
        if sample["bsr_tcks"] != EXPECTED_BSR_SEL_TCK:
            raise AssertionError(
                f"SAMPLE_PRELOAD bsr_tcks={sample['bsr_tcks']} "
                f"want {EXPECTED_BSR_SEL_TCK} tck_n={sample['tck_n']}"
            )
        self.s3_ok = True
        self._log(
            f"CHK-DTP-BSR-SAMPLE-PRELOAD-SELECT tck_n={sample['tck_n']} "
            f"bsr_tcks={sample['bsr_tcks']} want={EXPECTED_BSR_SEL_TCK}"
        )
        sb.expect_eq(
            "CHK-DTP-BSR-SAMPLE-PRELOAD-SELECT",
            sample["bsr_tcks"],
            EXPECTED_BSR_SEL_TCK,
        )

        self._log(
            f"PASS DTP-BSR-IJTAG s1={self.s1_ok} s2={self.s2_ok} s3={self.s3_ok} "
            f"unsel={unsel['bsr_tcks']} extest={extest['bsr_tcks']} "
            f"sample={sample['bsr_tcks']}"
        )
