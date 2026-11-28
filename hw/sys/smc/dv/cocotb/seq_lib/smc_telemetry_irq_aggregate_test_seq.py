# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry interrupt aggregation across receivers 0, 1 and 2.

Spec sources: hw/sys/smc/doc/interrupts.adoc, hw/ip/telemetry_receiver/doc/architecture.adoc,
regs/telemetry_receiver.rdl.

Each receiver has one interrupt source, ``BUFFER_THRESHOLD``, raised either by more beats in
the FIFO than ``CTRL.BUFFER_THRESHOLD`` or by ``INTR_TEST.BUFFER_THRESHOLD``. A
``TELEMETRY_DATA`` read that brings the count back down releases the first, and writing
``INTR_TEST`` to 0 releases the second.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_EMPTY_BM,
    ENABLE_THRESHOLD_BM,
    RX_FLUSH_BM,
    _HeldSource,
    _rx_addr,
    _tel,
    _word,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
RECEIVERS = (0, 1, 2)

THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
TEST_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm")

#: With `CTRL.BUFFER_THRESHOLD` at its reset of 0, one beat raises the source.
COUNT_BEAT = (0x11, 0x5C)
MASKED_BEAT = (0x12, 0x7E)

FUSE_SENSE_BOUND = 200_000
IRQ_POLL_BOUND = 64
STATUS_POLL_BOUND = 200
QUIET_CYCLES = 64

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
FENCE_TERMS = (
    "SETUP_DONE",
    "ONE_RECEIVER_DONE",
    "TWO_RECEIVERS_DONE",
    "EACH_SOURCE_DONE",
    "MASKED_QUIET_DONE",
)
CHK_STEP = (
    ("CHK-TELEMETRY-IRQ-ANY-OF-THREE", "S2"),
    ("CHK-TELEMETRY-IRQ-LAST-RELEASE", "S3"),
    ("CHK-TELEMETRY-IRQ-EACH-SOURCE", "S4"),
    ("CHK-TELEMETRY-IRQ-MASKED-QUIET", "S5"),
    ("CHK-TIMEOUT-PATHS", "S5"),
)


def _level(signal, name: str) -> int:
    raw = signal.value
    assert raw.is_resolvable, f"{name} is X/Z: {raw}"
    return int(raw)


class smc_telemetry_irq_aggregate_test_seq(SmcCsrSeq):
    """One, two, independent and masked interrupt sources across the three receivers."""

    def __init__(self, name: str = "smc_telemetry_irq_aggregate_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last = "none"

    def _note_wait(self, name: str, bound: str) -> None:
        if all(known != name for known, _, _ in self._waits):
            self._waits.append((name, bound, ""))

    def _end_wait(self, name: str, last: str) -> None:
        self._waits = [(n, b, last if n == name else s) for n, b, s in self._waits]

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        cocotb.log.info("%s: " + text, chk_id, *args)
        self._chk_marks.append((chk_id, len(self._stamps)))

    def _vector(self) -> tuple[int, int]:
        dut = cocotb.top
        return _level(dut.tb_telemetry_irq, "tb_telemetry_irq"), _level(
            dut.tb_telemetry_irq_any, "tb_telemetry_irq_any"
        )

    async def _read(self, label: str, reg: str, rx: int) -> int:
        self._last = f"read {label} {reg}[{rx}]"
        return await self.csr_read(f"{label}_{reg}_{rx}", _rx_addr(reg, rx))

    async def _write(self, label: str, reg: str, rx: int, data: int) -> None:
        self._last = f"write {label} {reg}[{rx}]=0x{data:08x}"
        await self.csr_write(f"{label}_{reg}_{rx}", _rx_addr(reg, rx), data)

    async def _await_vector(self, label: str, want_vec: int, want_any: int) -> int:
        """Poll the irq vector and aggregate until both match; returns the cycles taken."""
        self._note_wait("irq_poll", f"{IRQ_POLL_BOUND}_clk_smc_i_cycles")
        vec, any_ = self._vector()
        for cyc in range(IRQ_POLL_BOUND + 1):
            if (vec, any_) == (want_vec, want_any):
                self._end_wait("irq_poll", f"{label}_irq=0b{vec:03b}_any={any_}")
                return cyc
            await RisingEdge(cocotb.top.clk_smc_i)
            vec, any_ = self._vector()
        self._end_wait("irq_poll", f"{label}_irq=0b{vec:03b}_any={any_}_expired")
        raise AssertionError(
            f"{label}: tb_telemetry_irq=0b{vec:03b} tb_telemetry_irq_any={any_} did not reach "
            f"0b{want_vec:03b}/{want_any} over {IRQ_POLL_BOUND} clk_smc_i cycles"
        )

    async def _wait_flushed(self, label: str, rx: int) -> None:
        self._note_wait("status_poll", f"{STATUS_POLL_BOUND}_polls")
        status = 0
        for _ in range(STATUS_POLL_BOUND):
            status = await self._read(label, "STATUS", rx)
            if status & BUFFER_EMPTY_BM:
                self._end_wait("status_poll", f"rx{rx}_STATUS=0x{status:08x}")
                return
        self._end_wait("status_poll", f"rx{rx}_STATUS=0x{status:08x}_expired")
        raise AssertionError(
            f"{label}: receiver {rx} STATUS.BUFFER_EMPTY not set over {STATUS_POLL_BOUND} polls "
            f"(last STATUS=0x{status:08x})"
        )

    async def _raise_by_count(self, label: str, rx: int, beat: tuple[int, int]) -> int:
        """Send one beat with `CTRL.BUFFER_THRESHOLD` at 0; returns the polls to the source."""
        self._note_wait("threshold_poll", f"{STATUS_POLL_BOUND}_polls")
        await _HeldSource(cocotb.top, [beat], rx=rx).task
        intr = 0
        for polls in range(1, STATUS_POLL_BOUND + 1):
            intr = await self._read(f"{label}_{polls}", "INTR_STATUS", rx)
            if intr & THRESHOLD_BM:
                self._end_wait("threshold_poll", f"rx{rx}_INTR_STATUS=0x{intr:08x}")
                return polls
        self._end_wait("threshold_poll", f"rx{rx}_INTR_STATUS=0x{intr:08x}_expired")
        raise AssertionError(
            f"{label}: INTR_STATUS.BUFFER_THRESHOLD of receiver {rx} never set over "
            f"{STATUS_POLL_BOUND} polls with one beat against a threshold of 0"
        )

    async def _release_test(self, label: str, rx: int) -> None:
        await self._write(label, "INTR_TEST", rx, 0)

    async def _setup(self) -> int:
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self._waits.append(("fuse_sense_done", f"{FUSE_SENSE_BOUND}_smc_cycles", "done"))
        cg = await self.csr_read("CG_SAVE", CLOCK_GATE_CONTROL)
        ungated = cg & ~TELEMETRY_CG_EN
        await self.csr_write("CG_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CG_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)
        for rx in RECEIVERS:
            await self._write("SETUP_FLUSH", "CTRL", rx, RX_FLUSH_BM)
            await self._wait_flushed("SETUP_FLUSHED", rx)
            await self._write("SETUP_ENABLE", "INTR_ENABLE", rx, 0)
            await self._write("SETUP_TEST", "INTR_TEST", rx, 0)
        vec, any_ = self._vector()
        assert (vec, any_) == (0, 0), f"setup left irq=0b{vec:03b} any={any_}"
        self._stamp("S1")
        return cg

    async def _one_receiver(self) -> list[tuple[int, int]]:
        seen = []
        for rx in RECEIVERS:
            await self._write("ONE_ENABLE", "INTR_ENABLE", rx, ENABLE_THRESHOLD_BM)
            await self._write("ONE_TEST", "INTR_TEST", rx, TEST_THRESHOLD_BM)
            rise = await self._await_vector(f"one_rx{rx}_rise", 1 << rx, 1)
            await self._release_test(f"ONE_REL_{rx}", rx)
            fall = await self._await_vector(f"one_rx{rx}_fall", 0, 0)
            await self._write("ONE_DISABLE", "INTR_ENABLE", rx, 0)
            seen.append((rise, fall))
        self._stamp("S2")
        self._chk(
            "CHK-TELEMETRY-IRQ-ANY-OF-THREE",
            "a source on receiver 0, 1 and 2 alone set tb_telemetry_irq to 0b001, 0b010 and "
            "0b100 with tb_telemetry_irq_any=1 after %s clk_smc_i cycle(s); both read 0 after "
            "release, after %s cycle(s); platform interrupt IDs and PLIC delivery are not "
            "observable here (not specified, measured)",
            "/".join(str(r) for r, _ in seen),
            "/".join(str(f) for _, f in seen),
        )
        return seen

    async def _two_receivers(self) -> None:
        for rx in (0, 2):
            await self._write("TWO_ENABLE", "INTR_ENABLE", rx, ENABLE_THRESHOLD_BM)
            await self._write("TWO_TEST", "INTR_TEST", rx, TEST_THRESHOLD_BM)
        both = await self._await_vector("two_rise", 0b101, 1)
        await self._release_test("TWO_REL_0", 0)
        first = await self._await_vector("two_after_rx0", 0b100, 1)
        await self._release_test("TWO_REL_2", 2)
        last = await self._await_vector("two_after_rx2", 0, 0)
        for rx in (0, 2):
            await self._write("TWO_DISABLE", "INTR_ENABLE", rx, 0)
        self._stamp("S3")
        self._chk(
            "CHK-TELEMETRY-IRQ-LAST-RELEASE",
            "receivers 0 and 2 asserted 0b101 after %d cycle(s); clearing receiver 0 left "
            "tb_telemetry_irq=0b100 with tb_telemetry_irq_any=1 after %d; clearing receiver 2 "
            "released both to 0 after %d",
            both,
            first,
            last,
        )

    async def _each_source(self) -> None:
        rx = 1
        await self._write("EACH_COUNT_ENABLE", "INTR_ENABLE", rx, ENABLE_THRESHOLD_BM)
        polls = await self._raise_by_count("EACH_COUNT", rx, COUNT_BEAT)
        count_rise = await self._await_vector("each_count_rise", 0b010, 1)
        data = await self._read("EACH_COUNT_POP", "TELEMETRY_DATA", rx)
        assert data == _word(COUNT_BEAT), (
            f"EACH_COUNT: receiver {rx} TELEMETRY_DATA read 0x{data:08x}, expected the beat sent "
            f"0x{_word(COUNT_BEAT):08x}"
        )
        count_fall = await self._await_vector("each_count_fall", 0, 0)
        await self._write("EACH_COUNT_DISABLE", "INTR_ENABLE", rx, 0)
        await self._write("EACH_BT_ENABLE", "INTR_ENABLE", rx, ENABLE_THRESHOLD_BM)
        await self._write("EACH_BT_TEST", "INTR_TEST", rx, TEST_THRESHOLD_BM)
        bt_rise = await self._await_vector("each_bt_rise", 0b010, 1)
        await self._release_test("EACH_BT_REL", rx)
        bt_fall = await self._await_vector("each_bt_fall", 0, 0)
        await self._write("EACH_BT_DISABLE", "INTR_ENABLE", rx, 0)
        self._stamp("S4")
        self._chk(
            "CHK-TELEMETRY-IRQ-EACH-SOURCE",
            "on receiver 1 a beat over CTRL.BUFFER_THRESHOLD=0 alone (INTR_STATUS set after %d "
            "poll(s)) drove tb_telemetry_irq=0b010 and the aggregate after %d cycle(s) and the "
            "TELEMETRY_DATA read that returned it released both after %d; INTR_TEST alone drove "
            "0b010 and the aggregate after %d and released after %d on INTR_TEST=0",
            polls,
            count_rise,
            count_fall,
            bt_rise,
            bt_fall,
        )

    async def _masked_quiet(self) -> None:
        polls = await self._raise_by_count("MASK_COUNT", 1, MASKED_BEAT)
        for rx in RECEIVERS:
            await self._write("MASK_TEST", "INTR_TEST", rx, TEST_THRESHOLD_BM)
        statuses = {}
        for rx in RECEIVERS:
            statuses[rx] = await self._read("MASK_STATUS", "INTR_STATUS", rx)
            assert statuses[rx] & THRESHOLD_BM, (
                f"masked state is vacuous: receiver {rx} INTR_STATUS=0x{statuses[rx]:08x}, "
                f"BUFFER_THRESHOLD not set"
            )
        dut = cocotb.top
        for cyc in range(QUIET_CYCLES):
            await RisingEdge(dut.clk_smc_i)
            vec, any_ = self._vector()
            assert (vec, any_) == (0, 0), (
                f"masked sources raised tb_telemetry_irq=0b{vec:03b} any={any_} at quiet "
                f"cycle {cyc}"
            )
        for rx in RECEIVERS:
            await self._release_test(f"MASK_REL_{rx}", rx)
        await self._write("MASK_FLUSH", "CTRL", 1, RX_FLUSH_BM)
        await self._wait_flushed("MASK_END", 1)
        for rx in RECEIVERS:
            await self.csr_read(f"MASK_RELEASED_{rx}", _rx_addr("INTR_STATUS", rx), expected=0)
        vec, any_ = self._vector()
        assert (vec, any_) == (0, 0), f"after the releases irq=0b{vec:03b} any={any_}"
        self._stamp("S5")
        self._chk(
            "CHK-TELEMETRY-IRQ-MASKED-QUIET",
            "with every INTR_ENABLE 0, tb_telemetry_irq=0b000 and tb_telemetry_irq_any=0 for %d "
            "cycles while INTR_STATUS read 0x%08x / 0x%08x / 0x%08x on receivers 0 / 1 / 2 "
            "(INTR_TEST on all three, and on receiver 1 also a beat over the threshold, set "
            "after %d poll(s)); releasing INTR_TEST and flushing receiver 1 returned all three "
            "to 0",
            QUIET_CYCLES,
            statuses[0],
            statuses[1],
            statuses[2],
            polls,
        )

    async def body(self) -> None:
        dut = cocotb.top
        for name in ("tb_telemetry_irq", "tb_telemetry_irq_any"):
            assert hasattr(dut, name), f"{name} missing from the bench top"
        cg = await self._setup()
        await self._one_receiver()
        await self._two_receivers()
        await self._each_source()
        await self._masked_quiet()
        await self.csr_write("CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        self._note_wait("sep_in_access", f"{self.cfg.axi_timeout_ns}ns_driver_bound")
        self._end_wait("sep_in_access", self._last)
        waits = " ".join(f"{n}={b} last={s}" for n, b, s in self._waits)
        self._chk(
            "CHK-TIMEOUT-PATHS",
            "%d bounded waits: %s; expiry raises AssertionError",
            len(self._waits),
            waits,
        )
        self._assert_fence()

    def _assert_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == STEP_ORDER, f"step ids {ids} != expected order {STEP_ORDER}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        want = tuple(c for c, _ in CHK_STEP)
        assert chk_ids == want, f"checker lines {chk_ids} != order {want}"
        step_index = {s: i + 1 for i, s in enumerate(STEP_ORDER)}
        for (chk_id, stamps_at_print), (_, step) in zip(self._chk_marks, CHK_STEP):
            assert stamps_at_print >= step_index[step], f"{chk_id} printed before step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            " ".join(chk_ids),
            " ".join(f"{s}={t}" for s, t in self._stamps),
        )
