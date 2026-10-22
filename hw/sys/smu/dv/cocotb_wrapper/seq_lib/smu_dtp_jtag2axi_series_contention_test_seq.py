# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC fabric JTAG2AXI series datapath, sticky status and single-operation contention.

The sequence scans the SMC fabric bridge of the primary TAP and proves, through the write-launch and
write-response counters at the SMU boundary and SINGLE_OP read-backs of the landed words, that
SERIES_DATA_INCR carries 32-bit and 64-bit words to the SMC scratch words, that
SERIES_DATA_NO_INCR keeps its address and places a 32-bit payload on the lanes its address selects,
that SERIES_DATA_WITH_ERROR_STATUS honours its per-scan increment bit and that queued writes of
pipeline depth 0 and 3 land in order. A series read is compared only as one SERIES_CTRL read load
followed by two data scans; longer read streams, marker beats and the pl_depth field of captures
are measured and logged only. SERIES_CTRL.op latches the first failure (SLVERR from an empty
mailbox read, or DECERR) until SERIES_CTRL.reset, SINGLE_OP status neither changes nor
depends on that code, and that a SINGLE_OP scan with no Run-Test/Idle TCK after the previous one is
measured while the spaced retry completes.

Sources: hw/ip/jtag/jtag_ptap/doc/architecture.adoc (*_AXI_SINGLE_OP, *_AXI_SERIES_CTRL,
*_AXI_SERIES_DATA_INCR, *_AXI_SERIES_DATA_NO_INCR, *_AXI_SERIES_DATA_WITH_ERROR_STATUS and the
JTAG2AXI capability fields), hw/sys/dtp/doc/jtag.adoc (JTAG2AXI bridge table) and
hw/sys/smc/doc/memmap.adoc (DECERR with 0xBADCAB1E between unit apertures) and
hw/ip/axi_lite_mailbox_unit/doc/interface.adoc (SLVERR with 0xFEEDDEAD, READ_DATA while empty).
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
    DTP_IR_SMC_AXI_SERIES_CTRL,
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
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SERIES_CTRL_LEN,
    SMC_DBG_SINGLE_OP_LEN,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    pack_single_op,
    pack_smc_series_ctrl,
    require_jtag_tdo_resolved,
    unpack_single_op,
    unpack_smc_series_ctrl,
)

# hw/sys/smc/doc/memmap.adoc: LOCAL_BASE is 0xC000_0000.
LOCAL_BASE = 0xC000_0000
# hw/sys/smc/doc/memmap.adoc: BASE + 0x001_7000 through BASE + 0x001_7FFF lies between unit
# apertures, which answer DECERR. The response of a write over this bridge is logged and not
# compared.
SLVERR_WINDOW = LOCAL_BASE + 0x001_7000
WINDOW_WRITE_WORD = 0xDEAD_0001
# hw/sys/smc/regs/gen/c/smc_addr.h: outbound mailbox 0 READ_DATA and STATUS.
MBX_READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR")
MBX_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
# hw/ip/axi_lite_mailbox_unit/regs STATUS.EMPTY bit mask (generated mailbox header).
ST_EMPTY = mailbox_u32("AXIL_MAILBOX__STATUS__EMPTY_bm")
# hw/ip/axi_lite_mailbox_unit/doc/interface.adoc, Access Results: a read of READ_DATA while the
# mailbox is empty answers SLVERR with data 0xFEEDDEAD.
EMPTY_READ_DATA = 0xFEED_DEAD
# hw/sys/smc/doc/memmap.adoc: a read between unit apertures returns 0xBADCAB1E.
DECERR_READ_DATA = 0xBADC_AB1E
# hw/sys/smc/regs/gen/c/smc_addr.h: SCRATCH_COLD_WARM is eight 32-bit words at 0xC0002880
# (hw/sys/smc/regs/blocks/scratch/scratch.rdl).
_SCRATCH_WARM = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR"
# hw/sys/smc/regs/gen/c/smc_addr.h: CPU_CTRL SCRATCH, 8-byte stride; the register implements
# data[31:0] only (hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl).
_CPU_SCRATCH = "SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR"
SCRATCH_WORDS = 8
CPU_SCRATCH_INDEX = 8

# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_CTRL: 2 + S + P + A + 1 bits; with the
# 56-bit address of hw/sys/dtp/doc/jtag.adoc (JTAG2AXI bridge table) that is 63.
SERIES_CTRL_BITS = 63
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_DATA_WITH_ERROR_STATUS: n + 1 bits for
# n = 8 * 2**E, E = 2.
WES_BITS = 33
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_DATA_INCR: n = 8 * 2**E bits.
DATA_BITS_E2 = 8 << SMC_DBG_AXSIZE_4B
DATA_BITS_E3 = 8 << SMC_DBG_AXSIZE_8B
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_CTRL op and *_AXI_SINGLE_OP op.
OP_OKAY = 0
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, JTAG2AXI capability fields: the pipeline depth fields
# of the bridge range up to 3.
PL_DEPTHS = (0, 3)
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_DATA_WITH_ERROR_STATUS: the bit shifted
# out reports 0 for a transaction that succeeded and 1 for one that failed.
STATUS_SUCCEEDED = 0
STATUS_FAILED = 1

WORDS = tuple(0xA5A5_0001 + i for i in range(SCRATCH_WORDS))
E3_WORDS = (0x5A5A_0008, 0x5A5A_0009)
NO_INCR_WORDS = (0xC3C3_0001, 0xC3C3_0002, 0xC3C3_0003)
WES_WORDS = tuple(0xE1E1_0000 + i for i in range(4))
WES_WRITE_INCREMENTS = (1, 0, 1, 1)
CLEAN_WORD = 0x600D_0006
CLEAN_INDEX = 6
LAST_INDEX = 7
READBACK_INDEXES = (0, 1, CLEAN_INDEX, LAST_INDEX)
NO_INCR_INDEX = 5
NEIGHBOUR_INDEX = 4
CHAIN_MARKER = 0xA5C3_96E1
CHAIN_MARKER_BITS = 32
CTRL_CHAIN_SCAN_BITS = 128
WES_CHAIN_SCAN_BITS = 96


def _pipeline_words(depth: int) -> tuple[int, int]:
    return (0x0D0D_0000 + 0x100 * depth, 0x0D0D_0000 + 0x100 * depth + 1)


GATE_POLL_LIMIT = 400
GATE_POLL_CLK = 50
OP_POLL_LIMIT = 16
B_POLL_LIMIT = 64
B_POLL_CLK = 4
SINGLE_POLL_LIMIT = 8
POLL_CLK = 16
UNSPACED_ATTEMPTS = 8
RETRY_POLL_LIMIT = 16
# TCKs spent in Run-Test/Idle after a data scan or an operation so the target can finish
# (hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SINGLE_OP op 3 guidance).
SERIES_IDLE_TCKS = 16
SINGLE_IDLE_TCKS = 64

# Wait sites per kind: the gate wait; the SERIES_CTRL.op polls of S2, S4, S5, S6, S7 (two), S8
# (three) and S9 (two); the B counter waits of S2, S4, S5, S6 and S7 (two); the SINGLE_OP capture
# polls of S3 (four), S4 (two), S5 (three), S6 (three), S7 (four), S8 (two) and S10 (two); and the
# unspaced-attempt loop of S11 and one retry capture site for the whole loop, however many attempts
# it makes.
EXPECTED_SITE_KINDS = {
    "gate": 1,
    "op_poll": 11,
    "b_count": 6,
    "single_capture": 20,
    "unspaced_attempts": 1,
    "retry_capture": 1,
}
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12")
FENCE_CYCLES = 2
SCANNED_STEPS = STEPS[:-1]


def _word_addr(idx: int) -> int:
    return smc_indexed_addr(_SCRATCH_WARM, idx)


def _mask(width: int) -> int:
    return (1 << width) - 1


def _lane_word(rdata: int, addr: int) -> int:
    return ((rdata >> 32) if addr & 0x4 else rdata) & 0xFFFF_FFFF


def _chain_length(captured: int, width: int) -> int:
    """TCKs until the chain marker reappears on TDO, or -1 when it is not found exactly once."""
    bits = [(captured >> i) & 1 for i in range(width)]
    pat = [(CHAIN_MARKER >> i) & 1 for i in range(CHAIN_MARKER_BITS)]
    hits = [
        i for i in range(width - CHAIN_MARKER_BITS + 1) if bits[i : i + CHAIN_MARKER_BITS] == pat
    ]
    return hits[0] if len(hits) == 1 else -1


class smu_dtp_jtag2axi_series_contention_test_seq:
    """SMC fabric JTAG2AXI series data, sticky status and single-operation contention."""

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
        self.checks: list[tuple] = []
        self.done = False
        self.base = (0, 0, 0)
        self.retry_polls_max = 0
        self.slverr_reset = (0, 0)
        self.okay_after_slverr_reset = 0
        self.op_data = {
            "INCR": dtp_ir_opcode("SMC_AXI_SERIES_DATA_INCR"),
            "NO_INCR": dtp_ir_opcode("SMC_AXI_SERIES_DATA_NO_INCR"),
            "WES": dtp_ir_opcode("SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS"),
        }

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
        self.checks.append((chk, proof, got, want))

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
        self,
        opcode: int,
        value: int,
        width: int,
        label: str,
        *,
        counted: bool = True,
        back_to_rti: bool = True,
    ) -> int:
        await self._ir(opcode, label)
        captured = await self.jtag.shift_dr(value, width, back_to_rti=back_to_rti)
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
        size: int,
        pl_depth: int,
        label: str,
        *,
        reset: int = 0,
        counted: bool = True,
    ) -> tuple[int, int, int, int, int]:
        """Scan SERIES_CTRL; returns the captured (reset, addr, pl_depth, size, op)."""
        word = pack_smc_series_ctrl(op, addr, pipeline_depth=pl_depth, size=size, reset=reset)
        captured = await self._dr(
            DTP_IR_SMC_AXI_SERIES_CTRL, word, SMC_DBG_SERIES_CTRL_LEN, label, counted=counted
        )
        return unpack_smc_series_ctrl(captured)

    async def _nop_op(self, label: str) -> int:
        """Capture SERIES_CTRL.op with a nop control scan."""
        *_, op = await self._ctrl(J2A_OP_NOP, 0, SMC_DBG_AXSIZE_4B, 0, label)
        return op

    async def _reset_series(self, label: str) -> tuple[int, int]:
        """Write SERIES_CTRL.reset; returns (op captured by the write, op of the next capture)."""
        *_, before = await self._ctrl(
            J2A_OP_NOP, 0, SMC_DBG_AXSIZE_4B, 0, f"{label}_reset", reset=1
        )
        return before, await self._nop_op(f"{label}_after_reset")

    async def _wait_op(
        self, op: int, addr: int, size: int, pl_depth: int, label: str
    ) -> tuple[int, int]:
        """Rescan the leg's control word until op leaves 3; returns (first pl_depth field, op)."""
        used = 0
        first = None
        while True:
            _, _, field, _, status = await self._ctrl(
                op, addr, size, pl_depth, f"{label}_op{used}", counted=False
            )
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
        return first, status

    async def _wait_b(self, base: tuple[int, int, int], want: int, label: str) -> None:
        """Poll the B counter at the SMU boundary until it shows `want` completions."""
        used = 0
        while True:
            delta = self._delta(self._counts(), base)[2]
            if delta >= want:
                break
            if used >= B_POLL_LIMIT:
                self._site("b_count", label, B_POLL_LIMIT, "polls", used, f"b_delta={delta}", True)
            used += 1
            await ClockCycles(self.dut.clk_smu_i, B_POLL_CLK)
        self._site("b_count", label, B_POLL_LIMIT, "polls", used, f"b_delta={delta}", False)

    async def _data(
        self, kind: str, value: int, width: int, label: str, *, idle: bool = True
    ) -> int:
        captured = await self._dr(self.op_data[kind], value, width, label)
        if idle:
            await self._idle(SERIES_IDLE_TCKS)
        return captured & _mask(width)

    async def _wes(self, data: int, inc: int, label: str) -> tuple[int, int]:
        cap = await self._data("WES", (inc << 32) | data, WES_BITS, label)
        return cap & 0xFFFF_FFFF, (cap >> 32) & 1

    async def _measure_width(self, opcode: int, scan_bits: int, label: str) -> int:
        """Scan a marker through a data register held under a nop control; returns its length."""
        cap = await self._dr(opcode, CHAIN_MARKER, scan_bits, label)
        return _chain_length(cap, scan_bits)

    async def _write_series(
        self, kind: str, addr: int, size: int, words: tuple[int, ...], label: str, **kw
    ) -> tuple[int, int, int]:
        """Load a write, shift the words, wait for op and the B counter; returns (op, aw, b)."""
        width = 8 << size
        base = self._counts()
        await self._ctrl(J2A_OP_WRITE, addr, size, 0, f"{label}_ctrl")
        for i, word in enumerate(words):
            await self._data(kind, word, width, f"{label}_wr{i}", **kw)
        _, op = await self._wait_op(J2A_OP_WRITE, addr, size, 0, label)
        await self._wait_b(base, len(words), label)
        aw_d, _, b_d = self._delta(self._counts(), base)
        last = await self._ctrl(J2A_OP_NOP, 0, size, 0, f"{label}_address")
        self._log(f"OBSERVATION {label} address field after the series measured=0x{last[1]:x}")
        return op, aw_d, b_d

    async def _single_load_read(
        self, kind: str, addr: int, size: int, label: str
    ) -> tuple[int, int]:
        """One SERIES_CTRL read load and two data scans; returns (capture 1, capture 2)."""
        caps = await self._read_stream(kind, addr, size, 2, label)
        return caps[0], caps[1]

    async def _read_stream(
        self, kind: str, addr: int, size: int, scans: int, label: str
    ) -> tuple[int, ...]:
        width = 8 << size
        await self._ctrl(J2A_OP_READ, addr, size, 0, f"{label}_ctrl")
        return tuple([await self._data(kind, 0, width, f"{label}_rd{i}") for i in range(scans)])

    async def _single(
        self, op: int, addr: int, data: int, wstrb: int, label: str, *, rti: bool = True
    ) -> tuple[int, int]:
        """One SINGLE_OP scan; returns (op, rdata) captured, which belong to the previous scan."""
        raw = pack_single_op(op, addr, data, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)
        cap = await self._dr(
            DTP_IR_SMC_AXI_SINGLE_OP, raw, SMC_DBG_SINGLE_OP_LEN, label, back_to_rti=rti
        )
        return unpack_single_op(cap)

    async def _single_capture(self, label: str, *, counted: bool = True) -> tuple[int, int]:
        cap = await self._dr(
            DTP_IR_SMC_AXI_SINGLE_OP, 0, SMC_DBG_SINGLE_OP_LEN, label, counted=counted
        )
        return unpack_single_op(cap)

    async def _single_done(
        self, op: int, addr: int, data: int, wstrb: int, label: str, size: int = SMC_DBG_AXSIZE_4B
    ) -> tuple[int, int]:
        """Issue a SINGLE_OP and capture its status, rescanning while op reads 3, bounded."""
        raw = pack_single_op(op, addr, data, wstrb=wstrb, size=size)
        await self._dr(DTP_IR_SMC_AXI_SINGLE_OP, raw, SMC_DBG_SINGLE_OP_LEN, f"{label}_issue")
        used = 0
        while True:
            status, rdata = await self._single_capture(f"{label}_c{used}", counted=used == 0)
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
        return status, rdata

    async def _read_word(self, addr: int, label: str) -> tuple[int, int]:
        """SINGLE_OP read of a 32-bit word; returns (op, word)."""
        status, rdata = await self._single_done(J2A_OP_READ, addr, 0, 0, label)
        return status, _lane_word(rdata, addr)

    async def _retry_capture(self, label: str) -> tuple[int, int]:
        """Capture a SINGLE_OP status, rescanning while it reads BUSY, bounded."""
        used = 0
        while True:
            status, rdata = await self._single_capture(f"{label}_c{used}", counted=used == 0)
            used += 1
            if status != J2A_STATUS_BUSY:
                self.retry_polls_max = max(self.retry_polls_max, used)
                return status, rdata
            if used >= RETRY_POLL_LIMIT:
                self._site(
                    "retry_capture",
                    label,
                    RETRY_POLL_LIMIT,
                    "captures",
                    used,
                    f"op={status}",
                    True,
                )
            await ClockCycles(self.dut.clk_smu_i, POLL_CLK)

    async def run(self) -> None:
        await self._setup()
        await self._incr()
        await self._no_incr()
        await self._error_status()
        await self._pipeline()
        await self._sticky_slverr_first()
        await self._sticky_decerr_first()
        await self._single_independence()
        await self._unspaced_single()
        await self._finish()

    async def _setup(self) -> None:
        await self._mark("S1", "TAP reset, IDCODE, gate, counter baseline, SERIES_CTRL scan, reset")
        self.jtag = jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        self.ir_cur = None
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        self.scans += 1
        idcode = await jtag.read_idcode()
        self.ir_cur = None
        require_jtag_tdo_resolved("IDCODE")
        self._log(f"SCAN {self.scans} DR IDCODE out=0x{idcode:08x}")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:08x} got 0x{idcode:08x}")

        gate = self.dut.tb_smc_jtag2axi_security_disable
        used = 0
        while True:
            val = gate.value
            if val.is_resolvable and int(val) == 0:
                break
            if used >= GATE_POLL_LIMIT:
                self._site(
                    "gate", "security_disable", GATE_POLL_LIMIT, "polls", used, str(val), True
                )
            used += 1
            await ClockCycles(self.dut.clk_smu_i, GATE_POLL_CLK)
        self._site("gate", "security_disable", GATE_POLL_LIMIT, "polls", used, str(val), False)
        gate_value = int(gate.value)

        self.base = self._counts()
        length = await self._measure_width(
            DTP_IR_SMC_AXI_SERIES_CTRL, CTRL_CHAIN_SCAN_BITS, "series_ctrl_width"
        )
        fields = await self._ctrl(J2A_OP_NOP, 0, SMC_DBG_AXSIZE_4B, 0, "series_ctrl_fields")
        self._log(
            "OBSERVATION SERIES_CTRL fields (reset, addr, pl_depth, size, op) "
            f"measured={fields} width measured={length}"
        )
        before, after = await self._reset_series("setup")
        self._check(
            "CHK-DBG-J2A-SERIES-SETUP",
            f"gate tap read {gate_value} after {used} polls, SERIES_CTRL scan {length} bits, "
            f"baselines aw/ar/b={self.base}, SERIES_CTRL.reset written (op {before} -> {after}) "
            f"(want {SERIES_CTRL_BITS} bits, op 0)",
            (length, after),
            (SERIES_CTRL_BITS, OP_OKAY),
        )

    async def _incr(self) -> None:
        w0 = _word_addr(0)
        size = SMC_DBG_AXSIZE_4B
        await self._mark("S2", "INCR write E=2 of eight words")
        base = self._counts()
        await self._ctrl(J2A_OP_WRITE, w0, size, 0, "incr_wr_ctrl")
        for i, word in enumerate(WORDS):
            await self._data("INCR", word, DATA_BITS_E2, f"incr_wr_wr{i}")
        _, wr_op = await self._wait_op(J2A_OP_WRITE, w0, size, 0, "incr_wr")
        await self._wait_b(base, SCRATCH_WORDS, "incr_wr")
        aw_d, _, b_d = self._delta(self._counts(), base)
        last = await self._ctrl(J2A_OP_NOP, 0, size, 0, "incr_wr_address")
        self._log(f"OBSERVATION address field after the write series measured=0x{last[1]:x}")

        await self._mark("S3", "SINGLE_OP read-back, read stream, single-load read")
        readback = []
        for i in READBACK_INDEXES:
            readback.append(await self._read_word(_word_addr(i), f"incr_rb{i}"))
        base = self._counts()
        stream = await self._read_stream("INCR", w0, size, SCRATCH_WORDS, "incr_stream")
        _, ar_d, _ = self._delta(self._counts(), base)
        self._log(
            f"OBSERVATION INCR read stream captures measured={[hex(c) for c in stream]} "
            f"ar delta measured={ar_d}"
        )
        first, second = await self._single_load_read("INCR", _word_addr(1), size, "incr_single")
        self._log(f"OBSERVATION single-load read first capture measured=0x{first:x}")

        await self._mark("S4", "E=3 write and SINGLE_OP read-back at CPU_CTRL SCRATCH(8)")
        cpu = smc_indexed_addr(_CPU_SCRATCH, CPU_SCRATCH_INDEX)
        e3_op, e3_aw, e3_b = await self._write_series(
            "INCR", cpu, SMC_DBG_AXSIZE_8B, E3_WORDS, "e3_wr"
        )
        e3_read = []
        for i in range(2):
            status, rdata = await self._single_done(
                J2A_OP_READ, cpu + 8 * i, 0, 0, f"e3_rb{i}", SMC_DBG_AXSIZE_8B
            )
            e3_read.append((status, rdata))
        self._check(
            "CHK-DBG-J2A-SERIES-INCR",
            f"E=2 write: aw/b delta {aw_d}/{b_d} (want {SCRATCH_WORDS}), op {wr_op} (want 0); "
            f"SINGLE_OP read-backs (op, word) {readback} (want op 0 with W0, W1, W6, W7 "
            f"{[hex(WORDS[i]) for i in READBACK_INDEXES]}); single-load read capture 2 "
            f"0x{second:08x} (want W1 "
            f"0x{WORDS[1]:08x}); E=3 ({DATA_BITS_E3}-bit): op {e3_op}, aw/b delta {e3_aw}/{e3_b} "
            f"(want {len(E3_WORDS)}), read-backs {e3_read} (want op 0 with "
            f"{[hex(w) for w in E3_WORDS]}); read stream and AR delta measured and logged only",
            (aw_d, b_d, wr_op, tuple(readback), second, e3_op, e3_aw, e3_b, tuple(e3_read)),
            (
                SCRATCH_WORDS,
                SCRATCH_WORDS,
                OP_OKAY,
                tuple((J2A_STATUS_SUCCESS, WORDS[i]) for i in READBACK_INDEXES),
                WORDS[1],
                OP_OKAY,
                len(E3_WORDS),
                len(E3_WORDS),
                tuple((J2A_STATUS_SUCCESS, w) for w in E3_WORDS),
            ),
        )

    async def _no_incr(self) -> None:
        await self._mark("S5", "NO_INCR write, SINGLE_OP read-back, NO_INCR read, rewrite")
        w5, w4 = _word_addr(NO_INCR_INDEX), _word_addr(NEIGHBOUR_INDEX)
        x1, x2, x3 = NO_INCR_WORDS
        size = SMC_DBG_AXSIZE_4B
        wr_op, aw_d, b_d = await self._write_series("NO_INCR", w5, size, (x1, x2), "noinc_wr")
        read5 = await self._read_word(w5, "noinc_rb5")
        read4 = await self._read_word(w4, "noinc_rb4")
        first, pre = await self._single_load_read("NO_INCR", w5, size, "noinc_rd")
        self._log(f"OBSERVATION NO_INCR read first capture measured=0x{first:x}")
        wr_status, _ = await self._single_done(J2A_OP_WRITE, w5, x3 << 32, 0xF0, "rewrite_single")
        first, post = await self._single_load_read("NO_INCR", w5, size, "rewrite_rd")
        self._log(f"OBSERVATION NO_INCR rewrite read first capture measured=0x{first:x}")
        self._check(
            "CHK-DBG-J2A-SERIES-NOINCR",
            f"NO_INCR write at word 5: op {wr_op}, aw/b delta {aw_d}/{b_d} (want 2); read-back "
            f"word 5 {read5} (want op 0, X2 0x{x2:08x}); neighbour word 4 {read4} (want op 0, W4 "
            f"0x{WORDS[NEIGHBOUR_INDEX]:08x}); NO_INCR read before the rewrite 0x{pre:08x} (want "
            f"X2), rewrite op {wr_status}, read after it 0x{post:08x} (want X3 0x{x3:08x})",
            (wr_op, aw_d, b_d, read5, read4, pre, wr_status, post),
            (
                OP_OKAY,
                2,
                2,
                (J2A_STATUS_SUCCESS, x2),
                (J2A_STATUS_SUCCESS, WORDS[NEIGHBOUR_INDEX]),
                x2,
                J2A_STATUS_SUCCESS,
                x3,
            ),
        )

    async def _error_status(self) -> None:
        await self._mark("S6", "WITH_ERROR_STATUS write, read-back and single-load read")
        w0 = _word_addr(0)
        size = SMC_DBG_AXSIZE_4B
        await self._ctrl(J2A_OP_NOP, 0, size, 0, "wes_width_ctrl")
        length = await self._measure_width(self.op_data["WES"], WES_CHAIN_SCAN_BITS, "wes_width")
        base = self._counts()
        await self._ctrl(J2A_OP_WRITE, w0, size, 0, "wes_wr_ctrl")
        wr_status = []
        for i, inc in enumerate(WES_WRITE_INCREMENTS):
            _, status = await self._wes(WES_WORDS[i], inc, f"wes_wr{i}")
            wr_status.append(status)
        _, wr_op = await self._wait_op(J2A_OP_WRITE, w0, size, 0, "wes_wr")
        await self._wait_b(base, len(WES_WRITE_INCREMENTS), "wes_wr")
        aw_d, _, b_d = self._delta(self._counts(), base)
        landed = tuple([await self._read_word(_word_addr(i), f"wes_rb{i}") for i in range(3)])
        await self._ctrl(J2A_OP_READ, w0, size, 0, "wes_rd_ctrl")
        rd = [await self._wes(0, inc, f"wes_rd{i}") for i, inc in enumerate((1, 0))]
        self._log(f"OBSERVATION WES single-load first capture measured=0x{rd[0][0]:x}")
        await self._ctrl(J2A_OP_READ, SLVERR_WINDOW, size, 0, "wes_err_ctrl")
        err = [await self._wes(0, 0, f"wes_err{i}") for i in range(2)]
        self._log(f"OBSERVATION WES gap read first capture measured=0x{err[0][0]:x}")
        err_reset = await self._reset_series("wes_err")
        self._check(
            "CHK-DBG-J2A-SERIES-ERRSTATUS",
            f"scan width {length} bits (want {WES_BITS}); write series (increments "
            f"{WES_WRITE_INCREMENTS}) status bits {tuple(wr_status)} (want all "
            f"{STATUS_SUCCEEDED}), op {wr_op}, aw/b delta {aw_d}/{b_d} (want "
            f"{len(WES_WRITE_INCREMENTS)}); read-backs of words 0..2 {landed} (want op 0 with "
            f"P0, P2, P3); single-load read capture 2 0x{rd[1][0]:08x} status {rd[1][1]} (want "
            f"P0 0x{WES_WORDS[0]:08x}, status {STATUS_SUCCEEDED}); read of 0x{SLVERR_WINDOW:08x} "
            f"followed by two scans with increment 0: status of the second {err[1][1]} (want "
            f"{STATUS_FAILED}); SERIES_CTRL.reset then op {err_reset[0]} -> {err_reset[1]} (want "
            f"{J2A_STATUS_DECERR} -> {OP_OKAY})",
            (length, tuple(wr_status), wr_op, aw_d, b_d, landed, rd[1], err[1][1], err_reset),
            (
                WES_BITS,
                (STATUS_SUCCEEDED,) * len(WES_WRITE_INCREMENTS),
                OP_OKAY,
                len(WES_WRITE_INCREMENTS),
                len(WES_WRITE_INCREMENTS),
                (
                    (J2A_STATUS_SUCCESS, WES_WORDS[0]),
                    (J2A_STATUS_SUCCESS, WES_WORDS[2]),
                    (J2A_STATUS_SUCCESS, WES_WORDS[3]),
                ),
                (WES_WORDS[0], STATUS_SUCCEEDED),
                STATUS_FAILED,
                (J2A_STATUS_DECERR, OP_OKAY),
            ),
        )

    async def _pipeline(self) -> None:
        await self._mark("S7", "back-to-back queued writes for pl_depth 0 and 3, read-back")
        w0 = _word_addr(0)
        size = SMC_DBG_AXSIZE_4B
        got, want = [], []
        for depth in PL_DEPTHS:
            c0, c1 = _pipeline_words(depth)
            base = self._counts()
            await self._ctrl(J2A_OP_WRITE, w0, size, depth, f"pl{depth}_wr_ctrl")
            # Each beat passes through one Run-Test/Idle TCK, the master's back_to_rti, and no
            # further idle TCKs.
            for i, word in enumerate((c0, c1)):
                await self._data("INCR", word, DATA_BITS_E2, f"pl{depth}_wr{i}", idle=False)
            first, _ = await self._wait_op(J2A_OP_WRITE, w0, size, depth, f"pl{depth}_wr")
            self._log(
                f"OBSERVATION pl_depth {depth} pending indication right after the last beat "
                f"measured={first}"
            )
            await self._wait_b(base, 2, f"pl{depth}_wr")
            aw_d, _, b_d = self._delta(self._counts(), base)
            landed = (
                await self._read_word(w0, f"pl{depth}_rb0"),
                await self._read_word(w0 + 4, f"pl{depth}_rb1"),
            )
            op_after = await self._nop_op(f"pl{depth}_after")
            got.append((aw_d, b_d, landed, op_after))
            want.append((2, 2, ((J2A_STATUS_SUCCESS, c0), (J2A_STATUS_SUCCESS, c1)), OP_OKAY))
        self._check(
            "CHK-DBG-J2A-SERIES-PIPELINE",
            f"per pl_depth {PL_DEPTHS} (aw delta, b delta, read-backs of words 0 and 1, op after "
            f"the leg): {got} (want {want}) at jtag_period_ns={self.cfg.jtag_period_ns}",
            tuple(got),
            tuple(want),
        )

    async def _sticky_slverr_first(self) -> None:
        await self._mark("S8", "sticky SLVERR first from the empty mailbox read, OKAY, DECERR")
        size = SMC_DBG_AXSIZE_4B
        w6 = _word_addr(CLEAN_INDEX)
        await self._reset_series("slverr_start")
        status_op, status_word = await self._read_word(MBX_STATUS, "mbx_status")
        first, mbx = await self._single_load_read("INCR", MBX_READ_DATA, size, "mbx")
        _, op_slverr = await self._wait_op(J2A_OP_READ, MBX_READ_DATA, size, 0, "mbx")
        self._log(f"OBSERVATION mailbox read first capture measured=0x{first:x}")
        await self._ctrl(J2A_OP_WRITE, w6, size, 0, "okay_ctrl")
        await self._data("INCR", CLEAN_WORD, DATA_BITS_E2, "okay_wr")
        _, op_okay = await self._wait_op(J2A_OP_WRITE, w6, size, 0, "okay")
        first, gap = await self._single_load_read("INCR", SLVERR_WINDOW, size, "gap")
        _, op_gap = await self._wait_op(J2A_OP_READ, SLVERR_WINDOW, size, 0, "gap")
        self._log(f"OBSERVATION SLVERR-first gap read first capture measured=0x{first:x}")
        _, clean = await self._single_load_read("INCR", w6, size, "clean_rd")
        window_op, _ = await self._single_done(
            J2A_OP_WRITE, SLVERR_WINDOW, WINDOW_WRITE_WORD, 0xF, "window_wr"
        )
        self._log(f"OBSERVATION write at 0x{SLVERR_WINDOW:08x} op field measured={window_op}")
        before, after = await self._reset_series("slverr")
        await self._ctrl(J2A_OP_WRITE, w6, size, 0, "slverr_okay_ctrl")
        await self._data("INCR", CLEAN_WORD, DATA_BITS_E2, "slverr_okay_wr")
        self.slverr_reset = (before, after)
        self._check(
            "CHK-DBG-J2A-STICKY-SLVERR-FIRST",
            f"STATUS read op {status_op} word 0x{status_word:08x} & EMPTY 0x{ST_EMPTY:x} (want "
            f"op 0, EMPTY set); empty READ_DATA series read capture 2 0x{mbx:08x} (want "
            f"0x{EMPTY_READ_DATA:08x}); op after it {op_slverr}, after an OKAY beat {op_okay}, "
            f"after the DECERR gap read {op_gap} (want {J2A_STATUS_SLVERR} each); gap read "
            f"capture 2 0x{gap:08x} (want 0x{DECERR_READ_DATA:08x}); single-load read of word 6 "
            f"0x{clean:08x} (want 0x{CLEAN_WORD:08x})",
            (status_op, status_word & ST_EMPTY, mbx, op_slverr, op_okay, op_gap, gap, clean),
            (
                J2A_STATUS_SUCCESS,
                ST_EMPTY,
                EMPTY_READ_DATA,
                J2A_STATUS_SLVERR,
                J2A_STATUS_SLVERR,
                J2A_STATUS_SLVERR,
                DECERR_READ_DATA,
                CLEAN_WORD,
            ),
        )

    async def _sticky_decerr_first(self) -> None:
        await self._mark("S9", "sticky DECERR first, clean read, empty mailbox read")
        size = SMC_DBG_AXSIZE_4B
        w6 = _word_addr(CLEAN_INDEX)
        *_, okay_after_reset = await self._ctrl(J2A_OP_READ, SLVERR_WINDOW, size, 0, "decerr_ctrl")
        gap = tuple([await self._data("INCR", 0, DATA_BITS_E2, f"decerr_rd{i}") for i in range(2)])
        _, op_decerr = await self._wait_op(J2A_OP_READ, SLVERR_WINDOW, size, 0, "decerr")
        _, clean = await self._single_load_read("INCR", w6, size, "decerr_clean_rd")
        first, mbx = await self._single_load_read("INCR", MBX_READ_DATA, size, "decerr_mbx")
        _, op_after = await self._wait_op(J2A_OP_READ, MBX_READ_DATA, size, 0, "decerr_mbx")
        self._log(f"OBSERVATION DECERR-first gap read first capture measured=0x{gap[0]:x}")
        self._log(f"OBSERVATION DECERR-first mailbox read first capture measured=0x{first:x}")
        self.okay_after_slverr_reset = okay_after_reset
        self._check(
            "CHK-DBG-J2A-STICKY-DECERR-FIRST",
            f"op after the DECERR gap read {op_decerr}, after the empty mailbox read {op_after} "
            f"(want {J2A_STATUS_DECERR} each); gap read capture 2 0x{gap[1]:08x} (want "
            f"0x{DECERR_READ_DATA:08x}); single-load read of word 6 0x{clean:08x} (want "
            f"0x{CLEAN_WORD:08x}); mailbox capture 2 0x{mbx:08x} (want 0x{EMPTY_READ_DATA:08x})",
            (op_decerr, op_after, gap[1], clean, mbx),
            (J2A_STATUS_DECERR, J2A_STATUS_DECERR, DECERR_READ_DATA, CLEAN_WORD, EMPTY_READ_DATA),
        )

    async def _single_independence(self) -> None:
        await self._mark("S10", "SINGLE_OP status with series code 2 latched, then reset")
        size = SMC_DBG_AXSIZE_4B
        w6 = _word_addr(CLEAN_INDEX)
        rd_op, rd_word = await self._read_word(w6, "single_rd")
        series_after_rd = await self._nop_op("single_rd_series")
        mbx_op, mbx_word = await self._read_word(MBX_READ_DATA, "single_mbx")
        series_after_mbx = await self._nop_op("single_mbx_series")
        before, after = await self._reset_series("single")
        await self._ctrl(J2A_OP_WRITE, w6, size, 0, "single_okay_ctrl")
        await self._data("INCR", CLEAN_WORD, DATA_BITS_E2, "single_okay_wr")
        okay_after = await self._nop_op("single_okay_series")
        self._check(
            "CHK-DBG-J2A-SINGLE-INDEP",
            f"SINGLE_OP read of word 6: op {rd_op} data 0x{rd_word:08x} (want 0, "
            f"0x{CLEAN_WORD:08x}); SINGLE_OP read of the empty mailbox READ_DATA: op {mbx_op} "
            f"data 0x{mbx_word:08x} (want {J2A_STATUS_SLVERR}, 0x{EMPTY_READ_DATA:08x}); "
            f"SERIES_CTRL.op after each {series_after_rd}, {series_after_mbx} (want "
            f"{J2A_STATUS_DECERR})",
            (rd_op, rd_word, mbx_op, mbx_word, series_after_rd, series_after_mbx),
            (
                J2A_STATUS_SUCCESS,
                CLEAN_WORD,
                J2A_STATUS_SLVERR,
                EMPTY_READ_DATA,
                J2A_STATUS_DECERR,
                J2A_STATUS_DECERR,
            ),
        )
        self._check(
            "CHK-DBG-J2A-STICKY-RESET",
            f"reset with code 1 latched: op {self.slverr_reset[0]} -> {self.slverr_reset[1]}, "
            f"then an OKAY beat leaves op {self.okay_after_slverr_reset}; reset with code 2 "
            f"latched: op {before} -> {after}, then an OKAY beat leaves op {okay_after} "
            f"(want 1 -> 0 -> 0 and 2 -> 0 -> 0)",
            (self.slverr_reset, self.okay_after_slverr_reset, (before, after), okay_after),
            ((J2A_STATUS_SLVERR, OP_OKAY), OP_OKAY, (J2A_STATUS_DECERR, OP_OKAY), OP_OKAY),
        )

    async def _unspaced_single(self) -> None:
        await self._mark("S11", "SINGLE_OP pairs without Run-Test/Idle spacing, spaced retry")
        w6, w7 = _word_addr(CLEAN_INDEX), _word_addr(LAST_INDEX)
        retries = []
        busy_seen = False
        attempts = 0
        for attempt in range(UNSPACED_ATTEMPTS):
            attempts = attempt + 1
            base = self._counts()
            t0 = self._now()
            await self._single(J2A_OP_READ, w6, 0, 0, f"unspaced{attempt}_first", rti=False)
            op, _ = await self._single(J2A_OP_READ, w7, 0, 0, f"unspaced{attempt}_second")
            t1 = self._now()
            await self._idle(SINGLE_IDLE_TCKS)
            _, ar_d, _ = self._delta(self._counts(), base)
            tcks = (t1 - t0) / float(self.cfg.jtag_period_ns)
            self._log(
                f"OBSERVATION unspaced attempt {attempt} op field measured={op} "
                f"ar delta measured={ar_d} tck per operation measured={tcks / 2:.1f} "
                f"idle tcks={SINGLE_IDLE_TCKS}"
            )
            if op == J2A_STATUS_BUSY:
                busy_seen = True
                await self._single(J2A_OP_READ, w7, 0, 0, f"unspaced{attempt}_retry")
                await self._idle(SINGLE_IDLE_TCKS)
            status, rdata = await self._retry_capture(f"unspaced{attempt}_retry")
            retries.append((status, _lane_word(rdata, w7)))
            if busy_seen:
                break
        self._site(
            "unspaced_attempts",
            "unspaced",
            UNSPACED_ATTEMPTS,
            "attempts",
            attempts,
            f"busy_seen={busy_seen} retries={retries}",
            False,
        )
        self._site(
            "retry_capture",
            "unspaced",
            RETRY_POLL_LIMIT,
            "captures",
            self.retry_polls_max,
            f"attempts={attempts} op={retries[-1][0]}",
            False,
        )
        self._log(f"OBSERVATION unspaced pairs reading op 3 measured={int(busy_seen)}")

        controls = []
        for pair in range(2):
            await self._single(J2A_OP_READ, w6, 0, 0, f"control{pair}_first")
            await self._idle(SINGLE_IDLE_TCKS)
            op_a, data_a = await self._single(J2A_OP_READ, w7, 0, 0, f"control{pair}_second")
            await self._idle(SINGLE_IDLE_TCKS)
            op_b, data_b = await self._single_capture(f"control{pair}_capture")
            controls += [(op_a, _lane_word(data_a, w6)), (op_b, _lane_word(data_b, w7))]
        self._check(
            "CHK-DBG-J2A-BUSY-OP3",
            f"retries after {SINGLE_IDLE_TCKS} idle TCKs (op, word 7) {retries} (want op 0 with "
            f"0x{WORDS[LAST_INDEX]:08x} each); spaced control pairs {controls} (want op 0 with "
            f"0x{CLEAN_WORD:08x} and 0x{WORDS[LAST_INDEX]:08x}); unspaced op field and AR delta "
            f"measured and logged only",
            (tuple(retries), tuple(controls)),
            (
                ((J2A_STATUS_SUCCESS, WORDS[LAST_INDEX]),) * len(retries),
                ((J2A_STATUS_SUCCESS, CLEAN_WORD), (J2A_STATUS_SUCCESS, WORDS[LAST_INDEX])) * 2,
            ),
        )

    async def _finish(self) -> None:
        sb = self.sb
        await self._mark("S12", "ordered checker lines, wait sites and the pass stamp")
        failures = []

        def run_check(chk: str, name: str, got, want) -> None:
            try:
                sb.expect_eq(name, got, want, evidence=chk)
            except AssertionError as exc:
                failures.append(str(exc))

        order = [
            "CHK-DBG-J2A-SERIES-SETUP",
            "CHK-DBG-J2A-SERIES-INCR",
            "CHK-DBG-J2A-SERIES-NOINCR",
            "CHK-DBG-J2A-SERIES-ERRSTATUS",
            "CHK-DBG-J2A-SERIES-PIPELINE",
            "CHK-DBG-J2A-STICKY-SLVERR-FIRST",
            "CHK-DBG-J2A-STICKY-DECERR-FIRST",
            "CHK-DBG-J2A-STICKY-RESET",
            "CHK-DBG-J2A-SINGLE-INDEP",
            "CHK-DBG-J2A-BUSY-OP3",
        ]
        by_id = {chk: (proof, got, want) for chk, proof, got, want in self.checks}
        for chk in order:
            proof, got, want = by_id[chk]
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
            f"scans per step S1..S11={counts}"
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
