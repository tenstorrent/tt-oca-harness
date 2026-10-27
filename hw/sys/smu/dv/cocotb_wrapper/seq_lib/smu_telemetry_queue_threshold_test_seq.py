# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 message queue order, empty/full status and buffer threshold.

Spec: telemetry_receiver.rdl (CTRL.BUFFER_POP / BUFFER_THRESHOLD, STATUS.BUFFER_EMPTY / BUFFER_FULL,
TELEMETRY_PROBE_ID, INTR_STATUS.BUFFER_THRESHOLD read-only, INTR_TEST.BUFFER_THRESHOLD);
doc/architecture.adoc "Message Queue and Readout" and "Interrupts" (eight-message queue, oldest
message exposed, empty reads zero, live threshold status); doc/index.adoc "Message Format".

Each message is one last-flagged ATB packet on lane 0 whose probe id is in bits [60:56], whose
header block is invalid and whose other blocks are all ones; the observed registers do not depend
on the open block layout. Registers are read over JTAG2AXI. INTR_STATUS.BUFFER_THRESHOLD is
sampled as a register readback only; interrupt delivery at the SMU boundary is not claimed.

The queue fills to its depth of eight before the first pop in every run. The seed draws three
thresholds (0 to 8, the queue depth) and where the second and third threshold writes fall among
the sixteen fill and pop events; every INTR_STATUS.BUFFER_THRESHOLD compare expects
``occupancy > threshold`` for the threshold in force and the number of messages queued. The
first threshold and every threshold whose write precedes a fill are drawn below the depth, so the
threshold in force at the write of 1 with eight queued is exceeded and that leg's source is live;
only a threshold whose write precedes a pop may draw 8.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_boundary_regs import smc_base_config_u32, telemetry_receiver_u32
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

_PFX = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_"
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
CG_EN_BM = smc_base_config_u32("SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__TELEMETRY_CG_EN_bm")

STATUS_EMPTY_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
STATUS_FULL_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_FULL_bm")
PROBE_ID_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bm")
PROBE_ID_BITS = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bw")
BUFFER_POP_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm")
THRESHOLD_BP = telemetry_receiver_u32("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
INTR_THRESHOLD_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
INTR_TEST_THRESHOLD_BM = telemetry_receiver_u32(
    "TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm"
)

# hw/ip/telemetry_receiver/doc/index.adoc "Message Format": eight little-endian beats form a
# 64-bit packet, last_packet is bit 63, probe_id is bits [60:56], a block is nine bits and seven
# blocks fill bits [62:0].
ATB_BEAT_BITS = 8
ATB_BEATS_PER_PACKET = 8
ATB_LAST_PACKET_BIT = 63
ATB_PROBE_ID_LSB = 56
ATB_BLOCK_BITS = 9
ATB_BLOCK_FILL = (1 << ATB_BLOCK_BITS) - 1
ATB_HEADER_BLOCK_LSB = ATB_LAST_PACKET_BIT - ATB_BLOCK_BITS
ATB_BEAT_MASK = (1 << ATB_BEAT_BITS) - 1
ATB_ID = 0x2A
ATB_READY_BOUND = 64

QUEUE_DEPTH = 8
THRESHOLD_WRITES = 3
EVENTS = 2 * QUEUE_DEPTH
J2A_POLL_LIMIT = 128


def _tel(name: str) -> int:
    return smc_indexed_addr(f"{_PFX}{name}_BASE_ADDR", 0)


TEL_CTRL = _tel("CTRL")
TEL_STATUS = _tel("STATUS")
TEL_INTR_STATUS = _tel("INTR_STATUS")
TEL_INTR_TEST = _tel("INTR_TEST")
TEL_PROBE_ID = _tel("TELEMETRY_PROBE_ID")


class smu_telemetry_queue_threshold_test_seq:
    """Eight-message queue and threshold walk on receiver 0."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.sites: dict[str, dict] = {}
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed)
        self.thresholds: list[int] = []
        self.positions: list[int] = []
        self.threshold = 0

    def _draw(self) -> None:
        """Three thresholds and the events the second and third writes precede (2..EVENTS).

        The first threshold and every threshold whose write precedes a fill (an event at or
        below QUEUE_DEPTH) are drawn below QUEUE_DEPTH, so the threshold in force at the write
        of 1 with eight queued is exceeded; a write placed among the pops may draw QUEUE_DEPTH.
        """
        self.positions = sorted(self.rng.sample(range(2, EVENTS + 1), THRESHOLD_WRITES - 1))
        tops = [QUEUE_DEPTH - 1] + [
            QUEUE_DEPTH - 1 if position <= QUEUE_DEPTH else QUEUE_DEPTH
            for position in self.positions
        ]
        self.thresholds = [self.rng.randint(0, top) for top in tops]
        self._log(
            f"SEED: RANDOM_SEED={self.seed} drawn thresholds={self.thresholds} "
            f"positions={self.positions} (the first write precedes fill 1; an event is one of "
            f"{QUEUE_DEPTH} fills then {QUEUE_DEPTH} pops; a threshold in force at or before "
            f"fill {QUEUE_DEPTH} is drawn below {QUEUE_DEPTH})"
        )

    def _drawn(self, occupancy: int) -> str:
        return f"drawn threshold={self.threshold} occupancy={occupancy}"

    def _expect_intr(self, occupancy: int) -> int:
        return 1 if occupancy > self.threshold else 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    def _site(self, name: str, bound: str) -> dict:
        return self.sites.setdefault(
            name, {"bound": bound, "count": 0, "last": "none", "expired": 0}
        )

    async def _rd(self, addr: int, label: str) -> int:
        rec = self._site("j2a", f"{J2A_POLL_LIMIT} polls")
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED RD {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"RD {label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr(self, addr: int, data: int, label: str) -> None:
        rec = self._site("j2a", f"{J2A_POLL_LIMIT} polls")
        wstrb, beat = axi64_pack32(addr, data)
        try:
            status, _ = await jtag2axi_single_write(
                self.jtag,
                addr,
                beat,
                wstrb=wstrb,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED WR {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A WR {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"WR {label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {label} @0x{addr:08x} status={status}")

    def _set_lane0(self, name: str, width: int, value: int) -> None:
        pin = getattr(self.dut, name)
        current = int(pin.value) if pin.value.is_resolvable else 0
        pin.value = (current & ~((1 << width) - 1)) | (value & ((1 << width) - 1))

    def _atready(self) -> int:
        val = self.dut.tb_telemetry_atready.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on tb_telemetry_atready: {val}")
        return int(val) & 1

    async def _beat(self, value: int, index: int) -> None:
        rec = self._site("atb_beat", f"{ATB_READY_BOUND} clk_telemetry_i cycles")
        self._set_lane0("tb_telemetry_atdata", ATB_BEAT_BITS, value & ATB_BEAT_MASK)
        self._set_lane0("tb_telemetry_atid", 7, ATB_ID)
        self._set_lane0("tb_telemetry_atvalid", 1, 1)
        await RisingEdge(self.dut.clk_ref_i)
        accepted = False
        for _ in range(ATB_READY_BOUND):
            if self._atready():
                accepted = True
                break
            await RisingEdge(self.dut.clk_ref_i)
        self._set_lane0("tb_telemetry_atvalid", 1, 0)
        if not accepted:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED beat {index} data=0x{value & ATB_BEAT_MASK:02x} atready=0"
            self._log(f"TIMEOUT-PATH atb_beat: bound={rec['bound']} {rec['last']}")
            raise AssertionError(f"ATB beat {index} never accepted within {ATB_READY_BOUND} cycles")
        rec["count"] += 1
        rec["last"] = f"beat {index} data=0x{value & ATB_BEAT_MASK:02x} atready=1"

    async def _send_message(self, probe_id: int) -> None:
        packet = (1 << ATB_LAST_PACKET_BIT) | (probe_id << ATB_PROBE_ID_LSB)
        for block_lsb in range(0, ATB_HEADER_BLOCK_LSB, ATB_BLOCK_BITS):
            packet |= ATB_BLOCK_FILL << block_lsb
        for i in range(ATB_BEATS_PER_PACKET):
            await self._beat((packet >> (i * ATB_BEAT_BITS)) & ATB_BEAT_MASK, i)

    async def _pop_and_probe(self, label: str) -> int:
        await self._wr(TEL_CTRL, self.ctrl | BUFFER_POP_BM, f"CTRL pop {label}")
        probe = await self._rd(TEL_PROBE_ID, f"PROBE_ID after {label}")
        self._cell(f"PROBE_ID after {label}", TEL_PROBE_ID, f"value=0x{probe:08x}")
        return probe & PROBE_ID_BM

    async def _intr_threshold(self, label: str) -> int:
        value = await self._rd(TEL_INTR_STATUS, f"INTR_STATUS {label}")
        self._cell(f"INTR_STATUS {label}", TEL_INTR_STATUS, f"value=0x{value:08x}")
        return 1 if value & INTR_THRESHOLD_BM else 0

    async def _set_threshold(self, threshold: int) -> None:
        self.threshold = threshold
        self.ctrl = threshold << THRESHOLD_BP
        await self._wr(TEL_CTRL, self.ctrl, f"CTRL BUFFER_THRESHOLD={threshold}")
        self._cell(f"CTRL BUFFER_THRESHOLD={threshold}", TEL_CTRL, f"wrote=0x{self.ctrl:08x}")

    async def _threshold_writes_before(self, event: int, occupancy: int) -> None:
        """Write every drawn threshold whose position is this event, then compare the status."""
        for write, position in enumerate(self.positions, start=1):
            if position != event:
                continue
            await self._set_threshold(self.thresholds[write])
            intr = await self._intr_threshold(f"after threshold write {write} before event {event}")
            self.sb.expect_eq(
                f"CHK-TELQ-THRESHOLD-CLEAR status follows threshold write {write} before event "
                f"{event} {self._drawn(occupancy)}",
                intr,
                self._expect_intr(occupancy),
                evidence="TELQ_THRESHOLD_CLEAR",
            )

    async def run(self) -> None:
        sb = self.sb
        dut = self.dut
        self.ctrl = 0
        assert PROBE_ID_BITS == 5 and QUEUE_DEPTH < (1 << PROBE_ID_BITS)

        self._draw()
        self._mark("S1", "SETUP: bring-up, IDCODE, J2A gate open, telemetry clock gate")
        await self.cfg.reset_done.wait()
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self._log(f"CELL setup idcode=0x{idcode:08x} security_disable={int(gate)}")
        cg_word = await self._rd(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        self._cell("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, f"value=0x{cg_word:08x}")
        if cg_word & CG_EN_BM:
            raise AssertionError(f"telemetry clock gate closed: CLOCK_GATE_CONTROL=0x{cg_word:08x}")

        self._mark("S2", "CTRL.BUFFER_POP on the empty queue")
        await self._wr(TEL_CTRL, BUFFER_POP_BM, "CTRL pop on empty")
        status = await self._rd(TEL_STATUS, "STATUS after pop on empty")
        self._cell("pop on empty STATUS", TEL_STATUS, f"value=0x{status:08x}")
        probe = await self._rd(TEL_PROBE_ID, "PROBE_ID after pop on empty")
        self._cell("pop on empty PROBE_ID", TEL_PROBE_ID, f"value=0x{probe:08x}")
        sb.expect_eq(
            "CHK-TELQ-POP-EMPTY STATUS.BUFFER_EMPTY after pop on the empty queue",
            status & STATUS_EMPTY_BM,
            STATUS_EMPTY_BM,
            evidence="TELQ_POP_EMPTY",
        )
        sb.expect_eq(
            "CHK-TELQ-POP-EMPTY PROBE_ID after pop on the empty queue",
            probe & PROBE_ID_BM,
            0,
            evidence="TELQ_POP_EMPTY",
        )

        self._mark("S3", "drawn thresholds, eight messages, STATUS and INTR_STATUS after each")
        await self._set_threshold(self.thresholds[0])
        for p in range(1, QUEUE_DEPTH + 1):
            await self._threshold_writes_before(p, p - 1)
            await self._send_message(p)
            status = await self._rd(TEL_STATUS, f"STATUS after message {p}")
            self._cell(f"message {p} STATUS", TEL_STATUS, f"value=0x{status:08x}")
            intr = await self._intr_threshold(f"after message {p}")
            sb.expect_eq(
                f"CHK-TELQ-EMPTY-FULL message {p} BUFFER_EMPTY",
                status & STATUS_EMPTY_BM,
                0,
                evidence="TELQ_EMPTY_FULL",
            )
            sb.expect_eq(
                f"CHK-TELQ-EMPTY-FULL message {p} BUFFER_FULL",
                1 if status & STATUS_FULL_BM else 0,
                1 if p == QUEUE_DEPTH else 0,
                evidence="TELQ_EMPTY_FULL",
            )
            sb.expect_eq(
                f"CHK-TELQ-THRESHOLD-LIVE message {p} INTR_STATUS.BUFFER_THRESHOLD "
                f"{self._drawn(p)}",
                intr,
                self._expect_intr(p),
                evidence="TELQ_THRESHOLD_LIVE",
            )

        self._mark("S4", "write 1 to INTR_STATUS, pop and re-threshold through the queue")
        await self._wr(TEL_INTR_STATUS, INTR_THRESHOLD_BM, "INTR_STATUS write 1")
        intr = await self._intr_threshold("after write of 1 with eight queued")
        # The threshold in force here is drawn below QUEUE_DEPTH, so the source is live and the
        # status reads 1; the pinned 1 keeps this leg from passing on a cleared status.
        sb.expect_eq(
            "CHK-TELQ-THRESHOLD-CLEAR write of 1 leaves INTR_STATUS.BUFFER_THRESHOLD live "
            f"{self._drawn(QUEUE_DEPTH)}",
            intr,
            1,
            evidence="TELQ_THRESHOLD_CLEAR",
        )
        for pop in range(1, QUEUE_DEPTH + 1):
            occupancy = QUEUE_DEPTH - pop
            await self._threshold_writes_before(QUEUE_DEPTH + pop, occupancy + 1)
            probe = await self._pop_and_probe(f"pop {pop}")
            intr = await self._intr_threshold(f"after pop {pop}")
            sb.expect_eq(
                f"CHK-TELQ-ORDER probe id after pop {pop}",
                probe,
                pop + 1 if pop < QUEUE_DEPTH else 0,
                evidence="TELQ_ORDER",
            )
            sb.expect_eq(
                f"CHK-TELQ-THRESHOLD-LIVE after pop {pop} {self._drawn(occupancy)}",
                intr,
                self._expect_intr(occupancy),
                evidence="TELQ_THRESHOLD_LIVE",
            )

        self._mark("S5", "INTR_TEST.BUFFER_THRESHOLD force and release on the empty queue")
        await self._wr(TEL_INTR_TEST, INTR_TEST_THRESHOLD_BM, "INTR_TEST write 1")
        intr = await self._intr_threshold("after INTR_TEST=1")
        sb.expect_eq(
            "CHK-TELQ-THRESHOLD-TEST INTR_STATUS.BUFFER_THRESHOLD after INTR_TEST write of 1",
            intr,
            1,
            evidence="TELQ_THRESHOLD_TEST",
        )
        await self._wr(TEL_INTR_TEST, 0, "INTR_TEST write 0")
        intr = await self._intr_threshold("after INTR_TEST=0")
        sb.expect_eq(
            "CHK-TELQ-THRESHOLD-TEST INTR_STATUS.BUFFER_THRESHOLD after INTR_TEST write of 0",
            intr,
            0,
            evidence="TELQ_THRESHOLD_TEST",
        )
        await self._wr(TEL_CTRL, 0, "CTRL restore")
        self._set_lane0("tb_telemetry_atdata", ATB_BEAT_BITS, 0)
        self._set_lane0("tb_telemetry_atid", 7, 0)

        self._mark("S6", "TIMEOUT: bounded waits and last state")
        lines = []
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{site}: bound={rec['bound']} {state} count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"j2a_accesses_counted={self.j2a} (counted at the call sites of this seq)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait sites exercised", sorted(self.sites), ["atb_beat", "j2a"])
        self.done = True
