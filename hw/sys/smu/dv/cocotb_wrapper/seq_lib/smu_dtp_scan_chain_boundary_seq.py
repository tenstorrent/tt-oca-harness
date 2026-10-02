# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_dtp_scan_chain_boundary_test. SEP=1 wrapper, no Force.

The three iJTAG SIB hosts and the secondary-TAP hosts leave the wrapper as
scan_out/TDO and come back as scan_in/TDI. The bench closes each iJTAG loop
through one bench scan cell and each STAP and the BSR loop with a bare net
(``tb/tb_wrapper_top.sv``), so the shift path under test runs through the
boundary pins.

Expected behaviour comes from the JTAG specification pages:

* ``hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc`` "iJTAG Network": three
  cascaded Segment Insertion Bits, DFT secure, DFT non-secure, DFD from TDI;
  each SIB is one bit, and an open SIB inserts its segment on the TDO side of
  its bit, the SIB bit driving the segment's scan input. The STAP chain
  hierarchy table: the I/O STAP is built with TDI lockup, the others without.
* ``hw/ip/jtag/jtag_ptap/doc/architecture.adoc`` "Scan Path", "TDO Retiming",
  "iJTAG Support" and "STAP selection": a TDR is selected only while its
  instruction is active, SELECT_IJTAG (and RUNBIST) select the iJTAG network,
  TDO is retimed on the falling edge of TCK, and with the 3DCR select set the
  STAP chain input replaces the TDR multiplexer output on IR and DR scans.
* ``hw/ip/jtag/jtag_stap/doc/architecture.adoc`` "STAP Module", "3DCR
  Register" and "Lockup Latches": ``host_tdo_oen_o`` and ``host_tap_ctrl_o``
  derive from ``stap_sel`` and the TAP controls; an unselected STAP parks its
  host TMS at TMS-Hold (reset value 0) and a selected one follows the PTAP
  TMS; the TDO lockup captures the client scan data on every falling edge of
  TCK and drives it on ``host_tdo_o``, and the TDI lockup "adds one
  additional cycle of latency".
* ``hw/sys/dtp/doc/jtag.adoc`` "STAP Secondary Scan Path" for the STAP order
  I/O, SMC debug, SEP debug, extra (``smu_boundary_regs.SMU_SEP_STAP_ORDER``),
  one SIB per STAP.

The bench iJTAG cell is a one-bit ``prim_jtag_scan_reg`` on the host's scan
control: it captures 0 at Capture-DR and shifts while its host select is set.
The model below lays the iJTAG DR out from TDI as, for each SIB in order, its
bit and, while it is open, that host's bench cell; it gives every expected
TDO word, every expected host scan-out stream and the SIB state each Update-DR
leaves.

S1  Instruction gating. Under SELECT_IJTAG all three SIBs are opened, and a
    scan with them open has to assert every host select (the positive
    control) and return the model's word. IDCODE is then loaded, and from the
    Update-IR that loads it, over an IDCODE DR scan and the IR scan of a
    second IDCODE load, none of the three selects may assert. Back under
    SELECT_IJTAG the scan returns the open-SIB word again, so the SIBs were
    open through IDCODE, and its Update-DR closes them.

S2  Chain length, through the host loops and without them. The open pass
    keeps all three SIBs open across every payload shift: the DR is six cells
    (three SIB bits and three bench cells), every payload returns six bits
    late after the captured 0b101010, and each host's scan-out pin carries
    the model's stream on every Shift-DR TCK. The closed pass repeats the
    payloads with every SIB shut: three cells, three bits late after 0b000.
    The two passes return different words, so a SIB that did not route its
    host pins when open would fail the open pass.

S3  SIB round trip. Each SIB is opened alone, then all three, then none; the
    next scan returns the model's word for that SIB state (an open SIB reads
    back 1 and puts its bench cell after it), and the matching host select
    asserts while that scan runs.

S4  I/O STAP select. Unselected, it drives no host TDO enable and holds its
    host TMS at TMS-Hold 0 on every TCK of an IDCODE scan. Selected over
    TAP_3DCR, an IDCODE scan through the network is the PTAP register, the
    TDO and TDI lockup pair of the I/O STAP across the bench's bare return
    (two falling-edge stages in series, one TCK), and the four STAP SIBs: 37
    cells. The scan shifts an 8-bit nonzero tail behind them, which returns
    37 bits late above the IDCODE, the lockup bit and four SIB bits of 0; the
    lockup pair holds at Capture-DR whatever it last held, so that bit is
    masked. Its TDO enable covers exactly the IR and DR shift TCKs, its host
    TMS follows the primary TAP on every TCK, the pad pin ``tb_stap_io_tdo``
    carries the IDCODE bits LSB first on the first 32 Shift-DR TCKs and the
    tail after, and the extra STAP stays quiet.

S5  The extra STAP, the same way (run before S4). Its network IDCODE scan is
    the PTAP register, the three SIBs of the STAPs ahead of it, its bare
    return (no cell: no TDI lockup) and its own SIB: 36 cells, with the tail
    36 bits late. The pad pin ``tb_stap_extra0_tdo`` carries the three SIB
    captures (0), then the IDCODE bits, then the tail. The selection is written with
    Config-Hold clear in the PTAP and the STAP 3DCR, so the Test-Logic-Reset
    S4 starts from clears it (``jtag_stap`` page, "3DCR Register"), which
    S4's idle and "extra STAP stays quiet" checks then read.

Every checked DR shift requires the PTAP TDO to be resolved on each TCK on
which ``jtag_tdo_oen`` drives it, and the number of driven TCKs to cover the
shift: the JTAG VIP maps an X or Z TDO to 0.

Where the pages stop short -- the ``jtag_scan_ctrl_t.select`` definition and
the TAP states that assert ``host_tdo_oen_o`` -- the expectation is the
DV-owned rule above and the plan card records the gap.
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

# TDI-first SIB cascade of the JIU architecture page "iJTAG Network".
IJTAG_SIB_ORDER = ("dft_secure", "dft", "dfd")
IJTAG_SIB_COUNT = len(IJTAG_SIB_ORDER)
IJTAG_SELECT_PIN = {
    "dft_secure": "tb_dft_secure_select",
    "dft": "tb_dft_select",
    "dfd": "tb_dfd_select",
}
IJTAG_SCAN_OUT_PIN = {
    "dft_secure": "tb_dft_secure_scan_out",
    "dft": "tb_dft_scan_out",
    "dfd": "tb_dfd_scan_out",
}
# Payload bits shifted beyond the chain in every S2 scan.
PAYLOAD_LEN = 9
PAYLOAD_MASK = (1 << PAYLOAD_LEN) - 1
# Directed payloads, all nonzero: the JTAG VIP maps an X/Z TDO to 0, so an
# all-zero expectation could not fail.
PAYLOADS = (0xFF, 0x55, 0xAA, 0x01, 0x80)
# The S1 and S3 scans: long enough for the six-cell open chain and a margin.
DR_LEN = 12

IDCODE_DR_WIDTH = 32
STAP_OBSERVE_CYCLES = 2000
SHIFT_STATES = (int(OcahJtagState.SHIFT_IR), int(OcahJtagState.SHIFT_DR))

# The STAP 3DCR TMS-Hold reset value (jtag_stap architecture page, "3DCR
# Register"): the host TMS of an unselected STAP after Test-Logic-Reset.
TMS_HOLD_RESET = 0

# Network IDCODE DR with one STAP selected: PTAP register, the SIBs of the
# STAPs ahead of it, the cells of its host return, its SIB and the SIBs behind
# it. The bench returns each STAP host TDO on a bare net; the I/O STAP's TDO
# and TDI lockups are two falling-edge stages in series, one TCK.
STAP_RETURN_CELLS = {"io": 1, "extra0": 0}
# Bits shifted in behind the network so they reach TDO and the pad: nonzero
# and mixed, and short of the SIB cells, which take only zeros and stay shut.
STAP_TAIL_LEN = 8
STAP_TAIL = 0xA5
STAP_TDO_PIN = {"io": "tb_stap_io_tdo", "extra0": "tb_stap_extra0_tdo"}
STAP_OEN_PIN = {"io": "tb_stap_io_tdo_oen", "extra0": "tb_stap_extra0_tdo_oen"}
STAP_TMS_PIN = {"io": "tb_stap_io_tms", "extra0": "tb_stap_extra0_tms"}
STAP_CHECKER = {"io": "CHK-SMU-STAP-IO-SELECT", "extra0": "CHK-SMU-STAP-EXTRA-SELECT"}
STAP_LABEL = {"io": "I/O", "extra0": "extra"}


def ijtag_chain(opened: frozenset[str]) -> list[tuple[str, str]]:
    """The iJTAG DR from TDI: each SIB bit, then its bench cell while it is open."""
    chain: list[tuple[str, str]] = []
    for name in IJTAG_SIB_ORDER:
        chain.append(("sib", name))
        if name in opened:
            chain.append(("cell", name))
    return chain


def ijtag_word(opened: frozenset[str], open_next: frozenset[str], payload: int, width: int) -> int:
    """A DR word of ``width`` bits that leaves ``open_next`` open after Update-DR.

    The last bit shifted lands in the TDI-nearest cell, so the cell at TDI-first
    index j takes word bit ``width - 1 - j``; ``payload`` fills the bits below.
    """
    chain = ijtag_chain(opened)
    if payload >> (width - len(chain)):
        raise AssertionError(f"payload 0x{payload:x} does not fit a {width}-bit scan")
    word = payload
    for j, (kind, name) in enumerate(chain):
        if kind == "sib" and name in open_next:
            word |= 1 << (width - 1 - j)
    return word


def ijtag_shift(
    opened: frozenset[str], word: int, width: int
) -> tuple[int, dict[str, list[int]], frozenset[str]]:
    """Model one DR scan: (TDO word, per-host scan-out stream, SIBs open after it).

    Capture-DR loads each SIB with its enable and each bench cell with 0. Each
    stream entry is the host's SIB bit before one Shift-DR TCK.
    """
    chain = ijtag_chain(opened)
    state = [1 if kind == "sib" and name in opened else 0 for kind, name in chain]
    sib_at = {name: j for j, (kind, name) in enumerate(chain) if kind == "sib"}
    tdo = 0
    streams: dict[str, list[int]] = {name: [] for name in IJTAG_SIB_ORDER}
    for k in range(width):
        tdo |= state[-1] << k
        for name, j in sib_at.items():
            streams[name].append(state[j])
        state = [(word >> k) & 1, *state[:-1]]
    after = frozenset(name for name, j in sib_at.items() if state[j])
    return tdo, streams, after


class smu_dtp_scan_chain_boundary_seq:
    """iJTAG SIB chain and secondary-TAP select, closed through the pads."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.opened: frozenset[str] = frozenset()
        self.tdo_driven = 0
        self.tdo_unresolved = 0
        self.fall_pins: tuple[str, ...] = ()
        self.rise_pins: tuple[str, ...] = ()
        self.samples: dict[str, list[int]] = {}

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    def _state(self) -> int:
        val = self.dut.jtag_ptap_state.value
        if isinstance(val, int):
            return val
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on jtag_ptap_state: {val}")
        return int(val)

    async def _watch_tck(self) -> None:
        """Per TCK: TDO resolvability, and the Shift-DR samples the current shift asks for.

        ``fall_pins`` change on the rising edge, so they are read at each
        falling edge in Shift-DR, the value the next rising edge shifts on.
        ``rise_pins`` change on the falling edge, so they are read at the rising
        edge that follows a falling edge in Shift-DR.
        """
        prev_tck = self._bit("jtag_tck")
        shift_pending = False
        while True:
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._bit("jtag_tck")
            if tck == 1 and prev_tck == 0:
                if self._bit("jtag_tdo_oen"):
                    self.tdo_driven += 1
                    if not self.dut.jtag_tdo.value.is_resolvable:
                        self.tdo_unresolved += 1
                if shift_pending:
                    for name in self.rise_pins:
                        self.samples[name].append(self._bit(name))
                shift_pending = False
            elif tck == 0 and prev_tck == 1 and self._state() == OcahJtagState.SHIFT_DR:
                shift_pending = True
                for name in self.fall_pins:
                    self.samples[name].append(self._bit(name))
            prev_tck = tck

    async def _checked_shift_dr(
        self,
        word: int,
        width: int,
        label: str,
        *,
        fall_pins: tuple[str, ...] = (),
        rise_pins: tuple[str, ...] = (),
    ) -> int:
        """A DR shift whose TDO is resolved on every driven TCK, ``width`` of them at least."""
        self.tdo_driven = 0
        self.tdo_unresolved = 0
        self.fall_pins, self.rise_pins = fall_pins, rise_pins
        self.samples = {name: [] for name in (*fall_pins, *rise_pins)}
        try:
            captured = await self.jtag.shift_dr(word, width, back_to_rti=True)
        finally:
            self.fall_pins, self.rise_pins = (), ()
        require_jtag_tdo_resolved(label)
        if self.tdo_unresolved or self.tdo_driven < width:
            raise AssertionError(
                f"TDO during {label}: {self.tdo_unresolved} X/Z TCKs of "
                f"{self.tdo_driven} driven, {width} shifted"
            )
        return int(captured)

    async def _ijtag_scan(
        self, open_next: frozenset[str], payload: int, width: int, label: str, *, pins=False
    ) -> tuple[int, int, dict[str, list[int]]]:
        """One SELECT_IJTAG DR scan from the current SIB state: (captured, expected, streams)."""
        word = ijtag_word(self.opened, open_next, payload, width)
        expected, streams, after = ijtag_shift(self.opened, word, width)
        fall = tuple(IJTAG_SCAN_OUT_PIN[name] for name in IJTAG_SIB_ORDER) if pins else ()
        captured = await self._checked_shift_dr(word, width, label, fall_pins=fall)
        if after != open_next:
            raise AssertionError(f"model leaves {sorted(after)} open, wanted {sorted(open_next)}")
        self.opened = after
        return captured & ((1 << width) - 1), expected, streams

    async def _count_selected_tcks(self, cycles: int, pins: tuple[str, ...]) -> dict[str, int]:
        """TCK rising edges seen, and how many of them each pin was high for."""
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
        cocotb.start_soon(self._watch_tck())
        await self.jtag.shift_ir(DTP_IR_IDCODE)
        idcode = await self._checked_shift_dr(0, IDCODE_DR_WIDTH, "IDCODE")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")

        await self._ijtag_gating()
        await self._ijtag_chain_payload()
        await self._ijtag_sib_round_trip()
        await self._stap_select("extra0", config_hold=0)
        await self._stap_select("io", config_hold=1)

    # ------------------------------------------------------------------
    # S1: the iJTAG hosts are gated by instruction, with every SIB open.
    # ------------------------------------------------------------------
    async def _ijtag_gating(self) -> None:
        pins = tuple(IJTAG_SELECT_PIN[name] for name in IJTAG_SIB_ORDER)
        everything = frozenset(IJTAG_SIB_ORDER)
        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG)
        await self._ijtag_scan(everything, 0, DR_LEN, "iJTAG SIB open")

        watcher = cocotb.start_soon(self._count_selected_tcks(STAP_OBSERVE_CYCLES, pins))
        captured, expected, _ = await self._ijtag_scan(everything, 0, DR_LEN, "iJTAG SIB hold open")
        opened = await watcher
        self.sb.expect_eq(
            "SELECT_IJTAG scan with all three SIBs open returns the open-chain word",
            captured,
            expected,
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
            raise AssertionError(f"IDCODE window saw only {counts['tck_n']} TCKs; it is too short")
        for name in IJTAG_SIB_ORDER:
            self.sb.expect_eq(
                f"{name} iJTAG host stays unselected under IDCODE with its SIB open "
                f"({counts['tck_n']} TCKs observed)",
                counts[IJTAG_SELECT_PIN[name]],
                0,
                evidence="CHK-SMU-IJTAG-GATE",
            )

        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG)
        captured, expected, _ = await self._ijtag_scan(frozenset(), 0, DR_LEN, "iJTAG SIB close")
        self.sb.expect_eq(
            "the SIBs still return the open-chain word after the IDCODE scan",
            captured,
            expected,
            evidence="CHK-SMU-IJTAG-GATE",
        )

    # ------------------------------------------------------------------
    # S2: the chain through the open host loops, then without them.
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
        payloads = (*PAYLOADS, *randoms)
        everything = frozenset(IJTAG_SIB_ORDER)
        await self._ijtag_scan(everything, 0, DR_LEN, "iJTAG SIB open for S2")
        await self._payload_pass(payloads, everything, "all SIBs open, through the host loops")
        await self._ijtag_scan(frozenset(), 0, DR_LEN, "iJTAG SIB close for S2")
        await self._payload_pass(payloads, frozenset(), "all SIBs closed")

    async def _payload_pass(
        self, payloads: tuple[int, ...], opened: frozenset[str], label: str
    ) -> None:
        cells = len(ijtag_chain(opened))
        width = cells + PAYLOAD_LEN
        pin_bits = 0
        for payload in payloads:
            captured, expected, streams = await self._ijtag_scan(
                opened,
                payload & PAYLOAD_MASK,
                width,
                f"iJTAG DR payload 0x{payload:x} ({label})",
                pins=bool(opened),
            )
            self.sb.expect_eq(
                f"iJTAG DR returns payload 0x{payload:x} {cells} bits late after the "
                f"captured 0b{expected & ((1 << cells) - 1):0{cells}b} ({label})",
                captured,
                expected,
                evidence="CHK-SMU-IJTAG-CHAIN",
            )
            if opened:
                for name in IJTAG_SIB_ORDER:
                    pin = IJTAG_SCAN_OUT_PIN[name]
                    self.sb.expect_eq(
                        f"{pin} carries the {name} SIB bit on each of the {width} Shift-DR "
                        f"TCKs of payload 0x{payload:x}",
                        self.samples[pin],
                        streams[name],
                        evidence="CHK-SMU-IJTAG-CHAIN",
                    )
                    pin_bits += len(self.samples[pin])
        if opened:
            self.sb.expect_eq(
                f"host scan-out samples over the open pass ({label})",
                pin_bits,
                len(payloads) * width * IJTAG_SIB_COUNT,
                evidence="CHK-SMU-IJTAG-CHAIN",
            )

    # ------------------------------------------------------------------
    # S3: Update-DR latches the SIB enables and the next scan reads them back.
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
            target = frozenset(opened)
            await self._ijtag_scan(target, 0, DR_LEN, f"iJTAG SIB set ({label})")

            watcher = cocotb.start_soon(self._count_selected_tcks(STAP_OBSERVE_CYCLES, pins))
            captured, expected, _ = await self._ijtag_scan(
                frozenset(), 0, DR_LEN, f"iJTAG SIB capture ({label})"
            )
            counts = await watcher
            self.sb.expect_eq(
                f"the scan after Update-DR returns the SIB enables and open cells ({label})",
                captured,
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
    # S4 (I/O STAP) and S5 (extra STAP): select over TAP_3DCR.
    # ------------------------------------------------------------------
    async def _stap_select(self, name: str, *, config_hold: int) -> None:
        checker = STAP_CHECKER[name]
        who = STAP_LABEL[name]
        other = "extra0" if name == "io" else "io"
        await self.jtag.reset_to_tlr()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)

        idle, _, _ = await self._observe_stap(name, IDCODE_DR_WIDTH)
        self.sb.expect_eq(
            f"the {who} STAP drives no TDO enable while it is unselected",
            idle[STAP_OEN_PIN[name]],
            0,
            evidence=checker,
        )
        self.sb.expect_eq(
            f"unselected {who} STAP host TMS holds TMS-Hold {TMS_HOLD_RESET} on every TCK "
            f"of an IDCODE scan ({idle['tck_n']} TCKs, at least "
            f"{DTP_IR_WIDTH + IDCODE_DR_WIDTH})",
            (idle["tms_high"], idle["tck_n"] >= DTP_IR_WIDTH + IDCODE_DR_WIDTH),
            (idle["tck_n"] if TMS_HOLD_RESET else 0, True),
            evidence=checker,
        )

        await self._select_stap(name, config_hold=config_hold)
        ahead = SMU_SEP_STAP_ORDER.index(name)
        sibs_from = len(SMU_SEP_STAP_ORDER) - ahead
        returned = STAP_RETURN_CELLS[name]
        cells = IDCODE_DR_WIDTH + ahead + returned + sibs_from
        width = cells + STAP_TAIL_LEN
        live, captured, pad = await self._observe_stap(name, width, STAP_TAIL)

        below = cells - IDCODE_DR_WIDTH
        lockup_mask = ((1 << returned) - 1) << sibs_from
        self.sb.expect_eq(
            f"a {width}-bit network IDCODE scan with the {who} STAP selected returns "
            f"{ahead + sibs_from} SIB bits of 0"
            + (f", {returned} masked lockup bit" if returned else "")
            + f", the IDCODE, then the {STAP_TAIL_LEN} tail bits 0x{STAP_TAIL:02x} "
            f"{cells} bits late",
            captured & ~lockup_mask & ((1 << width) - 1),
            (DTP_DEFAULT_IDCODE << below) | (STAP_TAIL << cells),
            evidence=checker,
        )
        expected_pad = (
            [0] * ahead
            + [(DTP_DEFAULT_IDCODE >> k) & 1 for k in range(IDCODE_DR_WIDTH)]
            + [(STAP_TAIL >> k) & 1 for k in range(width - ahead - IDCODE_DR_WIDTH)]
        )
        self.sb.expect_eq(
            f"{STAP_TDO_PIN[name]} carries the STAP's client stream on each of the {width} "
            f"Shift-DR TCKs: {ahead} SIB captures, the IDCODE LSB first, then the tail",
            pad,
            expected_pad,
            evidence=checker,
        )
        self.sb.expect_eq(
            f"the selected {who} STAP drives its TDO enable for exactly the "
            f"{DTP_IR_WIDTH} + {width} IR and DR shift TCKs",
            live[STAP_OEN_PIN[name]],
            DTP_IR_WIDTH + width,
            evidence=checker,
        )
        self.sb.expect_eq(
            f"the selected {who} STAP's TDO enable is high on every Shift-IR and Shift-DR "
            f"TCK and low on every other TCK of the window ({live['tck_n']} TCKs)",
            live["oen_state_mismatch"],
            0,
            evidence=checker,
        )
        self.sb.expect_eq(
            f"the selected {who} STAP host TMS follows the primary TAP on every TCK",
            live["tms_mismatch"],
            0,
            evidence=checker,
        )
        self.sb.expect_eq(
            f"the {STAP_LABEL[other]} STAP beside it stays unselected",
            live[STAP_OEN_PIN[other]],
            0,
            evidence=checker,
        )

    async def _select_stap(self, name: str, config_hold: int = 1) -> None:
        """TAP_3DCR select: PTAP select, then the SIB, then the STAP 3DCR.

        The three DR scans run under one TAP_3DCR load. The last one writes
        the STAP 3DCR and closes the SIB of ``name`` again, and a later IR
        load leaves the selection in place: the network IDCODE scan reads it.
        ``config_hold`` is written to the PTAP and the STAP 3DCR alike.
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

    async def _observe_stap(
        self, name: str, dr_width: int, word: int = 0
    ) -> tuple[dict[str, int], int, list[int]]:
        """An IDCODE IR scan and a ``dr_width`` DR scan, watched at both STAP hosts.

        Returns the per-pin TCK counts, the captured DR and the STAP pad TDO
        on each Shift-DR TCK.
        """
        pins = (STAP_OEN_PIN["io"], STAP_OEN_PIN["extra0"])
        watcher = cocotb.start_soon(
            self._watch_stap(2 * STAP_OBSERVE_CYCLES, pins, STAP_TMS_PIN[name], STAP_OEN_PIN[name])
        )
        await self.jtag.shift_ir(DTP_IR_IDCODE)
        captured = await self._checked_shift_dr(
            word,
            dr_width,
            f"IDCODE through the {STAP_LABEL[name]} STAP",
            rise_pins=(STAP_TDO_PIN[name],),
        )
        pad = list(self.samples[STAP_TDO_PIN[name]])
        return await watcher, captured, pad

    async def _watch_stap(
        self, cycles: int, pins: tuple[str, ...], tms_pin: str, oen_pin: str
    ) -> dict[str, int]:
        """Per-pin high counts on each TCK, host TMS against the PTAP's, and the
        TCKs on which ``oen_pin`` disagrees with the PTAP being in Shift-IR or
        Shift-DR. That pair is read after each falling edge: IEEE 1149.1
        (Section 4.5.1) changes TDO and its enable on the falling edge, and the
        state the TAP holds until the next rising edge is the one in force."""
        counts = {name: 0 for name in pins}
        counts["tck_n"] = 0
        counts["tms_mismatch"] = 0
        counts["tms_high"] = 0
        counts["oen_state_mismatch"] = 0
        prev_tck = self._bit("jtag_tck")
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_ref_i)
            tck = self._bit("jtag_tck")
            if tck == 1 and prev_tck == 0:
                counts["tck_n"] += 1
                for name in pins:
                    counts[name] += self._bit(name)
                host_tms = self._bit(tms_pin)
                counts["tms_high"] += host_tms
                if host_tms != self._bit("jtag_tms"):
                    counts["tms_mismatch"] += 1
            elif tck == 0 and prev_tck == 1:
                if self._bit(oen_pin) != (self._state() in SHIFT_STATES):
                    counts["oen_state_mismatch"] += 1
            prev_tck = tck
        return counts
