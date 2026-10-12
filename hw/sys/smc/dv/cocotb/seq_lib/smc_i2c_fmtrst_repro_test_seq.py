# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# Goal smc-i2c-fmtrst-repro, reproduction experiment derived from
# smc_i2c_controller_scl_hold_test S1-S2.
# Spec sources: hw/ip/i2c/regs/i2c.rdl TIMEOUT_CTRL, CONTROLLER_EVENTS, INTR_STATE, FIFO_CTRL.
# Fact-recording leaf: the START, CMD_COMPLETE and FDATA-consumed lines carry measured values.
"""I2C0 controller recovery from a bus-timeout halt with FIFO_CTRL.FMTRST and a W1C of BUS_TIMEOUT.

The DUT's I2C0 controller writes to the bench EEPROM target at 0x50 while a
second bench pad driver holds ``tb_i2c0_scl`` low at the address acknowledge for
3V, past ``TIMEOUT_CTRL.VAL`` in bus-timeout mode. The controller halts with
``CONTROLLER_EVENTS.BUS_TIMEOUT`` and ``INTR_STATE.CONTROLLER_HALT``.

Two recovery arms follow the halt, each ending with one START-flagged write
queued and a bounded observation window on the pads:

* arm A writes FIFO_CTRL.FMTRST and a W1C of BUS_TIMEOUT with CTRL.ENABLEHOST left set;
* arm B clears CTRL.ENABLEHOST first, writes FMTRST and the W1C, then sets ENABLEHOST.

Each arm prints three fact lines: a START decoded on the pads, INTR_STATE.CMD_COMPLETE
and the FMTLVL change across the window. A value of 0 on a fact line is a valid outcome.
TLOW of the bench bring-up timing is L; the timeout value V is 4L. Holds and the
observation window are counted on the peripheral clock.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_cg_obs_utils import assert_fence_progress, log_step, mark_fence
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CONTROLLER_EVENTS_BUS_TIMEOUT,
    I2C_FIFO_CTRL_FMTRST,
    I2C_HOST_FIFO_STATUS_FMTLVL,
    I2C_INTR_STATE_STRETCH_TIMEOUT,
    I2C_TIMEOUT_CTRL_EN,
    I2C_TIMEOUT_CTRL_VAL,
    I2C_TIMEOUT_MODE_BUS,
)
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CONTROLLER_EVENTS,
    I2C0_CTRL,
    I2C0_FDATA,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_OVRD_OFF,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_ENABLE_CONTROLLER,
    _fdata,
    _i2c_u32,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip

I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
I2C0_TIMEOUT_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR", 0)
I2C0_HOST_FIFO_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", 0)

INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
INTR_SCL_INTERFERENCE = _i2c_u32("I2C__INTR_STATE__SCL_INTERFERENCE_bm")
INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
INTR_STRETCH_TIMEOUT = I2C_INTR_STATE_STRETCH_TIMEOUT
EVENTS_BUS_TIMEOUT = I2C_CONTROLLER_EVENTS_BUS_TIMEOUT

CONTROLLER_EVENTS_ALL = 0xF
INTR_STATE_ALL = 0x0000_FFFF

EEPROM_ADDR = 0x50
ADDR_BYTE = 0xA0

#: Bench bring-up timing (TIMING0 THIGH / TLOW in peripheral clock cycles).
THIGH_CYCLES = 0x1A
TLOW_CYCLES = 0x32
L_CYCLES = TLOW_CYCLES
V_CYCLES = 4 * L_CYCLES
HALT_HOLD_CYCLES = 3 * V_CYCLES
HALT_OBSERVE_CYCLES = 2 * V_CYCLES
FMTLVL_GAP_CYCLES = 2 * L_CYCLES
OBSERVE_WINDOW_PERIPH_CYCLES = int(
    os.environ.get("SMC_I2C_FMTRST_WINDOW_CYCLES", str(40 * V_CYCLES))
)

#: SCL rising edges counted from the START: the address byte takes rises 1-8,
#: and its acknowledge is rise 9.
ADDR_ACK_RISE = 9

S2_ENTRIES = ((ADDR_BYTE, I2C_FDATA_START), (0x01, 0), (0x02, I2C_FDATA_STOP))
S2_POINTER = 0x01

EDGE_BOUND_SMC_CYCLES = 200_000
POLL_GAP_SMC_CYCLES = 200
POLL_LIMIT = 2000
FAST_POLL_GAP_SMC_CYCLES = 8

PAD_TRACE_EDGES = 48
PAD_TRACE_CHUNK = 12

FENCE_TERMS = ("SETUP", "HALT-A", "REPRO-A", "CLEANUP", "HALT-B", "REPRO-B")

_PadCond = Callable[[int, int, int, int], bool]


class _PadDecoder:
    """Samples ``tb_i2c0_scl``/``sda`` every SMC clock and timestamps bus events.

    Every wait is bounded in SMC clock cycles and recorded through the owning
    sequence; an unresolvable pad sample fails the wait rather than counting.
    """

    def __init__(self, record_wait) -> None:
        dut = cocotb.top
        self._scl = dut.tb_i2c0_scl
        self._sda = dut.tb_i2c0_sda
        self._clk = dut.clk_smc_i
        self._record_wait = record_wait
        self.starts = 0
        self.rises = 0
        self.last_event = "none"
        self.stop_seen: int | None = None
        self.watching = False

    def state(self) -> str:
        dut = cocotb.top
        return (
            f"decoder last_event={self.last_event} starts={self.starts} "
            f"rises_since_start={self.rises} stop_seen_ns={self.stop_seen} "
            f"scl={dut.tb_i2c0_scl.value} "
            f"sda={dut.tb_i2c0_sda.value} scl_dut_low={dut.tb_i2c0_scl_dut_low.value} "
            f"sda_dut_low={dut.tb_i2c0_sda_dut_low.value} "
            f"scl_ext_low={dut.tb_i2c0_scl_ext_low.value}"
        )

    def _sample(self) -> tuple[int, int]:
        scl = self._scl.value
        sda = self._sda.value
        assert scl.is_resolvable and sda.is_resolvable, (
            f"tb_i2c0 pads are not resolvable: scl={scl} sda={sda}"
        )
        return int(scl), int(sda)

    async def _until(self, label: str, cond: _PadCond) -> int:
        t0 = int(get_sim_time("ns"))
        prev_scl, prev_sda = self._sample()
        for _ in range(EDGE_BOUND_SMC_CYCLES):
            await RisingEdge(self._clk)
            scl, sda = self._sample()
            if cond(prev_scl, prev_sda, scl, sda):
                now = int(get_sim_time("ns"))
                self._record_wait(label, EDGE_BOUND_SMC_CYCLES, "smc", now - t0)
                self.last_event = label
                return now
            prev_scl, prev_sda = scl, sda
        raise AssertionError(
            f"{label}: the pad event did not occur within {EDGE_BOUND_SMC_CYCLES} smc cycles; "
            f"{self.state()}"
        )

    async def wait_start(self, label: str) -> int:
        t = await self._until(label, lambda ps, pd, s, d: bool(ps and s and pd and not d))
        self.starts += 1
        self.rises = 0
        return t

    async def wait_rise(self, label: str) -> int:
        t = await self._until(label, lambda ps, pd, s, d: bool((not ps) and s))
        self.rises += 1
        return t

    async def wait_fall(self, label: str) -> int:
        return await self._until(label, lambda ps, pd, s, d: bool(ps and not s))

    async def wait_rises(self, label: str, count: int) -> int:
        t = 0
        for i in range(1, count + 1):
            t = await self.wait_rise(f"{label}_RISE{i}")
        return t

    async def wait_released(self, label: str) -> int:
        return await self._until(label, lambda ps, pd, s, d: bool(s and d))

    async def watch_stop(self, label: str) -> None:
        """Record the first STOP (SDA rising while SCL is high) while ``watching`` holds.

        A recorded observation, not a wait: the owner ends the window and reads
        ``stop_seen``; the bound only keeps the task finite.
        """
        self.stop_seen = None
        self.watching = True
        prev_scl, prev_sda = self._sample()
        for _ in range(EDGE_BOUND_SMC_CYCLES):
            await RisingEdge(self._clk)
            if not self.watching:
                return
            scl, sda = self._sample()
            if prev_scl and scl and (not prev_sda) and sda:
                self.stop_seen = int(get_sim_time("ns"))
                self.last_event = label
                cocotb.log.info("%s: STOP decoded @ %dns", label, self.stop_seen)
                return
            prev_scl, prev_sda = scl, sda


class smc_i2c_fmtrst_repro_test_seq(SmcCsrSeq):
    """Bus-timeout halt, then FMTRST recovery with and without a CTRL.ENABLEHOST toggle."""

    def __init__(self, name: str = "smc_i2c_fmtrst_repro_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.holder: SmcI2cMasterVip | None = None
        self.decoder: _PadDecoder | None = None
        self.waits: list[tuple[str, int, str, int]] = []
        self.fence: list[tuple[str, int]] = []
        self.last_state: dict[str, int] = {}
        self.decoder_error: AssertionError | None = None

        self.start_seen_ns: int | None = None
        self.pad_stats: dict[str, int | None] = {}

    # ------------------------------------------------------------ plumbing --
    def _periph_ns(self) -> int:
        period = getattr(self.cfg, "periph_clk_period_ns", None)
        assert period, "the sequence has no peripheral clock period to convert cycles with"
        return int(period)

    @staticmethod
    async def _periph_cycles(count: int) -> None:
        await ClockCycles(cocotb.top.clk_periph_i, count)

    def _record_wait(self, label: str, bound: int, unit: str, elapsed_ns: int) -> None:
        self.waits.append((label, bound, unit, elapsed_ns))
        cocotb.log.info(
            "WAIT %s: bound=%d %s cycles elapsed_ns=%d expired=0", label, bound, unit, elapsed_ns
        )

    async def _snapshot(self, label: str) -> dict[str, int]:
        state = {
            "STATUS": await self.csr_read(f"{label}_STATUS", I2C0_STATUS),
            "HOST_FIFO_STATUS": await self.csr_read(f"{label}_HFS", I2C0_HOST_FIFO_STATUS),
            "INTR_STATE": await self.csr_read(f"{label}_INTR", I2C0_INTR_STATE),
            "CONTROLLER_EVENTS": await self.csr_read(f"{label}_CEV", I2C0_CONTROLLER_EVENTS),
        }
        self.last_state.update(state)
        return state

    async def _fail(self, label: str, message: str) -> None:
        state = await self._snapshot(f"{label}_EXPIRED")
        raise AssertionError(
            f"{label}: {message}; "
            + " ".join(f"{k}=0x{v:08x}" for k, v in state.items())
            + f"; {self.decoder.state()}"
        )

    async def _poll(
        self, label: str, addr: int, mask: int, want_set: bool, gap: int = POLL_GAP_SMC_CYCLES
    ) -> int:
        """Read ``addr`` until ``mask`` has the wanted state; expiry fails the leaf."""
        t0 = int(get_sim_time("ns"))
        bound = POLL_LIMIT * gap
        value = 0
        for _ in range(POLL_LIMIT):
            value = await self.csr_read(label, addr)
            if bool(value & mask) == want_set:
                self._record_wait(label, bound, "smc", int(get_sim_time("ns")) - t0)
                return value
            await ClockCycles(cocotb.top.clk_smc_i, gap)
        await self._fail(
            label,
            f"mask 0x{mask:08x} never read {'set' if want_set else 'clear'} within about "
            f"{bound} smc cycles (last value 0x{value:08x})",
        )
        return value

    async def _wait_hostidle(self, label: str) -> None:
        await self._poll(f"{label}_IDLE", I2C0_STATUS, I2C_STATUS_HOSTIDLE, True)

    async def _wait_slave(self, label: str, cond: Callable[[], bool], what: str) -> None:
        t0 = int(get_sim_time("ns"))
        bound = POLL_LIMIT * POLL_GAP_SMC_CYCLES
        for _ in range(POLL_LIMIT):
            if cond():
                self._record_wait(label, bound, "smc", int(get_sim_time("ns")) - t0)
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_GAP_SMC_CYCLES)
        await self._fail(label, f"the EEPROM target never {what} within {bound} smc cycles")

    async def _queue(self, label: str, entries) -> None:
        for i, (byte, flags) in enumerate(entries):
            await self.csr_write(f"{label}_FDATA{i}", I2C0_FDATA, _fdata(byte, flags))

    def _hold_scl(self, low: bool) -> None:
        assert self.holder is not None
        self.holder._pull_scl(low)
        cocotb.log.info(
            "HOLDER scl_ext_low=%d @ %dns %s",
            int(low),
            int(get_sim_time("ns")),
            self.decoder.state(),
        )

    async def _run_decoder(self, coro) -> None:
        """Run a decoder script as a task; its failure is kept for the foreground."""
        try:
            await coro
        except AssertionError as exc:
            self.decoder_error = exc
            self._hold_scl(False)

    async def _join_decoder(self, label: str, task) -> None:
        await task
        if self.decoder_error is not None:
            err, self.decoder_error = self.decoder_error, None
            await self._fail(label, str(err))

    async def _s1_setup(self) -> None:
        log_step("S1", "bring up I2C0 as controller against the EEPROM at 0x50, timeout disabled")
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_SCL_HOLD")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_scl_hold_eeprom")
        self.holder = SmcI2cMasterVip(speed=1_000_000, name="smc_i2c0_scl_hold_holder")
        self.decoder = _PadDecoder(self._record_wait)
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(THIGH_CYCLES, TLOW_CYCLES))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write("I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C0_TIMEOUT_OFF", I2C0_TIMEOUT_CTRL, 0)
        await self.csr_write("I2C0_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, CONTROLLER_EVENTS_ALL)
        await self.csr_write("I2C0_INTR_CLR", I2C0_INTR_STATE, INTR_STATE_ALL)
        await self.csr_write("I2C0_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        await self.csr_read("I2C0_TIMEOUT_RB", I2C0_TIMEOUT_CTRL, expected=0)
        await self.csr_read("I2C0_EVENTS_RB", I2C0_CONTROLLER_EVENTS, expected=0)
        intr = await self.csr_read("I2C0_INTR_RB", I2C0_INTR_STATE)
        watched = (
            INTR_CONTROLLER_HALT | INTR_SCL_INTERFERENCE | INTR_STRETCH_TIMEOUT | INTR_CMD_COMPLETE
        )
        assert intr & watched == 0, (
            f"S1: INTR_STATE reads 0x{intr:08x} with a watched flag already set before any transfer"
        )
        await self._wait_hostidle("S1")
        cocotb.log.info(
            "S1 done: L=TLOW=%d periph cycles V=4L=%d cycles (%d ns at %d ns/cycle) THIGH=%d",
            L_CYCLES,
            V_CYCLES,
            V_CYCLES * self._periph_ns(),
            self._periph_ns(),
            THIGH_CYCLES,
        )
        mark_fence(self.fence, "SETUP")

    # ----------------------------------------------------------------- S2 --
    async def _s2_decode_to_addr_ack_low(self) -> None:
        dec = self.decoder
        await dec.wait_start("S2_START")
        await dec.wait_rises("S2_ADDR", ADDR_ACK_RISE)
        await dec.wait_fall("S2_ACK_FALL")

    async def _bus_timeout_halt(self, tag: str) -> None:
        log_step(tag, "TIMEOUT_CTRL bus mode VAL=V; hold SCL 3V at the address acknowledge")
        periph_ns = self._periph_ns()
        timeout_word = (
            I2C_TIMEOUT_CTRL_EN | I2C_TIMEOUT_MODE_BUS | (V_CYCLES & I2C_TIMEOUT_CTRL_VAL)
        )
        await self.csr_write(f"{tag}_TIMEOUT_CTRL", I2C0_TIMEOUT_CTRL, timeout_word)
        await self.csr_read(f"{tag}_TIMEOUT_CTRL_RB", I2C0_TIMEOUT_CTRL, expected=timeout_word)
        self.slave.write_mem(S2_POINTER, b"\x00")
        bytes_before = self.slave.bytes
        starts_before = self.slave.starts

        task = cocotb.start_soon(self._run_decoder(self._s2_decode_to_addr_ack_low()))
        await self._queue(tag, S2_ENTRIES)
        await self._join_decoder(f"{tag}_DECODE", task)

        hold_start = int(get_sim_time("ns"))
        self._hold_scl(True)
        hold = cocotb.start_soon(self._periph_cycles(HALT_HOLD_CYCLES))

        observe_bound_ns = HALT_OBSERVE_CYCLES * periph_ns
        events = 0
        seen_at = None
        while True:
            events = await self.csr_read(f"{tag}_EVENTS_POLL", I2C0_CONTROLLER_EVENTS)
            now = int(get_sim_time("ns"))
            if events & EVENTS_BUS_TIMEOUT:
                seen_at = now - hold_start
                self._record_wait(f"{tag}_BUS_TIMEOUT_SET", HALT_OBSERVE_CYCLES, "periph", seen_at)
                break
            if now - hold_start > observe_bound_ns:
                self._hold_scl(False)
                await self._fail(
                    f"{tag}_BUS_TIMEOUT_SET",
                    f"CONTROLLER_EVENTS.BUS_TIMEOUT stayed clear for {now - hold_start} ns after "
                    f"the hold start, past the 2V bound of {observe_bound_ns} ns "
                    f"({HALT_OBSERVE_CYCLES} periph cycles); last CONTROLLER_EVENTS=0x{events:08x}",
                )
            await ClockCycles(cocotb.top.clk_smc_i, FAST_POLL_GAP_SMC_CYCLES)
        cocotb.log.info(
            "BUS-TIMEOUT set: CONTROLLER_EVENTS=0x%08x %d ns after the hold start",
            events,
            seen_at,
        )
        intr = await self.csr_read(f"{tag}_INTR_HALTED", I2C0_INTR_STATE)
        cocotb.log.info(
            "BUS-TIMEOUT observed: CONTROLLER_EVENTS=0x%08x INTR_STATE=0x%08x",
            events,
            intr,
        )
        assert intr & INTR_CONTROLLER_HALT, (
            f"{tag}: BUS_TIMEOUT is set (CONTROLLER_EVENTS=0x{events:08x}) but "
            f"INTR_STATE.CONTROLLER_HALT "
            f"reads 0 (INTR_STATE=0x{intr:08x}); the event has to halt the controller"
        )
        assert intr & INTR_STRETCH_TIMEOUT == 0, (
            f"{tag}: INTR_STATE.STRETCH_TIMEOUT is set (0x{intr:08x}) although TIMEOUT_CTRL.MODE=1 "
            f"selects the bus timeout"
        )

        await hold
        self._hold_scl(False)
        fmt1 = (
            await self.csr_read(f"{tag}_FMTLVL_A", I2C0_HOST_FIFO_STATUS)
            & I2C_HOST_FIFO_STATUS_FMTLVL
        )
        await ClockCycles(cocotb.top.clk_periph_i, FMTLVL_GAP_CYCLES)
        fmt2 = (
            await self.csr_read(f"{tag}_FMTLVL_B", I2C0_HOST_FIFO_STATUS)
            & I2C_HOST_FIFO_STATUS_FMTLVL
        )
        assert fmt1 == fmt2, (
            f"{tag}: HOST_FIFO_STATUS.FMTLVL went {fmt1} -> {fmt2} across 2L after the release; "
            f"a halted "
            f"controller must not consume format entries"
        )
        recorded = self.slave.read_mem(S2_POINTER, 1)
        assert self.slave.bytes == bytes_before and recorded == b"\x00", (
            f"{tag}: the EEPROM recorded a data byte while the controller was halted "
            f"(bytes {bytes_before}->{self.slave.bytes}, mem[0x{S2_POINTER:02x}]={recorded.hex()})"
        )
        assert self.slave.starts == starts_before + 1, (
            f"{tag}: the EEPROM saw {self.slave.starts - starts_before} STARTs for one "
            f"queued transfer"
        )
        mark_fence(self.fence, tag)

    # -------------------------------------------------------------- repro --
    async def _watch_start(self, label: str, window_cycles: int) -> None:
        """Sample the pads every SMC clock for the window; record START, STOP and edge facts."""
        self.start_seen_ns = None
        stats = {
            "scl_rises": 0,
            "scl_falls": 0,
            "restarts": 0,
            "stops": 0,
            "first_stop_ns": None,
            "first_edge_ns": None,
            "last_edge_ns": None,
        }
        self.pad_stats = stats
        trace: list[tuple[int, int, int, int, int, int]] = []
        dut = cocotb.top
        window_ns = window_cycles * self._periph_ns()
        t0 = int(get_sim_time("ns"))
        prev_scl, prev_sda = self.decoder._sample()
        while int(get_sim_time("ns")) - t0 < window_ns:
            await RisingEdge(dut.clk_smc_i)
            now = int(get_sim_time("ns"))
            scl, sda = self.decoder._sample()
            if (scl, sda) != (prev_scl, prev_sda):
                stats["first_edge_ns"] = (
                    now if stats["first_edge_ns"] is None else stats["first_edge_ns"]
                )
                stats["last_edge_ns"] = now
                if len(trace) < PAD_TRACE_EDGES:
                    trace.append(
                        (
                            now,
                            scl,
                            sda,
                            int(dut.tb_i2c0_scl_dut_low.value),
                            int(dut.tb_i2c0_sda_dut_low.value),
                            int(dut.tb_i2c0_scl_ext_low.value),
                        )
                    )
            stats["scl_rises"] += int(scl and not prev_scl)
            stats["scl_falls"] += int(prev_scl and not scl)
            if prev_scl and scl and prev_sda and not sda:
                stats["restarts"] += 1
                self.decoder.starts += 1
                if self.start_seen_ns is None:
                    self.start_seen_ns = now
                    cocotb.log.info("%s: START decoded @ %dns", label, now)
            if prev_scl and scl and not prev_sda and sda:
                stats["stops"] += 1
                if stats["first_stop_ns"] is None:
                    stats["first_stop_ns"] = now
            prev_scl, prev_sda = scl, sda
        self._record_wait(label, window_cycles, "periph", int(get_sim_time("ns")) - t0)
        for i in range(0, len(trace), PAD_TRACE_CHUNK):
            cocotb.log.info(
                "%s_PAD_TRACE (ns, scl, sda, scl_dut_low, sda_dut_low, scl_ext_low) %d: %s",
                label[0],
                i // PAD_TRACE_CHUNK,
                trace[i : i + PAD_TRACE_CHUNK],
            )
        cocotb.log.info("%s_PAD_TRACE transitions_traced=%d", label[0], len(trace))

    def _slave_facts(self) -> tuple[int, int, int, int, str]:
        sl = self.slave
        return sl.starts, sl.acks, sl.stops, sl.bytes, sl.read_mem(S2_POINTER, 2).hex()

    async def _fmtlvl(self, label: str) -> int:
        hfs = await self.csr_read(label, I2C0_HOST_FIFO_STATUS)
        return hfs & I2C_HOST_FIFO_STATUS_FMTLVL

    async def _repro(self, tag: str, suffix: str, recovery: str, toggle: bool) -> None:
        """Recover from the halt, queue one START-flagged write and print the fact lines."""
        log_step(tag, f"recovery {recovery}, then one START-flagged write")
        pfx = "B" if toggle else "A"
        if toggle:
            await self.csr_write(f"{pfx}_CTRL_DISABLE", I2C0_CTRL, 0)
        else:
            await self.csr_write(f"{pfx}_INTR_W1C_CMD_COMPLETE", I2C0_INTR_STATE, INTR_CMD_COMPLETE)
            intr_w1c = await self.csr_read(f"{pfx}_INTR_AFTER_W1C", I2C0_INTR_STATE)
            cocotb.log.info("%s: INTR_STATE=0x%08x after the CMD_COMPLETE W1C", tag, intr_w1c)
        await self.csr_write(f"{pfx}_FIFO_CTRL_FMTRST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_FMTRST)
        await self.csr_write(
            f"{pfx}_EVENTS_W1C_BUS_TIMEOUT", I2C0_CONTROLLER_EVENTS, EVENTS_BUS_TIMEOUT
        )
        if toggle:
            await self.csr_write(f"{pfx}_INTR_W1C_CMD_COMPLETE", I2C0_INTR_STATE, INTR_CMD_COMPLETE)
            await self._wait_hostidle(f"{pfx}_RECOVERY")
            await self.csr_write(f"{pfx}_CTRL_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        snap = await self._snapshot(f"{pfx}_AFTER_RECOVERY")
        cocotb.log.info(
            "%s: after recovery %s", tag, " ".join(f"{k}=0x{v:08x}" for k, v in snap.items())
        )
        fmt_before = snap["HOST_FIFO_STATUS"] & I2C_HOST_FIFO_STATUS_FMTLVL
        starts_before = self.decoder.starts
        slave_starts_before = self.slave.starts
        bytes_before = self.slave.bytes
        scl0, sda0 = self.decoder._sample()
        cocotb.log.info("%s: pads before the queue scl=%d sda=%d", tag, scl0, sda0)
        sl_before = self._slave_facts()
        cocotb.log.info(
            "%s: eeprom before the queue starts/acks/stops/bytes=%d/%d/%d/%d mem[ptr..ptr+1]=%s",
            tag,
            *sl_before,
        )

        cocotb.log.info(
            "%s: observation window %d periph cycles", tag, OBSERVE_WINDOW_PERIPH_CYCLES
        )
        watch = cocotb.start_soon(
            self._watch_start(f"{pfx}_START_WATCH", OBSERVE_WINDOW_PERIPH_CYCLES)
        )
        await self._queue(pfx, ((ADDR_BYTE, I2C_FDATA_START), (0x33, I2C_FDATA_STOP)))
        fmt_queued = await self._fmtlvl(f"{pfx}_FMTLVL_QUEUED")
        await watch

        intr = await self.csr_read(f"{pfx}_INTR_END", I2C0_INTR_STATE)
        fmt_after = await self._fmtlvl(f"{pfx}_FMTLVL_END")
        status = await self.csr_read(f"{pfx}_STATUS_END", I2C0_STATUS)
        events = await self.csr_read(f"{pfx}_EVENTS_END", I2C0_CONTROLLER_EVENTS)
        scl, sda = self.decoder._sample()
        sl_after = self._slave_facts()
        slave_starts = sl_after[0]
        bytes_after = sl_after[3]
        ps = self.pad_stats
        first_edge = "none" if ps["first_edge_ns"] is None else ps["first_edge_ns"]
        last_edge = "none" if ps["last_edge_ns"] is None else ps["last_edge_ns"]
        first_stop = "none" if ps["first_stop_ns"] is None else ps["first_stop_ns"]
        cocotb.log.info(
            "%s: eeprom at window end starts/acks/stops/bytes=%d/%d/%d/%d mem[ptr..ptr+1]=%s",
            tag,
            *sl_after,
        )
        cocotb.log.info(
            "%s: window end INTR_STATE=0x%08x FMTLVL=%d STATUS=0x%08x CONTROLLER_EVENTS=0x%08x "
            "scl=%d sda=%d eeprom_starts=%d eeprom_bytes=%d",
            tag,
            intr,
            fmt_after,
            status,
            events,
            scl,
            sda,
            slave_starts,
            bytes_after,
        )
        start_ns = "none" if self.start_seen_ns is None else str(self.start_seen_ns)
        cmd_complete = int(bool(intr & INTR_CMD_COMPLETE))
        hostidle = int(bool(status & I2C_STATUS_HOSTIDLE))
        cocotb.log.info(
            "CHK-FMTRST-REPRO-START-SEEN%s: value=%d start_ns=%s window_periph_cycles=%d "
            "decoder_starts=%d->%d eeprom_starts=%d->%d scl=%d sda=%d recovery=%s "
            "scl_rises=%d scl_falls=%d restart_patterns=%d stop_patterns=%d first_stop_ns=%s "
            "first_edge_ns=%s last_edge_ns=%s",
            suffix,
            int(self.start_seen_ns is not None),
            start_ns,
            OBSERVE_WINDOW_PERIPH_CYCLES,
            starts_before,
            self.decoder.starts,
            slave_starts_before,
            slave_starts,
            scl,
            sda,
            recovery,
            ps["scl_rises"],
            ps["scl_falls"],
            ps["restarts"],
            ps["stops"],
            first_stop,
            first_edge,
            last_edge,
        )
        cocotb.log.info(
            "CHK-FMTRST-REPRO-CMD-COMPLETE%s: value=%d INTR_STATE=0x%08x (CMD_COMPLETE cleared by "
            "W1C before the queue) CONTROLLER_EVENTS=0x%08x STATUS=0x%08x HOSTIDLE=%d",
            suffix,
            cmd_complete,
            intr,
            events,
            status,
            hostidle,
        )
        cocotb.log.info(
            "CHK-FMTRST-REPRO-FDATA-CONSUMED%s: value=%d FMTLVL=%d->%d->%d entries_queued=2 "
            "eeprom_bytes=%d->%d eeprom_acks=%d->%d eeprom_stops=%d->%d eeprom_mem=%s->%s",
            suffix,
            int(fmt_after < fmt_queued),
            fmt_before,
            fmt_queued,
            fmt_after,
            bytes_before,
            bytes_after,
            sl_before[1],
            sl_after[1],
            sl_before[2],
            sl_after[2],
            sl_before[4],
            sl_after[4],
        )
        mark_fence(self.fence, tag)

    async def _cleanup(self) -> None:
        log_step("CLEANUP", "disable, reset the FIFOs, clear every event, re-enable")
        await self.csr_write("CLEANUP_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("CLEANUP_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("CLEANUP_EVENTS_W1C", I2C0_CONTROLLER_EVENTS, CONTROLLER_EVENTS_ALL)
        await self.csr_write("CLEANUP_INTR_W1C", I2C0_INTR_STATE, INTR_STATE_ALL)
        status = await self._poll("CLEANUP_HOSTIDLE", I2C0_STATUS, I2C_STATUS_HOSTIDLE, True)
        released_ns = await self.decoder.wait_released("CLEANUP_PADS_RELEASED")
        cocotb.log.info("CLEANUP: STATUS=0x%08x pads released @ %dns", status, released_ns)
        await self.csr_write("CLEANUP_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await self._wait_hostidle("CLEANUP")
        snap = await self._snapshot("CLEANUP_FINAL")
        cocotb.log.info("CLEANUP: " + " ".join(f"{k}=0x{v:08x}" for k, v in snap.items()))
        mark_fence(self.fence, "CLEANUP")

    async def body(self) -> None:
        await self._s1_setup()
        await self._bus_timeout_halt("HALT-A")
        await self._repro(
            "REPRO-A", "", "FMTRST+W1C_BUS_TIMEOUT (no ENABLEHOST toggle)", toggle=False
        )
        await self._cleanup()
        await self._bus_timeout_halt("HALT-B")
        await self._repro(
            "REPRO-B", "-CTRL", "ENABLEHOST=0,FMTRST,W1C_BUS_TIMEOUT,ENABLEHOST=1", toggle=True
        )
        times = assert_fence_progress(self.fence, list(FENCE_TERMS))
        cocotb.log.info("CHK-NONVAC: %s < PASS (fence ns %s)", " < ".join(FENCE_TERMS), times)
        mark_fence(self.fence, "PASS")
