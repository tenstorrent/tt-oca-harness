# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receivers 0, 1 and 2 stay independent of one another.

Spec sources: hw/ip/telemetry_receiver/doc/architecture.adoc, doc/interface.adoc,
regs/telemetry_receiver.rdl.

The ATB framing is the DV-owned layout of the receiver CSR leaf: eight-bit beats assemble
LSB-first into 64-bit packets of 9-bit blocks (doc/architecture.adoc, doc/interface.adoc), a
5-bit probe ID header and a last-packet flag; the bit positions of header and flag are bench
assumptions, as in that leaf. The message driven here is one last-flagged packet.
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

BUFFER_POP_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm")
RX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
THRESHOLD_BP = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bm")
BUFFER_EMPTY_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
PROBE_ID_BM = _tel("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bm")
INTR_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
ENABLE_THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__BUFFER_THRESHOLD_bm")

REGS_ALL = ("STATUS", "TELEMETRY_PROBE_ID", "TELEMETRY_COUNTER_VLDS", "INTR_STATUS", "CTRL")
REGS_OPS = ("STATUS", "TELEMETRY_PROBE_ID", "INTR_STATUS", "CTRL")

# DV-owned ATB framing (bit positions are bench assumptions, see the module docstring).
BEAT_BITS = 8
PACKET_BITS = 64
BEATS_PER_PACKET = PACKET_BITS // BEAT_BITS
BLOCK_BITS = 9
PROBE_ID_BITS = 5
PROBE_ID_LSB = 56
LAST_PACKET_BIT = 63
NEXT_BLOCK_LSB = 54

ATID = {0: 0x00, 1: 0x11, 2: 0x22}
SINGLE_PROBE = {0: 0x0A, 1: 0x0B, 2: 0x0C}
SIMULTANEOUS_PROBES = {0: (0x05, 0x06), 1: (0x0A, 0x0B), 2: (0x13, 0x14)}
OPS_PROBES = {0: (0x05,), 1: (0x0A, 0x0B), 2: (0x13, 0x14, 0x15)}
OPS_THRESHOLD = 1
OPS_THRESHOLD_REWRITE = 2

FUSE_SENSE_BOUND = 200_000
ATB_ACCEPT_BOUND = 64
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


def _frame_message(probe_id: int) -> int:
    """One last-flagged packet: probe ID in the header, every block valid with all-ones data."""
    packet = 1 << LAST_PACKET_BIT
    packet |= (probe_id & ((1 << PROBE_ID_BITS) - 1)) << PROBE_ID_LSB
    for lsb in range(0, NEXT_BLOCK_LSB, BLOCK_BITS):
        packet |= ((1 << BLOCK_BITS) - 1) << lsb
    return packet


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
        return await self.csr_read(f"{label}_{reg}_{rx}", _addr(reg, rx), expected=expected)

    async def _write(self, label: str, reg: str, rx: int, data: int) -> None:
        self._last = f"write {label} {reg}[{rx}]=0x{data:08x}"
        await self.csr_write(f"{label}_{reg}_{rx}", _addr(reg, rx), data)

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

    async def _beat(self, rx: int, value: int, beat: int, accepted_ps: list[int]) -> None:
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
                accepted_ps.append(int(get_sim_time("ps")))
                break
            await RisingEdge(dut.clk_smc_i)
        atvalid.value = 0
        self._note_wait("atb_beat_accept", f"{ATB_ACCEPT_BOUND}_clk_smc_i_cycles")
        if not accepted:
            self._end_wait("atb_beat_accept", f"rx{rx}_beat{beat}_atready_low")
            raise AssertionError(
                f"ATB beat {beat} (0x{value & 0xFF:02x}) into receiver {rx} never accepted over "
                f"{ATB_ACCEPT_BOUND} clk_smc_i cycles"
            )
        self._end_wait("atb_beat_accept", f"rx{rx}_beat{beat}_accepted")

    async def _send_messages(
        self, rx: int, probes: tuple[int, ...], accepted_ps: list[int]
    ) -> None:
        for index, probe_id in enumerate(probes):
            if index:
                await RisingEdge(cocotb.top.clk_smc_i)
            packet = _frame_message(probe_id)
            for i in range(BEATS_PER_PACKET):
                await self._beat(rx, (packet >> (i * BEAT_BITS)) & 0xFF, i, accepted_ps)

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
                assert before[o]["STATUS"] & BUFFER_EMPTY_BM, (
                    f"S2: receiver {o} not empty before the message to receiver {rx}"
                )
            await self._send_messages(rx, (SINGLE_PROBE[rx],), [])
            await self._wait_empty("S2_NONEMPTY", rx, False)
            probe = await self._read("S2_PROBE", "TELEMETRY_PROBE_ID", rx) & PROBE_ID_BM
            assert probe == SINGLE_PROBE[rx], (
                f"S2: receiver {rx} PROBE_ID reads 0x{probe:02x}, expected 0x{SINGLE_PROBE[rx]:02x}"
            )
            for o in others:
                await self._require_unchanged("S2_OTHER", o, before[o], REGS_ALL)
            await self._write("S2_POP", "CTRL", rx, BUFFER_POP_BM)
            await self._wait_empty("S2_DRAINED", rx, True)
            records.append(f"rx{rx}=0x{probe:02x}")
        self._stamp("S2")
        self._chk(
            "CHK-TELEMETRY-ISOLATION-TRAFFIC",
            "one single-packet message per receiver (%s) left STATUS, PROBE_ID, COUNTER_VLDS, "
            "INTR_STATUS and CTRL of the other two receivers at their pre-message words; the "
            "receiver addressed read nonempty with its own probe ID, then popped to empty",
            " ".join(records),
        )

    async def _simultaneous_traffic(self) -> None:
        accepted = {rx: [] for rx in RECEIVERS}
        tasks = [
            cocotb.start_soon(self._send_messages(rx, SIMULTANEOUS_PROBES[rx], accepted[rx]))
            for rx in RECEIVERS
        ]
        for task in tasks:
            await task
        shared = set(accepted[0]) & set(accepted[1]) & set(accepted[2])
        self.same_cycle_beats = len(shared)
        assert shared, "S3: no clk_smc_i cycle accepted a beat on all three receivers together"
        records = []
        for rx in RECEIVERS:
            got = []
            for idx, want in enumerate(SIMULTANEOUS_PROBES[rx]):
                await self._wait_empty(f"S3_NONEMPTY{idx}", rx, False)
                probe = await self._read(f"S3_PROBE{idx}", "TELEMETRY_PROBE_ID", rx) & PROBE_ID_BM
                got.append(probe)
                assert probe == want, (
                    f"S3: receiver {rx} message {idx} reads probe ID 0x{probe:02x}, expected "
                    f"0x{want:02x}; sent {[hex(p) for p in SIMULTANEOUS_PROBES[rx]]}"
                )
                await self._write(f"S3_POP{idx}", "CTRL", rx, BUFFER_POP_BM)
            await self._wait_empty("S3_DRAINED", rx, True)
            records.append(f"rx{rx}=" + ",".join(f"0x{p:02x}" for p in got))
        self._stamp("S3")
        self._chk(
            "CHK-TELEMETRY-ISOLATION-SIMULTANEOUS",
            "three ATB sources accepted beats in %d common clk_smc_i cycles; each receiver "
            "returned its own two probe IDs in order (%s) and was empty after the second pop",
            self.same_cycle_beats,
            " ".join(records),
        )

    async def _isolated_operations(self, dut) -> None:
        ctrl_thr = (OPS_THRESHOLD << THRESHOLD_BP) & THRESHOLD_BM
        for rx in RECEIVERS:
            await self._write("S4_THRESHOLD", "CTRL", rx, ctrl_thr)
            await self._read("S4_THRESHOLD_RB", "CTRL", rx, expected=ctrl_thr)
        for rx in RECEIVERS:
            await self._send_messages(rx, OPS_PROBES[rx], [])
            await self._wait_empty("S4_FILLED", rx, False)
            probe = await self._read("S4_FIRST", "TELEMETRY_PROBE_ID", rx) & PROBE_ID_BM
            assert probe == OPS_PROBES[rx][0], (
                f"S4: receiver {rx} PROBE_ID reads 0x{probe:02x}, expected "
                f"0x{OPS_PROBES[rx][0]:02x}"
            )

        irq_any_start = _level(dut.tb_telemetry_irq_any, "tb_telemetry_irq_any")
        intr_by_rx = {}
        # Pop receiver 0.
        before = {o: await self._stable_snapshot("S4_POP_PRE", o, REGS_OPS) for o in (1, 2)}
        intr_by_rx = {o: before[o]["INTR_STATUS"] for o in (1, 2)}
        await self._write("S4_POP", "CTRL", 0, BUFFER_POP_BM | ctrl_thr)
        await self._wait_empty("S4_POP_EMPTY", 0, True)
        for o in (1, 2):
            await self._require_unchanged("S4_POP_OTHER", o, before[o], REGS_OPS)
        # Flush receiver 1.
        before = {o: await self._stable_snapshot("S4_FLUSH_PRE", o, REGS_OPS) for o in (0, 2)}
        await self._write("S4_FLUSH", "CTRL", 1, RX_FLUSH_BM | ctrl_thr)
        await self._wait_empty("S4_FLUSH_EMPTY", 1, True)
        for o in (0, 2):
            await self._require_unchanged("S4_FLUSH_OTHER", o, before[o], REGS_OPS)
        # Rewrite threshold and enable of receiver 2.
        before = {o: await self._stable_snapshot("S4_CFG_PRE", o, REGS_OPS) for o in (0, 1)}
        ctrl_new = (OPS_THRESHOLD_REWRITE << THRESHOLD_BP) & THRESHOLD_BM
        await self._write("S4_CFG_THRESHOLD", "CTRL", 2, ctrl_new)
        await self._read("S4_CFG_THRESHOLD_RB", "CTRL", 2, expected=ctrl_new)
        await self._write("S4_CFG_ENABLE", "INTR_ENABLE", 2, ENABLE_THRESHOLD_BM)
        await self._read("S4_CFG_ENABLE_RB", "INTR_ENABLE", 2, expected=ENABLE_THRESHOLD_BM)
        for o in (0, 1):
            await self._require_unchanged("S4_CFG_OTHER", o, before[o], REGS_OPS)
        irq_any_end = _level(dut.tb_telemetry_irq_any, "tb_telemetry_irq_any")
        # Drain receiver 2 for a clean end state.
        await self._write("S4_CLEAN_FLUSH", "CTRL", 2, RX_FLUSH_BM)
        await self._wait_empty("S4_CLEAN_EMPTY", 2, True)
        self._stamp("S4")
        sf020 = {
            rx: hasattr(dut, f"tb_telemetry{rx}_afvalid")
            and hasattr(dut, f"tb_telemetry{rx}_afready")
            for rx in (1, 2)
        }
        self._chk(
            "CHK-TELEMETRY-ISOLATION-OPS",
            "with CTRL.BUFFER_THRESHOLD=%d and receivers holding 1, 2 and 3 messages, a pop on "
            "receiver 0, a flush on receiver 1 and a threshold (%d) plus enable (0x%x) rewrite "
            "on receiver 2 left the untouched receivers at the words taken before each "
            "operation (STATUS, PROBE_ID, INTR_STATUS, CTRL); measured INTR_STATUS before the "
            "pop rx1=0x%x rx2=0x%x, tb_telemetry_irq_any %d -> %d; measured: transmitter "
            "flush pins at the bench boundary rx1=%s rx2=%s",
            OPS_THRESHOLD,
            OPS_THRESHOLD_REWRITE,
            ENABLE_THRESHOLD_BM,
            intr_by_rx[1],
            intr_by_rx[2],
            irq_any_start,
            irq_any_end,
            "present" if sf020[1] else "absent",
            "present" if sf020[2] else "absent",
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
