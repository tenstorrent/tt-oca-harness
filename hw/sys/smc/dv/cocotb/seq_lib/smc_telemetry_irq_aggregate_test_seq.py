# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry interrupt aggregation across receivers 0, 1 and 2.

Spec sources: hw/sys/smc/doc/interrupts.adoc, hw/ip/telemetry_receiver/doc/architecture.adoc,
regs/telemetry_receiver.rdl.

ATB framing from telemetry_receiver/doc/architecture.adoc (Assembly and Decode): eight beats
LSB first, bit 63 last packet, probe ID [60:56]; the 9-bit block layout from bit 0 is a bench
choice.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    _REPO,
    TELEMETRY_CG_EN,
    _field_mask,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

_TELEMETRY_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)


def _tel(symbol: str) -> int:
    return _field_mask(_TELEMETRY_H, symbol)


def _addr(register: str, rx: int) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{register}_BASE_ADDR", rx
    )


CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
RECEIVERS = (0, 1, 2)

RX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
BUFFER_EMPTY_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
MISSING_LAST_BM = _tel("TELEMETRY_RECEIVER__INTR_STATUS__MISSING_LAST_bm")
THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
ENABLE_MISSING_LAST_BM = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__MISSING_LAST_bm")
ENABLE_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__BUFFER_THRESHOLD_bm")
TEST_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm")

BEAT_BITS = 8
PACKET_BITS = 64
BEATS_PER_PACKET = PACKET_BITS // BEAT_BITS
BLOCK_BITS = 9
PROBE_ID_BITS = 5
PROBE_ID_LSB = 56
LAST_PACKET_BIT = 63
NEXT_BLOCK_LSB = 54
ATID = {0: 0x00, 1: 0x11, 2: 0x22}

FUSE_SENSE_BOUND = 200_000
ATB_ACCEPT_BOUND = 64
IRQ_POLL_BOUND = 64
STATUS_POLL_BOUND = 200
MAX_PACKETS = 16
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


def _mid_packet() -> int:
    """A packet without the last-packet flag."""
    packet = 0x0A << PROBE_ID_LSB
    for lsb in range(0, NEXT_BLOCK_LSB, BLOCK_BITS):
        packet |= ((1 << BLOCK_BITS) - 1) << lsb
    return packet


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
        self.packets_to_missing_last = 0

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
        return await self.csr_read(f"{label}_{reg}_{rx}", _addr(reg, rx))

    async def _write(self, label: str, reg: str, rx: int, data: int) -> None:
        self._last = f"write {label} {reg}[{rx}]=0x{data:08x}"
        await self.csr_write(f"{label}_{reg}_{rx}", _addr(reg, rx), data)

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

    async def _beat(self, rx: int, value: int, beat: int) -> None:
        dut = cocotb.top
        getattr(dut, f"tb_telemetry{rx}_atdata").value = value & 0xFF
        getattr(dut, f"tb_telemetry{rx}_atid").value = ATID[rx] & 0x7F
        atvalid = getattr(dut, f"tb_telemetry{rx}_atvalid")
        atready = getattr(dut, f"tb_telemetry{rx}_atready")
        atvalid.value = 1
        await RisingEdge(dut.clk_smc_i)
        accepted = False
        for _ in range(ATB_ACCEPT_BOUND):
            if _level(atready, f"tb_telemetry{rx}_atready"):
                accepted = True
                break
            await RisingEdge(dut.clk_smc_i)
        atvalid.value = 0
        self._note_wait("atb_beat_accept", f"{ATB_ACCEPT_BOUND}_clk_smc_i_cycles")
        state = f"rx{rx}_beat{beat}_{'accepted' if accepted else 'atready_low'}"
        self._end_wait("atb_beat_accept", state)
        if not accepted:
            raise AssertionError(
                f"ATB beat {beat} into receiver {rx} never accepted over {ATB_ACCEPT_BOUND} "
                f"clk_smc_i cycles"
            )

    async def _send_packet(self, rx: int, packet: int) -> None:
        for beat in range(BEATS_PER_PACKET):
            await self._beat(rx, (packet >> (beat * BEAT_BITS)) & 0xFF, beat)

    async def _raise_missing_last(self, label: str, rx: int) -> int:
        """Send unflagged packets until INTR_STATUS.MISSING_LAST sets; returns the count."""
        for packets in range(1, MAX_PACKETS + 1):
            await self._send_packet(rx, _mid_packet())
            intr = await self._read(f"{label}_{packets}", "INTR_STATUS", rx)
            if intr & MISSING_LAST_BM:
                return packets
        raise AssertionError(
            f"{label}: INTR_STATUS.MISSING_LAST of receiver {rx} never set over {MAX_PACKETS} "
            f"packets without the last-packet flag"
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
            await self._write("SETUP_CLR", "INTR_STATUS", rx, MISSING_LAST_BM)
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
        await self._write("EACH_ML_ENABLE", "INTR_ENABLE", rx, ENABLE_MISSING_LAST_BM)
        packets = await self._raise_missing_last("EACH_ML", rx)
        self.packets_to_missing_last = packets
        ml_rise = await self._await_vector("each_ml_rise", 0b010, 1)
        await self._write("EACH_ML_CLR", "INTR_STATUS", rx, MISSING_LAST_BM)
        ml_fall = await self._await_vector("each_ml_fall", 0, 0)
        await self._write("EACH_ML_DISABLE", "INTR_ENABLE", rx, 0)
        await self._write("EACH_BT_ENABLE", "INTR_ENABLE", rx, ENABLE_THRESHOLD_BM)
        await self._write("EACH_BT_TEST", "INTR_TEST", rx, TEST_THRESHOLD_BM)
        bt_rise = await self._await_vector("each_bt_rise", 0b010, 1)
        await self._release_test("EACH_BT_REL", rx)
        bt_fall = await self._await_vector("each_bt_fall", 0, 0)
        await self._write("EACH_BT_DISABLE", "INTR_ENABLE", rx, 0)
        self._stamp("S4")
        self._chk(
            "CHK-TELEMETRY-IRQ-EACH-SOURCE",
            "on receiver 1 MISSING_LAST alone (set after %d unflagged packets, measured) drove "
            "tb_telemetry_irq=0b010 and the aggregate after %d cycle(s) and released after %d "
            "on a written one; BUFFER_THRESHOLD alone drove 0b010 and the aggregate after %d "
            "and released after %d on INTR_TEST=0",
            packets,
            ml_rise,
            ml_fall,
            bt_rise,
            bt_fall,
        )

    async def _masked_quiet(self) -> None:
        for rx in RECEIVERS:
            await self._write("MASK_TEST", "INTR_TEST", rx, TEST_THRESHOLD_BM)
        packets = await self._raise_missing_last("MASK_ML", 1)
        statuses = {}
        for rx in RECEIVERS:
            statuses[rx] = await self._read("MASK_STATUS", "INTR_STATUS", rx)
            want = THRESHOLD_BM | (MISSING_LAST_BM if rx == 1 else 0)
            assert statuses[rx] & want == want, (
                f"masked state is vacuous: receiver {rx} INTR_STATUS=0x{statuses[rx]:08x}, "
                f"sources 0x{want:08x} not all set"
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
            await self._write("MASK_CLR", "INTR_STATUS", rx, MISSING_LAST_BM | THRESHOLD_BM)
        await self._wait_flushed("MASK_END", 1)
        vec, any_ = self._vector()
        assert (vec, any_) == (0, 0), f"after the clears irq=0b{vec:03b} any={any_}"
        self._stamp("S5")
        self._chk(
            "CHK-TELEMETRY-IRQ-MASKED-QUIET",
            "with every INTR_ENABLE 0, tb_telemetry_irq=0b000 and tb_telemetry_irq_any=0 for %d "
            "cycles while INTR_STATUS read 0x%08x / 0x%08x / 0x%08x on receivers 0 / 1 / 2 "
            "(receiver 1 MISSING_LAST set after %d unflagged packets, measured)",
            QUIET_CYCLES,
            statuses[0],
            statuses[1],
            statuses[2],
            packets,
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
