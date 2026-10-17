# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI capability words and SMC fabric single-operation status.

The sequence scans the three *_JTAG2AXI_CAPS registers of the primary TAP and compares each word
field by field to the bridge table, shifts zeros, ones and 0x2AAA into each and recaptures it
across an intervening IDCODE scan and BYPASS load, then drives the SMC fabric SINGLE_OP register.
The op field of each capture is the status of the previous operation: an empty-mailbox READ_DATA
read reports SLVERR with 0xFEEDDEAD, a read between unit apertures reports DECERR with 0xBADCAB1E, a
write and a read of CPU_CTRL SCRATCH report OKAY with the written word, and an op 0 scan sends
nothing. The launch counters at the SMU boundary give the number of AXI transfers behind each leg.

Sources: hw/ip/jtag/jtag_ptap/doc/architecture.adoc (*_JTAG2AXI_CAPS, *_AXI_SINGLE_OP),
hw/sys/dtp/doc/jtag.adoc (JTAG2AXI bridge table), hw/sys/smc/doc/memmap.adoc (DECERR between unit
apertures) and hw/ip/axi_lite_mailbox_unit/doc/interface.adoc (SLVERR on an empty READ_DATA).
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import mailbox_u32, smc_addr, smc_indexed_addr
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    DTP_IR_WIDTH,
    DTP_JTAG2AXI_CAPS_LEN,
    J2A_OP_NOP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    make_smu_jtag_tap,
    pack_jtag2axi_caps,
    pack_single_op,
    require_jtag_tdo_resolved,
    unpack_single_op,
)

# hw/sys/smc/doc/memmap.adoc: LOCAL_BASE is 0xC000_0000. A read from BASE + 0x001_7000 is an
# address between unit apertures and answers DECERR with 0xBADCAB1E. A write from BASE + 0x001_7000
# through BASE + 0x001_7FFF is documented as SLVERR; its response over this bridge is logged and
# not compared.
LOCAL_BASE = 0xC000_0000
GAP_ADDR = LOCAL_BASE + 0x001_7000
GAP_WRITE_WORD = 0xDEAD_0003
DECERR_READ_DATA = 0xBADC_AB1E
# hw/sys/smc/regs/gen/c/smc_addr.h: CPU_CTRL SCRATCH[13], 8-byte stride from 0xC0039080; the
# register resets to 0 (hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl).
_CPU_SCRATCH = "SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR"
SCRATCH_INDEX = 13
SCRATCH_ADDR = smc_indexed_addr(_CPU_SCRATCH, SCRATCH_INDEX)
SCRATCH_WORD = 0x0A11_CE5E
# hw/sys/smc/regs/gen/c/smc_addr.h: outbound mailbox 0 READ_DATA and STATUS.
MBX_READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR")
MBX_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
# hw/ip/axi_lite_mailbox_unit/regs STATUS.EMPTY mask from the generated mailbox header.
ST_EMPTY = mailbox_u32("AXIL_MAILBOX__STATUS__EMPTY_bm")
# hw/ip/axi_lite_mailbox_unit/doc/interface.adoc, Access Results: READ_DATA while empty answers
# SLVERR with data 0xFEEDDEAD.
EMPTY_READ_DATA = 0xFEED_DEAD
NOP_DATA_WORD = 0x0BAD_BEEF
WORD_STROBE = 0x0F

# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, PTAP JTAG2AXI capability fields table: field
# positions in the 14-bit word and the bus_type encodings.
CAPS_BUS_TYPE_LSB = 0
CAPS_ADDR_SIZE_LSB = 1
CAPS_ADDR_SIZE_MASK = 0x3F
CAPS_DATA_SIZE_LSB = 7
CAPS_DATA_SIZE_MASK = 0x7
CAPS_WR_PL_LSB = 10
CAPS_RD_PL_LSB = 12
CAPS_PL_MASK = 0x3
BUS_AXI4 = 0
BUS_AXI4_LITE = 1
# hw/sys/dtp/doc/jtag.adoc, DTP JTAG2AXI bridges table: SMC fabric AXI4 56 / 64 bits, SMC OTP and
# SEP OTP AXI4-Lite 32 / 32 bits, pipeline-depth parameters default 3. The data_size field is the
# size in powers-of-2 bytes (architecture.adoc): 64 bits is 3 and 32 bits is 2.
FABRIC_ADDR_BITS = 56
FABRIC_DATA_SIZE = 3
OTP_ADDR_BITS = 32
OTP_DATA_SIZE = 2
PL_DEPTH = 3
# (bus_type, addr_size, data_size, wr_pl_depth, rd_pl_depth)
FABRIC_FIELDS = (BUS_AXI4, FABRIC_ADDR_BITS, FABRIC_DATA_SIZE, PL_DEPTH, PL_DEPTH)
OTP_FIELDS = (BUS_AXI4_LITE, OTP_ADDR_BITS, OTP_DATA_SIZE, PL_DEPTH, PL_DEPTH)
FABRIC_CAPS_WORD = pack_jtag2axi_caps(
    rd_pl=PL_DEPTH,
    wr_pl=PL_DEPTH,
    data_size=FABRIC_DATA_SIZE,
    addr_size=FABRIC_ADDR_BITS,
    bus_type=BUS_AXI4,
)
OTP_CAPS_WORD = pack_jtag2axi_caps(
    rd_pl=PL_DEPTH,
    wr_pl=PL_DEPTH,
    data_size=OTP_DATA_SIZE,
    addr_size=OTP_ADDR_BITS,
    bus_type=BUS_AXI4_LITE,
)
CAPS_REGS = (
    ("SMC_JTAG2AXI_CAPS", FABRIC_CAPS_WORD),
    ("SMC_OTP_JTAG2AXI_CAPS", OTP_CAPS_WORD),
    ("SEP_OTP_JTAG2AXI_CAPS", OTP_CAPS_WORD),
)
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_JTAG2AXI_CAPS: a 14-bit read-only TDR; the shift-in
# patterns are all zeros, all ones and the alternating word.
CAPS_BITS = DTP_JTAG2AXI_CAPS_LEN
SHIFT_PATTERNS = (0, (1 << CAPS_BITS) - 1, 0x2AAA)
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SINGLE_OP fields (2 + S + D/8 + D + A bits)
# with the SMC fabric widths of hw/sys/dtp/doc/jtag.adoc: op 2, size 2, wstrb 8, data 64, addr 56.
SINGLE_OP_BITS = 2 + 2 + 8 + 64 + 56
SINGLE_OP_SCAN_BITS = 192
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SINGLE_OP op field: 0 OKAY, 1 SLVERR, 2 DECERR.
OP_OKAY = J2A_STATUS_SUCCESS
SINGLE_OP_IR = "SMC_AXI_SINGLE_OP"
CHAIN_MARKER = 0xA5C3_96E1
CHAIN_MARKER_BITS = 32

GATE_POLL_LIMIT = 400
GATE_POLL_CLK = 50
CAPTURE_LIMIT = 8

# Wait sites per kind: the gate wait and one capture poll after each of the ten SINGLE_OP accesses.
EXPECTED_SITE_KINDS = {"gate": 1, "poll": 10}
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
FENCE_CYCLES = 2
SCANNED_STEPS = STEPS[:-1]


def _lane_word(rdata: int, addr: int) -> int:
    """The 32-bit word a size-2 read returns on the lane its address selects."""
    return ((rdata >> 32) if addr & 0x4 else rdata) & 0xFFFF_FFFF


def _chain_length(captured: int, width: int) -> int:
    """TCKs until the chain marker reappears on TDO, or -1 when it is not found exactly once."""
    bits = [(captured >> i) & 1 for i in range(width)]
    pat = [(CHAIN_MARKER >> i) & 1 for i in range(CHAIN_MARKER_BITS)]
    hits = [
        i for i in range(width - CHAIN_MARKER_BITS + 1) if bits[i : i + CHAIN_MARKER_BITS] == pat
    ]
    return hits[0] if len(hits) == 1 else -1


def _fields(raw: int) -> tuple[int, int, int, int, int]:
    """(bus_type, addr_size, data_size, wr_pl_depth, rd_pl_depth) of a capability word."""
    return (
        (raw >> CAPS_BUS_TYPE_LSB) & 1,
        (raw >> CAPS_ADDR_SIZE_LSB) & CAPS_ADDR_SIZE_MASK,
        (raw >> CAPS_DATA_SIZE_LSB) & CAPS_DATA_SIZE_MASK,
        (raw >> CAPS_WR_PL_LSB) & CAPS_PL_MASK,
        (raw >> CAPS_RD_PL_LSB) & CAPS_PL_MASK,
    )


class smu_dtp_jtag2axi_caps_single_op_test_seq:
    """JTAG2AXI capability words and SMC fabric SINGLE_OP status."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.scans = 0
        self.step_ns: dict[str, float] = {}
        self.step_scans: dict[str, int] = {}
        self.sites: list[dict] = []
        self.failures: list[str] = []
        self.base = (0, 0, 0)
        self.width = 0
        self.decerr = (0, 0, 0)
        self.before_write = 0
        self.write_op = 0
        self.write_deltas = (0, 0, 0)
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.step_ns[step] = self._now()
        self.step_scans[step] = self.scans
        self._log(f"STEP {step} @{self.step_ns[step]:.3f}ns scans={self.scans}: {text}")

    def _check(self, chk: str, proof: str, got, want) -> None:
        self._log(f"{chk}: {proof}")
        try:
            self.sb.expect_eq(chk, got, want, evidence=chk)
        except AssertionError as exc:
            self.failures.append(str(exc))

    def _site(self, kind: str, label: str, bound: int, unit: str, used: int, last: str) -> None:
        expired = last.startswith("EXPIRED")
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": unit,
                "used": used,
                "last": last,
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} {unit} used={used} last_state={last}"
            )

    def _counts(self) -> tuple[int, int, int]:
        dut = self.dut
        return (
            sample(dut.dtp_smc_dbg_aw_count_o, "dtp_smc_dbg_aw_count_o"),
            sample(dut.dtp_smc_dbg_ar_count_o, "dtp_smc_dbg_ar_count_o"),
            sample(dut.dtp_smc_dbg_b_count_o, "dtp_smc_dbg_b_count_o"),
        )

    @staticmethod
    def _delta(now: tuple[int, int, int], base: tuple[int, int, int]) -> tuple[int, int, int]:
        return tuple((n - b) & 0xFFFF_FFFF for n, b in zip(now, base))

    async def _scan(self, reg: str, value: int, label: str) -> int:
        captured = await self.jtag.read(reg, shift_value=value)
        require_jtag_tdo_resolved(f"scan {label}")
        self.scans += 1
        self._log(f"SCAN {self.scans} {reg} {label} in=0x{value:x} out=0x{captured:x}")
        return captured

    async def _caps(self, reg: str, value: int, label: str) -> int:
        return await self._scan(reg, value, label) & ((1 << CAPS_BITS) - 1)

    async def _capture(self, label: str) -> int:
        """Scan SINGLE_OP with op 0; the op field is the status of the previous operation."""
        status, _ = unpack_single_op(await self._scan(SINGLE_OP_IR, 0, label))
        return status

    async def _single_op(
        self, op: int, addr: int, data: int, wstrb: int, label: str
    ) -> tuple[int, int, tuple[int, int, int]]:
        """Issue one SINGLE_OP and capture until op leaves 3; returns (op, lane word, deltas)."""
        base = self._counts()
        await self.jtag.write(
            SINGLE_OP_IR, pack_single_op(op, addr, data, wstrb, SMC_DBG_AXSIZE_4B)
        )
        require_jtag_tdo_resolved(f"issue {label}")
        self.scans += 1
        self._log(f"SCAN {self.scans} {SINGLE_OP_IR} issue {label} op={op} addr=0x{addr:08x}")
        status, rdata, used = J2A_STATUS_BUSY, 0, 0
        while used < CAPTURE_LIMIT:
            capt = await self._scan(SINGLE_OP_IR, 0, f"{label}_capture{used}")
            used += 1
            status, rdata = unpack_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
        last = f"op={status}" if status != J2A_STATUS_BUSY else f"EXPIRED op={status}"
        self._site("poll", label, CAPTURE_LIMIT, "captures", used, last)
        deltas = self._delta(self._counts(), base)
        word = _lane_word(rdata, addr)
        self._log(f"CELL {label} op={status} data=0x{word:08x} aw/ar/b delta={deltas}")
        return status, word, deltas

    async def _read(self, addr: int, label: str) -> tuple[int, int, tuple[int, int, int]]:
        return await self._single_op(J2A_OP_READ, addr, 0, 0, label)

    async def _write(
        self, addr: int, data: int, label: str
    ) -> tuple[int, int, tuple[int, int, int]]:
        return await self._single_op(J2A_OP_WRITE, addr, data, WORD_STROBE, label)

    async def run(self) -> None:
        await self._setup()
        await self._caps_smc()
        await self._caps_otp()
        await self._caps_stable()
        await self._slverr()
        await self._decerr()
        await self._okay_write()
        await self._okay_read()
        await self._recovery()
        await self._nop()
        await self._finish()

    async def _setup(self) -> None:
        await self._mark("S1", "TAP reset, IDCODE, gate, SINGLE_OP width, counter baselines")
        self.jtag = jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        idcode = await self._scan("IDCODE", 0, "idcode")
        gate = self.dut.tb_smc_jtag2axi_security_disable
        used = 0
        while True:
            val = gate.value
            if val.is_resolvable and int(val) == 0:
                break
            if used >= GATE_POLL_LIMIT:
                self._site(
                    "gate", "security_disable", GATE_POLL_LIMIT, "polls", used, f"EXPIRED {val}"
                )
            used += 1
            await ClockCycles(self.dut.clk_smu_i, GATE_POLL_CLK)
        self._site("gate", "security_disable", GATE_POLL_LIMIT, "polls", used, str(val))
        gate_value = int(gate.value)
        self.base = self._counts()
        await jtag.shift_ir(DTP_IR_SMC_AXI_SINGLE_OP, width=DTP_IR_WIDTH, back_to_rti=False)
        probe = await jtag.shift_dr(CHAIN_MARKER, SINGLE_OP_SCAN_BITS, back_to_rti=True)
        require_jtag_tdo_resolved("width probe")
        self.scans += 1
        self.width = _chain_length(probe, SINGLE_OP_SCAN_BITS)
        self._log(f"SCAN {self.scans} {SINGLE_OP_IR} width_probe out=0x{probe:x}")
        self._check(
            "CHK-DBG-J2A-CAPS-SETUP",
            f"gate tap read {gate_value} after {used} polls, IDCODE 0x{idcode:08x}, "
            f"aw/ar/b baselines {self.base} sampled "
            f"(want IDCODE 0x{DTP_DEFAULT_IDCODE:08x})",
            (idcode,),
            (DTP_DEFAULT_IDCODE,),
        )

    async def _caps_smc(self) -> None:
        await self._mark("S2", "SMC_JTAG2AXI_CAPS field by field")
        reg, want_word = CAPS_REGS[0]
        raw = await self._caps(reg, 0, "caps")
        self._check(
            "CHK-DBG-J2A-CAPS-SMC",
            f"{reg} word 0x{raw:04x} fields (bus_type, addr_size, data_size, wr_pl, rd_pl)="
            f"{_fields(raw)} (want 0x{want_word:04x} {FABRIC_FIELDS})",
            (raw, _fields(raw)),
            (want_word, FABRIC_FIELDS),
        )

    async def _caps_otp(self) -> None:
        await self._mark("S3", "SMC_OTP and SEP_OTP JTAG2AXI_CAPS field by field")
        words = [await self._caps(reg, 0, "caps") for reg, _ in CAPS_REGS[1:]]
        self._check(
            "CHK-DBG-J2A-CAPS-OTP",
            f"SMC_OTP 0x{words[0]:04x} {_fields(words[0])} and SEP_OTP 0x{words[1]:04x} "
            f"{_fields(words[1])} (want 0x{OTP_CAPS_WORD:04x} {OTP_FIELDS} each)",
            [(w, _fields(w)) for w in words],
            [(OTP_CAPS_WORD, OTP_FIELDS)] * 2,
        )

    async def _caps_stable(self) -> None:
        await self._mark("S4", "CAPS words across shift-ins and an IDCODE scan and BYPASS load")
        got, want = [], []
        for reg, word in CAPS_REGS:
            recaptured = []
            for pattern in SHIFT_PATTERNS:
                await self._caps(reg, pattern, f"shift_0x{pattern:04x}")
                recaptured.append(await self._caps(reg, 0, f"recapture_0x{pattern:04x}"))
            await self._scan("IDCODE", 0, "idcode_between")
            recaptured.append(await self._caps(reg, 0, "recapture_idcode"))
            await self.jtag.bypass()
            recaptured.append(await self._caps(reg, 0, "recapture_bypass"))
            got.append(recaptured)
            want.append([word] * len(recaptured))
        self._check(
            "CHK-DBG-J2A-CAPS-STABLE",
            "recaptured words after zeros, ones, 0x2AAA, IDCODE and BYPASS: "
            + ", ".join(f"{reg}={[hex(w) for w in ws]}" for (reg, _), ws in zip(CAPS_REGS, got))
            + f" (want {[hex(w) for _, w in CAPS_REGS]} every time)",
            got,
            want,
        )

    async def _slverr(self) -> None:
        await self._mark("S5", "STATUS read, empty-mailbox READ_DATA read, window write")
        st_op, st_word, _ = await self._read(MBX_STATUS, "mbx_status_read")
        before = await self._capture("before_mbx_read")
        op, data, deltas = await self._read(MBX_READ_DATA, "mbx_read_data_empty")
        after = await self._capture("after_mbx_read")
        w_op, _, w_deltas = await self._write(GAP_ADDR, GAP_WRITE_WORD, "window_write")
        self._log(
            f"OBSERVATION SINGLE_OP write at 0x{GAP_ADDR:08x} op measured={w_op} "
            f"aw/ar/b delta measured={w_deltas}"
        )
        self._check(
            "CHK-DBG-J2A-SINGLE-SLVERR",
            f"STATUS read EMPTY={bool(st_word & ST_EMPTY)} op {st_op}; the capture before the "
            f"READ_DATA read op {before}; the empty READ_DATA read op {op} data 0x{data:08x} "
            f"with AR delta {deltas[1]}, the capture after it op {after}; SINGLE_OP scans "
            f"{self.width} bits (want EMPTY 1, op 0, 0, op {J2A_STATUS_SLVERR} data "
            f"0x{EMPTY_READ_DATA:08x}, AR 1, op {J2A_STATUS_SLVERR}, {SINGLE_OP_BITS} bits)",
            (st_word & ST_EMPTY, st_op, before, op, data, deltas[1], after, self.width),
            (
                ST_EMPTY,
                OP_OKAY,
                OP_OKAY,
                J2A_STATUS_SLVERR,
                EMPTY_READ_DATA,
                1,
                J2A_STATUS_SLVERR,
                SINGLE_OP_BITS,
            ),
        )

    async def _decerr(self) -> None:
        await self._mark("S6", "read between unit apertures")
        op, data, deltas = await self._read(GAP_ADDR, "gap_read")
        self.decerr = (op, data, deltas[1])
        self._check(
            "CHK-DBG-J2A-SINGLE-DECERR",
            f"gap read at 0x{GAP_ADDR:08x} op {op} data 0x{data:08x} AR delta {deltas[1]} "
            f"(want op {J2A_STATUS_DECERR} data 0x{DECERR_READ_DATA:08x} AR 1)",
            self.decerr,
            (J2A_STATUS_DECERR, DECERR_READ_DATA, 1),
        )

    async def _okay_write(self) -> None:
        await self._mark("S7", "OKAY write of SCRATCH[13]")
        self.before_write = await self._capture("before_okay_write")
        self.write_op, _, deltas = await self._write(SCRATCH_ADDR, SCRATCH_WORD, "okay_write")
        self.write_deltas = deltas

    async def _okay_read(self) -> None:
        await self._mark("S8", "gap read, then OKAY read of SCRATCH[13]")
        gap_op, gap_data, _ = await self._read(GAP_ADDR, "gap_read_before_okay_read")
        op, data, deltas = await self._read(SCRATCH_ADDR, "okay_read")
        self._check(
            "CHK-DBG-J2A-SINGLE-OKAY",
            f"capture before the write op {self.before_write}, write op {self.write_op} with AW "
            f"delta {self.write_deltas[0]} and B delta {self.write_deltas[2]}, read op {op} data "
            f"0x{data:08x} with AR delta {deltas[1]}; the gap read right before it op {gap_op} "
            f"data 0x{gap_data:08x} (want op {J2A_STATUS_DECERR}, op {OP_OKAY}, AW 1, B 1, "
            f"op {OP_OKAY} data 0x{SCRATCH_WORD:08x}, AR 1, op {J2A_STATUS_DECERR} data "
            f"0x{DECERR_READ_DATA:08x})",
            (
                self.before_write,
                self.write_op,
                self.write_deltas[0],
                self.write_deltas[2],
                op,
                data,
                deltas[1],
                gap_op,
                gap_data,
            ),
            (
                J2A_STATUS_DECERR,
                OP_OKAY,
                1,
                1,
                OP_OKAY,
                SCRATCH_WORD,
                1,
                J2A_STATUS_DECERR,
                DECERR_READ_DATA,
            ),
        )

    async def _recovery(self) -> None:
        await self._mark("S9", "empty-mailbox read, then a clean read")
        err_op, err_data, _ = await self._read(MBX_READ_DATA, "mbx_read_data_empty_again")
        op, data, _ = await self._read(SCRATCH_ADDR, "clean_read")
        self._check(
            "CHK-DBG-J2A-SINGLE-RECOVERY",
            f"second empty READ_DATA read op {err_op} data 0x{err_data:08x}; the clean read of "
            f"SCRATCH[13] op {op} data 0x{data:08x}; the write after the DECERR read op "
            f"{self.write_op} (want op {J2A_STATUS_SLVERR} data 0x{EMPTY_READ_DATA:08x}, op "
            f"{OP_OKAY} data 0x{SCRATCH_WORD:08x}, op {OP_OKAY})",
            (err_op, err_data, op, data, self.write_op),
            (J2A_STATUS_SLVERR, EMPTY_READ_DATA, OP_OKAY, SCRATCH_WORD, OP_OKAY),
        )

    async def _nop(self) -> None:
        await self._mark("S10", "op 0 scans send nothing, the op 1 scan reads")
        base = self._counts()
        for i in range(2):
            raw = pack_single_op(
                J2A_OP_NOP, SCRATCH_ADDR, NOP_DATA_WORD, WORD_STROBE, SMC_DBG_AXSIZE_4B
            )
            await self._scan(SINGLE_OP_IR, raw, f"nop{i}")
        _, nop_ar, _ = self._delta(self._counts(), base)
        _, _, deltas = await self._single_op(
            J2A_OP_READ, SCRATCH_ADDR, NOP_DATA_WORD, WORD_STROBE, "nop_control_read"
        )
        nop_aw = self._delta(self._counts(), base)[0]
        self._check(
            "CHK-DBG-J2A-SINGLE-NOP",
            f"two op 0 scans left AR delta {nop_ar}; after the op 1 scan completed the AW delta "
            f"is {nop_aw} and the op 1 scan raised AR by {deltas[1]} (want 0, 0, 1)",
            (nop_aw, nop_ar, deltas[1]),
            (0, 0, 1),
        )

    async def _finish(self) -> None:
        await self._mark("S11", "wait sites and the pass stamp")
        for rec in self.sites:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        no_last = [rec["label"] for rec in self.sites if not rec["last"]]
        self._check(
            "CHK-TIMEOUT-PATHS",
            f"sites={len(self.sites)} kinds={kinds} expired={expired} "
            f"without_last_state={no_last} (want kinds {EXPECTED_SITE_KINDS}, expired 0)",
            (expired, no_last, kinds),
            (0, [], EXPECTED_SITE_KINDS),
        )
        await ClockCycles(self.dut.clk_smu_i, FENCE_CYCLES)
        self.step_ns["PASS"] = self._now()
        self.step_scans["PASS"] = self.scans
        order = [*STEPS, "PASS"]
        stamps = [self.step_ns[s] for s in order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        counts = tuple(
            self.step_scans[b] - self.step_scans[a] for a, b in zip(SCANNED_STEPS, STEPS[1:])
        )
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(order, stamps))
        self._check(
            "CHK-NONVAC",
            f"ordered sim-time fence {fence} scans={self.scans} scans per step S1..S10={counts}",
            (all(d > 0 for d in deltas), tuple(n > 0 for n in counts)),
            (True, (True,) * len(SCANNED_STEPS)),
        )
        if self.failures:
            raise AssertionError(f"{len(self.failures)} checker compare(s) failed: {self.failures}")
        self.done = True
