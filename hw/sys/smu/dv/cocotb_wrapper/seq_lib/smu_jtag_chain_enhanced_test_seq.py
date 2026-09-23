# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PTAP IDCODE + BYPASS at 1/5/10/20 MHz TCK (SEP=1, no Force).

S1: TAP ready at the default period (IDCODE).
S2: For each programmed VIP TCK period, IDCODE matches the IEEE packing.
S3: At each period, BYPASS is a one-bit register (8-bit TDI, TDO is
    capture-0 then TDI delayed one bit).
S4: Completeness vs the independent required set (labels + programmed
    VIP ``tck_period_ns``). A missing ``FREQ_NS`` leg or a plusarg that
    pins every TAP to one period fails here.

Does not claim analog setup/hold vs silicon; FAIL-ON is wrong IDCODE,
BYPASS delay, missing required frequency, or VIP period not matching
the required nanosecond set.
Not claimed: Force feat_ctrl; JTAG2AXI.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_BYPASS,
    DTP_IR_WIDTH,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

# Independent required set: the loop source FREQ_NS may shrink; S4 must
# still demand these four programmed periods.
REQUIRED_FREQ_LABELS = ("1MHz", "5MHz", "10MHz", "20MHz")
REQUIRED_TCK_NS = (1000, 200, 100, 50)
FREQ_NS = (
    (1000, "1MHz"),
    (200, "5MHz"),
    (100, "10MHz"),
    (50, "20MHz"),
)
BYPASS_PATTERN = 0xA5
BYPASS_WIDTH = 8


class smu_jtag_chain_enhanced_test_seq:
    """IDCODE + BYPASS after VIP TCK period reprogram."""

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

    async def _idcode(self, jtag) -> int:
        idcode = await jtag.read_idcode()
        require_jtag_tdo_resolved("IDCODE")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:08x} got 0x{idcode:08x}")
        return idcode

    async def _bypass(self, jtag) -> int:
        await jtag.shift_ir(DTP_IR_BYPASS, width=DTP_IR_WIDTH, back_to_rti=False)
        captured = int(await jtag.shift_dr(BYPASS_PATTERN, BYPASS_WIDTH, back_to_rti=True))
        require_jtag_tdo_resolved("BYPASS")
        mask = (1 << BYPASS_WIDTH) - 1
        got = captured & mask
        want = (BYPASS_PATTERN << 1) & mask
        if got != want:
            raise AssertionError(
                f"BYPASS TDO mismatch tdi=0x{BYPASS_PATTERN:02x} tdo=0x{got:02x} want 0x{want:02x}"
            )
        return got

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        default = int(self.cfg.jtag_period_ns)
        jtag = make_smu_jtag_tap(self.dut, default)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        id0 = await self._idcode(jtag)
        self.s1_ok = True
        sb.expect_eq("CHK-JTAG-CHAIN-READY", id0, DTP_DEFAULT_IDCODE)

        id_obs: list[int] = []
        byp_obs: list[int] = []
        done: list[str] = []
        prog_ns: list[int] = []
        want_byp = (BYPASS_PATTERN << 1) & ((1 << BYPASS_WIDTH) - 1)
        for period_ns, label in FREQ_NS:
            jtag = make_smu_jtag_tap(self.dut, period_ns)
            programmed = int(jtag.get_statistics()["tck_period_ns"])
            if programmed != int(period_ns):
                raise AssertionError(
                    f"{label}: VIP tck_period_ns={programmed} want {period_ns} (plusarg pin?)"
                )
            await jtag.reset_tap()
            await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
            for _ in range(8):
                await jtag.step_tms(0)
            idc = await self._idcode(jtag)
            byp = await self._bypass(jtag)
            id_obs.append(idc)
            byp_obs.append(byp)
            done.append(label)
            prog_ns.append(programmed)
            self._log(
                f"CHK-JTAG-CHAIN-FREQ {label} tck={programmed}ns "
                f"idcode=0x{idc:08x} bypass=0x{byp:02x}"
            )

        expect_ids = [DTP_DEFAULT_IDCODE] * len(REQUIRED_FREQ_LABELS)
        expect_byp = [want_byp] * len(REQUIRED_FREQ_LABELS)
        if id_obs != expect_ids:
            raise AssertionError(f"IDCODE sweep got {id_obs} want {expect_ids}")
        self.s2_ok = True
        sb.expect_eq(
            "CHK-JTAG-IDCODE",
            tuple(id_obs),
            tuple(expect_ids),
            evidence="JTAG_IDCODE_OK",
        )
        if byp_obs != expect_byp:
            raise AssertionError(f"BYPASS sweep got {byp_obs} want {expect_byp}")
        self.s3_ok = True
        sb.expect_eq(
            "CHK-JTAG-BYPASS",
            tuple(byp_obs),
            tuple(expect_byp),
            evidence="JTAG_BYPASS_OK",
        )

        self.s4_ok = True
        sb.expect_eq(
            "CHK-JTAG-CHAIN-ENHANCED",
            (tuple(done), tuple(prog_ns)),
            (REQUIRED_FREQ_LABELS, REQUIRED_TCK_NS),
            evidence="JTAG_CHAIN_ENHANCED_OK",
        )

        self._log(
            f"PASS JTAG-CHAIN-ENHANCED s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} freqs={done}"
        )
