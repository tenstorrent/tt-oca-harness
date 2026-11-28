# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_telemetry_atb_capture_test. No force.

The ATB telemetry source interface at the SMU boundary, driven on the wrapper
pins and read back through each telemetry receiver's own registers over
JTAG2AXI. A receiver stores every accepted ATB beat as ``{atid, atdata}``; one
read of ``TELEMETRY_DATA`` returns the oldest beat with ``VALID`` set and
removes it, and a read of an empty FIFO returns 0 and removes nothing
(``telemetry_receiver.rdl``, TELEMETRY_DATA).

S1  Reset state. Receiver 0 reads ``STATUS.BUFFER_EMPTY`` set and
    ``TELEMETRY_DATA`` 0.

S2  The telemetry clock gate. ``SMC_BASE_CONFIG.CLOCK_GATE_CONTROL``'s
    ``TELEMETRY_CG_EN`` is read, cleared and read back before any beat, so a
    captured beat cannot be credited to an accidentally gated receiver.

S3  Capture. Five beats, each with an ATID and data byte no other beat
    shares, are driven on lane 0 and read back through ``TELEMETRY_DATA`` as
    the exact words, in order; the FIFO then reads empty.

S4  The ATB flush handshake. ``CTRL.TELEMETRY_TX_FLUSH`` requests the
    upstream flush over the ATB AF interface and clears itself when the flush
    completes (``regs/telemetry_receiver.rdl``; ``doc/programmer/src/smc-programming.adoc``,
    "Flush Operations"); ``afvalid_o`` is the flush request and ``afready_i``
    its acknowledgment (``doc/interface.adoc``). With ``telemetry_afready_i``
    held low the request must stay asserted at the pin and in the field, and
    raising it retires both. Lowering it again at the wrapper pin leaves the
    retired request retired.

S5  Every receiver. Each receiver takes, on its own lane, a beat with every
    ATID and data bit high, one with every bit low and one of its own, and
    returns exactly those words; every receiver then reads empty, so no beat
    reached another lane's FIFO.

S6  The flush handshake of S4 on receivers 1 and 2.

S7  Backpressure, on every receiver. ``FULL_OFFER`` beats are offered with
    no reads. The receiver holds ``BUFFER_DEPTH`` beats and the wrapper's ATB
    crossing FIFO ``ATB_CROSSING_DEPTH`` more, so ``STATUS.BUFFER_FULL`` sets,
    exactly ``HELD_CAPACITY`` beats are accepted, and ``telemetry_atready_o``
    stays low with the last beat held on the pins. Draining returns every
    offered beat in order, the held one included. ``CTRL.TELEMETRY_RX_FLUSH``
    then discards queued beats: the FIFO reads empty, and beats sent after it
    read back alone.

``TelemetryBeatSource`` holds each beat on the pins until ``atready`` takes
it, sampling ``atready`` on the falling edge of ``clk_telemetry_i``
(``clk_ref_i`` on this bench), so a beat is counted once however long it waits.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
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

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
TELEMETRY_CG_EN_BM = smc_base_config_u32("SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__TELEMETRY_CG_EN_bm")

STATUS_EMPTY_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
STATUS_FULL_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_FULL_bm")
TX_FLUSH_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__CTRL__TELEMETRY_TX_FLUSH_bm")
RX_FLUSH_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
THRESHOLD_BP = telemetry_receiver_u32("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
INTR_THRESHOLD_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
DATA_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_bm")
DATA_BP = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_bp")
ATID_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_bm")
ATID_BP = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_bp")
VALID_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_DATA__VALID_bm")
ATB_DATA_BITS = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_bw")
ATB_ID_BITS = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_bw")

# smc_config_pkg::TelemetryReceiverBufferDepth and the AtFifoDepth of the
# wrapper's ATB crossing FIFO.
BUFFER_DEPTH = 32
ATB_CROSSING_DEPTH = 8
HELD_CAPACITY = BUFFER_DEPTH + ATB_CROSSING_DEPTH
FULL_OFFER = HELD_CAPACITY + 1

NUM_RECEIVERS = 3
STATUS_POLL_BOUND = 200
ATREADY_LOW_BOUND = 64
# clk_telemetry_i cycles the source is watched with the FIFOs full and no reads issued.
STALL_HOLD_CYCLES = 64
AF_SETTLE_CYCLES = 16

Beat = tuple[int, int]


def tel_addr(register: str, receiver: int = 0) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{register}_BASE_ADDR", receiver
    )


def telemetry_word(beat: Beat) -> int:
    """The TELEMETRY_DATA value a read of ``beat`` returns."""
    atid, data = beat
    return VALID_BM | ((atid << ATID_BP) & ATID_BM) | ((data << DATA_BP) & DATA_BM)


def beat_stream(first_atid: int, first_data: int, count: int) -> list[Beat]:
    """``count`` beats, each with an ATID and a data byte no other beat in it shares."""
    return [
        ((first_atid + i) % (1 << ATB_ID_BITS), (first_data + 3 * i) % (1 << ATB_DATA_BITS))
        for i in range(count)
    ]


def set_lane(dut, name: str, lane: int, width: int, value: int) -> None:
    pin = getattr(dut, name)
    mask = ((1 << width) - 1) << (lane * width)
    current = int(pin.value) if pin.value.is_resolvable else 0
    pin.value = (current & ~mask) | ((value << (lane * width)) & mask)


def atready(dut, lane: int) -> int:
    val = dut.tb_telemetry_atready.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z on tb_telemetry_atready: {val}")
    return (int(val) >> lane) & 1


class TelemetryBeatSource:
    """An ATB source on one lane that holds each beat on the pins until ``atready`` takes it."""

    def __init__(self, dut, beats: list[Beat], lane: int = 0) -> None:
        self.dut = dut
        self.beats = beats
        self.lane = lane
        self.sent = 0
        self.task = cocotb.start_soon(self._run())

    @property
    def pending(self) -> int:
        return len(self.beats) - self.sent

    async def _run(self) -> None:
        dut, lane = self.dut, self.lane
        # Each beat goes on the pins just after a rising edge, so the falling edge that samples
        # atready comes before the rising edge that can take it.
        await RisingEdge(dut.clk_ref_i)
        for beat_atid, beat_data in self.beats:
            set_lane(dut, "tb_telemetry_atid", lane, ATB_ID_BITS, beat_atid)
            set_lane(dut, "tb_telemetry_atdata", lane, ATB_DATA_BITS, beat_data)
            set_lane(dut, "tb_telemetry_atvalid", lane, 1, 1)
            while True:
                await FallingEdge(dut.clk_ref_i)
                if atready(dut, lane):
                    break
            await RisingEdge(dut.clk_ref_i)
            self.sent += 1
        set_lane(dut, "tb_telemetry_atvalid", lane, 1, 0)
        set_lane(dut, "tb_telemetry_atid", lane, ATB_ID_BITS, 0)
        set_lane(dut, "tb_telemetry_atdata", lane, ATB_DATA_BITS, 0)


CAPTURE_BEATS = beat_stream(0x11, 0xA0, 5)
RECEIVER_BEATS = [
    [((1 << ATB_ID_BITS) - 1, (1 << ATB_DATA_BITS) - 1), (0, 0), (0x15 + rx, 0x3C + 0x11 * rx)]
    for rx in range(NUM_RECEIVERS)
]
FULL_BEATS = [
    beat_stream(0x20 + 0x10 * rx, 0x01 + 0x40 * rx, FULL_OFFER) for rx in range(NUM_RECEIVERS)
]
FLUSHED_BEATS = [beat_stream(0x60 + rx, 0x90 + rx, 4) for rx in range(NUM_RECEIVERS)]
RESENT_BEATS = [beat_stream(0x68 + rx, 0xC8 + rx, 3) for rx in range(NUM_RECEIVERS)]


class smu_telemetry_atb_capture_seq:
    """ATB beats driven at the SMU boundary and read back from each receiver."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _bit(self, name: str, lane: int = 0) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return (int(val) >> lane) & 1

    async def _rd32(self, addr: int, what: str) -> int:
        status, rdata = await jtag2axi_single_read(
            self.jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag, addr, beat, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def _poll(self, receiver: int, register: str, mask: int, want: bool) -> int:
        """Poll a receiver register until ``mask`` reads ``want``; raise on expiry."""
        addr = tel_addr(register, receiver)
        value = 0
        for _ in range(STATUS_POLL_BOUND):
            value = await self._rd32(addr, f"TELEMETRY{receiver} {register}")
            if bool(value & mask) == want:
                return value
        raise AssertionError(
            f"receiver {receiver} {register} mask 0x{mask:08x} never read {int(want)} over "
            f"{STATUS_POLL_BOUND} polls (last 0x{value:08x})"
        )

    async def _drain(self, receiver: int, count: int) -> list[int]:
        """Read ``count`` beats from ``receiver``, re-reading a 0 while a beat is crossing."""
        addr = tel_addr("TELEMETRY_DATA", receiver)
        words: list[int] = []
        for _ in range(count + STATUS_POLL_BOUND):
            if len(words) == count:
                break
            word = await self._rd32(addr, f"TELEMETRY{receiver} TELEMETRY_DATA")
            if word:
                words.append(word)
        return words

    async def _empty(self, receiver: int) -> tuple[int, int]:
        """(STATUS.BUFFER_EMPTY, TELEMETRY_DATA) of ``receiver``."""
        status = await self._rd32(tel_addr("STATUS", receiver), f"TELEMETRY{receiver} STATUS")
        data = await self._rd32(
            tel_addr("TELEMETRY_DATA", receiver), f"TELEMETRY{receiver} TELEMETRY_DATA"
        )
        return status & STATUS_EMPTY_BM, data

    async def run(self) -> None:
        dut = self.dut
        await self.cfg.reset_done.wait()
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._bit("tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._reset_state()
        await self._ungate()
        await self._capture()
        await self._flush_handshake()
        await self._every_receiver()
        for receiver in range(1, NUM_RECEIVERS):
            await self._flush_handshake(receiver)
        await self._backpressure()

    # ------------------------------------------------------------------
    # S1 / S2
    # ------------------------------------------------------------------
    async def _reset_state(self) -> None:
        self.sb.expect_eq(
            "receiver 0 reads STATUS.BUFFER_EMPTY set and TELEMETRY_DATA 0 out of reset",
            await self._empty(0),
            (STATUS_EMPTY_BM, 0),
            evidence="CHK-SMU-TEL-RESET",
        )

    async def _ungate(self) -> None:
        cg_mask = TELEMETRY_CG_EN_BM
        before = await self._rd32(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        await self._wr32(CLOCK_GATE_CONTROL, before & ~cg_mask, "CLOCK_GATE_CONTROL")
        after = await self._rd32(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        self.sb.expect_eq(
            "the telemetry clock gate is open before any beat is driven",
            after & cg_mask,
            0,
            evidence="CHK-SMU-TEL-CAPTURE",
        )

    # ------------------------------------------------------------------
    # S3
    # ------------------------------------------------------------------
    async def _capture(self) -> None:
        await TelemetryBeatSource(self.dut, CAPTURE_BEATS).task
        words = await self._drain(0, len(CAPTURE_BEATS))
        self.sb.expect_eq(
            "TELEMETRY_DATA returns each captured beat as {VALID, ATID, DATA}, in order",
            [f"0x{w:08x}" for w in words],
            [f"0x{telemetry_word(b):08x}" for b in CAPTURE_BEATS],
            evidence="CHK-SMU-TEL-CAPTURE",
        )
        self.sb.expect_eq(
            "the drained FIFO reads STATUS.BUFFER_EMPTY set and TELEMETRY_DATA 0",
            await self._empty(0),
            (STATUS_EMPTY_BM, 0),
            evidence="CHK-SMU-TEL-CAPTURE",
        )

    # ------------------------------------------------------------------
    # S4
    # ------------------------------------------------------------------
    async def _flush_handshake(self, receiver: int = 0) -> None:
        dut = self.dut
        ctrl = tel_addr("CTRL", receiver)
        set_lane(dut, "tb_telemetry_afready", receiver, 1, 0)
        await ClockCycles(dut.clk_ref_i, AF_SETTLE_CYCLES)
        self.sb.expect_eq(
            "no ATB flush is requested before software asks for one",
            self._bit("tb_telemetry_afvalid", receiver),
            0,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        await self._wr32(ctrl, TX_FLUSH_BM, "TELEMETRY CTRL")
        await ClockCycles(dut.clk_ref_i, AF_SETTLE_CYCLES)
        self.sb.expect_eq(
            "CTRL.TELEMETRY_TX_FLUSH raises telemetry_afvalid_o",
            self._bit("tb_telemetry_afvalid", receiver),
            1,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        held = await self._rd32(ctrl, "TELEMETRY CTRL")
        self.sb.expect_eq(
            "the flush request stays asserted while telemetry_afready_i is low",
            held & TX_FLUSH_BM,
            TX_FLUSH_BM,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        self.sb.expect_eq(
            "telemetry_afvalid_o is still high when telemetry_afready_i rises",
            self._bit("tb_telemetry_afvalid", receiver),
            1,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        set_lane(dut, "tb_telemetry_afready", receiver, 1, 1)
        await ClockCycles(dut.clk_ref_i, AF_SETTLE_CYCLES)
        self.sb.expect_eq(
            "telemetry_afready_i retires the request at the pin",
            self._bit("tb_telemetry_afvalid", receiver),
            0,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        cleared = await self._rd32(ctrl, "TELEMETRY CTRL")
        self.sb.expect_eq(
            "the acknowledged flush clears CTRL.TELEMETRY_TX_FLUSH",
            cleared & TX_FLUSH_BM,
            0,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        set_lane(dut, "tb_telemetry_afready", receiver, 1, 0)
        await ClockCycles(dut.clk_ref_i, AF_SETTLE_CYCLES)
        wrapper_afready = dut.u_dut.telemetry_afready_i.value
        if not wrapper_afready.is_resolvable:
            raise AssertionError(f"X/Z on u_dut.telemetry_afready_i: {wrapper_afready}")
        self.sb.expect_eq(
            "with telemetry_afready_i low again at the wrapper the request stays retired "
            "(afready, afvalid)",
            ((int(wrapper_afready) >> receiver) & 1, self._bit("tb_telemetry_afvalid", receiver)),
            (0, 0),
            evidence="CHK-SMU-TEL-FLUSH",
        )

    # ------------------------------------------------------------------
    # S5 / S7
    # ------------------------------------------------------------------
    async def _every_receiver(self) -> None:
        observed, want = {}, {}
        for receiver, beats in enumerate(RECEIVER_BEATS):
            await TelemetryBeatSource(self.dut, beats, lane=receiver).task
            words = await self._drain(receiver, len(beats))
            empties = []
            for rx in range(NUM_RECEIVERS):
                empties.append(await self._empty(rx))
            observed[receiver] = ([f"0x{w:08x}" for w in words], empties)
            want[receiver] = (
                [f"0x{telemetry_word(b):08x}" for b in beats],
                [(STATUS_EMPTY_BM, 0)] * NUM_RECEIVERS,
            )
        self.log.info("CHK-SMU-TEL-EVERY-RECEIVER (words read, every receiver empty) %s", observed)
        self.sb.expect_eq(
            "CHK-SMU-TEL-EVERY-RECEIVER", observed, want, evidence="CHK-SMU-TEL-EVERY-RECEIVER"
        )

    async def _backpressure(self) -> None:
        observed, want = {}, {}
        for receiver in range(NUM_RECEIVERS):
            observed[receiver] = await self._backpressure_lane(receiver)
            want[receiver] = (
                STATUS_FULL_BM,
                HELD_CAPACITY,
                0,
                HELD_CAPACITY,
                [f"0x{telemetry_word(b):08x}" for b in FULL_BEATS[receiver]],
                (STATUS_EMPTY_BM, 0),
                (STATUS_EMPTY_BM, 0),
                [f"0x{telemetry_word(b):08x}" for b in RESENT_BEATS[receiver]],
            )
        self.log.info(
            "CHK-SMU-TEL-BACKPRESSURE (BUFFER_FULL, accepted at stall, atready after hold, "
            "accepted after hold, drained words, empty after drain, empty after RX flush, "
            "words sent after the flush) %s",
            observed,
        )
        self.sb.expect_eq(
            "CHK-SMU-TEL-BACKPRESSURE", observed, want, evidence="CHK-SMU-TEL-BACKPRESSURE"
        )

    async def _backpressure_lane(self, receiver: int) -> tuple:
        dut = self.dut
        full_beats = FULL_BEATS[receiver]
        source = TelemetryBeatSource(dut, full_beats, lane=receiver)
        full = await self._poll(receiver, "STATUS", STATUS_FULL_BM, True)
        for _ in range(ATREADY_LOW_BOUND):
            if not atready(dut, receiver):
                break
            await RisingEdge(dut.clk_ref_i)
        await FallingEdge(dut.clk_ref_i)
        at_stall = source.sent
        await ClockCycles(dut.clk_ref_i, STALL_HOLD_CYCLES)
        await FallingEdge(dut.clk_ref_i)
        held_ready = atready(dut, receiver)
        after_hold = source.sent
        drained = await self._drain(receiver, len(full_beats))
        await source.task
        empty_after_drain = await self._empty(receiver)

        flushed = FLUSHED_BEATS[receiver]
        await TelemetryBeatSource(dut, flushed, lane=receiver).task
        ctrl = tel_addr("CTRL", receiver)
        await self._wr32(ctrl, (len(flushed) - 1) << THRESHOLD_BP, f"TELEMETRY{receiver} CTRL")
        await self._poll(receiver, "INTR_STATUS", INTR_THRESHOLD_BM, True)
        await self._wr32(ctrl, RX_FLUSH_BM, f"TELEMETRY{receiver} CTRL")
        await ClockCycles(dut.clk_smu_i, AF_SETTLE_CYCLES)
        empty_after_flush = await self._empty(receiver)
        resent = RESENT_BEATS[receiver]
        await TelemetryBeatSource(dut, resent, lane=receiver).task
        resent_words = await self._drain(receiver, len(resent))
        return (
            full & STATUS_FULL_BM,
            at_stall,
            held_ready,
            after_hold,
            [f"0x{w:08x}" for w in drained],
            empty_after_drain,
            empty_after_flush,
            [f"0x{w:08x}" for w in resent_words],
        )
