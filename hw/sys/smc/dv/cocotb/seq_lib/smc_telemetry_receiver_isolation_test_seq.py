# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receivers 0, 1 and 2 stay independent of one another.

Spec sources: hw/ip/telemetry_receiver/doc/architecture.adoc, doc/interface.adoc,
regs/telemetry_receiver.rdl.

Beats pushed into receiver *i* appear only at receiver *i*'s ``TELEMETRY_DATA``. Every beat
carries an ATB ID and a data byte no other beat in the test shares, so a beat that reached
another receiver's FIFO fails that receiver's compare. A read of an empty FIFO returns 0 and
removes nothing, so an idle receiver's ``TELEMETRY_DATA`` can be read before and after another
receiver's traffic without disturbing it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_EMPTY_BM,
    ENABLE_THRESHOLD_BM,
    RX_FLUSH_BM,
    THRESHOLD_BP,
    Beat,
    _HeldSource,
    _rx_addr,
    _stream,
    pop_expect,
    wait_more_than,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
RECEIVERS = (0, 1, 2)

# TELEMETRY_DATA is read only on a receiver whose FIFO is empty, where the read removes nothing.
REGS_ALL = ("STATUS", "TELEMETRY_DATA", "INTR_STATUS", "CTRL")
REGS_OPS = ("STATUS", "INTR_STATUS", "CTRL")

SINGLE_BEATS = {0: _stream(0x01, 0x10, 3), 1: _stream(0x11, 0x40, 3), 2: _stream(0x21, 0x70, 3)}
SIMULTANEOUS_BEATS = {
    0: _stream(0x31, 0x81, 6),
    1: _stream(0x41, 0xA1, 6),
    2: _stream(0x51, 0xC1, 6),
}
OPS_BEATS = {0: _stream(0x61, 0x02, 1), 1: _stream(0x64, 0x22, 2), 2: _stream(0x68, 0x42, 3)}
OPS_THRESHOLD = 1
OPS_THRESHOLD_REWRITE = 2
_ALL_BEATS = [
    b for table in (SINGLE_BEATS, SIMULTANEOUS_BEATS, OPS_BEATS) for v in table.values() for b in v
]
assert len(set(_ALL_BEATS)) == len(_ALL_BEATS), "two beats in the test share ATID and data"

FUSE_SENSE_BOUND = 200_000
STATUS_POLL_BOUND = 200
SNAPSHOT_BOUND = 8

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
FENCE_TERMS = (
    "SETUP_DONE",
    "SINGLE_RECEIVER_TRAFFIC",
    "SIMULTANEOUS_TRAFFIC",
    "ISOLATED_OPERATIONS",
)
CHK_STEP = (
    ("CHK-TELEMETRY-ISOLATION-TRAFFIC", "S2"),
    ("CHK-TELEMETRY-ISOLATION-SIMULTANEOUS", "S3"),
    ("CHK-TELEMETRY-ISOLATION-OPS", "S4"),
    ("CHK-TIMEOUT-PATHS", "S5"),
)


def _level(signal, name: str) -> int:
    raw = signal.value
    assert raw.is_resolvable, f"{name} is X/Z: {raw}"
    return int(raw)


class smc_telemetry_receiver_isolation_test_seq(SmcCsrSeq):
    """Traffic, simultaneous traffic and CSR operations on one receiver against the others."""

    def __init__(self, name: str = "smc_telemetry_receiver_isolation_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last = "none"
        self.same_cycle_beats = 0

    def _note_wait(self, name: str, bound: str) -> None:
        for known, _, _ in self._waits:
            if known == name:
                return
        self._waits.append((name, bound, ""))

    def _end_wait(self, name: str, last: str) -> None:
        self._waits = [(n, b, last if n == name else s) for n, b, s in self._waits]

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        cocotb.log.info("%s: " + text, chk_id, *args)
        self._chk_marks.append((chk_id, len(self._stamps)))

    async def _read(self, label: str, reg: str, rx: int, expected: int | None = None) -> int:
        self._last = f"read {label} {reg}[{rx}]"
        return await self.csr_read(f"{label}_{reg}_{rx}", _rx_addr(reg, rx), expected=expected)

    async def _write(self, label: str, reg: str, rx: int, data: int) -> None:
        self._last = f"write {label} {reg}[{rx}]=0x{data:08x}"
        await self.csr_write(f"{label}_{reg}_{rx}", _rx_addr(reg, rx), data)

    async def _snapshot(self, label: str, rx: int, regs: tuple[str, ...]) -> dict[str, int]:
        return {reg: await self._read(label, reg, rx) for reg in regs}

    async def _stable_snapshot(self, label: str, rx: int, regs: tuple[str, ...]) -> dict[str, int]:
        """Read the registers until two consecutive snapshots agree."""
        self._note_wait("stable_snapshot", f"{SNAPSHOT_BOUND}_rounds")
        prev = await self._snapshot(label, rx, regs)
        for _ in range(SNAPSHOT_BOUND):
            cur = await self._snapshot(label, rx, regs)
            if cur == prev:
                self._end_wait("stable_snapshot", f"rx{rx}_stable")
                return cur
            prev = cur
        self._end_wait("stable_snapshot", f"rx{rx}_unstable")
        raise AssertionError(f"{label}: receiver {rx} never read stably over {SNAPSHOT_BOUND}")

    async def _require_unchanged(
        self, label: str, rx: int, before: dict[str, int], regs: tuple[str, ...]
    ) -> None:
        for reg in regs:
            got = await self._read(label, reg, rx)
            assert got == before[reg], (
                f"{label}: receiver {rx} {reg} reads 0x{got:08x}, the word taken before was "
                f"0x{before[reg]:08x}"
            )

    async def _wait_empty(self, label: str, rx: int, empty: bool) -> int:
        self._note_wait("status_poll", f"{STATUS_POLL_BOUND}_polls")
        status = 0
        for polls in range(1, STATUS_POLL_BOUND + 1):
            status = await self._read(label, "STATUS", rx)
            if bool(status & BUFFER_EMPTY_BM) == empty:
                self._end_wait("status_poll", f"rx{rx}_STATUS=0x{status:08x}")
                return polls
        self._end_wait("status_poll", f"rx{rx}_STATUS=0x{status:08x}_expired")
        raise AssertionError(
            f"{label}: receiver {rx} STATUS.BUFFER_EMPTY never reached {int(empty)} over "
            f"{STATUS_POLL_BOUND} polls (last STATUS=0x{status:08x})"
        )

    async def _pop_beats(self, label: str, rx: int, beats: list[Beat]) -> list[int]:
        """Read `beats` in order from receiver `rx`, then require its TELEMETRY_DATA empty."""
        self._last = f"read {label} TELEMETRY_DATA[{rx}]"
        words = [await pop_expect(self, f"{label}{i}", beat, rx) for i, beat in enumerate(beats)]
        await self._read(f"{label}_EMPTY", "TELEMETRY_DATA", rx, expected=0)
        return words

    async def body(self) -> None:
        dut = cocotb.top
        for rx in RECEIVERS:
            for pin in ("atdata", "atid", "atvalid", "atready"):
                assert hasattr(dut, f"tb_telemetry{rx}_{pin}"), f"tb_telemetry{rx}_{pin} missing"
        assert hasattr(dut, "tb_telemetry_irq_any"), "tb_telemetry_irq_any missing"
        await self._setup(dut)
        await self._single_receiver_traffic()
        await self._simultaneous_traffic()
        await self._isolated_operations(dut)
        await self._timeout_paths()
        self._nonvac()

    async def _setup(self, dut) -> None:
        self._last = "wait_fuse_sense_done"
        self._note_wait("fuse_sense_done", f"{FUSE_SENSE_BOUND}_clk_smc_i_cycles")
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self._end_wait("fuse_sense_done", "done")
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        ungated = cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)
        for rx in RECEIVERS:
            await self._write("SETUP_FLUSH", "CTRL", rx, RX_FLUSH_BM)
            await self._wait_empty("SETUP_FLUSHED", rx, True)
            await self._write("SETUP_INTR_ENABLE", "INTR_ENABLE", rx, 0)
            await self._read("SETUP_INTR_ENABLE_RB", "INTR_ENABLE", rx, expected=0)
        self._stamp("S1")

    async def _single_receiver_traffic(self) -> None:
        records = []
        for rx in RECEIVERS:
            others = [r for r in RECEIVERS if r != rx]
            before = {o: await self._stable_snapshot("S2_PRE", o, REGS_ALL) for o in others}
            for o in others:
                assert before[o]["STATUS"] & BUFFER_EMPTY_BM and before[o]["TELEMETRY_DATA"] == 0, (
                    f"S2: receiver {o} not empty before the beats to receiver {rx}"
                )
            await _HeldSource(cocotb.top, SINGLE_BEATS[rx], rx=rx).task
            await self._wait_empty("S2_NONEMPTY", rx, False)
            words = await self._pop_beats("S2_DATA", rx, SINGLE_BEATS[rx])
            await self._wait_empty("S2_DRAINED", rx, True)
            for o in others:
                await self._require_unchanged("S2_OTHER", o, before[o], REGS_ALL)
            records.append(f"rx{rx}=" + ",".join(f"0x{w:08x}" for w in words))
        self._stamp("S2")
        self._chk(
            "CHK-TELEMETRY-ISOLATION-TRAFFIC",
            "three beats into one receiver at a time left STATUS, TELEMETRY_DATA (0, empty), "
            "INTR_STATUS and CTRL of the other two at their pre-traffic words; the receiver "
            "addressed returned exactly its own beats in order through TELEMETRY_DATA (%s) and "
            "was empty after them",
            " ".join(records),
        )

    async def _simultaneous_traffic(self) -> None:
        dut = cocotb.top
        sources = [_HeldSource(dut, SIMULTANEOUS_BEATS[rx], rx=rx) for rx in RECEIVERS]
        shared = 0
        while not all(source.done for source in sources):
            await FallingEdge(dut.clk_smc_i)
            shared += all(
                _level(getattr(dut, f"tb_telemetry{rx}_atvalid"), f"tb_telemetry{rx}_atvalid")
                and _level(getattr(dut, f"tb_telemetry{rx}_atready"), f"tb_telemetry{rx}_atready")
                for rx in RECEIVERS
            )
        for source in sources:
            await source.task
        self.same_cycle_beats = shared
        assert shared, "S3: no clk_smc_i cycle accepted a beat on all three receivers together"
        records = []
        for rx in RECEIVERS:
            words = await self._pop_beats("S3_DATA", rx, SIMULTANEOUS_BEATS[rx])
            await self._wait_empty("S3_DRAINED", rx, True)
            records.append(f"rx{rx}=" + ",".join(f"0x{w:08x}" for w in words))
        self._stamp("S3")
        self._chk(
            "CHK-TELEMETRY-ISOLATION-SIMULTANEOUS",
            "three ATB sources accepted beats in %d common clk_smc_i cycles; each receiver "
            "returned exactly its own %d beats in order (%s) and was empty after them",
            self.same_cycle_beats,
            len(SIMULTANEOUS_BEATS[0]),
            " ".join(records),
        )

    async def _isolated_operations(self, dut) -> None:
        ctrl_thr = OPS_THRESHOLD << THRESHOLD_BP
        for rx in RECEIVERS:
            await self._write("S4_THRESHOLD", "CTRL", rx, ctrl_thr)
            await self._read("S4_THRESHOLD_RB", "CTRL", rx, expected=ctrl_thr)
        for rx in RECEIVERS:
            await _HeldSource(dut, OPS_BEATS[rx], rx=rx).task
            await wait_more_than(self, "S4_FILLED", len(OPS_BEATS[rx]) - 1, rx, restore=ctrl_thr)

        irq_any_start = _level(dut.tb_telemetry_irq_any, "tb_telemetry_irq_any")
        # Read receiver 0's one beat.
        before = {o: await self._stable_snapshot("S4_POP_PRE", o, REGS_OPS) for o in (1, 2)}
        intr_by_rx = {o: before[o]["INTR_STATUS"] for o in (1, 2)}
        popped = await self._pop_beats("S4_POP", 0, OPS_BEATS[0])
        await self._wait_empty("S4_POP_EMPTY", 0, True)
        for o in (1, 2):
            await self._require_unchanged("S4_POP_OTHER", o, before[o], REGS_OPS)
        # Flush receiver 1.
        before = {o: await self._stable_snapshot("S4_FLUSH_PRE", o, REGS_OPS) for o in (0, 2)}
        await self._write("S4_FLUSH", "CTRL", 1, RX_FLUSH_BM | ctrl_thr)
        await self._wait_empty("S4_FLUSH_EMPTY", 1, True)
        await self._read("S4_FLUSH_DATA", "TELEMETRY_DATA", 1, expected=0)
        for o in (0, 2):
            await self._require_unchanged("S4_FLUSH_OTHER", o, before[o], REGS_OPS)
        # Rewrite threshold and enable of receiver 2.
        before = {o: await self._stable_snapshot("S4_CFG_PRE", o, REGS_OPS) for o in (0, 1)}
        ctrl_new = OPS_THRESHOLD_REWRITE << THRESHOLD_BP
        await self._write("S4_CFG_THRESHOLD", "CTRL", 2, ctrl_new)
        await self._read("S4_CFG_THRESHOLD_RB", "CTRL", 2, expected=ctrl_new)
        await self._write("S4_CFG_ENABLE", "INTR_ENABLE", 2, ENABLE_THRESHOLD_BM)
        await self._read("S4_CFG_ENABLE_RB", "INTR_ENABLE", 2, expected=ENABLE_THRESHOLD_BM)
        for o in (0, 1):
            await self._require_unchanged("S4_CFG_OTHER", o, before[o], REGS_OPS)
        irq_any_end = _level(dut.tb_telemetry_irq_any, "tb_telemetry_irq_any")
        # Receiver 2 kept its beats through the operations on the other two.
        kept = await self._pop_beats("S4_KEPT", 2, OPS_BEATS[2])
        await self._wait_empty("S4_CLEAN_EMPTY", 2, True)
        for rx in RECEIVERS:
            await self._write("S4_CLEAN_CTRL", "CTRL", rx, 0)
        await self._write("S4_CLEAN_ENABLE", "INTR_ENABLE", 2, 0)
        self._stamp("S4")
        af_pins_present = {
            rx: hasattr(dut, f"tb_telemetry{rx}_afvalid")
            and hasattr(dut, f"tb_telemetry{rx}_afready")
            for rx in (1, 2)
        }
        self._chk(
            "CHK-TELEMETRY-ISOLATION-OPS",
            "with CTRL.BUFFER_THRESHOLD=%d and receivers holding 1, 2 and 3 beats, a "
            "TELEMETRY_DATA read on receiver 0 (0x%08x), a flush on receiver 1 and a threshold "
            "(%d) plus enable (0x%x) rewrite on receiver 2 left the untouched receivers at the "
            "words taken before each operation (STATUS, INTR_STATUS, CTRL), and receiver 2 "
            "still returned its three beats in order (%s); measured INTR_STATUS before the read "
            "rx1=0x%x rx2=0x%x, tb_telemetry_irq_any %d -> %d; measured: transmitter flush pins "
            "at the bench boundary rx1=%s rx2=%s",
            OPS_THRESHOLD,
            popped[0],
            OPS_THRESHOLD_REWRITE,
            ENABLE_THRESHOLD_BM,
            ",".join(f"0x{w:08x}" for w in kept),
            intr_by_rx[1],
            intr_by_rx[2],
            irq_any_start,
            irq_any_end,
            "present" if af_pins_present[1] else "absent",
            "present" if af_pins_present[2] else "absent",
        )

    async def _timeout_paths(self) -> None:
        self._note_wait("sep_in_access", f"{self.cfg.axi_timeout_ns}ns_driver_bound")
        self._end_wait("sep_in_access", f"{self.accesses}_accesses_completed")
        await RisingEdge(cocotb.top.clk_smc_i)
        self._stamp("S5")
        text = " ".join(f"{n}={b} last={s}" for n, b, s in self._waits)
        self._chk(
            "CHK-TIMEOUT-PATHS",
            "%d bounded waits: %s; every expiry raises AssertionError with the last state",
            len(self._waits),
            text,
        )

    def _nonvac(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert steps == list(STEP_ORDER), f"step stamps {steps} not in expected order"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"step stamps not strictly increasing: {times}"
        )
        ids = [c for c, _ in self._chk_marks]
        assert ids == [c for c, _ in CHK_STEP], f"checker lines {ids} not in expected order"
        for (chk_id, count), (_, step) in zip(self._chk_marks, CHK_STEP, strict=True):
            assert count >= STEP_ORDER.index(step) + 1, (
                f"{chk_id} printed before its step {step} stamp"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ",".join(ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
