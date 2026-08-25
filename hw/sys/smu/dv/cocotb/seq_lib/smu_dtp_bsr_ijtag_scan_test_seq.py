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
from cocotb.triggers import RisingEdge
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
# Extra ref edges after the scan so the last TCK rise is not dropped.
_DRAIN_REF_CYCLES = 16


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

    async def _observe_select(self, stop: list[bool]) -> dict[str, int]:
        """TCK-sync BSR select-high counts; window tracks the concurrent scan."""
        prev_tck = self._sample_bit("jtag_tck")
        tck_n = 0
        bsr_tcks = 0

        async def _tick() -> None:
            nonlocal prev_tck, tck_n, bsr_tcks
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._sample_bit("jtag_tck")
            bsr = self._sample_bit("tb_bsr_select")
            if tck == 1 and prev_tck == 0:
                tck_n += 1
                if bsr:
                    bsr_tcks += 1
            prev_tck = tck

        while not stop[0]:
            await _tick()
        for _ in range(_DRAIN_REF_CYCLES):
            await _tick()
        return {"tck_n": tck_n, "bsr_tcks": bsr_tcks}

    async def _scan_and_observe(
        self, jtag: OcahJtagMasterSequence, ir: int, dr_val: int, dr_width: int
    ) -> dict[str, int]:
        stop = [False]
        mon = cocotb.start_soon(self._observe_select(stop))
        await jtag.shift_ir(ir, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(dr_val, dr_width, back_to_rti=True)
        stop[0] = True
        return await mon

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
            raise AssertionError(
                f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}"
            )
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
        self._log(
            f"CHK-DTP-BSR-UNSEL-IDCODE tck_n={unsel['tck_n']} "
            f"bsr_tcks={unsel['bsr_tcks']}"
        )
        sb.expect_eq("CHK-DTP-BSR-UNSEL-IDCODE", unsel["bsr_tcks"], 0)

        extest = await self._scan_and_observe(
            jtag, DTP_IR_EXTEST, 0xA5, DTP_BSR_MODEL_LEN
        )
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
        )

        # TLR so SAMPLE_PRELOAD IR does not inherit EXTEST decode on Select-DR/IR.
        await jtag.reset_to_tlr()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)

        sample = await self._scan_and_observe(
            jtag, DTP_IR_SAMPLE_PRELOAD, 0x5A, DTP_BSR_MODEL_LEN
        )
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
