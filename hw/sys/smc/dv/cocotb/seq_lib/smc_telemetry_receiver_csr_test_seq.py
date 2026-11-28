# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-6: TELEMETRY CSR reset, INTR_TEST interrupt, and one ATB beat per receiver.

Every register of all three receivers is read at reset before any ATB
stimulus, ``TELEMETRY_DATA`` included: its reset is 0 and a read of an empty
FIFO removes nothing (``telemetry_receiver.rdl``). Receivers 1 and 2 also
store and restore ``INTR_ENABLE``. On receiver 0, ``INTR_TEST.BUFFER_THRESHOLD``
raises ``tb_telemetry_irq_any`` and a write of 0 releases it.

Each receiver then takes one beat with an ATB ID and a data byte of its own.
What this testcase scores is the CSR-visible consequence: ``STATUS.BUFFER_EMPTY``
clears on that receiver and its ``TELEMETRY_DATA`` returns exactly that beat.
A wrap that routed the beat elsewhere fails the empty sample of the receiver
it was told to fill, and one that delivered another receiver's beat fails the
data compare. Ordering, backpressure and flushes are graded by
``smc_telemetry_atb_capture_test``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_EMPTY_BM,
    ENABLE_THRESHOLD_BM,
    INTR_THRESHOLD_BM,
    _HeldSource,
    _rx_addr,
    _tel,
    _word,
)

# `STATUS` carries the discrimination: its generated reset is 0x1 (EMPTY set),
# the one non-zero value in the group, so a dead or unmapped receiver window
# reading 0 fails on it rather than satisfying five zero compares.
_TELEMETRY_REG_TYPES = (
    ("CTRL", 0x0),
    ("STATUS", BUFFER_EMPTY_BM),
    ("INTR_ENABLE", 0x0),
    ("INTR_STATUS", 0x0),
    ("INTR_TEST", 0x0),
    ("TELEMETRY_DATA", 0x0),
)
_TELEMETRY_RECEIVERS = 3
# A reset sweep alone would leave receivers 1 and 2 at "mapped, and at reset",
# so each also takes a write/readback/restore of INTR_ENABLE's one writable
# field before its ATB beat. A window that decodes but does not store, or one
# that returns a bus default, fails the readback.
_QUIET_RECEIVERS = (1, 2)
_TEST_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm")

TELEMETRY_READS = [
    (f"TELEMETRY_RECEIVER_{_rx}_{_rt}", _rx_addr(_rt, _rx), _reset)
    for _rx in range(_TELEMETRY_RECEIVERS)
    for _rt, _reset in _TELEMETRY_REG_TYPES
]

_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

# One beat per receiver, each with an ATB ID and a data byte no other receiver's
# beat shares, so a beat that reached the wrong FIFO fails the data compare.
RX_BEATS = {0: (0x05, 0x3A), 1: (0x11, 0x6D), 2: (0x22, 0xEF)}
assert len({beat[0] for beat in RX_BEATS.values()}) == len(RX_BEATS)
assert len({beat[1] for beat in RX_BEATS.values()}) == len(RX_BEATS)
# Bound on the beat crossing into the receiver FIFO.
_BUFFER_POLL_BOUND = 200
# Bound for the INTR_TEST-to-IRQ and IRQ-release observations. A ceiling on a
# bounded poll that returns on the level it waits for and raises on expiry.
_IRQ_POLL_BOUND = 64


async def _await_irq_level(dut, want: int, label: str) -> int:
    """Poll tb_telemetry_irq_any for `want`; raise on expiry. Returns cycles."""
    last = int(dut.tb_telemetry_irq_any.value)
    if last == want:
        return 0
    for cyc in range(1, _IRQ_POLL_BOUND + 1):
        await RisingEdge(dut.clk_smc_i)
        last = int(dut.tb_telemetry_irq_any.value)
        if last == want:
            return cyc
    raise AssertionError(
        f"{label}: tb_telemetry_irq_any stayed {last} for {_IRQ_POLL_BOUND} "
        f"clk_smc_i cycles, want {want}"
    )


class smc_telemetry_receiver_csr_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_telemetry_receiver_csr_test_seq") -> None:
        super().__init__(name)
        # Values the run measured, published for the testcase module's record.
        self.irq_rise_cycles: int | None = None
        self.irq_fall_cycles: int | None = None
        self.quiet_receivers_proved: list[int] = []
        #: TELEMETRY_DATA read per receiver after its own beat.
        self.rx_data: dict[int, int] = {}
        #: STATUS word sampled per receiver while its FIFO was non-empty.
        self.rx_status: dict[int, int] = {}

    async def _atb_beat_leg(self, dut, rx: int) -> None:
        """Send one beat into receiver `rx` and score its CSR consequence."""
        beat = RX_BEATS[rx]
        status_addr = _rx_addr("STATUS", rx)
        data_addr = _rx_addr("TELEMETRY_DATA", rx)
        before = await self.csr_read(f"TELEMETRY_{rx}_STATUS_PRE_ATB", status_addr)
        assert before & BUFFER_EMPTY_BM, (
            f"TELEMETRY_{rx} STATUS.BUFFER_EMPTY expected before its ATB beat, got "
            f"0x{before:08x}; a later non-empty sample would not be attributable to this leg"
        )
        await _HeldSource(dut, [beat], rx=rx).task
        status = 0
        for _ in range(_BUFFER_POLL_BOUND):
            status = await self.csr_read(f"TELEMETRY_{rx}_STATUS_ATB", status_addr)
            if not (status & BUFFER_EMPTY_BM):
                break
            await ClockCycles(dut.clk_smc_i, 1)
        else:
            raise AssertionError(
                f"TELEMETRY_{rx} FIFO stayed EMPTY after its ATB beat "
                f"(STATUS=0x{status:08x}) over {_BUFFER_POLL_BOUND} polls"
            )
        data = await self.csr_read(f"TELEMETRY_{rx}_DATA_ATB", data_addr, expected=_word(beat))
        await self.csr_read(f"TELEMETRY_{rx}_DATA_EMPTY", data_addr, expected=0)
        await self.csr_read(f"TELEMETRY_{rx}_STATUS_DRAINED", status_addr, expected=BUFFER_EMPTY_BM)
        self.rx_data[rx] = data
        self.rx_status[rx] = status
        cocotb.log.info(
            "CHK-TELEMETRY-RECEIVER-%d-ATB: STATUS went 0x%08x (EMPTY set) -> 0x%08x (EMPTY "
            "clear) and TELEMETRY_DATA read back 0x%08x for the beat (ATID 0x%02X, DATA 0x%02X) "
            "sent into receiver %d, then 0x00000000 with the FIFO empty again",
            rx,
            before,
            status,
            data,
            beat[0],
            beat[1],
            rx,
        )

    async def body(self) -> None:
        dut = cocotb.top
        for name, addr, expected in TELEMETRY_READS:
            await self.csr_read(name, addr, expected=expected)

        # Receivers 1/2: one behavioural leg each, so the claim for them is not
        # limited to "the window decodes and reads its reset values".
        for rx in _QUIET_RECEIVERS:
            addr = _rx_addr("INTR_ENABLE", rx)
            await self.csr_write(f"TELEMETRY_{rx}_INTR_ENABLE_WR", addr, ENABLE_THRESHOLD_BM)
            await self.csr_read(
                f"TELEMETRY_{rx}_INTR_ENABLE_RB", addr, expected=ENABLE_THRESHOLD_BM
            )
            await self.csr_write(f"TELEMETRY_{rx}_INTR_ENABLE_RESTORE", addr, 0)
            await self.csr_read(f"TELEMETRY_{rx}_INTR_ENABLE_RESTORE_RB", addr, expected=0)
            self.quiet_receivers_proved.append(rx)

        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write(
            "CLOCK_GATE_CONTROL_TELEMETRY_UNGATE", _CLOCK_GATE_CONTROL, cg & ~TELEMETRY_CG_EN
        )
        # The readback is the completion handshake for the ungate: a real AXI
        # round trip with an exact expectation, not a settling delay.
        await self.csr_read(
            "CLOCK_GATE_CONTROL_TELEMETRY_UNGATE_RB",
            _CLOCK_GATE_CONTROL,
            expected=cg & ~TELEMETRY_CG_EN,
        )

        # --- U4-6a: INTR_TEST -> tb_telemetry_irq_any
        irq_before = int(dut.tb_telemetry_irq_any.value)
        assert irq_before == 0, (
            f"tb_telemetry_irq_any is already {irq_before} before INTR_TEST is "
            f"written; the rise observed below could not be attributed to it"
        )
        intr_enable = _rx_addr("INTR_ENABLE")
        intr_test = _rx_addr("INTR_TEST")
        intr_status = _rx_addr("INTR_STATUS")
        await self.csr_write("TELEMETRY_0_INTR_ENABLE", intr_enable, ENABLE_THRESHOLD_BM)
        await self.csr_write("TELEMETRY_0_INTR_TEST", intr_test, _TEST_THRESHOLD)
        self.irq_rise_cycles = await _await_irq_level(dut, 1, "INTR_TEST rise")
        intr_st = await self.csr_read("TELEMETRY_0_INTR_STATUS_POST", intr_status)
        assert intr_st == INTR_THRESHOLD_BM, (
            f"tb_telemetry_irq_any rose but TELEMETRY_0 INTR_STATUS reads 0x{intr_st:08x}, "
            f"not exactly BUFFER_THRESHOLD (0x{INTR_THRESHOLD_BM:x})"
        )
        await self.csr_write("TELEMETRY_0_INTR_TEST_RELEASE", intr_test, 0)
        self.irq_fall_cycles = await _await_irq_level(dut, 0, "INTR_TEST release")
        await self.csr_read("TELEMETRY_0_INTR_STATUS_RELEASED", intr_status, expected=0)
        await self.csr_write("TELEMETRY_0_INTR_ENABLE_OFF", intr_enable, 0)

        # --- U4-6b/c: one beat into each receiver
        for rx in range(_TELEMETRY_RECEIVERS):
            assert hasattr(dut, f"tb_telemetry{rx}_atvalid"), f"tb_telemetry{rx}_* ports missing"
            await self._atb_beat_leg(dut, rx)

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        # Every field below is a value this run read back or counted.
        cocotb.log.info(
            "CHK-TELEMETRY-RECEIVER-CSR: %d registers of %d receivers read their reset values, "
            "TELEMETRY_DATA 0 among them; INTR_TEST.BUFFER_THRESHOLD raised "
            "tb_telemetry_irq_any %d clk_smc_i cycle(s) after the write and writing it to 0 "
            "released it %d cycle(s) after; receivers %s each stored and restored "
            "INTR_ENABLE=0x%02x; receiver 0 read back TELEMETRY_DATA 0x%08x and STATUS 0x%08x "
            "(EMPTY clear) after its own beat",
            len(_TELEMETRY_REG_TYPES),
            _TELEMETRY_RECEIVERS,
            self.irq_rise_cycles,
            self.irq_fall_cycles,
            ",".join(str(r) for r in self.quiet_receivers_proved),
            ENABLE_THRESHOLD_BM,
            self.rx_data[0],
            self.rx_status[0],
        )
