# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 beat FIFO order, empty/full status and buffer threshold.

Spec: telemetry_receiver.rdl (TELEMETRY_DATA, CTRL.BUFFER_THRESHOLD, STATUS.BUFFER_EMPTY /
BUFFER_FULL, INTR_STATUS.BUFFER_THRESHOLD read-only, INTR_TEST.BUFFER_THRESHOLD). The receiver
stores each ATB beat as ``{atid, atdata}`` in a FIFO of ``BUFFER_DEPTH`` beats; a read of
TELEMETRY_DATA returns the oldest beat with VALID set and removes it, a read of the empty FIFO
returns 0 and removes nothing, and the threshold status is live while the number of beats held
is greater than BUFFER_THRESHOLD.

Each beat is driven on lane 0 and carries an ATID and data byte no other beat shares. Registers
are read over JTAG2AXI. INTR_STATUS.BUFFER_THRESHOLD is sampled as a register readback only;
interrupt delivery at the SMU boundary is not claimed.

The FIFO fills to its depth before the first read in every run. The seed draws three thresholds
(0 to the depth) and where the second and third threshold writes fall among the fill and read
events; every INTR_STATUS.BUFFER_THRESHOLD compare expects ``occupancy > threshold`` for the
threshold in force and the number of beats held. The first threshold and every threshold whose
write precedes a fill are drawn below the depth, so the threshold in force at the write of 1 with
the FIFO full is exceeded and that leg's source is live; only a threshold whose write precedes a
read may draw the depth. The directed flip cell stays pinned beside the draws: with
``PINNED_OCCUPANCY`` beats held after ``PINNED_POP`` reads the threshold is written one below the
occupancy (status 1), raised to the occupancy (status 0, the FIFO unchanged), set back (status 1),
then the drawn threshold is restored.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
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
from seq_lib.smu_telemetry_atb_capture_seq import (
    BUFFER_DEPTH,
    INTR_THRESHOLD_BM,
    STATUS_EMPTY_BM,
    STATUS_FULL_BM,
    THRESHOLD_BP,
    TelemetryBeatSource,
    beat_stream,
    tel_addr,
    telemetry_word,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
CG_EN_BM = smc_base_config_u32("SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__TELEMETRY_CG_EN_bm")
INTR_TEST_THRESHOLD_BM = telemetry_receiver_u32(
    "TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm"
)

QUEUE_DEPTH = BUFFER_DEPTH
BEATS = beat_stream(0x01, 0x40, QUEUE_DEPTH)
THRESHOLD_WRITES = 3
# The pinned flip cell: after PINNED_POP reads (PINNED_OCCUPANCY held) the threshold is written
# PINNED_LOW, PINNED_HIGH and PINNED_LOW again, so the status is driven 1, 0 and 1 by the threshold
# alone with the FIFO unchanged.
PINNED_POP = 3
PINNED_OCCUPANCY = QUEUE_DEPTH - PINNED_POP
PINNED_LOW = PINNED_OCCUPANCY - 1
PINNED_HIGH = PINNED_OCCUPANCY
EVENTS = 2 * QUEUE_DEPTH
# STATUS is read after the fills where BUFFER_EMPTY first drops and BUFFER_FULL is last clear
# and first set; INTR_STATUS is read after every fill.
STATUS_FILLS = (1, QUEUE_DEPTH - 1, QUEUE_DEPTH)
ATB_READY_BOUND = 64
J2A_POLL_LIMIT = 128

TEL_CTRL = tel_addr("CTRL")
TEL_STATUS = tel_addr("STATUS")
TEL_INTR_STATUS = tel_addr("INTR_STATUS")
TEL_INTR_TEST = tel_addr("INTR_TEST")
TEL_DATA = tel_addr("TELEMETRY_DATA")


class smu_telemetry_queue_threshold_test_seq:
    """Beat FIFO fill, read order and threshold walk on receiver 0."""

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
        of 1 with the FIFO full is exceeded; a write placed among the reads may draw QUEUE_DEPTH.
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
            f"{QUEUE_DEPTH} fills then {QUEUE_DEPTH} reads; a threshold in force at or before "
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

    async def _beat(self, index: int) -> None:
        """Drive beat ``index`` on lane 0 and require ``atready`` to take it within the bound."""
        rec = self._site("atb_beat", f"{ATB_READY_BOUND} clk_telemetry_i cycles")
        beat = BEATS[index]
        source = TelemetryBeatSource(self.dut, [beat])
        for _ in range(ATB_READY_BOUND):
            await RisingEdge(self.dut.clk_ref_i)
            if source.sent:
                break
        if not source.sent:
            source.task.cancel()
            rec["expired"] += 1
            rec["last"] = f"EXPIRED beat {index + 1} {beat} atready=0"
            self._log(f"TIMEOUT-PATH atb_beat: bound={rec['bound']} {rec['last']}")
            raise AssertionError(
                f"ATB beat {index + 1} never accepted within {ATB_READY_BOUND} cycles"
            )
        await source.task
        rec["count"] += 1
        rec["last"] = f"beat {index + 1} {beat} atready=1"

    async def _pop(self, label: str) -> int:
        word = await self._rd(TEL_DATA, f"TELEMETRY_DATA {label}")
        self._cell(f"TELEMETRY_DATA {label}", TEL_DATA, f"value=0x{word:08x}")
        return word

    async def _intr_threshold(self, label: str) -> int:
        value = await self._rd(TEL_INTR_STATUS, f"INTR_STATUS {label}")
        self._cell(f"INTR_STATUS {label}", TEL_INTR_STATUS, f"value=0x{value:08x}")
        return 1 if value & INTR_THRESHOLD_BM else 0

    async def _set_threshold(self, threshold: int) -> None:
        self.threshold = threshold
        ctrl = threshold << THRESHOLD_BP
        await self._wr(TEL_CTRL, ctrl, f"CTRL BUFFER_THRESHOLD={threshold}")
        self._cell(f"CTRL BUFFER_THRESHOLD={threshold}", TEL_CTRL, f"wrote=0x{ctrl:08x}")

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

    async def _pinned_flip(self) -> None:
        """Drive the status 1, 0, 1 by the threshold alone with PINNED_OCCUPANCY queued."""
        drawn = self.threshold
        occupancy = PINNED_OCCUPANCY
        for threshold, token, label in (
            (PINNED_LOW, "TELQ_THRESHOLD_LIVE", f"threshold {PINNED_LOW} with {occupancy} held"),
            (
                PINNED_HIGH,
                "TELQ_THRESHOLD_CLEAR",
                f"threshold raised to {PINNED_HIGH} with {occupancy} held",
            ),
            (
                PINNED_LOW,
                "TELQ_THRESHOLD_LIVE",
                f"threshold back to {PINNED_LOW} with {occupancy} held",
            ),
        ):
            await self._set_threshold(threshold)
            intr = await self._intr_threshold(label)
            self.sb.expect_eq(
                f"CHK-{token.replace('_', '-')} {label} (pinned)",
                intr,
                self._expect_intr(occupancy),
                evidence=token,
            )
        await self._set_threshold(drawn)
        intr = await self._intr_threshold(f"drawn threshold restored with {occupancy} held")
        self.sb.expect_eq(
            f"CHK-TELQ-THRESHOLD-CLEAR drawn threshold restored with {occupancy} held "
            f"{self._drawn(occupancy)}",
            intr,
            self._expect_intr(occupancy),
            evidence="TELQ_THRESHOLD_CLEAR",
        )

    async def run(self) -> None:
        sb = self.sb
        dut = self.dut
        assert 0 < PINNED_LOW < PINNED_OCCUPANCY <= PINNED_HIGH < QUEUE_DEPTH

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

        self._mark("S2", "TELEMETRY_DATA read on the empty FIFO")
        word = await self._pop("on empty")
        status = await self._rd(TEL_STATUS, "STATUS after read on empty")
        self._cell("read on empty STATUS", TEL_STATUS, f"value=0x{status:08x}")
        sb.expect_eq(
            "CHK-TELQ-POP-EMPTY TELEMETRY_DATA read on the empty FIFO",
            word,
            0,
            evidence="TELQ_POP_EMPTY",
        )
        sb.expect_eq(
            "CHK-TELQ-POP-EMPTY STATUS.BUFFER_EMPTY after a read on the empty FIFO",
            status & STATUS_EMPTY_BM,
            STATUS_EMPTY_BM,
            evidence="TELQ_POP_EMPTY",
        )

        self._mark("S3", f"drawn thresholds, {QUEUE_DEPTH} beats, INTR_STATUS after each")
        await self._set_threshold(self.thresholds[0])
        for p in range(1, QUEUE_DEPTH + 1):
            await self._threshold_writes_before(p, p - 1)
            await self._beat(p - 1)
            if p in STATUS_FILLS:
                status = await self._rd(TEL_STATUS, f"STATUS after beat {p}")
                self._cell(f"beat {p} STATUS", TEL_STATUS, f"value=0x{status:08x}")
                sb.expect_eq(
                    f"CHK-TELQ-EMPTY-FULL beat {p} BUFFER_EMPTY",
                    status & STATUS_EMPTY_BM,
                    0,
                    evidence="TELQ_EMPTY_FULL",
                )
                sb.expect_eq(
                    f"CHK-TELQ-EMPTY-FULL beat {p} BUFFER_FULL",
                    1 if status & STATUS_FULL_BM else 0,
                    1 if p == QUEUE_DEPTH else 0,
                    evidence="TELQ_EMPTY_FULL",
                )
            intr = await self._intr_threshold(f"after beat {p}")
            sb.expect_eq(
                f"CHK-TELQ-THRESHOLD-LIVE beat {p} INTR_STATUS.BUFFER_THRESHOLD {self._drawn(p)}",
                intr,
                self._expect_intr(p),
                evidence="TELQ_THRESHOLD_LIVE",
            )

        self._mark(
            "S4", "write 1 to INTR_STATUS, read out, pinned flip and re-threshold through the FIFO"
        )
        await self._wr(TEL_INTR_STATUS, INTR_THRESHOLD_BM, "INTR_STATUS write 1")
        intr = await self._intr_threshold("after write of 1 with the FIFO full")
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
            word = await self._pop(f"read {pop}")
            intr = await self._intr_threshold(f"after read {pop}")
            sb.expect_eq(
                f"CHK-TELQ-ORDER TELEMETRY_DATA read {pop}",
                f"0x{word:08x}",
                f"0x{telemetry_word(BEATS[pop - 1]):08x}",
                evidence="TELQ_ORDER",
            )
            sb.expect_eq(
                f"CHK-TELQ-THRESHOLD-LIVE after read {pop} {self._drawn(occupancy)}",
                intr,
                self._expect_intr(occupancy),
                evidence="TELQ_THRESHOLD_LIVE",
            )
            if pop == PINNED_POP:
                await self._pinned_flip()
        word = await self._pop("after the FIFO is drained")
        sb.expect_eq(
            "CHK-TELQ-ORDER TELEMETRY_DATA read on the drained FIFO",
            word,
            0,
            evidence="TELQ_ORDER",
        )

        self._mark("S5", "INTR_TEST.BUFFER_THRESHOLD force and release on the empty FIFO")
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
