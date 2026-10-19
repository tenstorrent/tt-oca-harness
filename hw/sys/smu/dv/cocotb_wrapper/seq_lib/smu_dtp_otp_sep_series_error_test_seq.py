# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OTP JTAG2AXIL series access, the in-span decode hole response and bridge isolation.

The sequence writes two words of the SEP shadow map through SERIES_DATA_NO_INCR, reads them back as
one SERIES_CTRL read load followed by two data scans through NO_INCR and INCR, and reads the first
in-span offset that owns no register with SINGLE_OP and as a series beat. The SINGLE_OP read
answers SLVERR in op, the series beat latches code 1 in SERIES_CTRL.op, a later beat at a
documented word returns its data, a SINGLE_OP read of a documented word reports op 0 beside the
latched code, SERIES_CTRL.reset clears the code, and the DTP-to-SMC debug AXI counters stay put
while two SMC fabric SINGLE_OP reads move the AR counter by two. A series read is compared only in
its single-load form; the longer read stream, the marker beats, the pl_depth field of captures and
the data word of the SLVERR read are measured and logged only.

Sources: hw/ip/jtag/jtag_ptap/doc/architecture.adoc (*_AXI_SINGLE_OP, *_AXI_SERIES_CTRL,
*_AXI_SERIES_DATA_INCR, *_AXI_SERIES_DATA_NO_INCR), hw/ip/jtag/jtag_intf_unit/doc/interface.adoc
(Instruction Encodings), hw/sys/dtp/doc/jtag.adoc (JTAG2AXI bridge table),
hw/sys/sep/doc/otp_fuse_controller.adoc (APB decode) and hw/sys/sep/regs/gen/c/sep_addr.h.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32, smc_indexed_addr
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    DTP_IR_WIDTH,
    J2A_OP_NOP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_SINGLE_OP_LEN,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    pack_otp_series_ctrl,
    pack_otp_single_op,
    pack_single_op,
    require_jtag_tdo_resolved,
    unpack_otp_series_ctrl,
    unpack_otp_single_op,
    unpack_single_op,
)
from seq_lib.smu_lifecycle_table import LC_STATE_PRESENSE

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"

# hw/sys/sep/regs/gen/c/sep_addr.h: SPARE0 is a 256-bit register of the SEP shadow map; its first
# two 32-bit words sit at 0x109302E0 and 0x109302E4.
SPARE0_W0 = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_SPARE0_BASE_ADDR")
SPARE0_W1 = SPARE0_W0 + 4
# hw/sys/sep/regs/gen/c/sep_addr.h: the EFUSE_INTERFACE_CTRL window ends at BASE + SIZE, below
# EFUSE_MMR_BASE_ADDR; that first word owns no register. hw/sys/sep/doc/otp_fuse_controller.adoc:
# the APB decode answers an address in the span outside the register windows with SLVERR.
HOLE_ADDR = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR") + c_header_u32(
    _SEP_ADDR_H, "SEP_TOP_EFUSE_INTERFACE_CTRL_SIZE"
)
EFUSE_MMR_BASE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR_BASE_ADDR")
if not HOLE_ADDR < EFUSE_MMR_BASE:
    raise RuntimeError(f"hole 0x{HOLE_ADDR:08x} is not below EFUSE_MMR 0x{EFUSE_MMR_BASE:08x}")
# Words written to the SPARE0 words: non-zero and distinct.
PATTERN_A = 0x1357_9BDF
PATTERN_B = 0x2468_ACE0

# hw/sys/smc/doc/memmap.adoc: LOCAL_BASE is 0xC000_0000 and a read from BASE + 0x001_7000 is an
# address between unit apertures that answers DECERR. hw/sys/smc/regs/gen/c/smc_addr.h: CPU_CTRL
# SCRATCH[13], 8-byte stride from 0xC0039080.
LOCAL_BASE = 0xC000_0000
FABRIC_GAP_ADDR = LOCAL_BASE + 0x001_7000
FABRIC_SCRATCH_ADDR = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 13)

# hw/ip/jtag/jtag_intf_unit/doc/interface.adoc, Instruction Encodings: SEP_OTP 0x21..0x26.
IR_SEP_OTP_SERIES_CTRL = dtp_ir_opcode("SEP_OTP_AXI_SERIES_CTRL")
IR_SEP_OTP_SERIES_INCR = dtp_ir_opcode("SEP_OTP_AXI_SERIES_DATA_INCR")
IR_SEP_OTP_SERIES_NO_INCR = dtp_ir_opcode("SEP_OTP_AXI_SERIES_DATA_NO_INCR")
IR_SEP_OTP_SINGLE_OP = dtp_ir_opcode("SEP_OTP_AXI_SINGLE_OP")

# hw/sys/dtp/doc/jtag.adoc, JTAG2AXI bridges table: the SEP OTP bridge is AXI4-Lite with 32-bit
# address and data. hw/ip/jtag/jtag_ptap/doc/architecture.adoc: SINGLE_OP has 2 + S + D/8 + D + A
# bits with S = 2 for D = 32; SERIES_CTRL has 2 + S + P + A + 1 bits with P = 2; the series data
# registers are n = 8 * 2**E bits.
DATA_BITS = 32
SINGLE_OP_BITS = 2 + 2 + DATA_BITS // 8 + DATA_BITS + 32
SERIES_SIZE = 2
SERIES_DATA_BITS = 8 << SERIES_SIZE
SERIES_CTRL_BITS = 2 + 2 + 2 + 32 + 1
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_CTRL op and *_AXI_SINGLE_OP op: 0 is
# OKAY, 1 SLVERR; the series code latches until SERIES_CTRL.reset.
OP_OKAY = J2A_STATUS_SUCCESS
OP_SLVERR = J2A_STATUS_SLVERR
PL_DEPTH = 0
CHAIN_MARKER = 0xA5C3_96E1
CHAIN_MARKER_BITS = 32
SINGLE_CHAIN_SCAN_BITS = 128
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SINGLE_OP, with the SMC fabric widths of
# hw/sys/dtp/doc/jtag.adoc: the fabric bridge SINGLE_OP register is 132 bits.
FABRIC_SINGLE_OP_BITS = SMC_DBG_SINGLE_OP_LEN
# One AR handshake per SMC fabric read on the DTP-to-SMC debug AXI port
# (doc/integrator/src/smu-composition.adoc, SMC Fabric Debug AXI Interface), counted at
# dtp_smc_dbg_ar_count_o.
FABRIC_READS = 2

SENSE_POLL_LIMIT = 2000
SENSE_POLL_CLK = 50
OP_POLL_LIMIT = 16
SINGLE_POLL_LIMIT = 8
POLL_CLK = 16
# TCKs spent in Run-Test/Idle after a data scan so the target can finish
# (hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SINGLE_OP op 3 guidance).
SERIES_IDLE_TCKS = 16

# Wait sites per kind: the sensing wait; the SERIES_CTRL.op polls of S2 (three), S3 (two), S5 (two)
# and S7 (one); the SINGLE_OP capture polls of S4 (two) and S6 (three).
EXPECTED_SITE_KINDS = {"sensing": 1, "op_poll": 8, "single_capture": 5}
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
FENCE_CYCLES = 2
SCANNED_STEPS = STEPS[:-1]
CHECK_ORDER = (
    "CHK-DBG-SEP-OTP-SETUP",
    "CHK-DBG-SEP-OTP-POSCTRL",
    "CHK-DBG-SEP-OTP-HOLE-SINGLE",
    "CHK-DBG-SEP-OTP-HOLE-SERIES",
    "CHK-DBG-SEP-OTP-ISOLATION",
    "CHK-DBG-SEP-OTP-RESET",
)


def _chain_length(captured: int, width: int) -> int:
    """TCKs until the chain marker reappears on TDO, or -1 when it is not found exactly once."""
    bits = [(captured >> i) & 1 for i in range(width)]
    pat = [(CHAIN_MARKER >> i) & 1 for i in range(CHAIN_MARKER_BITS)]
    hits = [
        i for i in range(width - CHAIN_MARKER_BITS + 1) if bits[i : i + CHAIN_MARKER_BITS] == pat
    ]
    return hits[0] if len(hits) == 1 else -1


class smu_dtp_otp_sep_series_error_test_seq:
    """SEP OTP JTAG2AXIL series access, in-span hole response and fabric isolation."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.ir_cur: int | None = None
        self.scans = 0
        self.polls = 0
        self.step_ns: dict[str, float] = {}
        self.step_scans: dict[str, int] = {}
        self.sites: list[dict] = []
        self.checks: dict[str, tuple] = {}
        self.base = (0, 0, 0)
        self.hole_single = (0, 0)
        self.spare_single = (0, 0)
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

    def _site(
        self, kind: str, label: str, bound: int, unit: str, used: int, last: str, expired: bool
    ) -> None:
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

    def _check(self, chk: str, proof: str, got, want) -> None:
        """Queue a compare; its proof line and the compare run in step order at the end."""
        self.checks[chk] = (proof, got, want)

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

    async def _idle(self, tcks: int) -> None:
        for _ in range(tcks):
            await self.jtag.step_tms(0)

    async def _ir(self, opcode: int, label: str) -> None:
        if self.ir_cur == opcode:
            return
        captured = await self.jtag.shift_ir(opcode, width=DTP_IR_WIDTH, back_to_rti=False)
        require_jtag_tdo_resolved(f"IR {label}")
        self.ir_cur = opcode
        self._log(f"SCAN IR {label} w={DTP_IR_WIDTH} in=0x{opcode:x} out=0x{captured:x}")

    async def _dr(
        self, opcode: int, value: int, width: int, label: str, *, counted: bool = True
    ) -> int:
        await self._ir(opcode, label)
        captured = await self.jtag.shift_dr(value, width, back_to_rti=True)
        require_jtag_tdo_resolved(f"DR {label}")
        if counted:
            self.scans += 1
            tag = f"SCAN {self.scans}"
        else:
            self.polls += 1
            tag = f"POLL {self.polls}"
        self._log(f"{tag} DR {label} w={width} in=0x{value:x} out=0x{captured:x}")
        return captured

    async def _ctrl(
        self,
        op: int,
        addr: int,
        label: str,
        *,
        reset: int = 0,
        counted: bool = True,
    ) -> tuple[int, int, int, int, int]:
        """Scan SERIES_CTRL; returns the captured (reset, addr, pl_depth, size, op)."""
        word = pack_otp_series_ctrl(
            op, addr, pipeline_depth=PL_DEPTH, size=SERIES_SIZE, reset=reset
        )
        captured = await self._dr(
            IR_SEP_OTP_SERIES_CTRL, word, SERIES_CTRL_BITS, label, counted=counted
        )
        return unpack_otp_series_ctrl(captured)

    async def _nop_op(self, label: str) -> int:
        """Capture SERIES_CTRL.op with a nop control scan."""
        *_, op = await self._ctrl(J2A_OP_NOP, 0, label)
        return op

    async def _reset_series(self, label: str) -> tuple[int, int]:
        """Write SERIES_CTRL.reset; returns (op captured by the write, op of the next capture)."""
        *_, before = await self._ctrl(J2A_OP_NOP, 0, f"{label}_reset", reset=1)
        return before, await self._nop_op(f"{label}_after_reset")

    async def _wait_op(self, op: int, addr: int, label: str) -> int:
        """Rescan the leg's control word until op leaves 3; returns op."""
        used = 0
        first = None
        while True:
            _, _, field, _, status = await self._ctrl(op, addr, f"{label}_op{used}", counted=False)
            used += 1
            first = field if first is None else first
            if status != J2A_STATUS_BUSY:
                break
            if used >= OP_POLL_LIMIT:
                self._site("op_poll", label, OP_POLL_LIMIT, "captures", used, f"op={status}", True)
            await ClockCycles(self.dut.clk_smu_i, POLL_CLK)
        self._site("op_poll", label, OP_POLL_LIMIT, "captures", used, f"op={status}", False)
        self._log(
            f"OBSERVATION {label} pl_depth field of the first SERIES_CTRL capture measured={first}"
        )
        return status

    async def _data(self, opcode: int, value: int, label: str) -> int:
        captured = await self._dr(opcode, value, SERIES_DATA_BITS, label)
        await self._idle(SERIES_IDLE_TCKS)
        return captured & ((1 << SERIES_DATA_BITS) - 1)

    async def _write_word(self, addr: int, value: int, label: str) -> int:
        """Load a write, shift one NO_INCR word, wait for op; returns op."""
        await self._ctrl(J2A_OP_WRITE, addr, f"{label}_ctrl")
        await self._data(IR_SEP_OTP_SERIES_NO_INCR, value, f"{label}_wr")
        return await self._wait_op(J2A_OP_WRITE, addr, label)

    async def _read_scans(self, opcode: int, addr: int, scans: int, label: str) -> tuple[int, ...]:
        """One SERIES_CTRL read load and `scans` data scans; returns the captures."""
        await self._ctrl(J2A_OP_READ, addr, f"{label}_ctrl")
        return tuple([await self._data(opcode, 0, f"{label}_rd{i}") for i in range(scans)])

    async def _read_word(self, opcode: int, addr: int, label: str) -> tuple[int, int]:
        """Single-load series read, then op; returns (capture 2, op)."""
        caps = await self._read_scans(opcode, addr, 2, label)
        self._log(f"OBSERVATION {label} first capture measured=0x{caps[0]:x}")
        return caps[1], await self._wait_op(J2A_OP_READ, addr, label)

    async def _single_scan(
        self, ir: int, raw: int, width: int, label: str, *, counted: bool = True
    ) -> int:
        return await self._dr(ir, raw, width, label, counted=counted)

    async def _single_done(self, fabric: bool, op: int, addr: int, label: str) -> tuple[int, int]:
        """Issue a SINGLE_OP and capture its status, rescanning while op reads 3, bounded."""
        if fabric:
            ir, width = DTP_IR_SMC_AXI_SINGLE_OP, FABRIC_SINGLE_OP_BITS
            raw = pack_single_op(op, addr, 0, wstrb=0, size=SMC_DBG_AXSIZE_4B)
            unpack = unpack_single_op
        else:
            ir, width = IR_SEP_OTP_SINGLE_OP, SINGLE_OP_BITS
            raw = pack_otp_single_op(op, addr, 0, wstrb=0, size=SERIES_SIZE)
            unpack = unpack_otp_single_op
        await self._single_scan(ir, raw, width, f"{label}_issue")
        used = 0
        while True:
            status, rdata = unpack(
                await self._single_scan(ir, 0, width, f"{label}_c{used}", counted=used == 0)
            )
            used += 1
            if status != J2A_STATUS_BUSY:
                break
            if used >= SINGLE_POLL_LIMIT:
                self._site(
                    "single_capture",
                    label,
                    SINGLE_POLL_LIMIT,
                    "captures",
                    used,
                    f"op={status}",
                    True,
                )
            await ClockCycles(self.dut.clk_smu_i, POLL_CLK)
        self._site(
            "single_capture", label, SINGLE_POLL_LIMIT, "captures", used, f"op={status}", False
        )
        word = (rdata >> 32) & 0xFFFF_FFFF if fabric and addr & 0x4 else rdata & 0xFFFF_FFFF
        self._log(f"CELL {label} op={status} data=0x{word:08x}")
        return status, word

    async def run(self) -> None:
        await self._setup()
        await self._no_incr_write_read()
        await self._incr_reads()
        await self._single_hole()
        await self._series_hole()
        await self._independence_isolation()
        await self._reset_clears()
        await self._finish()

    async def _setup(self) -> None:
        await self._mark("S1", "TAP reset, IDCODE, sensing, gate, counter baseline, series reset")
        self.jtag = jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        self.ir_cur = None
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        self.scans += 1
        idcode = await jtag.read_idcode()
        self.ir_cur = None
        require_jtag_tdo_resolved("IDCODE")
        self._log(f"SCAN {self.scans} DR IDCODE out=0x{idcode:08x}")

        used = 0
        while True:
            lc_state = sample(self.dut.lc_state_o, "lc_state_o")
            if lc_state != LC_STATE_PRESENSE:
                break
            if used >= SENSE_POLL_LIMIT:
                self._site(
                    "sensing",
                    "lc_state",
                    SENSE_POLL_LIMIT,
                    "polls",
                    used,
                    f"lc_state=0x{lc_state:02x}",
                    True,
                )
            used += 1
            await ClockCycles(self.dut.clk_smu_i, SENSE_POLL_CLK)
        self._site(
            "sensing",
            "lc_state",
            SENSE_POLL_LIMIT,
            "polls",
            used,
            f"lc_state=0x{lc_state:02x}",
            False,
        )
        gate = sample(self.dut.tb_otp_jtag2axi_security_disable, "tb_otp_jtag2axi_security_disable")
        if gate != 0:
            raise AssertionError(f"SEP OTP JTAG2AXI still gated: security_disable={gate}")
        self.base = self._counts()
        before, after = await self._reset_series("setup")
        self._check(
            "CHK-DBG-SEP-OTP-SETUP",
            f"lc_state_o 0x{lc_state:02x} left the pre-sense value 0x{LC_STATE_PRESENSE:02x} after "
            f"{used} polls, gate tap read {gate}, IDCODE 0x{idcode:08x}, aw/ar/b baselines "
            f"{self.base} sampled, SERIES_CTRL.reset written (op {before} -> {after}) "
            f"(want a changed state, IDCODE 0x{DTP_DEFAULT_IDCODE:08x}, op {OP_OKAY})",
            (lc_state != LC_STATE_PRESENSE, idcode, after),
            (True, DTP_DEFAULT_IDCODE, OP_OKAY),
        )

    async def _no_incr_write_read(self) -> None:
        await self._mark("S2", "NO_INCR write of two SPARE0 words, NO_INCR read of word 0")
        self.op_wa = await self._write_word(SPARE0_W0, PATTERN_A, "wr_a")
        self.op_wb = await self._write_word(SPARE0_W1, PATTERN_B, "wr_b")
        self.no_incr_rd, self.no_incr_op = await self._read_word(
            IR_SEP_OTP_SERIES_NO_INCR, SPARE0_W0, "no_incr_rd"
        )

    async def _incr_reads(self) -> None:
        await self._mark("S3", "INCR read of two documented words, one load each")
        self.incr_a, self.incr_a_op = await self._read_word(
            IR_SEP_OTP_SERIES_INCR, SPARE0_W0, "incr_a"
        )
        self.incr_b, self.incr_b_op = await self._read_word(
            IR_SEP_OTP_SERIES_INCR, SPARE0_W1, "incr_b"
        )
        stream = await self._read_scans(IR_SEP_OTP_SERIES_INCR, SPARE0_W0, 3, "incr_stream")
        self._log(
            "OBSERVATION three-scan INCR stream from one load measured="
            + str([f"0x{w:08x}" for w in stream])
        )

    async def _single_hole(self) -> None:
        await self._mark("S4", "SINGLE_OP read at the hole, then at SPARE0 word 0")
        cap = await self._single_scan(
            IR_SEP_OTP_SINGLE_OP, CHAIN_MARKER, SINGLE_CHAIN_SCAN_BITS, "single_op_width"
        )
        width = _chain_length(cap, SINGLE_CHAIN_SCAN_BITS)
        hole = await self._single_done(False, J2A_OP_READ, HOLE_ADDR, "hole_single")
        spare = await self._single_done(False, J2A_OP_READ, SPARE0_W0, "spare_single")
        self.hole_single, self.spare_single = hole, spare
        self._log(f"OBSERVATION data word of the SINGLE_OP hole read measured=0x{hole[1]:08x}")
        self._check(
            "CHK-DBG-SEP-OTP-POSCTRL",
            f"NO_INCR write ops {self.op_wa}, {self.op_wb}; NO_INCR read capture 2 "
            f"0x{self.no_incr_rd:08x} op {self.no_incr_op}; INCR single-load reads capture 2 "
            f"0x{self.incr_a:08x} op {self.incr_a_op} and 0x{self.incr_b:08x} op {self.incr_b_op}; "
            f"SINGLE_OP read of 0x{SPARE0_W0:08x} op {spare[0]} data 0x{spare[1]:08x}; SINGLE_OP "
            f"scan {width} bits (want ops {OP_OKAY}, Pa 0x{PATTERN_A:08x}, Pb "
            f"0x{PATTERN_B:08x}, {SINGLE_OP_BITS} bits)",
            (
                self.op_wa,
                self.op_wb,
                self.no_incr_rd,
                self.no_incr_op,
                self.incr_a,
                self.incr_a_op,
                self.incr_b,
                self.incr_b_op,
                spare,
                width,
            ),
            (
                OP_OKAY,
                OP_OKAY,
                PATTERN_A,
                OP_OKAY,
                PATTERN_A,
                OP_OKAY,
                PATTERN_B,
                OP_OKAY,
                (OP_OKAY, PATTERN_A),
                SINGLE_OP_BITS,
            ),
        )
        self._check(
            "CHK-DBG-SEP-OTP-HOLE-SINGLE",
            f"SINGLE_OP read at 0x{HOLE_ADDR:08x} captured op {hole[0]}, the SINGLE_OP read of "
            f"0x{SPARE0_W0:08x} right after it op {spare[0]} data 0x{spare[1]:08x} "
            f"(want op {OP_SLVERR}, op {OP_OKAY} with Pa 0x{PATTERN_A:08x})",
            (hole[0], spare),
            (OP_SLVERR, (OP_OKAY, PATTERN_A)),
        )

    async def _series_hole(self) -> None:
        await self._mark("S5", "series beat at the hole, then a clean beat")
        before = await self._nop_op("hole_before")
        await self._ctrl(J2A_OP_READ, HOLE_ADDR, "hole_ctrl")
        marker = await self._data(IR_SEP_OTP_SERIES_NO_INCR, 0, "hole_rd")
        self._log(f"OBSERVATION series hole beat marker capture measured=0x{marker:08x}")
        after = await self._wait_op(J2A_OP_READ, HOLE_ADDR, "hole")
        caps = await self._read_scans(IR_SEP_OTP_SERIES_NO_INCR, SPARE0_W0, 2, "clean_after_hole")
        self._log(
            f"OBSERVATION first capture of the SPARE0 load after the series hole beat "
            f"measured=0x{caps[0]:08x}"
        )
        clean_op = await self._wait_op(J2A_OP_READ, SPARE0_W0, "clean_after_hole")
        self.hole_series = (before, after, caps[1], clean_op)

    async def _independence_isolation(self) -> None:
        await self._mark("S6", "SINGLE_OP beside the latched code, counters, fabric reads")
        single = await self._single_done(False, J2A_OP_READ, SPARE0_W0, "latched_single")
        latched = await self._nop_op("latched_op")
        self._check(
            "CHK-DBG-SEP-OTP-HOLE-SERIES",
            f"SERIES_CTRL.op {self.hole_series[0]} before the hole beat and {self.hole_series[1]} "
            f"after it; the SPARE0 beat after it returned 0x{self.hole_series[2]:08x} with op "
            f"{self.hole_series[3]}; after a SINGLE_OP read (op {single[0]} data "
            f"0x{single[1]:08x}) op {latched} (want {OP_OKAY}, {OP_SLVERR}, Pa 0x{PATTERN_A:08x}, "
            f"{OP_SLVERR}, op {OP_OKAY} with Pa, {OP_SLVERR})",
            (*self.hole_series, single, latched),
            (OP_OKAY, OP_SLVERR, PATTERN_A, OP_SLVERR, (OP_OKAY, PATTERN_A), OP_SLVERR),
        )
        otp_counts = self._counts()
        gap_op, gap_word = await self._single_done(True, J2A_OP_READ, FABRIC_GAP_ADDR, "fabric_gap")
        scratch_op, _ = await self._single_done(True, J2A_OP_READ, FABRIC_SCRATCH_ADDR, "fabric_rd")
        deltas = self._delta(self._counts(), otp_counts)
        self._log(f"OBSERVATION fabric gap read data measured=0x{gap_word:08x}")
        self._check(
            "CHK-DBG-SEP-OTP-ISOLATION",
            f"aw/ar/b {otp_counts} after the SEP OTP traffic against baselines {self.base}; "
            f"fabric gap read op {gap_op}, the read of 0x{FABRIC_SCRATCH_ADDR:08x} op {scratch_op} "
            f"with aw/ar/b delta {deltas} (want equal baselines, op {J2A_STATUS_DECERR}, "
            f"op {OP_OKAY}, delta (0, {FABRIC_READS}, 0))",
            (otp_counts, gap_op, scratch_op, deltas),
            (self.base, J2A_STATUS_DECERR, OP_OKAY, (0, FABRIC_READS, 0)),
        )

    async def _reset_clears(self) -> None:
        await self._mark("S7", "SERIES_CTRL.reset clears the code, series over SPARE0 completes")
        before, after = await self._reset_series("clear")
        caps = await self._read_scans(IR_SEP_OTP_SERIES_NO_INCR, SPARE0_W0, 2, "after_reset")
        self._log(f"OBSERVATION marker beat after the reset measured=0x{caps[0]:08x}")
        op = await self._wait_op(J2A_OP_READ, SPARE0_W0, "after_reset")
        self._check(
            "CHK-DBG-SEP-OTP-RESET",
            f"SERIES_CTRL write with bit 38 set captured op {before} and the next capture op "
            f"{after}; the series read after it returned 0x{caps[1]:08x} with op {op} "
            f"(want op {OP_SLVERR}, op {OP_OKAY}, Pa 0x{PATTERN_A:08x}, op {OP_OKAY})",
            (before, after, caps[1], op),
            (OP_SLVERR, OP_OKAY, PATTERN_A, OP_OKAY),
        )

    async def _finish(self) -> None:
        sb = self.sb
        await self._mark("S8", "ordered checker lines, wait sites and the pass stamp")
        failures = []

        def run_check(chk: str, name: str, got, want) -> None:
            try:
                sb.expect_eq(name, got, want, evidence=chk)
            except AssertionError as exc:
                failures.append(str(exc))

        for chk in CHECK_ORDER:
            proof, got, want = self.checks[chk]
            self._log(f"{chk}: {proof}")
            run_check(chk, chk, got, want)

        for rec in self.sites:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        no_last = [rec["label"] for rec in self.sites if not rec["last"]]
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={kinds} expired={expired} "
            f"without_last_state={no_last} (want kinds {EXPECTED_SITE_KINDS}, expired 0)"
        )
        run_check(
            "CHK-TIMEOUT-PATHS",
            "wait records",
            (expired, no_last, kinds),
            (0, [], EXPECTED_SITE_KINDS),
        )

        await ClockCycles(self.dut.clk_smu_i, FENCE_CYCLES)
        self.step_ns["PASS"] = self._now()
        self.step_scans["PASS"] = self.scans
        fence_order = [*STEPS, "PASS"]
        stamps = [self.step_ns[s] for s in fence_order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        counts = tuple(
            self.step_scans[b] - self.step_scans[a] for a, b in zip(SCANNED_STEPS, STEPS[1:])
        )
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(fence_order, stamps))
        self._log(
            f"CHK-NONVAC: ordered sim-time fence {fence} scans={self.scans} polls={self.polls} "
            f"scans per step S1..S7={counts}"
        )
        run_check(
            "CHK-NONVAC", "CHK-NONVAC ordered sim-time fence", all(d > 0 for d in deltas), True
        )
        run_check(
            "CHK-NONVAC",
            "CHK-NONVAC scans per step",
            tuple(n > 0 for n in counts),
            (True,) * len(SCANNED_STEPS),
        )
        if failures:
            raise AssertionError(f"{len(failures)} checker compare(s) failed: {failures}")
        self.done = True
