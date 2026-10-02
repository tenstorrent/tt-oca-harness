# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_dtp_scan_chain_boundary_test. SEP=1 wrapper, no Force.

The three iJTAG SIB hosts and the secondary-TAP hosts leave the wrapper as
scan_out/TDO and come back as scan_in/TDI. The DTP port table ties an unused
chain's scan_in to its scan_out; the bench closes each loop the same way, so
the shift path under test runs through the boundary pins.

Expected behaviour comes from the JTAG specification pages:

* ``hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc`` "iJTAG Network": three
  cascaded Segment Insertion Bits, listed DFT secure, DFT non-secure, DFD;
  the scan-chain figure draws them TDI first in that order.
* ``hw/ip/jtag/jtag_ptap/doc/architecture.adoc`` "Scan Path", "TDO Retiming"
  and "iJTAG Support": a TDR is selected only while its instruction is
  active, SELECT_IJTAG (and RUNBIST) select the iJTAG network, and TDO is
  retimed on the falling edge of TCK as IEEE 1149.1 Section 4.5.2 requires.
* ``hw/ip/jtag/jtag_stap/doc/architecture.adoc`` "STAP Module" and "3DCR
  Register": ``host_tdo_oen_o`` and ``host_tap_ctrl_o`` derive from
  ``stap_sel`` and the TAP controls; an unselected STAP parks its host TMS at
  TMS-Hold and a selected one follows the PTAP TMS.
* ``hw/sys/dtp/doc/jtag.adoc`` "STAP Secondary Scan Path" and the Integrator
  Guide's "STAP Scan Chain Topology" for the STAP order
  (``smu_boundary_regs.SMU_SEP_STAP_ORDER``).

S1  Instruction gating. The iJTAG network is selected only by SELECT_IJTAG
    or RUNBIST, and an IEEE 1687 SIB includes its host segment only while it
    is open. Under SELECT_IJTAG all three SIBs are opened, and a scan with
    them open has to assert every host select (the positive control) and
    read the three enables back. IDCODE is then loaded, and from the
    Update-IR that loads it, over an IDCODE DR scan and the IR scan of a
    second IDCODE load, none of the three selects may assert. Back under
    SELECT_IJTAG the SIBs still read back open, so they were open through the
    IDCODE scan, and that scan's Update-DR closes them for S2.

S2  Chain length. Each SIB is one scan cell and the closed loops add none,
    so the DR is IJTAG_SIB_COUNT cells long and TDO bit i is the bit shifted
    in i - SIB_DELAY back. IEEE 1149.1 gives a DR of N cells N TCKs of shift
    latency; the falling-edge retimer moves TDO within the bit period and is
    not a cell.

S3  SIB round trip. The last IJTAG_SIB_COUNT bits shifted in land in the
    chain, Update-DR latches them as the SIB enables, and the next Capture-DR
    reads them back, nearest-TDO SIB first -- so the readback names which SIB
    was opened, and the matching host select asserts while that scan runs.
    Each of the three is opened alone and then all three together, which is
    also what separates the three boundary pin pairs from one another.

S4  Secondary-TAP select. An unselected STAP drives no host TDO enable and
    parks its host TMS at TMS-Hold (0 after Test-Logic-Reset). Selecting the
    I/O STAP over TAP_3DCR has to raise its TDO enable for exactly the
    Shift-IR and Shift-DR TCKs of a scan (IEEE 1149.1 Section 4.5.1 drives
    TDO only while shifting; IEEE 1838 runs the STAP through both scans) and
    make its host TMS follow the primary TAP, while the extra STAP next to it
    stays quiet -- that is what puts ``jtag_stap_io_host_tdi_i`` in the live
    chain.

S5  The extra STAP host, selected the same way (run before S4). The extra
    STAP sits beside the I/O STAP in the SEP=1 chain and shares its select
    rules: unselected it parks its host TMS at TMS-Hold and drives no TDO
    enable; selected over TAP_3DCR its enable covers exactly the IR+DR TCKs
    of a scan and its host TMS follows the primary TAP on every TCK, while
    the I/O STAP stays quiet. The selection is written with Config-Hold clear
    in both the PTAP and the STAP 3DCR, so the Test-Logic-Reset S4 starts
    from returns the chain to its reset state (``jtag_stap`` page, "3DCR
    Register", Config-Hold), which S4's own idle and "extra STAP stays
    unselected" checks then read.

Every checked DR shift also requires the PTAP TDO to be resolved on each
TCK on which ``jtag_tdo_oen`` drives it, and the number of driven TCKs to
cover the shift: the JTAG VIP maps an X or Z TDO to 0, so a readback that
expects a 0 could not otherwise fail on an X.

Where the pages stop short -- the TDI-to-TDO direction of the SIB cascade,
the ``jtag_scan_ctrl_t.select`` definition and the TAP states that assert
``host_tdo_oen_o`` -- the expectation is the DV-owned rule above and the
plan card records the gap.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_boundary_regs import (
    SMU_SEP_STAP_ORDER,
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_IDCODE,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    PTAP_3DCR_WIDTH,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    ptap_3dcr_value,
    require_jtag_tdo_resolved,
)

DTP_IR_SELECT_IJTAG = dtp_ir_opcode("SELECT_IJTAG")

# TDI-first SIB cascade of the JIU architecture page "iJTAG Network": DFT
# secure, DFT non-secure, DFD. LSB-first, so the first bit shifted in reaches
# the last SIB.
IJTAG_SIB_ORDER = ("dft_secure", "dft", "dfd")
IJTAG_SIB_COUNT = len(IJTAG_SIB_ORDER)
IJTAG_SELECT_PIN = {
    "dft_secure": "tb_dft_secure_select",
    "dft": "tb_dft_select",
    "dfd": "tb_dfd_select",
}
# One scan cell per SIB and none in the closed loops; the IEEE 1149.1
# falling-edge TDO retimer (PTAP architecture page "TDO Retiming") moves TDO
# within the bit period and is not a cell.
SIB_DELAY = IJTAG_SIB_COUNT
DR_LEN = 12
DR_MASK = (1 << DR_LEN) - 1
PAYLOAD_LEN = DR_LEN - SIB_DELAY
PAYLOAD_MASK = (1 << PAYLOAD_LEN) - 1
# Directed payloads, all nonzero: the JTAG VIP maps an X/Z TDO to 0, so an
# all-zero expectation could not fail.
PAYLOADS = (0xFF, 0x55, 0xAA, 0x01, 0x80)

IDCODE_DR_WIDTH = 32
STAP_OBSERVE_CYCLES = 2000
# Every SIB open: the last IJTAG_SIB_COUNT bits of a DR shift land in the
# SIBs, the last of all in the SIB nearest TDI.
SIB_ALL_OPEN = ((1 << IJTAG_SIB_COUNT) - 1) << (DR_LEN - IJTAG_SIB_COUNT)
SIB_ALL_READBACK = (1 << IJTAG_SIB_COUNT) - 1

# Shift-IR plus Shift-DR TCKs of one IDCODE scan: IEEE 1149.1 Section 4.5.1
# drives TDO only while shifting, and the STAP runs through both scans.
EXPECTED_STAP_OEN_TCKS = DTP_IR_WIDTH + IDCODE_DR_WIDTH


class smu_dtp_scan_chain_boundary_seq:
    """iJTAG SIB chain and secondary-TAP select, closed through the pads."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _watch_tdo(self) -> None:
        """Count, per checked shift, the TCKs on which the PTAP drives TDO and the X/Z ones."""
        prev_tck = self._bit("jtag_tck")
        while True:
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._bit("jtag_tck")
            if tck == 1 and prev_tck == 0 and self._bit("jtag_tdo_oen"):
                self.tdo_driven += 1
                if not self.dut.jtag_tdo.value.is_resolvable:
                    self.tdo_unresolved += 1
            prev_tck = tck

    async def _checked_shift_dr(self, word: int, width: int, label: str) -> int:
        """A DR shift whose TDO is resolved on every driven TCK, ``width`` of them at least."""
        self.tdo_driven = 0
        self.tdo_unresolved = 0
        captured = await self.jtag.shift_dr(word, width, back_to_rti=True)
        require_jtag_tdo_resolved(label)
        if self.tdo_unresolved or self.tdo_driven < width:
            raise AssertionError(
                f"TDO during {label}: {self.tdo_unresolved} X/Z TCKs of "
                f"{self.tdo_driven} driven, {width} shifted"
            )
        return int(captured)

    async def _count_selected_tcks(self, cycles: int, pins: tuple[str, ...]) -> dict[str, int]:
        """TCK rising edges seen, and how many of them each pin was high for.

        Counted on jtag_tck, not on a design clock: the randomized clock
        periods alias a sampler running on clk_ref_i.
        """
        counts = {name: 0 for name in pins}
        counts["tck_n"] = 0
        prev_tck = self._bit("jtag_tck")
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._bit("jtag_tck")
            if tck == 1 and prev_tck == 0:
                counts["tck_n"] += 1
                for name in pins:
                    counts[name] += self._bit(name)
            prev_tck = tck
        return counts

    async def run(self) -> None:
        dut = self.dut
        await self.cfg.reset_done.wait()
        raw = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        self.jtag = OcahJtagMasterSequence(raw)
        await self.jtag.reset_to_tlr()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await ClockCycles(dut.clk_smu_i, 8)
        await self.jtag.shift_ir(DTP_IR_IDCODE)
        idcode = int(await self.jtag.shift_dr(0, IDCODE_DR_WIDTH, back_to_rti=True))
        require_jtag_tdo_resolved("IDCODE")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        self.tdo_driven = 0
        self.tdo_unresolved = 0
        cocotb.start_soon(self._watch_tdo())

        await self._ijtag_gating()
        await self._ijtag_chain_payload()
        await self._ijtag_sib_round_trip()
        await self._stap_select_extra()
        await self._stap_select()

    # ------------------------------------------------------------------
    # S1: the iJTAG hosts are gated by instruction, with every SIB open.
    # ------------------------------------------------------------------
    async def _ijtag_gating(self) -> None:
        pins = tuple(IJTAG_SELECT_PIN[name] for name in IJTAG_SIB_ORDER)
        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG)
        await self._checked_shift_dr(SIB_ALL_OPEN, DR_LEN, "iJTAG SIB open")

        watcher = cocotb.start_soon(self._count_selected_tcks(STAP_OBSERVE_CYCLES, pins))
        captured = await self._checked_shift_dr(SIB_ALL_OPEN, DR_LEN, "iJTAG SIB hold open")
        opened = await watcher
        self.sb.expect_eq(
            "Capture-DR reads all three SIBs open under SELECT_IJTAG",
            captured & SIB_ALL_READBACK,
            SIB_ALL_READBACK,
            evidence="CHK-SMU-IJTAG-GATE",
        )
        for name in IJTAG_SIB_ORDER:
            self.sb.expect_eq(
                f"{name} host select asserts for at least the {DR_LEN} shift TCKs "
                "of a SELECT_IJTAG scan with its SIB open",
                opened[IJTAG_SELECT_PIN[name]] >= DR_LEN,
                True,
                evidence="CHK-SMU-IJTAG-GATE",
            )

        # Counted from Update-IR of IDCODE on: the TCKs of the IR scan before it
        # still run under SELECT_IJTAG. A second IDCODE load puts an IR scan
        # under IDCODE in the window too.
        await self.jtag.shift_ir(DTP_IR_IDCODE)
        watcher = cocotb.start_soon(self._count_selected_tcks(2 * STAP_OBSERVE_CYCLES, pins))
        idcode = await self._checked_shift_dr(0, IDCODE_DR_WIDTH, "IDCODE with SIBs open")
        await self.jtag.shift_ir(DTP_IR_IDCODE)
        counts = await watcher
        self.sb.expect_eq(
            "IDCODE reads the configured value with the iJTAG SIBs open",
            idcode & ((1 << IDCODE_DR_WIDTH) - 1),
            DTP_DEFAULT_IDCODE,
            evidence="CHK-SMU-IJTAG-GATE",
        )
        if counts["tck_n"] < DTP_IR_WIDTH + IDCODE_DR_WIDTH:
            raise AssertionError(
                f"IDCODE scan produced only {counts['tck_n']} TCKs; the window is too short"
            )
        for name in IJTAG_SIB_ORDER:
            self.sb.expect_eq(
                f"{name} iJTAG host stays unselected under IDCODE with its SIB open "
                f"({counts['tck_n']} TCKs observed)",
                counts[IJTAG_SELECT_PIN[name]],
                0,
                evidence="CHK-SMU-IJTAG-GATE",
            )

        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG)
        captured = await self._checked_shift_dr(0, DR_LEN, "iJTAG SIB close")
        self.sb.expect_eq(
            "the SIBs are still open after the IDCODE scan",
            captured & SIB_ALL_READBACK,
            SIB_ALL_READBACK,
            evidence="CHK-SMU-IJTAG-GATE",
        )

    # ------------------------------------------------------------------
    # S2: the closed chain is IJTAG_SIB_COUNT scan cells long.
    # ------------------------------------------------------------------
    async def _ijtag_chain_payload(self) -> None:
        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG)
        seed = self.test.random_seed()
        rng = random.Random(seed ^ 0x1A5B)
        randoms: list[int] = []
        while len(randoms) < 3:
            drawn = rng.getrandbits(PAYLOAD_LEN) & PAYLOAD_MASK
            if drawn and drawn not in randoms and drawn not in PAYLOADS:
                randoms.append(drawn)
        self.log.info(
            "iJTAG payloads: directed=%s random=%s (RANDOM_SEED=%d)",
            [hex(p) for p in PAYLOADS],
            [hex(p) for p in randoms],
            seed,
        )
        for payload in (*PAYLOADS, *randoms):
            # The three MSBs are what Update-DR latches into the SIBs; hold
            # them clear here so this leg only measures the shift path and
            # S3 owns the SIB state.
            word = payload & PAYLOAD_MASK
            captured = await self._checked_shift_dr(word, DR_LEN, f"iJTAG DR payload 0x{payload:x}")
            expected = (word << SIB_DELAY) & DR_MASK
            if expected == 0:
                raise AssertionError("all-zero expectation forbidden (VIP maps X/Z TDO to 0)")
            self.sb.expect_eq(
                f"iJTAG DR returns payload 0x{payload:x} {SIB_DELAY} bits late",
                int(captured) & DR_MASK,
                expected,
                evidence="CHK-SMU-IJTAG-CHAIN",
            )

    # ------------------------------------------------------------------
    # S3: Update-DR latches the SIB enables and Capture-DR reads them back.
    # ------------------------------------------------------------------
    async def _ijtag_sib_round_trip(self) -> None:
        cases: list[tuple[str, tuple[str, ...]]] = [
            ("dfd alone", ("dfd",)),
            ("dft alone", ("dft",)),
            ("dft_secure alone", ("dft_secure",)),
            ("all three", IJTAG_SIB_ORDER),
            ("none", ()),
        ]
        pins = tuple(IJTAG_SELECT_PIN[name] for name in IJTAG_SIB_ORDER)
        for label, opened in cases:
            word = 0
            # LSB-first: the last IJTAG_SIB_COUNT bits shifted in stop in the
            # chain, the last one of all in the SIB nearest TDI.
            for idx, name in enumerate(IJTAG_SIB_ORDER):
                if name in opened:
                    word |= 1 << (DR_LEN - 1 - idx)
            await self.jtag.shift_dr(word, DR_LEN, back_to_rti=True)

            watcher = cocotb.start_soon(self._count_selected_tcks(STAP_OBSERVE_CYCLES, pins))
            captured = await self._checked_shift_dr(0, DR_LEN, f"iJTAG SIB capture ({label})")
            counts = await watcher

            # Capture-DR loads each SIB with its own enable; shifting out
            # LSB-first puts the SIB nearest TDO first.
            expected = 0
            for idx, name in enumerate(IJTAG_SIB_ORDER):
                if name in opened:
                    expected |= 1 << (IJTAG_SIB_COUNT - 1 - idx)
            self.sb.expect_eq(
                f"Capture-DR reads back the SIB enables ({label})",
                int(captured) & ((1 << IJTAG_SIB_COUNT) - 1),
                expected,
                evidence="CHK-SMU-IJTAG-SIB",
            )
            for name in IJTAG_SIB_ORDER:
                selected = counts[IJTAG_SELECT_PIN[name]]
                if name in opened:
                    self.sb.expect_eq(
                        f"{name} host select asserts while its SIB is open ({label})",
                        selected > 0,
                        True,
                        evidence="CHK-SMU-IJTAG-SIB",
                    )
                else:
                    self.sb.expect_eq(
                        f"{name} host select stays low while its SIB is shut ({label})",
                        selected,
                        0,
                        evidence="CHK-SMU-IJTAG-SIB",
                    )

    # ------------------------------------------------------------------
    # S4: the I/O STAP host, selected over TAP_3DCR.
    # ------------------------------------------------------------------
    async def _stap_select(self) -> None:
        await self.jtag.reset_to_tlr()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)

        idle = await self._observe_stap()
        self.sb.expect_eq(
            "the I/O STAP drives no TDO enable while it is unselected",
            idle["tb_stap_io_tdo_oen"],
            0,
            evidence="CHK-SMU-STAP-IO-SELECT",
        )
        self.sb.expect_eq(
            "unselected I/O STAP host TMS does not follow the primary TAP",
            idle["tms_mismatch"] > 0,
            True,
            evidence="CHK-SMU-STAP-IO-SELECT",
        )

        await self._select_stap("io")
        live = await self._observe_stap()
        self.sb.expect_eq(
            "the selected I/O STAP drives its TDO enable for the whole IR+DR scan",
            live["tb_stap_io_tdo_oen"],
            EXPECTED_STAP_OEN_TCKS,
            evidence="CHK-SMU-STAP-IO-SELECT",
        )
        self.sb.expect_eq(
            "the selected I/O STAP host TMS follows the primary TAP on every TCK",
            live["tms_mismatch"],
            0,
            evidence="CHK-SMU-STAP-IO-SELECT",
        )
        self.sb.expect_eq(
            "the extra STAP beside it stays unselected",
            live["tb_stap_extra0_tdo_oen"],
            0,
            evidence="CHK-SMU-STAP-IO-SELECT",
        )

    # ------------------------------------------------------------------
    # S5: the extra STAP host, selected over TAP_3DCR without Config-Hold.
    # ------------------------------------------------------------------
    async def _stap_select_extra(self) -> None:
        await self.jtag.reset_to_tlr()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)

        idle = await self._observe_stap("tb_stap_extra0_tms")
        self.sb.expect_eq(
            "the extra STAP drives no TDO enable while it is unselected",
            idle["tb_stap_extra0_tdo_oen"],
            0,
            evidence="CHK-SMU-STAP-EXTRA-SELECT",
        )
        self.sb.expect_eq(
            "unselected extra STAP host TMS does not follow the primary TAP",
            idle["tms_mismatch"] > 0,
            True,
            evidence="CHK-SMU-STAP-EXTRA-SELECT",
        )

        await self._select_stap("extra0", config_hold=0)
        live = await self._observe_stap("tb_stap_extra0_tms")
        self.sb.expect_eq(
            "the selected extra STAP drives its TDO enable for the whole IR+DR scan",
            live["tb_stap_extra0_tdo_oen"],
            EXPECTED_STAP_OEN_TCKS,
            evidence="CHK-SMU-STAP-EXTRA-SELECT",
        )
        self.sb.expect_eq(
            "the selected extra STAP host TMS follows the primary TAP on every TCK",
            live["tms_mismatch"],
            0,
            evidence="CHK-SMU-STAP-EXTRA-SELECT",
        )
        self.sb.expect_eq(
            "the I/O STAP beside it stays unselected",
            live["tb_stap_io_tdo_oen"],
            0,
            evidence="CHK-SMU-STAP-EXTRA-SELECT",
        )

    async def _select_stap(self, name: str, config_hold: int = 1) -> None:
        """TAP_3DCR select: PTAP select, then the SIB, then the STAP 3DCR.

        The three DR scans run under one TAP_3DCR load. The last one writes
        the STAP 3DCR and closes the SIB of ``name`` again, and a later IR
        load leaves the selection in place: S4 and S5 read it through the
        IR+DR scan of IDCODE. ``config_hold`` is written to the PTAP and the
        STAP 3DCR alike.
        """
        await self.jtag.shift_ir(DTP_IR_TAP_3DCR)
        await self.jtag.shift_dr(
            ptap_3dcr_value(config_hold=config_hold, select=1),
            PTAP_3DCR_WIDTH,
            back_to_rti=True,
        )
        await self.jtag.step_tms(0)
        await self.jtag.step_tms(0)
        sib_word, sib_width = ptap_prefixed(
            stap_sib_pattern(name, 1), len(SMU_SEP_STAP_ORDER), config_hold=config_hold
        )
        await self.jtag.shift_dr(sib_word, sib_width, back_to_rti=True)
        stap_word, stap_width = stap_3dcr_scan_word(
            name, config_hold=config_hold, stap_sel=1, tms_hold=1, sib_en=0
        )
        value, width = ptap_prefixed(stap_word, stap_width, config_hold=config_hold)
        await self.jtag.shift_dr(value, width, back_to_rti=True)

    async def _observe_stap(self, tms_pin: str = "tb_stap_io_tms") -> dict[str, int]:
        """One IDCODE IR+DR scan, watched at the two secondary-TAP hosts.

        ``tms_mismatch`` counts the TCKs on which ``tms_pin`` differs from the
        primary TAP's TMS.
        """
        pins = ("tb_stap_io_tdo_oen", "tb_stap_extra0_tdo_oen")
        watcher = cocotb.start_soon(self._watch_stap(STAP_OBSERVE_CYCLES, pins, tms_pin))
        await self.jtag.shift_ir(DTP_IR_IDCODE)
        await self.jtag.shift_dr(0, IDCODE_DR_WIDTH, back_to_rti=True)
        return await watcher

    async def _watch_stap(self, cycles: int, pins: tuple[str, ...], tms_pin: str) -> dict[str, int]:
        counts = {name: 0 for name in pins}
        counts["tck_n"] = 0
        counts["tms_mismatch"] = 0
        prev_tck = self._bit("jtag_tck")
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._bit("jtag_tck")
            if tck == 1 and prev_tck == 0:
                counts["tck_n"] += 1
                for name in pins:
                    counts[name] += self._bit(name)
                if self._bit(tms_pin) != self._bit("jtag_tms"):
                    counts["tms_mismatch"] += 1
            prev_tck = tck
        return counts
